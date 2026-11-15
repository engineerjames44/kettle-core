"""Where the checkpoint keeps its state: held requests and the log of what happened.

One SQLite file. Every change happens inside a write transaction that takes the
file's write lock first (BEGIN IMMEDIATE), so two workers, threads or processes
sharing the file cannot both use the same yes.

The log is append-only and chained: each entry stores a hash of itself and of the
entry before it. verify_log() finds an entry that was edited, removed from the
middle or reordered. It cannot find entries cut from the end. It does not stop
someone who can write the file: they can change an entry and write new hashes for
it and every entry after it (for the last entry, that is one hash).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

SCHEMA_VERSION = "1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    record TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    decided_at REAL,
    decided_by TEXT,
    approved_fingerprint TEXT,
    started_at REAL,
    finished_at REAL,
    worker TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS log (
    seq INTEGER PRIMARY KEY,
    at REAL NOT NULL,
    event TEXT NOT NULL,
    request_id TEXT,
    tool TEXT,
    fingerprint TEXT,
    detail TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
"""

GENESIS = "0" * 64


class StoreError(Exception):
    """The store could not be opened, read or written."""


def _entry_hash(prev_hash: str, seq: int, at: float, event: str, request_id, tool, fingerprint, detail: str) -> str:
    body = json.dumps(
        [prev_hash, seq, at, event, request_id, tool, fingerprint, detail],
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("ascii")).hexdigest()


class Transaction:
    """The handle code gets while it holds the write lock."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def meta(self, key: str) -> Optional[str]:
        row = self._connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    def get(self, request_id: str) -> Optional[sqlite3.Row]:
        if type(request_id) is not str:
            return None
        return self._connection.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()

    def insert_request(self, request_id: str, fingerprint: str, record: str, created_at: float, expires_at: float) -> None:
        self._connection.execute(
            "INSERT INTO requests (id, fingerprint, record, state, created_at, expires_at) VALUES (?, ?, ?, 'held', ?, ?)",
            (request_id, fingerprint, record, created_at, expires_at),
        )

    def move(self, request_id: str, from_states: tuple, to_state: str, **fields: Any) -> bool:
        """Move a request to a new state only if it is still in one of from_states."""
        allowed = {"decided_at", "decided_by", "approved_fingerprint", "started_at", "finished_at", "worker", "note"}
        if not set(fields) <= allowed:
            raise StoreError("unknown field")
        sets = ", ".join(["state = ?"] + [f"{name} = ?" for name in fields])
        marks = ", ".join("?" for _ in from_states)
        cursor = self._connection.execute(
            f"UPDATE requests SET {sets} WHERE id = ? AND state IN ({marks})",
            (to_state, *fields.values(), request_id, *from_states),
        )
        return cursor.rowcount == 1

    def log(self, at: float, event: str, request_id=None, tool=None, fingerprint=None, detail: Optional[dict] = None) -> None:
        at = float(at)  # the hash is made from the same number SQLite will hand back
        last = self._connection.execute("SELECT seq, hash FROM log ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev_hash = (last["seq"] + 1, last["hash"]) if last else (1, GENESIS)
        detail_text = json.dumps(detail or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
        entry_hash = _entry_hash(prev_hash, seq, at, event, request_id, tool, fingerprint, detail_text)
        self._connection.execute(
            "INSERT INTO log (seq, at, event, request_id, tool, fingerprint, detail, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (seq, at, event, request_id, tool, fingerprint, detail_text, prev_hash, entry_hash),
        )


class Store:
    def __init__(self, path: str, busy_seconds: float = 10.0) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        try:
            self._connection = sqlite3.connect(
                self.path, timeout=busy_seconds, isolation_level=None, check_same_thread=False
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.executescript(_SCHEMA)
            with self.write() as tx:
                found = tx.meta("schema")
                if found is None:
                    tx.set_meta("schema", SCHEMA_VERSION)
                elif found != SCHEMA_VERSION:
                    raise StoreError(f"the store was made by a different version (schema {found})")
        except (sqlite3.Error, OSError) as error:
            raise StoreError(f"the checkpoint store could not be opened: {error}") from None

    @contextmanager
    def write(self) -> Iterator[Transaction]:
        """A write transaction. Everything inside happens, or none of it does."""
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
            except (sqlite3.Error, OSError) as error:
                raise StoreError(f"the checkpoint store is not available: {error}") from None
            try:
                yield Transaction(self._connection)
                self._connection.execute("COMMIT")
            except BaseException as error:
                try:
                    self._connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                if isinstance(error, (sqlite3.Error, OSError)):
                    raise StoreError(f"the checkpoint store is not available: {error}") from None
                raise

    def read(self, sql: str, args: tuple = ()) -> list:
        with self._lock:
            try:
                return self._connection.execute(sql, args).fetchall()
            except (sqlite3.Error, OSError) as error:
                raise StoreError(f"the checkpoint store is not available: {error}") from None

    def log_entries(self) -> list[dict]:
        entries = []
        for row in self.read("SELECT * FROM log ORDER BY seq"):
            entry = dict(row)
            try:
                entry["detail"] = json.loads(entry["detail"])
            except (ValueError, TypeError):  # edited by hand; verify_log() reports it
                pass
            entries.append(entry)
        return entries

    def verify_log(self) -> tuple[bool, str]:
        """Check the chain. Returns (True, "...") or (False, where it breaks)."""
        prev_hash, expected_seq = GENESIS, 1
        for row in self.read("SELECT * FROM log ORDER BY seq"):
            if row["seq"] != expected_seq:
                return False, f"entry {expected_seq} is missing"
            if row["prev_hash"] != prev_hash:
                return False, f"entry {row['seq']} does not follow the entry before it"
            try:
                wanted = _entry_hash(
                    prev_hash, row["seq"], row["at"], row["event"], row["request_id"], row["tool"], row["fingerprint"], row["detail"]
                )
            except (TypeError, ValueError):  # a value of a kind the checkpoint never writes
                wanted = None
            if row["hash"] != wanted:
                return False, f"entry {row['seq']} was changed"
            prev_hash, expected_seq = row["hash"], expected_seq + 1
        return True, f"{expected_seq - 1} entries, chain intact"

    def close(self) -> None:
        with self._lock:
            try:
                self._connection.close()
            except sqlite3.Error:
                pass
