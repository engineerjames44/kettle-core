# Putting a release on PyPI

For whoever publishes Kettle. Nothing here runs by itself. Version 0.1.0 went up this way on 16 November 2026.

The package is called `kettle-labs` on PyPI and is imported as `kettle`. The name `kettle` on PyPI belongs to
another project (one release, 0.0.1, with no files to download when we looked on 15 November 2026), so it
cannot be used.

## Before you start

- A PyPI account with two-step sign-in turned on: https://pypi.org/account/register/
- The version number in `src/kettle/__init__.py` is the one you want. It is the only place it is written.
  PyPI never lets a version number be used twice, even after a delete.

## 1. Check the code

```
.venv/bin/pytest -q
.venv/bin/python checks/break_checkpoint.py
.venv/bin/python checks/break_attacktest.py
.venv/bin/python checks/break_adapters.py
.venv/bin/python checks/break_telegram.py
.venv/bin/python checks/break_yes_set.py
.venv/bin/python checks/break_demo.py
.venv/bin/python checks/break_verify.py
.venv/bin/python -m kettle.attacktest --self-check
.venv/bin/python -m kettle.attacktest --self-check --cases fraud
.venv/bin/python -m kettle.attacktest --yes-set
```

Every one should end with nothing failed and nothing missed. The attacks on the yes should end with
"All as expected." `break_telegram.py` takes about a quarter of an hour.

## 2. Build it

```
.venv/bin/python -m pip install build twine
rm -rf dist
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

This leaves two files in `dist/`: a `.whl` and a `.tar.gz`. `dist/` is not kept in git.

The build packs every file under `src/kettle`, committed or not. If the folder holds work that is not in the
commit being released, build from a clean copy of that commit and bring the two files back:

```
rm -rf /tmp/kettle-release && mkdir /tmp/kettle-release
git archive HEAD | tar -x -C /tmp/kettle-release
(cd /tmp/kettle-release && /path/to/kettle-core/.venv/bin/python -m build)
```

## 3. Try the built package somewhere clean

```
python3 -m venv /tmp/kettle-try
/tmp/kettle-try/bin/pip install dist/*.whl
/tmp/kettle-try/bin/python -m kettle.attacktest --self-check
/tmp/kettle-try/bin/python -m kettle.attacktest --self-check --cases fraud
```

Both should say 8 of 8 checks held. This proves the case sets were packed with the code.

## 4. Upload

Make an API token at https://pypi.org/manage/account/token/. The first upload needs a token for the whole
account, because the project does not exist yet.

```
.venv/bin/python -m twine upload dist/*
```

It asks for the token. Paste it there and nowhere else: not in a chat, not in a file in this folder.

Afterwards, delete that token and make a new one that is limited to the `kettle-labs` project.

## 5. After it is up

- Check the page: https://pypi.org/project/kettle-labs/
- In a clean folder, `pip install kettle-labs` and run the self-check again.
- Tag the commit that was built, with its version: `git tag v0.2.0` and `git push origin v0.2.0`.
- In `README.md`, change the status line and the install step under "Set up" to `pip install kettle-labs`.
- On the website, tick "Packaged release" in the release list.

## If something is wrong after the upload

A release cannot be replaced. Raise the version number, build again and upload the new one. A broken release
can be "yanked" on its PyPI page, which hides it from new installs without breaking anyone who already has it.
