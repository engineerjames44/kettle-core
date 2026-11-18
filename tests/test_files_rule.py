"""The ready-made rule for file tools: rules.files.

Every test makes its own small home folder under pytest's temp folder, with a
project in it, a folder that may only be read, and links that lead out. No
file outside that temp folder is written, read or deleted: the rule only works
out where a path leads.
"""

import os
import unicodedata

import pytest

from kettle import rules
from kettle.checkpoint.rules import FREE, NEEDS_YES, NEVER, RulesError

FINE = "the path is inside the folders you allow"
UNREAD = "the path cannot be read"
UNSEEN = "the path holds a line break or a character that cannot be seen"
NOT_PLAIN = "the path is not written plainly, so a tool might take it for another place"
PATTERN = "the path holds a pattern, and this rule does not work out which files it stands for"
RELATIVE = "the path does not start from / or ~, and the rule was not told which folder the tool starts in"
OUTSIDE = "the path is outside the folders you allow"
LINK = "a link on the way leads outside the folders you allow"
READ_ONLY = "you allow reading there, not changing it"
KEYS = "it is a place where keys and passwords are kept"
PROTECTED = "it is one of the paths you protect"
SYSTEM = "it changes a system folder"
WHOLE = "it deletes the home folder or a top folder of the machine"
RUNS_ITSELF = "it changes a file that other tools run or obey"
FOLDER = "it deletes a whole folder"
MANY = "it deletes more than {} paths at once"
UNTOLD = "the rule was not told about {} of the inputs"

DOES = ["read", "write", "delete"]
CHANGES = ["write", "delete"]

