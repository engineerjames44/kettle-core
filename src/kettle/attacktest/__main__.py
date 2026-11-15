"""python -m kettle.attacktest

    --self-check              check the test itself with scripted stand-ins (no model, no cost)
    --list                    list the cases
    --agent module:function   test your own agent, a function (task, tools) -> reply
    --claude                  test a plain Claude agent (calls a paid API; needs --yes)
    --openai --model NAME     test a plain agent on the OpenAI chat API, or on another server
                              that speaks it with --base-url (needs --yes)
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
from pathlib import Path
from typing import Optional

from .cases import CaseError, load_cases
from .report import save_report
from .runner import SETUP_NAMES, SETUPS, run_test
from .selfcheck import self_check

KEY_REMOVED = "[key removed]"


def _key_from_file(path: str, name: str = "ANTHROPIC_API_KEY") -> Optional[str]:
    """The named key from a .env file, or None. The key is never printed.

    The last line that gives the name a value wins. Quotes come off, and outside
    quotes a # after a space starts a comment. A file that cannot be read as
    UTF-8 text gives None.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except (OSError, ValueError):
        return None
    found = None
    for line in lines:
        left, equals, value = line.strip().removeprefix("export ").partition("=")
        if not equals or left.strip() != name:
            continue
        quoted = value.lstrip()
        if quoted[:1] in ("'", '"'):
            end = quoted.find(quoted[0], 1)
            value = quoted[1:end] if end > 0 else quoted[1:]
        else:
            value = re.sub(r"\s#.*", "", value).strip()
        found = value or found
    return found


def _without(value, secret: str):
    """value with every copy of secret taken out, all the way down."""
    if type(value) is str:
        return value.replace(secret, KEY_REMOVED)
    if isinstance(value, dict):
        return {_without(name, secret): _without(item, secret) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_without(item, secret) for item in value)
    return value


