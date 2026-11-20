"""The files and shell rules against what coding agents were tricked with in 2026.

Files an agent obeys or starts from a project (.mcp.json, AGENTS.md and the
like) ask before they are changed. Another program's settings in /proc ask
before they are read. A path through a link says where it really leads.
"""

import os

import pytest

from kettle import FREE, NEEDS_YES, NEVER, rules
from kettle.rules import MAX_PLACE, _shown_place

RUNS_ITSELF = "it changes a file that other tools run or obey"
KEYS = "it is a place where keys and passwords are kept"
SECRET = "it reads from what looks like a place where keys or passwords are kept"
OUTSIDE = "the path is outside the folders you allow"
LINK = "a link on the way leads outside the folders you allow"

AGENT_FILES = [".mcp.json", "AGENTS.md", "CLAUDE.md", "CLAUDE.local.md", "GEMINI.md", ".cursorrules", ".windsurfrules", ".clinerules"]
AGENT_FOLDERS = [".gemini", ".codex", ".windsurf", ".amazonq", ".continue", ".clinerules"]


@pytest.fixture
def project(tmp_path):
    (tmp_path / "app").mkdir()
    return tmp_path / "app"


def verdict(does, path, project):
    found = rules.files([str(project)], does=does).explain({"path": str(path)} | ({"content": "x"} if does == "write" else {}))
    return found.level, found.reasons


@pytest.mark.parametrize("name", AGENT_FILES)
def test_an_agent_file_asks_before_it_is_changed_and_is_read_freely(project, name):
    for does in ("write", "delete"):
        assert verdict(does, project / name, project) == (NEEDS_YES, (RUNS_ITSELF,))
    assert verdict("read", project / name, project)[0] == FREE


@pytest.mark.parametrize("name", AGENT_FILES)
def test_an_agent_file_in_other_capitals_or_deeper_in_the_project_asks_too(project, name):
    assert verdict("write", project / name.upper(), project)[0] == NEEDS_YES
    assert verdict("write", project / "packages" / "web" / name, project)[0] == NEEDS_YES


@pytest.mark.parametrize("folder", AGENT_FOLDERS)
def test_what_is_in_an_agent_folder_asks_before_it_is_changed(project, folder):
    assert verdict("write", project / folder / "settings.json", project) == (NEEDS_YES, (RUNS_ITSELF,))
    assert verdict("read", project / folder / "settings.json", project)[0] == FREE


def test_files_with_names_close_to_an_agent_file_stay_free(project):
    for name in ("agents.md.bak", "my-claude.md", "mcp.json", ".mcp.json.example", "docs/claude-notes.md", "gemini.txt"):
        assert verdict("write", project / name, project)[0] == FREE, name


def test_a_link_with_an_ordinary_name_into_an_agent_file_asks_and_says_where_it_leads(project):
    (project / ".mcp.json").write_text("{}")
    (project / "docs").mkdir()
    os.symlink("../.mcp.json", project / "docs" / "clip.mp4")
    assert verdict("write", project / "docs" / "clip.mp4", project) == (NEEDS_YES, (f"it really leads to {_shown_place(os.path.realpath(project / '.mcp.json'), os.path.expanduser('~'))}", RUNS_ITSELF))


# ---- /proc: another program's settings and the words it was started with ---------------------


@pytest.mark.parametrize("path", ["/proc/1/environ", "/proc/self/environ", "/proc/4242/task/4243/environ", "/proc/1/cmdline", "/PROC/1/ENVIRON"])
def test_another_programs_settings_in_proc_are_a_place_where_secrets_are_kept(project, path):
    assert verdict("read", path, project) == (NEEDS_YES, (KEYS, OUTSIDE))
    assert verdict("write", path, project)[0] == NEVER


def test_proc_reached_by_going_up_is_known(project):
    assert verdict("read", str(project) + "/../../../../../../../../../../proc/1/environ", project)[1] == (KEYS, OUTSIDE)


def test_a_file_that_is_only_named_environ_or_cmdline_stays_free(project):
    for name in ("environ", "docs/environ", "proc/environ", "cmdline"):
        assert verdict("read", project / name, project) == (FREE, ()), name


def test_other_places_in_proc_are_judged_as_before(project):
    assert verdict("read", "/proc/cpuinfo", project) == (NEEDS_YES, (OUTSIDE,))
    assert verdict("read", "/proc/1/status", project) == (NEEDS_YES, (OUTSIDE,))


@pytest.mark.parametrize(
    "command",
    [
        "cat /proc/1/environ",
        "cat /proc/self/environ",
        "head -c 4000 /proc/1/environ",
        "grep -a TOKEN /proc/*/environ",
        "cat /proc/1/cmdline",
        "cat /proc/self/task/1/environ",
        "cat '/proc/1/environ'",
        "cat /PROC/1/ENVIRON",
        "cat ../../proc/1/environ",
        "cat /host/proc/1/environ",
    ],
)
def test_reading_another_programs_settings_in_the_shell_asks(command):
    found = rules.shell().explain({"command": command})
    assert found.level == NEEDS_YES and SECRET in found.reasons, command


@pytest.mark.parametrize("command", ["cat /proc/cpuinfo", "cat /proc/meminfo", "cat environ.txt", "cat docs/environ", "ls /proc"])
def test_other_reads_in_the_shell_are_judged_as_before(command):
    found = rules.shell().explain({"command": command})
    assert SECRET not in found.reasons, command


# ---- where a link really leads -----------------------------------------------------------------


def test_where_a_link_leads_is_said_only_when_the_path_asks_anyway(project):
    (project / "src").mkdir()
    os.symlink(project / "src", project / "code")
    assert verdict("write", project / "code" / "app.py", project) == (FREE, ())


def test_where_a_link_leads_is_said_first(tmp_path, project):
    (tmp_path / "out.txt").write_text("x")
    os.symlink(tmp_path / "out.txt", project / "notes.txt")
    assert verdict("write", project / "notes.txt", project)[1] == (f"it really leads to {_shown_place(os.path.realpath(tmp_path / 'out.txt'), os.path.expanduser('~'))}", LINK)


def test_the_systems_own_top_folder_links_are_not_news(project):
    for path in ("/tmp/kettle-x/a.txt", "/var/kettle-x/a.txt", "/etc/kettle-x/a.conf", "/TMP/kettle-x/a.txt"):
        assert not any(reason.startswith("it really leads to") for reason in verdict("read", path, project)[1]), path


def test_a_place_is_shown_from_the_home_folder_with_letters_that_cannot_be_shown_as_a_question_mark():
    assert _shown_place("/Users/sam/.zshrc", "/Users/sam") == "~/.zshrc"
    assert _shown_place("/Users/samuel/.zshrc", "/Users/sam") == "/Users/samuel/.zshrc"
    assert _shown_place("/Users/sam", "/Users/sam") == "~"
    assert _shown_place("/tmp/a\nb‮c", "/Users/sam") == "/tmp/a?b?c"


def test_a_long_place_is_cut_with_a_mark_so_two_long_places_stay_two():
    one, two = "/tmp/" + "a" * 200 + "/one", "/tmp/" + "a" * 200 + "/two"
    shown = _shown_place(one, "/Users/sam"), _shown_place(two, "/Users/sam")
    assert all(len(place) == MAX_PLACE for place in shown) and shown[0] != shown[1]
    assert all("... #" in place for place in shown)
    assert len(_shown_place("/tmp/" + "a" * (MAX_PLACE - 5), "/Users/sam")) == MAX_PLACE
