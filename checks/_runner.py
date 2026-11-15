"""Shared by the two break_*.py scripts: break the code one way, run the tests, see if they notice."""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent


def nth(text, old, new, n=1):
    """Replace only the nth place old appears."""
    parts = text.split(old)
    if len(parts) <= n:
        return text  # reported as NOT APPLIED
    return old.join(parts[:n]) + new + old.join(parts[n:])


def rep(*pairs):
    """Replace each (old, new) pair. If any old is missing, change nothing."""

    def change(text):
        for old, new in zip(pairs[::2], pairs[1::2]):
            if old not in text:
                return text  # reported as NOT APPLIED
            text = text.replace(old, new)
        return text

    return change


def run(mutants, tests, expected_to_survive=None):
    """Each mutant is (what was broken, file under src/kettle, change). Exits 1 if one is missed."""
    expected = expected_to_survive or {}
    words = sys.argv[1:]
    jobs = [(index, mutant) for index, mutant in enumerate(mutants) if not words or any(word in mutant[0] for word in words)]
    work = pathlib.Path(tempfile.mkdtemp(prefix="kettle-break-"))

    def one(job):
        index, (label, rel, change) = job
        copy = work / str(index)
        shutil.copytree(ROOT / "src" / "kettle", copy / "kettle")
        path = copy / "kettle" / rel
        before = path.read_text(encoding="utf-8")
        after = change(before)
        if after == before:
            return label, None, "the code this break is written for is no longer there"
        path.write_text(after, encoding="utf-8")
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"] + [str(ROOT / "tests" / name) for name in tests],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(copy)},
            capture_output=True,
            text=True,
        )
        lines = out.stdout.strip().splitlines()
        first = next((line for line in lines if line.startswith(("FAILED", "ERROR"))), "")
        return label, out.returncode != 0, first[:120] or (lines[-1] if lines else out.stderr[-200:])

    missed, known = [], []
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for label, caught, note in pool.map(one, jobs):
                if caught is None:
                    print(f"NOT APPLIED  {label}  |  {note}", flush=True)
                    missed.append(label)
                elif caught:
                    print(f"caught       {label}  |  {note}", flush=True)
                elif label in expected:
                    print(f"not caught   {label}  |  known: {expected[label]}", flush=True)
                    known.append(label)
                else:
                    print(f"NOT CAUGHT   {label}  |  {note}", flush=True)
                    missed.append(label)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{len(jobs)} breaks tried, {len(jobs) - len(missed) - len(known)} caught by the tests, {len(known)} known and explained, {len(missed)} missed.")
    for label in missed:
        print(f"  missed: {label}")
    sys.exit(1 if missed else 0)