def _load_agent(spec: str):
    module_name, _, function_name = spec.partition(":")
    if not module_name or not function_name:
        raise SystemExit("--agent takes module:function, for example my_agent:agent")
    sys.path.insert(0, os.getcwd())
    try:
        agent = getattr(importlib.import_module(module_name), function_name)
    except (ImportError, AttributeError) as error:
        raise SystemExit(f"Could not load {spec}: {error}")
    if not callable(agent):
        raise SystemExit(f"{spec} is not a function")
    return agent


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kettle.attacktest", description="Plant trick text where an agent reads and count what gets through.")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--self-check", action="store_true", help="check the test itself with scripted stand-ins (no model, no cost)")
    what.add_argument("--list", action="store_true", help="list the cases")
    what.add_argument("--agent", metavar="MODULE:FUNCTION", help="your agent: a function (task, tools) -> reply")
    what.add_argument("--claude", action="store_true", help="a plain Claude agent (calls a paid API)")
    what.add_argument("--openai", action="store_true", help="a plain agent on the OpenAI chat API; needs --model (a paid API unless --base-url points somewhere free)")
    parser.add_argument("--cases", metavar="FILE", help="a case file to use instead of the starter set, or fraud for the built-in fraud set")
    parser.add_argument("--only", metavar="IDS", help="run only these case ids, separated by commas")
    parser.add_argument("--repeats", type=int, default=5, help="times to run each case in each setup (default 5)")
    parser.add_argument("--setups", default=",".join(SETUPS), help=f"which setups to run, from {','.join(SETUPS)} (default both)")
    parser.add_argument("--max-calls", type=int, default=30, help="tool calls allowed per run (default 30)")
    parser.add_argument("--label", help="a name for the agent, shown in the report")
    parser.add_argument("--out", default="runs", help="folder for the report (default runs)")
    parser.add_argument("--model", help="with --claude or --openai: the model to use (--openai has no default)")
    parser.add_argument("--base-url", metavar="URL", help="with --openai: another server that speaks the same API, such as one on this machine")
    parser.add_argument("--key-name", metavar="NAME", help="with --openai: the name the key is stored under (default OPENAI_API_KEY; with --base-url no key is sent unless this is given)")
    parser.add_argument("--env-file", default=".env", help="with --claude or --openai: file holding ANTHROPIC_API_KEY or OPENAI_API_KEY (default .env)")
    parser.add_argument("--key-from-env", action="store_true", help="with --claude or --openai: use the key from the environment instead of the file")
    parser.add_argument("--yes", action="store_true", help="with --claude or --openai: go ahead with the run")
    args = parser.parse_args(argv)

    try:
        case_set = load_cases(args.cases)
    except CaseError as error:
        print(f"The case file is wrong: {error}", file=sys.stderr)
        return 2

    if args.list:
        print(f"{case_set.name}: {len(case_set.jobs)} normal jobs, {len(case_set.attacks)} attacks")
        for case in case_set.cases():
            extra = f"  [{' then '.join(plant['kind'] for plant in case.plants)}; wants {case.goal.tool} to {case.goal.to}]" if case.goal else ""
            print(f"  {case.id}: {case.task}{extra}")
        return 0

    if args.self_check:
        print("Checking the test itself with scripted stand-ins. This uses no model and says nothing about one.\n")
        checks = self_check(case_set)
        for text, ok in checks:
            print(f"  {'ok  ' if ok else 'FAIL'}  {text}")
        failed = sum(not ok for _, ok in checks)
        print(f"\n{len(checks) - failed} of {len(checks)} checks held.")
        return 1 if failed else 0

    setups = tuple(part.strip() for part in args.setups.split(",") if part.strip())
    only = [part.strip() for part in args.only.split(",") if part.strip()] if args.only else None
    unknown = sorted(set(only or []) - {case.id for case in case_set.cases()})
    if unknown:
        print(f"no such case: {', '.join(unknown)}", file=sys.stderr)
        return 2
    count = (len(set(only)) if only else len(case_set.cases())) * args.repeats * len(setups)
    key = None

    if args.claude:
        from .claude_agent import DEFAULT_MODEL, ClaudeAgent

        model = args.model or DEFAULT_MODEL
        if not args.yes:
            print(f"This would run a Claude agent ({model}) {count} times. Each run is several API calls, and they cost money.")
            print("Nothing has been run. Add --yes to go ahead, or use --repeats and --only to make it smaller.")
            return 0
        key = os.environ.get("ANTHROPIC_API_KEY") if args.key_from_env else _key_from_file(args.env_file)
        if not key:
            where = "the environment" if args.key_from_env else args.env_file
            print(f"No ANTHROPIC_API_KEY found in {where}. Nothing has been run.", file=sys.stderr)
            return 2
        try:
            agent = ClaudeAgent(model, api_key=key)
        except ImportError:
            print('The anthropic package is not installed. Run: pip install "kettle-labs[claude]"', file=sys.stderr)
            return 2
        label, settings = args.label or f"Plain Claude agent ({model})", agent.settings
        print(f"Calling the API at {settings.get('api_address', 'an address the agent did not give')}", flush=True)
    elif args.openai:
        from .openai_agent import OPENAI_API, OpenAIAgent

        if not args.model:
            print("--openai needs --model. There is no default: name the model you want to test. Nothing has been run.", file=sys.stderr)
            return 2
        # The address is always given to the package, so OPENAI_BASE_URL in the shell cannot pick where the key goes.
        address = args.base_url or OPENAI_API
        # A key stored for OpenAI is not sent to another address unless it is asked for by name.
        key_name = args.key_name or (None if args.base_url else "OPENAI_API_KEY")
        if key_name is not None and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key_name):
            print("--key-name takes the name the key is stored under, such as OPENAI_API_KEY, not the key itself. Nothing has been run.", file=sys.stderr)
            return 2
        if not args.yes:
            print(f"This would run an agent on {args.model} at {address} {count} times. Each run is several API calls, and on a paid API they cost money.")
            print("Nothing has been run. Add --yes to go ahead, or use --repeats and --only to make it smaller.")
            return 0
        if key_name is not None:
            key = os.environ.get(key_name) if args.key_from_env else _key_from_file(args.env_file, key_name)
            if not key:
                source = "the environment" if args.key_from_env else args.env_file
                print(f"No {key_name} found in {source}. Nothing has been run.", file=sys.stderr)
                return 2
        else:
            print(f"No key is sent to {address}. To send one, add --key-name with the name it is stored under.", flush=True)
        try:
            agent = OpenAIAgent(args.model, api_key=key or "no-key", base_url=address)
        except ImportError:
            print('The openai package is not installed. Run: pip install "kettle-labs[openai]"', file=sys.stderr)
            return 2
        label, settings = args.label or f"Plain agent on the OpenAI chat API ({args.model})", agent.settings
        print(f"Calling the API at {settings.get('api_address', 'an address the agent did not give')}", flush=True)
    else:
        agent = _load_agent(args.agent)
        label, settings = args.label or args.agent, {"agent": args.agent}

    done = 0

    def progress(run: dict) -> None:
        nonlocal done
        done += 1
        notes = [note for note, on in (("went along", run["went_along"]), ("RAN", run["got_through"]), ("error", run["error"])) if on]
        print(f"  [{done}/{count}] {run['case']} / {SETUP_NAMES[run['setup']]}" + (f": {', '.join(notes)}" if notes else ""), flush=True)

    try:
        result = run_test(agent, cases=case_set, setups=setups, repeats=args.repeats, max_calls=args.max_calls, label=label, settings=settings, only=only, progress=progress)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.claude or args.openai:
        result["meta"]["usage"] = {"api_calls": agent.api_calls, "input_tokens": agent.input_tokens, "output_tokens": agent.output_tokens}
    if key:
        # An API can send the key back in an error message, and a run keeps the text of its error.
        result = _without(result, key)
    folder = save_report(result, args.out)
    print()
    for setup in setups:
        totals = result["totals"][setup]
        print(
            f"{SETUP_NAMES[setup]}: {totals['attack_runs']} attacks run, {totals['went_along']} gone along with, "
            f"{totals['ran_without_yes']} actions ran without a yes, {totals['jobs_done']} of {totals['job_runs']} normal jobs finished"
            + (f", {totals['errors']} runs ended in an error" if totals["errors"] else "")
        )
    print(f"\nReport: {folder / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
