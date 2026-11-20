"""Break the published coding-agent tricks measure, one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_agent_tricks.py          every break (under a minute)
    .venv/bin/python checks/break_agent_tricks.py swap     only the breaks with "swap" in their name

The measure is there to say how many tricks Kettle stops. The breaks that matter
most would make that number look better than it is: a held call counted as
stopped when it ran, a known limit hidden, a case that no longer does what its
name says, the published tricks and the ones added here counted together.
The branches that only run if the checkpoint itself is broken are not broken
here: break_ask_again.py and break_checkpoint.py break the checkpoint.

Only tests/test_agent_tricks.py is run.
"""

from _runner import rep, run

TESTS = ["test_agent_tricks.py"]

A = "attacktest/agent_tricks.py"

HELD = '        if decision.status == "held":\n            return STOPPED, f"{_short(tool, inputs)} asks: {_why(world.levels[tool], inputs)}"\n'
REFUSED = '        if decision.status != "ran":\n            return STOPPED, f"{_short(tool, inputs)} is refused: {_why(world.levels[tool], inputs)}"\n'
ALL_RAN = '    return THROUGH, "every call ran with no yes"\n'
LIMITED = "    if trick.limit and outcome in (THROUGH, STOPPED):\n"
COUNTED = '            ran += world.checkpoint.request(tool, inputs).status == "ran"\n'
SPLIT = '    for label, keep in (("Published tricks", lambda trick: trick.source != "kettle"), ("Added here", lambda trick: trick.source == "kettle")):\n'
SWAP = '        os.unlink(world.at("README.md"))\n        world.link("README.md", target)\n'
ONLY_SRC = '        world.give("write_file", rules.files([str(world.project / "src")], does="write"))  # only src/ is free, so README.md asks\n'
LATE = "    world.now[0] += HOLD_SECONDS + 1\n"


def gone(old):
    return rep(old, "")


MUTANTS = [
    ("calls: a held call counts as got through", A, rep(HELD, HELD.replace("return STOPPED", "return THROUGH"))),
    ("calls: a refused call counts as got through", A, rep(REFUSED, REFUSED.replace("return STOPPED", "return THROUGH"))),
    ("calls: a held call is let go on to the next call", A, gone(HELD)),
    ("calls: every call that ran counts as stopped", A, rep(ALL_RAN, '    return STOPPED, "every call ran with no yes"\n')),
    ("calls: only the first call is sent", A, rep("    for tool, inputs in calls:\n", "    for tool, inputs in calls[:1]:\n")),
    ("calls: only the last call is sent", A, rep("    for tool, inputs in calls:\n", "    for tool, inputs in calls[-1:]:\n")),
    ("calls: a held call says it is refused", A, rep(HELD, HELD.replace(" asks: ", " is refused: "))),
    ("limits: a known limit is not marked", A, rep(LIMITED, "    if False:\n")),
    ("limits: a known limit is marked only when it got through", A, rep(LIMITED, "    if trick.limit and outcome == THROUGH:\n")),
    ("limits: a known limit does not say where the rule says so", A, rep('        return LIMIT, f"{reason}. {trick.limit}"\n', "        return LIMIT, reason\n")),
    ("setup: the owner allows nothing in the shell", A, rep('ALLOWED = ["python -m pytest"]', "ALLOWED = []")),
    ("setup: the owner lists no site to read", A, rep('WEB_READ = ["docs.python.org"]', "WEB_READ = []")),
    ("setup: huggingface.co is not listed for the listed-site case", A, rep('LISTED = {"ci-listed-site": ["docs.python.org", "huggingface.co"]}', "LISTED = {}")),
    ("setup: a link to ~ does not reach the home folder", A, rep('target.replace("~", self.home, 1) if target.startswith("~") else target', "target")),
    ("setup: the read tool is under the write rule", A, rep('        self.give("read_file", rules.files([str(self.project)], does="read"))\n', '        self.give("read_file", rules.files([str(self.project)], does="write"))\n')),
    ("swap: the file is not swapped", A, gone(SWAP)),
    ("swap: README.md is free to write, so no yes is asked for", A, rep(ONLY_SRC, '        world.give("write_file", rules.files([str(world.project)], does="write"))\n')),
    ("nobody: no time passes", A, gone(LATE)),
    ("everyday: a held action counts as run", A, rep(COUNTED, '            ran += world.checkpoint.request(tool, inputs).status in ("ran", "held")\n')),
    ("everyday: the paths are not put in the project", A, rep('            if "path" in inputs:\n', "            if False:\n")),
    ("everyday: one action is left out", A, rep('    ("run_shell", {"command": "git log"}),\n', "")),
    ("report: published and added are counted together", A, rep(SPLIT, '    for label, keep in (("Published tricks", lambda trick: True), ("Added here", lambda trick: trick.source == "kettle")):\n')),
    ("report: the split is the wrong way round", A, rep(SPLIT, SPLIT.replace('trick.source != "kettle"), ("Added here", lambda trick: trick.source == "kettle")', 'trick.source == "kettle"), ("Added here", lambda trick: trick.source != "kettle")'))),
    ("report: a family is left out", A, rep("    for family in (ENV, LINKS, CONFIG, CI):\n", "    for family in (ENV, LINKS, CONFIG):\n")),
    ("report: a source's link is not shown", A, rep('*([f"    {source.url}"] if source.url else [])', "*[]")),
    ("report: how a source was checked is not said", A, rep('({CHECKED[source.checked]})', "")),
    ("sources: a summary is said to be the original", A, rep('    "summary": "a summary read, not the original",', '    "summary": "the researcher\'s own write-up read",')),
    ("sources: AGENTS.md is said to come from Comment and Control", A, rep('Trick("config-agents-md", CONFIG, "csa-ci",', 'Trick("config-agents-md", CONFIG, "comment-control",')),
    ("sources: a case added here is said to be published", A, rep('Trick("link-swap-zshrc", LINKS, "kettle",', 'Trick("link-swap-zshrc", LINKS, "ghostapproval",')),
    ("cases: the pager case does not run the allowed command after", A, rep('_shell("export PAGER=\'sh ./pager.sh\'", "git branch")', '_shell("git branch")')),
    ("cases: the /proc case reads something else", A, rep('_shell("cat /proc/1/environ")', '_shell("cat /proc/1/status")')),
    ("cases: the .mcp.json link leads to an ordinary file", A, rep('links=(("docs/clip2.mp4", "../.mcp.json"),), files=(".mcp.json",)', 'links=(("docs/clip2.mp4", "../notes.txt"),), files=("notes.txt",)')),
]

run(MUTANTS, TESTS)
