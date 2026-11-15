"""Shared pieces for the fixed tests.

The World is the outside world. Its tools write down every time they really run.
A test passes or fails on what the World saw, not on what the checkpoint says.
"""

import socket

import pytest

from kettle import FREE, NEEDS_YES, NEVER, Checkpoint

THIS_MACHINE = ("127.0.0.1", "::1", "localhost")


def _on_this_machine(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    return host is None or host == "" or host in THIS_MACHINE or str(host).startswith("127.")


@pytest.fixture(autouse=True)
def nothing_leaves_this_machine(monkeypatch):
    """No test can reach another machine, so no test can call a paid API.

    The break checks take guards out of a copy of the code on purpose and then run these tests.
    This holds even then, and even when a real key is sitting in a .env file nearby.
    """
    real_connect, real_lookup = socket.socket.connect, socket.getaddrinfo

    def connect(self, address, *rest):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _on_this_machine(address[0]):
            raise AssertionError(f"the tests stay on this machine, and this one tried to reach {address[0]}")
        return real_connect(self, address, *rest)

    def lookup(host, *rest, **more):
        if not _on_this_machine(host):
            raise AssertionError(f"the tests stay on this machine, and this one tried to look up {host}")
        return real_lookup(host, *rest, **more)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", lookup)


class World:
    def __init__(self):
        self.ran = []

    def read_note(self):
        self.ran.append(("read_note", {}))
        return "the note"

    def send_email(self, to, body):
        self.ran.append(("send_email", {"to": to, "body": body}))
        return "sent"

    def pay(self, to, amount):
        self.ran.append(("pay", {"to": to, "amount": amount}))
        return "paid"

    def risky(self):
        """Everything except the free read."""
        return [entry for entry in self.ran if entry[0] != "read_note"]


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now

    def forward(self, seconds):
        self.now += seconds


def add_tools(checkpoint, world):
    checkpoint.tool("read_note", world.read_note, level=FREE)
    checkpoint.tool("send_email", world.send_email, level=NEEDS_YES)
    checkpoint.tool("pay", world.pay, level=NEEDS_YES)
    checkpoint.tool("wipe_account", level=NEVER)


@pytest.fixture
def world():
    return World()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "kettle.db")


@pytest.fixture
def cp(db_path, world, clock):
    checkpoint = Checkpoint(db_path, hold_seconds=600, clock=clock)
    add_tools(checkpoint, world)
    yield checkpoint
    checkpoint.close()


EMAIL = {"to": "sam@example.com", "body": "See you at 3."}


@pytest.fixture
def held(cp, world):
    """A send_email request that is held and has not run."""
    decision = cp.request("send_email", dict(EMAIL))
    assert decision.status == "held"
    assert world.risky() == []
    return decision


@pytest.fixture
def approved(cp, held):
    assert cp.approve(held.request_id, held.fingerprint).status == "approved"
    return held