# Written out here on purpose, and not read from kettle.rules: a test that loops over
# the rule's own list still passes when a word is taken off that list.
SYSTEM_FOLDERS = "bin boot dev etc lib lib32 lib64 Library proc root sbin sys System usr".split()
KEY_NAMES = ".ssh .aws .gnupg .kube .netrc .npmrc .pypirc .git-credentials .htpasswd .env .envrc id_rsa id_dsa id_ecdsa id_ed25519 Keychains".split()
KEY_PAIRS = [".docker/config.json", ".config/gh", ".config/gcloud", "etc/shadow", "etc/sudoers", "etc/master.passwd"]
KEY_STEMS = "credentials password passwords secret secrets".split()
KEY_ENDINGS = [".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ppk"]
EXAMPLE_ENDINGS = [".example", ".sample", ".template", ".dist"]
OBEYED_FOLDERS = ".git .github .husky .vscode .claude .cursor .devcontainer LaunchAgents LaunchDaemons".split()
OBEYED_FILES = ".zshrc .zshenv .zprofile .zlogin .bashrc .bash_profile .bash_login .profile .gitconfig".split()


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home folder with a project, a folder for reading, a key folder, and links that lead out of the project."""
    home = os.path.realpath(tmp_path / "home")
    app = os.path.join(home, "Projects", "my-app")
    for folder in ("Projects/my-app/src", "Documents/specs", ".ssh", "Projects/other"):
        os.makedirs(os.path.join(home, folder))
    for name in ("Projects/my-app/src/app.py", "Projects/my-app/kettle.db", "Documents/tax.txt", "Documents/specs/a.md"):
        with open(os.path.join(home, name), "w") as file:
            file.write("x")
    os.symlink("/etc", os.path.join(app, "out"))
    os.symlink(os.path.join(home, ".ssh"), os.path.join(app, "keys"))
    os.symlink(os.path.join(home, "Documents"), os.path.join(app, "docs"))
    os.symlink(os.path.join(app, "src"), os.path.join(app, "same"))
    os.symlink(os.path.join(app, "kettle.db"), os.path.join(app, "src", "data"))
    os.symlink(os.path.join(app, "round"), os.path.join(app, "round"))
    monkeypatch.setenv("HOME", home)
    return home


def rule(does, **settings):
    settings.setdefault("read_only", ["~/Documents/specs"])
    settings.setdefault("protect", ["~/Projects/my-app/kettle.db"])
    settings.setdefault("base", "~/Projects/my-app")
    return rules.files(settings.pop("folders", ["~/Projects/my-app"]), does=does, **settings)


def look(does, path, **settings):
    return rule(does, **settings).explain({"path": path})


def asks(does, path, reasons, **settings):
    verdict = look(does, path, **settings)
    assert (verdict.level, list(verdict.reasons)) == (NEEDS_YES, reasons), (does, path)


def never(does, path, reasons, **settings):
    verdict = look(does, path, **settings)
    assert (verdict.level, list(verdict.reasons)) == (NEVER, reasons), (does, path)


def free(does, path, **settings):
    assert look(does, path, **settings) == rules.Verdict(FREE, ()), (does, path)


def test_the_lists_written_out_here_are_whole():
    counts = [SYSTEM_FOLDERS, KEY_NAMES, KEY_PAIRS, KEY_STEMS, KEY_ENDINGS, EXAMPLE_ENDINGS, OBEYED_FOLDERS, OBEYED_FILES]
    assert [len(words) for words in counts] == [14, 16, 6, 5, 8, 4, 9, 9]
    assert all(len(set(words)) == len(words) for words in counts)


# ---- inside the owner's folders ------------------------------------------------------


@pytest.mark.parametrize("does", DOES)
def test_a_file_inside_the_folder_runs_without_asking(home, does):
    for path in (
        "~/Projects/my-app/src/app.py",
        f"{home}/Projects/my-app/README.md",
        "src/app.py",
        "README.md",
        "src/./app.py",
        "src//app.py",
        "src/../README.md",
        "same/app.py",
        f"/{home}/Projects/my-app/src/app.py",
        "new/folder/that/is/not/there/yet.txt",
    ):
        free(does, path)


@pytest.mark.parametrize("does", DOES)
def test_the_rule_gives_the_level_when_called_and_says_why_in_words(home, does):
    made = rule(does)
    assert made({"path": "src/app.py"}) == FREE
    assert made.why({"path": "src/app.py"}) == "Runs without asking: " + FINE
    assert made({"path": "~/Documents/tax.txt"}) == NEEDS_YES
    assert made.why({"path": "~/Documents/tax.txt"}) == "Asks because: " + OUTSIDE


def test_never_is_said_in_words(home):
    assert rule("write").why({"path": "/etc/hosts"}) == "Never allowed: " + SYSTEM


@pytest.mark.parametrize("does", DOES)
def test_a_list_of_paths_is_judged_path_by_path_and_the_strictest_wins(home, does):
    free(does, ["src/app.py", "README.md"])
    asks(does, ["src/app.py", "~/Documents/tax.txt"], [OUTSIDE])
    asks(does, ["~/Documents/tax.txt", "src/app.py"], [OUTSIDE])
    asks(does, ["~/Documents/tax.txt", "src/*.py"], [OUTSIDE, PATTERN])


def test_in_a_list_a_refusal_beats_an_ask(home):
    never("write", ["src/app.py", "~/Documents/tax.txt", "/etc/hosts"], [SYSTEM])
    never("delete", ["~/Documents/tax.txt", "~"], [WHOLE])


@pytest.mark.parametrize("does", DOES)
def test_more_than_one_folder_can_be_allowed(home, does):
    folders = ["~/Projects/my-app", "~/Projects/other"]
    free(does, "~/Projects/other/a.txt", folders=folders)
    free(does, "src/app.py", folders=folders)
    asks(does, "~/Projects/third/a.txt", [OUTSIDE], folders=folders)


@pytest.mark.parametrize("does", DOES)
def test_a_folder_whose_name_starts_the_same_is_not_inside(home, does):
    asks(does, "~/Projects/my-app-old/a.txt", [OUTSIDE])
    asks(does, "~/Projects/my-ap", [OUTSIDE])
    free(does, "~/Projects/my-app/a.txt", folders=["~/Projects/my-app/"])


@pytest.mark.parametrize("does", DOES)
def test_a_folder_spelled_in_other_capitals_is_not_taken_for_the_owners(home, does):
    # On a disk that tells capitals apart it is another folder. So it asks, on every disk.
    asks(does, "~/projects/my-app/src/app.py", [OUTSIDE])
    asks(does, "~/Projects/My-App/src/app.py", [OUTSIDE])
    asks(does, home.upper() + "/Projects/my-app/src/app.py", [OUTSIDE])
    free(does, "SRC/App.py")
    plain, split = unicodedata.normalize("NFC", "café"), unicodedata.normalize("NFD", "café")
    free(does, f"~/Projects/{plain}/a.txt", folders=[f"~/Projects/{plain}"])
    asks(does, f"~/Projects/{split}/a.txt", [OUTSIDE], folders=[f"~/Projects/{plain}"])


def test_a_folder_for_reading_spelled_in_other_capitals_asks(home):
    free("read", "~/Documents/specs/a.md")
    asks("read", "~/Documents/Specs/a.md", [OUTSIDE])
    asks("read", "~/documents/specs/a.md", [OUTSIDE])
    asks("write", "~/Documents/Specs/a.md", [OUTSIDE])


@pytest.mark.parametrize("does", DOES)
def test_a_folder_the_owner_names_through_a_link_is_the_place_it_leads_to(home, does):
    free(does, "src/app.py", folders=["~/Projects/my-app/same"])  # same is a link to src
    free(does, "same/app.py", folders=["~/Projects/my-app/same"])
    asks(does, "README.md", [OUTSIDE], folders=["~/Projects/my-app/same"])
    if does == "read":
        free(does, "~/Documents/tax.txt", folders=[], read_only=["~/Projects/my-app/docs"])  # docs is a link to ~/Documents
        free(does, "docs/tax.txt", folders=[], read_only=["~/Projects/my-app/docs"])


@pytest.mark.parametrize("does", DOES)
def test_with_no_folders_everything_asks(home, does):
    made = rules.files(does=does, base="~/Projects/my-app")
    assert list(made.explain({"path": "src/app.py"}).reasons) == [OUTSIDE]
    assert list(rules.files([], does=does).explain({"path": "~/Projects/my-app/a"}).reasons) == [OUTSIDE]


# ---- outside -------------------------------------------------------------------------


@pytest.mark.parametrize("does", DOES)
def test_a_path_outside_the_folders_asks(home, does):
    for path in ("~/Documents/tax.txt", "~/Projects/other/a.txt", "/tmp/kettle-x/a.txt", "/var/log/x.log", "/opt/tool/a", "/Volumes/Stick/a", "/Applications/A.app/b", "../other/a.txt", "src/../../a.txt"):
        asks(does, path, [OUTSIDE])


def test_reading_is_allowed_in_the_read_only_folders_and_changing_is_not(home):
    free("read", "~/Documents/specs/a.md")
    free("read", ["~/Documents/specs/a.md", "src/app.py"])
    for does in CHANGES:
        asks(does, "~/Documents/specs/a.md", [READ_ONLY])
    asks("read", "~/Documents/tax.txt", [OUTSIDE])
    asks("read", "~/Documents/specs/a.md", [OUTSIDE], read_only=None)


# ---- links and .. --------------------------------------------------------------------


@pytest.mark.parametrize("does", DOES)
def test_a_link_that_leads_out_of_the_folder_asks_and_says_it_is_a_link(home, does):
    asks(does, "docs/tax.txt", [LINK])
    asks(does, "~/Projects/my-app/docs/tax.txt", [LINK])


def test_the_place_is_worked_out_from_the_path_as_given(home):
    # docs is a link to ~/Documents, so docs/.. is the home folder and not the project
    for does in DOES:
        asks(does, "docs/../x.txt", [LINK])
    free("read", "docs/specs/a.md")  # the link leads to a folder that may be read
    asks("write", "docs/specs/a.md", [LINK])
    free("write", "same/../README.md")


def test_a_link_out_of_the_folder_for_reading_is_said_to_be_a_link(home):
    os.symlink(os.path.join(home, "Documents", "tax.txt"), os.path.join(home, "Documents", "specs", "more"))
    asks("read", "~/Documents/specs/more", [LINK])
    asks("write", "~/Documents/specs/more", [OUTSIDE])


def test_a_link_into_a_system_folder_or_a_key_folder_is_judged_as_that_place(home):
    asks("read", "out/hosts", [LINK])
    never("write", "out/hosts", [SYSTEM])
    never("delete", "out/hosts", [SYSTEM])
    asks("read", "keys/config", [KEYS, LINK])
    never("write", "keys/authorized_keys", [KEYS])
    never("delete", "keys/known_hosts", [KEYS])


def test_a_link_that_goes_round_in_a_circle_does_not_stop_the_rule(home):
    for does in DOES:
        assert look(does, "round/a.txt").level in (FREE, NEEDS_YES)


# ---- where keys are kept -------------------------------------------------------------


@pytest.mark.parametrize("name", KEY_NAMES)
def test_every_key_place_asks_inside_the_folder_as_a_file_and_as_a_folder(home, name):
    for does in DOES:
        asks(does, f"config/{name}", [KEYS])
        asks(does, f"{name}/inner.txt", [KEYS])
        asks(does, f"{name.upper()}/inner.txt", [KEYS])


@pytest.mark.parametrize("name", KEY_NAMES)
def test_every_key_place_outside_the_folder_asks_for_a_read_and_is_never_changed(home, name):
    asks("read", f"~/{name}", [KEYS, OUTSIDE])
    asks("read", f"~/{name}/inner", [KEYS, OUTSIDE])
    for does in CHANGES:
        never(does, f"~/{name}", [KEYS])
        never(does, f"~/{name}/inner", [KEYS])


@pytest.mark.parametrize("pair", KEY_PAIRS)
def test_every_key_place_that_is_two_names_together_is_known(home, pair):
    asks("read", f"backup/{pair}", [KEYS])
    asks("read", f"backup/{pair}/inner.yml", [KEYS])
    asks("write", f"backup/{pair}", [KEYS])
    never("write", f"~/Documents/{pair}", [KEYS])
    first, second = pair.split("/")
    free("read", f"backup/{first}/other")
    free("read", f"backup/other/{second}x")
    free("read", f"backup/{second}/{first}x")


@pytest.mark.parametrize("stem", KEY_STEMS)
def test_every_file_named_for_what_it_holds_asks(home, stem):
    for name in (stem, f"{stem}.json", f"{stem.upper()}.txt", f"{stem}.prod.yaml"):
        asks("read", f"config/{name}", [KEYS])
        asks("write", f"config/{name}", [KEYS])
        never("delete", f"~/Documents/{name}", [KEYS])
    free("read", f"src/{stem}_reset.py")
    free("read", f"src/reset_{stem}.py")
    free("write", f"{stem}s2/readme.md")


@pytest.mark.parametrize("ending", KEY_ENDINGS)
def test_every_key_file_ending_asks(home, ending):
    asks("read", f"certs/server{ending}", [KEYS])
    asks("write", f"certs/SERVER{ending.upper()}", [KEYS])
    never("write", f"~/Documents/server{ending}", [KEYS])
    free("read", f"certs/server{ending}s.md")


def test_an_env_file_of_any_kind_asks_and_a_history_file_does(home):
    for name in (".env", ".env.local", ".env.production", ".envrc", ".zsh_history", ".bash_history", ".python_history"):
        asks("read", name, [KEYS])
        asks("read", f"~/{name}", [KEYS, OUTSIDE])
        never("write", f"~/{name}", [KEYS])
    for name in (".envoy.yaml", "env.md", "my.env.md", "order_history.py", ".history", "chat_history"):
        free("read", f"src/{name}")
        free("write", f"src/{name}")


@pytest.mark.parametrize("name", ["secrets", "credentials", "passwords", "server.pem", ".env.production", ".zsh_history", "Secrets", "secret.d"])
def test_a_folder_named_for_keys_covers_what_is_in_it(home, name):
    asks("read", f"{name}/prod.yaml", [KEYS])
    asks("write", f"deploy/{name}/a/b.txt", [KEYS])
    never("delete", f"~/Documents/{name}/prod.yaml", [KEYS])
    free("read", f"x-{name}-x/prod.yaml")


def test_a_link_with_the_name_of_a_key_file_asks_wherever_it_leads(home):
    app = os.path.join(home, "Projects", "my-app")
    os.symlink(os.path.join(app, "src", "app.py"), os.path.join(app, ".env.local"))
    for does in DOES:
        asks(does, ".env.local", [KEYS])


def test_the_contents_of_a_file_reached_past_its_name_ask(home):
    # macOS gives the contents of a file at file/..namedfork/data
    for does in DOES:
        asks(does, "src/app.py/..namedfork/data", [NOT_PLAIN])
        asks(does, "src/app.py/..NamedFork/rsrc", [NOT_PLAIN])
        asks(does, "certs/server.pem/..namedfork/data", [NOT_PLAIN, KEYS])
    never("write", "kettle.db/..namedfork/data", [PROTECTED])
    with pytest.raises(RulesError, match="must be one plain path"):
        rules.files(["~/Projects/my-app/a/..namedfork/data"], does="read")


@pytest.mark.parametrize("ending", EXAMPLE_ENDINGS)
def test_an_example_of_a_key_file_is_not_a_key_file(home, ending):
    for name in (f".env{ending}", f"credentials.json{ending}", f"server.pem{ending}", f".env.local{ending}"):
        free("read", name)
        free("write", f"config/{name}")
    asks("read", f".ssh/config{ending}", [KEYS])  # inside a key folder it still is one
    never("write", f"~/.ssh/config{ending}", [KEYS])
    asks("read", f".env{ending}x", [KEYS])


# ---- paths the owner protects --------------------------------------------------------


def test_a_protected_path_asks_for_a_read_and_is_never_changed(home):
    asks("read", "kettle.db", [PROTECTED])
    for does in CHANGES:
        never(does, "kettle.db", [PROTECTED])
        never(does, "~/Projects/my-app/kettle.db", [PROTECTED])
        never(does, "src/../kettle.db", [PROTECTED])
        never(does, ["README.md", "kettle.db"], [PROTECTED])
        free(does, "kettle.db2")
        free(does, "kettle.d")


def test_a_protected_path_is_found_under_another_spelling_and_through_a_link(home):
    for does in CHANGES:
        never(does, "KETTLE.DB", [PROTECTED])  # the same file on a disk that ignores capitals
        never(does, "src/data", [PROTECTED])  # a link to it
        never(does, "same/data", [PROTECTED])
    plain, split = unicodedata.normalize("NFC", "café.db"), unicodedata.normalize("NFD", "café.db")
    assert plain != split
    never("write", split, [PROTECTED], protect=[f"~/Projects/my-app/{plain}"])
    never("write", plain, [PROTECTED], protect=[f"~/Projects/my-app/{split}"])


def test_a_path_that_only_looks_like_the_protected_one_before_links_are_followed_is_refused_too(home):
    # docs is a link to ~/Documents, so docs/../kettle.db is really ~/kettle.db. A tool that
    # tidies the path before it follows links would land on the protected file.
    for does in CHANGES:
        never(does, "docs/../kettle.db", [PROTECTED])
        never(does, f"/{home}/Projects/my-app/docs/../kettle.db", [PROTECTED])
    asks("read", "docs/../kettle.db", [PROTECTED, LINK])


def test_a_protected_folder_covers_what_is_in_it_and_no_more(home):
    settings = {"protect": ["~/Projects/my-app/rules", "~/Projects/my-app/src/app.py"]}
    for does in CHANGES:
        never(does, "rules/lists.toml", [PROTECTED], **settings)
        never(does, "rules", [PROTECTED], **settings)
        never(does, "src/app.py", [PROTECTED], **settings)
        free(does, "rules2/lists.toml", **settings)
        free(does, "kettle.db", **settings)
    asks("read", "rules/lists.toml", [PROTECTED], **settings)


def test_a_link_the_owner_protects_covers_the_place_it_leads_to(home):
    for does in CHANGES:
        never(does, "~/Documents/tax.txt", [PROTECTED], protect=["~/Projects/my-app/docs"])
    never("write", "~/Documents/tax.txt", [PROTECTED], protect=["~/Projects/my-app/docs/tax.txt"])
    asks("write", "~/Documents/tax.txt", [OUTSIDE], protect=None)


# ---- system folders, the home folder, the whole machine ------------------------------


@pytest.mark.parametrize("name", SYSTEM_FOLDERS)
def test_every_system_folder_is_never_changed_and_a_read_of_it_asks(home, name):
    for path in (f"/{name}/kettle-x/a.conf", f"/{name}/a", f"/{name.upper()}/kettle-x/a"):
        never("write", path, [SYSTEM])
        never("delete", path, [SYSTEM])
        asks("read", path, [OUTSIDE])


def test_the_real_place_of_etc_is_a_system_folder_too(home):
    never("write", "/private/etc/hosts", [SYSTEM])
    never("delete", "/private/etc/kettle-x/a", [SYSTEM])
    asks("write", "/private/kettle-x/a/b", [OUTSIDE])
    asks("write", "/private/var/kettle-x/a", [OUTSIDE])
    asks("write", "/other/etc/a", [OUTSIDE])


def test_a_folder_of_the_owners_inside_a_system_folder_can_be_worked_in(home):
    folders = ["/usr/local/kettle-x"]
    free("write", "/usr/local/kettle-x/a.txt", folders=folders)
    free("delete", "/usr/local/kettle-x/a.txt", folders=folders)
    never("write", "/usr/local/kettle-y/a.txt", [SYSTEM], folders=folders)


def test_deleting_the_home_folder_or_a_folder_it_is_in_is_never_allowed(home):
    for path in ("~", "~/", home, home.upper(), os.path.dirname(home), "~/..", "~/Projects/.."):
        never("delete", path, [WHOLE])
    never("delete", ["src/app.py", "~"], [WHOLE])
    asks("delete", "~/Projects", [OUTSIDE, FOLDER])
    asks("write", "~", [OUTSIDE])
    asks("read", "~", [OUTSIDE])


def test_the_home_folder_reached_through_a_link_is_never_deleted(home):
    never("delete", "docs/..", [WHOLE])  # docs is a link to ~/Documents, so this is the home folder
    never("delete", "~/Projects/my-app/docs/../", [WHOLE])
    # and a path that is the home folder until links are followed: a tool might tidy it first
    os.symlink(os.path.join(home, "Projects", "my-app", "src"), os.path.join(home, "lnk"))
    never("delete", "~/lnk/..", [WHOLE])
    asks("delete", "~/lnk/../src", [FOLDER])


def test_a_home_folder_that_is_named_through_a_link_is_still_known(home, monkeypatch):
    named = os.path.join(os.path.dirname(home), "named")
    os.symlink(home, named)
    monkeypatch.setenv("HOME", named)
    made = rule("delete")
    assert made.settings()["home"] == named
    assert made.explain({"path": "~/Projects/my-app/src/app.py"}).level == FREE
    for path in ("~", home, "~/Projects/my-app/docs/..", "docs/.."):
        assert made.explain({"path": path}) == rules.Verdict(NEVER, (WHOLE,)), path


def test_deleting_a_top_folder_of_the_machine_is_never_allowed(home):
    for path in ("/", "//", "/.", "/Users", "/home", "/Volumes", "/opt", "/kettle-x", "/private", "/private/kettle-x", "/tmp/.."):
        assert look("delete", path).level == NEVER, path
        assert WHOLE in look("delete", path).reasons, path
    never("delete", "/opt", [WHOLE])
    never("delete", "/private/kettle-x", [WHOLE])
    asks("delete", "/opt/kettle-x", [OUTSIDE])
    asks("delete", "/private/kettle-x/a", [OUTSIDE])
    asks("delete", "/kettle-x/a", [OUTSIDE])


def test_the_home_folder_is_the_one_the_rule_was_made_with(home, monkeypatch):
    made = rule("delete")
    monkeypatch.setenv("HOME", os.path.join(home, "Projects"))
    assert made.explain({"path": "~/Projects/my-app/src/app.py"}).level == FREE
    assert made.explain({"path": home}) == rules.Verdict(NEVER, (WHOLE,))
    assert made.settings()["home"] == home


# ---- files that other tools run or obey ----------------------------------------------


@pytest.mark.parametrize("name", OBEYED_FOLDERS)
def test_changing_anything_in_a_folder_other_tools_obey_asks(home, name):
    for does in CHANGES:
        asks(does, f"{name}/hooks/pre-commit", [RUNS_ITSELF])
        asks(does, f"sub/{name.upper()}/config", [RUNS_ITSELF])
        asks(does, f"~/Library/{name}/a.plist", [OUTSIDE, RUNS_ITSELF])
    free("read", f"{name}/config")
    free("write", f"{name}x/config")
    free("write", f"x{name}/config")


@pytest.mark.parametrize("name", OBEYED_FILES)
def test_changing_a_file_that_runs_when_a_shell_or_git_starts_asks(home, name):
    for does in CHANGES:
        asks(does, name, [RUNS_ITSELF])
        asks(does, f"~/{name}", [OUTSIDE, RUNS_ITSELF])
        asks(does, f"sub/{name.upper()}", [RUNS_ITSELF])
        free(does, f"{name}/inner.txt")  # a folder that only has the name
    free("read", name)
    free("write", f"{name}.md")


def test_a_link_into_a_folder_other_tools_obey_is_seen(home):
    os.makedirs(os.path.join(home, "Projects", "my-app", ".git", "hooks"))
    os.symlink(os.path.join(home, "Projects", "my-app", ".git", "hooks"), os.path.join(home, "Projects", "my-app", "tools"))
    asks("write", "tools/pre-commit", [RUNS_ITSELF])
    free("read", "tools/pre-commit")


def test_a_link_with_the_name_of_a_folder_other_tools_obey_is_seen(home):
    os.symlink(os.path.join(home, "Projects", "my-app", "src"), os.path.join(home, "Projects", "my-app", ".husky"))
    asks("write", ".husky/pre-commit", [RUNS_ITSELF])
    asks("delete", ".husky/pre-commit", [RUNS_ITSELF])
    free("read", ".husky/pre-commit")


# ---- deleting folders and many files -------------------------------------------------


def test_deleting_a_whole_folder_asks(home):
    asks("delete", "src", [FOLDER])
    asks("delete", "~/Projects/my-app", [FOLDER])
    asks("delete", "same", [FOLDER])  # a link to a folder
    asks("delete", "not-there/", [FOLDER])  # written as a folder
    free("delete", "not-there")
    free("delete", "src/app.py")
    free("read", "src")
    free("write", "src")
    free("read", "not-there/")
    free("write", "not-there/")


def test_deleting_many_paths_at_once_asks(home):
    ten, eleven = [f"old/{number}.txt" for number in range(10)], [f"old/{number}.txt" for number in range(11)]
    free("delete", ten)
    asks("delete", eleven, [MANY.format(10)])
    free("read", eleven)
    free("write", eleven)
    free("delete", ["a", "b"], many=2)
    asks("delete", ["a", "b", "c"], [MANY.format(2)], many=2)
    asks("delete", ["a", "b"], [MANY.format(1)], many=1)
    free("delete", "a", many=1)
    free("delete", ["a"], many=1)


# ---- paths that are not written plainly ----------------------------------------------


@pytest.mark.parametrize("does", DOES)
def test_a_path_a_tool_might_work_out_into_another_place_asks(home, does):
    for path in ("$HOME/x.txt", "src/$NAME.txt", "src\\app.py", "src/`id`.txt", "C:/Users/x.txt", "c:x", " src/app.py", "src/app.py ", "\tsrc/app.py", "src/app.py\u00a0"):
        verdict = look(does, path)
        assert verdict.level == NEEDS_YES and NOT_PLAIN in verdict.reasons, path
    asks(does, "src/$NAME.txt", [NOT_PLAIN])
    asks(does, "src\\app.py", [NOT_PLAIN])
    asks(does, "src/`id`.txt", [NOT_PLAIN])
    asks(does, "src/app.py ", [NOT_PLAIN])
    asks(does, " /tmp/kettle-x/a", [NOT_PLAIN, RELATIVE], base=None)
    asks(does, "~sam/notes.txt", [NOT_PLAIN, RELATIVE])
    asks(does, "~sam", [NOT_PLAIN, RELATIVE])
    for path in ("src/a b.txt", "src/a~b.txt", "src/a:b.txt", "src/~", "src/C:"):
        free(does, path)


@pytest.mark.parametrize("does", DOES)
def test_a_path_with_a_pattern_asks(home, does):
    for path in ("src/*.py", "src/a?.py", "src/[ab].py", "*"):
        asks(does, path, [PATTERN])
    asks(does, "~/Documents/*", [PATTERN, OUTSIDE])


def test_a_pattern_does_not_hide_a_refusal(home):
    never("delete", "/*", [WHOLE])
    never("write", "/etc/*.conf", [SYSTEM])
    never("write", "/../../etc/hosts", [SYSTEM])


@pytest.mark.parametrize("does", DOES)
def test_a_path_with_a_character_that_cannot_be_seen_asks(home, does):
    for path in ("src/app.py\n", "src/a\u200bpp.py", "src/\x1bapp.py", "src/app\x7f.py", "src/a\u202epp.py"):
        verdict = look(does, path)
        assert verdict.level == NEEDS_YES and UNSEEN in verdict.reasons, path
    asks(does, "src/a\u200bpp.py", [UNSEEN])
    asks(does, "src/\x01app.py", [UNSEEN])
    asks(does, "src/a\tb.py", [UNSEEN])
    asks(does, "src/app\x00.py", [UNSEEN, UNREAD])


@pytest.mark.parametrize("does", DOES)
def test_a_path_that_does_not_start_from_the_top_needs_a_starting_folder(home, does):
    asks(does, "src/app.py", [RELATIVE], base=None)
    asks(does, "./src/app.py", [RELATIVE], base=None)
    asks(does, ["~/Projects/my-app/a", "b"], [RELATIVE], base=None)
    free(does, "~/Projects/my-app/src/app.py", base=None)
    free(does, f"{home}/Projects/my-app/src/app.py", base=None)
    free(does, "app.py", base="~/Projects/my-app/src")
    asks(does, "app.py", [OUTSIDE], base="~/Documents")
    asks(does, "kettle-x/app.py", [OUTSIDE], base="/")
    free(does, f"{home}/Projects/my-app/src/app.py"[1:], base="/")


# ---- inputs the rule cannot read, or was not told about ------------------------------


@pytest.mark.parametrize("does", DOES)
@pytest.mark.parametrize("value", [None, 5, "", [], [""], ["src/app.py", 5], ["src/app.py", ""], ("src/app.py",), {"a": 1}, b"src/app.py", True, [["src/app.py"]]])
def test_a_path_that_is_not_text_or_a_list_of_text_asks(home, does, value):
    verdict = rule(does).explain({"path": value})
    assert (verdict.level, list(verdict.reasons)) == (NEEDS_YES, [UNREAD])


@pytest.mark.parametrize("does", DOES)
def test_no_path_at_all_asks_and_so_do_inputs_that_are_not_a_dict(home, does):
    assert list(rule(does).explain({}).reasons) == [UNREAD]
    assert rule(does).explain(["src/app.py"]) == rules.Verdict(NEEDS_YES, ("the inputs cannot be read",))


@pytest.mark.parametrize("does", DOES)
def test_an_input_the_rule_was_not_told_about_asks(home, does):
    made = rule(does)
    assert list(made.explain({"path": "src/app.py", "recursive": True}).reasons) == [UNTOLD.format(1)]
    assert list(made.explain({"path": "src/app.py", "recursive": True, "force": True}).reasons) == [UNTOLD.format(2)]
    assert list(made.explain({"path": 5, "mode": "w"}).reasons) == [UNTOLD.format(1), UNREAD]
    assert list(made.explain({"path": "~/Documents/tax.txt", "mode": "w"}).reasons) == [UNTOLD.format(1), OUTSIDE]
    told = rule(does, ignore=["encoding", "recursive"])
    assert told({"path": "src/app.py", "encoding": "utf-8", "recursive": False}) == FREE
    assert list(told.explain({"path": "src/app.py", "encoding": "utf-8", "mode": "w"}).reasons) == [UNTOLD.format(1)]


def test_what_is_written_is_expected_only_by_a_rule_for_writing(home):
    assert rule("write")({"path": "src/app.py", "content": "print('hi')"}) == FREE
    assert rule("write")({"path": "src/app.py", "content": 5}) == FREE
    for does in ("read", "delete"):
        assert list(rule(does).explain({"path": "src/app.py", "content": "x"}).reasons) == [UNTOLD.format(1)]
    assert rule("write", content="text")({"path": "src/app.py", "text": "x"}) == FREE
    assert list(rule("write", content="text").explain({"path": "src/app.py", "content": "x"}).reasons) == [UNTOLD.format(1)]


def test_the_input_that_holds_the_path_can_be_named(home):
    made = rule("read", path="file")
    assert made({"file": "src/app.py"}) == FREE
    assert list(made.explain({"path": "src/app.py"}).reasons) == [UNTOLD.format(1), UNREAD]
    assert list(made.explain({"file": "~/Documents/tax.txt"}).reasons) == [OUTSIDE]


# ---- making the rule -----------------------------------------------------------------


def test_the_rule_is_one_of_the_names_the_module_gives_out_and_cannot_be_changed(home):
    made = rule("read")
    assert made.kind == "files" and "files" in rules.__all__ and isinstance(made, rules.Rule)
    for name in ("_folders", "_does", "_protect", "_read_only", "_base", "_home", "_many", "_ignored", "_fields", "anything"):
        with pytest.raises(AttributeError):
            setattr(made, name, ())
        with pytest.raises(AttributeError):
            delattr(made, name)


def test_the_settings_are_kept_whole_and_tidied(home):
    made = rules.files(
        ["~/Projects/my-app/", "~/Projects/my-app", f"{home}/Projects/./other"],
        does="write", read_only=["~/Documents/specs"], protect=["~/Projects/my-app/kettle.db", "~"], base="~/Projects/my-app/src/..", many=3,
        ignore=["mode", "encoding"], path="file", content="text",
    )
    assert made.settings() == {
        "does": "write",
        "folders": [f"{home}/Projects/my-app", f"{home}/Projects/other"],
        "read_only": [f"{home}/Documents/specs"],
        "protect": [f"{home}/Projects/my-app/kettle.db", home],
        "base": f"{home}/Projects/my-app",
        "home": home,
        "many": 3,
        "ignore": ["encoding", "mode"],
        "fields": {"path": "file", "content": "text"},
    }
    assert rules.files(does="read").settings()["base"] is None


def test_a_change_to_any_setting_changes_the_name_the_checkpoint_records(home):
    names = {
        rule(does, **settings).__qualname__
        for does in DOES
        for settings in ({}, {"many": 11}, {"base": None}, {"protect": None}, {"read_only": None}, {"folders": ["~/Projects/other"]}, {"ignore": ["mode"]}, {"path": "file"}, {"content": "text"})
    }
    assert len(names) == 27 and all(name.startswith("kettle.rules.files:") for name in names)
    assert rule("read").__qualname__ == rule("read").__qualname__


def test_the_owners_lists_are_copied_when_the_rule_is_made(home):
    folders, guarded = ["~/Projects/my-app"], ["~/Projects/my-app/kettle.db"]
    made = rules.files(folders, does="write", protect=guarded)
    folders.append("~/Documents")
    guarded.clear()
    assert made({"path": "~/Documents/tax.txt"}) == NEEDS_YES
    assert made({"path": "~/Projects/my-app/kettle.db"}) == NEVER


@pytest.mark.parametrize("does", [None, "", "Read", "append", "move", ["read"], 1])
def test_does_must_be_one_of_the_three(home, does):
    with pytest.raises(RulesError, match='does must be "read", "write" or "delete"'):
        rules.files(["~/Projects/my-app"], does=does)


def test_does_must_be_given(home):
    with pytest.raises(TypeError):
        rules.files(["~/Projects/my-app"])


@pytest.mark.parametrize("name", ["folders", "read_only", "protect"])
def test_a_list_of_places_must_be_a_list_of_plain_whole_paths(home, name):
    def make(value):
        return rules.files(does="read", **{name: value})

    for value in ("~/Projects/my-app", {"~/Projects/my-app"}, 5, {"a": 1}):
        with pytest.raises(RulesError, match=f"{name} must be a list of paths"):
            make(value)
    for value in ([5], [""], [None], [["~/a"]], ["~/Projects/my-app", b"x"]):
        with pytest.raises(RulesError, match=f"{name} must be a list of paths, each as text"):
            make(value)
    for value in (["~/a\nb"], ["~/a\u200bb"], ["~/a\x00"], ["~/a\tb"], ["~/a\x7fb"], ["~/a\u202eb"]):
        with pytest.raises(RulesError, match=f"{name}: a path holds a line break or a character that cannot be seen"):
            make(value)
    for value in (["~/Projects/*"], ["~/a?"], ["~/[ab]"], ["$HOME/a"], ["~/a\\b"], ["~sam/a"], ["C:/a"], [" ~/a"], ["~/a "], ["~/`a`"]):
        with pytest.raises(RulesError, match="must be one plain path, with no pattern and nothing to work out"):
            make(value)
    for value in (["Projects/my-app"], ["./a"], ["../a"], ["a"]):
        with pytest.raises(RulesError, match="must start from / or ~"):
            make(value)
    assert make(None).settings()[name] == []
    assert make([]).settings()[name] == []
    assert make(("~/Projects/my-app",)).settings()[name] == [f"{home}/Projects/my-app"]


@pytest.mark.parametrize("name", ["folders", "read_only"])
def test_the_home_folder_and_the_folders_of_the_system_cannot_be_given_as_a_place_to_work(home, name):
    whole = ["/", "~", "~/", home, os.path.dirname(home), "~/..", "/Users", "/opt", "/kettle-x", "/private", "/private/var", "/private/kettle-x"]
    system = [f"/{folder}" for folder in SYSTEM_FOLDERS] + [f"/{folder}/local" for folder in SYSTEM_FOLDERS] + ["/private/etc", "/ETC/x", "/Usr/Local"]
    for value in whole + system:
        with pytest.raises(RulesError, match="is the home folder or a folder of the system. Name the folders the agent works in"):
            rules.files(does="read", **{name: [value]})
    for value in ("/usr/local/kettle-x", "/opt/kettle-x", "/private/var/kettle-x", "/private/etc/kettle/x", "~/Projects", "/kettle-x/a"):
        assert rules.files(does="read", **{name: [value]}).settings()[name] == [value.replace("~", home)]


def test_anything_may_be_protected_and_the_starting_folder_may_be_anywhere(home):
    made = rules.files(does="write", protect=["/", "~", "/etc"], base="/")
    assert made.settings()["protect"] == ["/", home, "/etc"] and made.settings()["base"] == "/"
    assert made({"path": "/tmp/kettle-x/a"}) == NEVER
    assert rules.files(does="read", base="~").settings()["base"] == home
    assert rules.files(does="read", base="/usr").settings()["base"] == "/usr"


@pytest.mark.parametrize("base", [5, "", ["~/Projects/my-app"], ("~/a",), "Projects/my-app", "~/a*", "$HOME", "~/a\nb", b"/", ["~/a", "~/b"], []])
def test_the_starting_folder_must_be_one_plain_whole_path(home, base):
    with pytest.raises(RulesError, match="base must be one folder, as text" if type(base) is not str else "base"):
        rules.files(["~/Projects/my-app"], does="read", base=base)


@pytest.mark.parametrize("many", [0, -1, 1.5, "10", None, True, [10]])
def test_many_must_be_a_whole_number_of_one_or_more(home, many):
    with pytest.raises(RulesError, match="many must be a whole number, 1 or more"):
        rules.files(["~/Projects/my-app"], does="delete", many=many)


def test_the_names_of_inputs_must_be_text_and_different(home):
    for settings in ({"path": ""}, {"path": 5}, {"content": ""}, {"content": None}):
        with pytest.raises(RulesError, match="must be the name of an input, as text"):
            rules.files(does="write", **settings)
    with pytest.raises(RulesError, match="two of the input names given are the same"):
        rules.files(does="write", path="file", content="file")
    for ignore in ("mode", 5, None, [5], [""], {"a": 1}):
        with pytest.raises(RulesError, match="ignore must be a list of the names of inputs"):
            rules.files(does="write", ignore=ignore)
    with pytest.raises(RulesError, match="the input that holds the path cannot be ignored"):
        rules.files(does="write", ignore=["path"])
    with pytest.raises(RulesError, match="the input that holds the path cannot be ignored"):
        rules.files(does="write", path="file", ignore={"file"})
    assert rules.files(does="write", ignore=("mode",)).settings()["ignore"] == ["mode"]
    assert rules.files(does="write", ignore=frozenset({"mode"})).settings()["ignore"] == ["mode"]


def test_a_home_folder_that_cannot_be_worked_out_stops_the_rule_being_made(home, monkeypatch):
    for value in ("/", "//", "relative/home"):
        monkeypatch.setenv("HOME", value)
        with pytest.raises(RulesError, match="the home folder of this user cannot be worked out"):
            rules.files(does="read")
    monkeypatch.setenv("HOME", home + "/./")
    assert rules.files(does="read").settings()["home"] == home


# ---- with a real checkpoint ----------------------------------------------------------


def test_with_a_checkpoint_a_file_inside_is_written_and_one_outside_is_held_and_a_system_file_is_refused(home, tmp_path):
    from kettle import Checkpoint

    written = []
    write = rule("write")
    checkpoint = Checkpoint(str(tmp_path / "kettle.db"))
    try:
        checkpoint.tool("write_file", lambda path, content: written.append(path) or "written", level=write, describe=write.why, watch=["path"])
        statuses = [checkpoint.gate.request("write_file", {"path": path, "content": "x"}).status for path in ("src/app.py", "~/Documents/tax.txt", "/etc/hosts")]
    finally:
        checkpoint.close()
    assert statuses == ["ran", "held", "refused"]
    assert written == ["src/app.py"]
