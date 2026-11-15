"""The long version of the preview read-back test: 150,000 random records, not 3,000.

    .venv/bin/python checks/read_back.py          (about a minute)

Each record is built from text chosen to be awkward (spaces, line breaks, unseen
characters, text that looks like the preview's own marks). Its preview is read back
by the reader in tests/test_record_and_preview.py, which must get exactly the record
it was written from. Two different records must never share a preview.

Each record is also written a second time with first-time marks on some inputs,
chosen at random. The marks must not change what is read back.
"""

import pathlib
import random
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

import test_record_and_preview as reader  # noqa: E402

from kettle.checkpoint.record import ActionRecord  # noqa: E402

SEEDS, EACH = 60, 2500


def main():
    start, wrong, seen = time.time(), 0, {}
    for seed in range(SEEDS):
        rng = random.Random(seed)
        for number in range(EACH):
            tool = reader._tricky_text(rng, 3) or "tool"
            actor = rng.choice([None, reader._tricky_text(rng, 3)])
            inputs = {reader._tricky_text(rng, 3): reader._tricky_value(rng) for _ in range(rng.randint(0, 4))}
            summary = rng.choice([None, reader._tricky_text(rng, 4)]) or None
            record = ActionRecord.make(tool, inputs, actor)
            preview = record.preview(summary)
            try:
                found = reader.read_back(preview)
                assert found["summary"] == summary, "the summary read back differently"
                assert ActionRecord.make(found["tool"], found["inputs"], found["actor"]) == record, "a different record was read back"
                assert found["fingerprint"] == record.fingerprint, "the fingerprint read back differently"
            except AssertionError as error:
                wrong += 1
                print(f"WRONG  seed {seed}, record {number}: {error}")
            marks = {key: rng.choice([None, sorted(rng.sample(range(1, 300), rng.randint(1, 20)))]) for key in inputs if rng.random() < 0.5}
            try:
                found = reader.read_back(record.preview(summary, marks))
                assert found["summary"] == summary, "the summary read back differently with marks"
                assert ActionRecord.make(found["tool"], found["inputs"], found["actor"]) == record, "a different record was read back with marks"
            except AssertionError as error:
                wrong += 1
                print(f"WRONG  seed {seed}, record {number}: {error}")
            body = preview.rsplit("\n", 1)[0]  # everything but the fingerprint line
            if seen.setdefault(body, (record.fingerprint, summary)) != (record.fingerprint, summary):
                wrong += 1
                print(f"WRONG  seed {seed}, record {number}: two different records share a preview")
    print(f"{SEEDS * EACH} records, {len(seen)} different previews, {wrong} wrong, {time.time() - start:.0f} seconds.")
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    main()
