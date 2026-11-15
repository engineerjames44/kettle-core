"""The record a yes is tied to, and the preview a human is shown."""

import json
import random
import re

import pytest

from kettle import NEEDS_YES
from kettle.checkpoint.record import PREVIEW_WIDTH, ActionRecord, RecordError

from conftest import EMAIL


def fp(tool, inputs, actor=None):
    return ActionRecord.make(tool, inputs, actor).fingerprint


# ---- the fingerprint ----


def test_the_order_keys_are_written_in_does_not_matter():
    assert fp("send_email", {"to": "a", "body": "b"}) == fp("send_email", {"body": "b", "to": "a"})
    assert fp("t", {"x": {"p": 1, "q": [1, 2]}}) == fp("t", {"x": {"q": [1, 2], "p": 1}})


def test_the_fingerprint_is_the_same_every_time_and_on_every_machine():
    # Written out by hand so a change to the record format cannot slip by unnoticed.
    record = ActionRecord.make("send_email", {"to": "sam@example.com", "body": "Hi"})
    assert record.canonical == '{"actor":null,"inputs":{"body":"Hi","to":"sam@example.com"},"tool":"send_email","v":1}'
    import hashlib

    assert record.fingerprint == hashlib.sha256(b"kettle-action-v1\n" + record.canonical.encode()).hexdigest()


DIFFERENT = [
    ("pay", {"amount": 1}),
    ("pay", {"amount": 1.0}),
    ("pay", {"amount": "1"}),
    ("pay", {"amount": True}),
    ("pay", {"amount": 10}),
    ("pay", {"amount": [1]}),
    ("pay", {"amount": None}),
    ("pay", {}),
    ("pay", {"amount": 1, "to": None}),
    ("pay", {"Amount": 1}),
    ("pay", {"amount ": 1}),
    ("pay2", {"amount": 1}),
    ("pay", {"a": "café"}),
    ("pay", {"a": "café"}),
    ("pay", {"a": "cafe"}),
    ("pay", {"a": "cafe "}),
    ("pay", {"a": "cafe​"}),
    ("pay", {"a": ["x", "y"]}),
    ("pay", {"a": ["y", "x"]}),
    ("pay", {"a": "x", "b": "y"}),
    ("pay", {"a": "y", "b": "x"}),
    ("pay", {"a": {"b": "x"}}),
    ("pay", {"a.b": "x"}),
]


def test_anything_a_human_would_call_a_different_action_has_a_different_fingerprint():
    prints = [fp(tool, inputs) for tool, inputs in DIFFERENT]
    assert len(set(prints)) == len(DIFFERENT)


def test_who_is_asking_is_part_of_the_record():
    assert fp("pay", {"amount": 1}) != fp("pay", {"amount": 1}, actor="worker-2")
    assert fp("pay", {"amount": 1}, actor="worker-1") != fp("pay", {"amount": 1}, actor="worker-2")


def test_a_record_does_not_change_when_the_callers_inputs_do():
    inputs = {"to": "sam@example.com", "list": [1, 2]}
    record = ActionRecord.make("t", inputs)
    inputs["to"] = "thief@example.net"
    inputs["list"].append(3)
    assert record.inputs() == {"to": "sam@example.com", "list": [1, 2]}
    copy = record.inputs()
    copy["to"] = "thief@example.net"
    assert record.inputs()["to"] == "sam@example.com"


def _random_value(rng, depth=0):
    kinds = ["none", "bool", "int", "float", "str"] + (["list", "dict"] if depth < 4 else [])
    kind = rng.choice(kinds)
    if kind == "none":
        return None
    if kind == "bool":
        return rng.random() < 0.5
    if kind == "int":
        return rng.choice([0, -1, 1, 2**53, 2**64 + 1, -(10**30), rng.randint(-1000, 1000)])
    if kind == "float":
        return rng.choice([0.0, -0.0, 0.1, 1e308, 5e-324, 1.0, rng.uniform(-1e6, 1e6)])
    if kind == "str":
        alphabet = ['a', 'Z', ' ', '"', "\\", "\n", "\t", "\x00", "é", "​", "‮", "\U0001f600", "{", "}", ":", ","]
        return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
    if kind == "list":
        return [_random_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {_random_value_key(rng): _random_value(rng, depth + 1) for _ in range(rng.randint(0, 4))}


def _random_value_key(rng):
    return "".join(rng.choice(["a", "b", "to", " ", '"', "\n", "é", "\\"]) for _ in range(rng.randint(0, 5)))


def test_two_thousand_random_records_survive_being_stored_and_read_back():
    rng = random.Random(20261115)
    for _ in range(2000):
        inputs = {_random_value_key(rng): _random_value(rng) for _ in range(rng.randint(0, 5))}
        record = ActionRecord.make("tool", inputs)
        again = ActionRecord.from_canonical(record.canonical)
        assert again == record
        assert again.inputs() == record.inputs()
        # Shuffling the order the keys were given in changes nothing.
        keys = list(inputs)
        rng.shuffle(keys)
        assert ActionRecord.make("tool", {key: inputs[key] for key in keys}).fingerprint == record.fingerprint
        # The preview can always be written and always names the fingerprint.
        assert record.preview().endswith("Fingerprint: " + record.fingerprint)


def test_stored_text_that_was_altered_is_either_refused_or_has_a_different_fingerprint():
    rng = random.Random(7)
    record = ActionRecord.make("send_email", {"to": "sam@example.com", "body": "See you at 3.", "n": [1, 2.5, None, True]})
    text = record.canonical
    seen_refused = seen_different = 0
    for _ in range(3000):
        position = rng.randrange(len(text))
        choice = rng.random()
        if choice < 0.4:
            changed = text[:position] + rng.choice('abz019 ",:{}[]\\') + text[position + 1 :]
        elif choice < 0.7:
            changed = text[:position] + text[position + 1 :]
        else:
            changed = text[:position] + rng.choice('abz019 ",:{}[]\\') + text[position:]
        if changed == text:
            continue
        try:
            other = ActionRecord.from_canonical(changed)
        except RecordError:
            seen_refused += 1
            continue
        seen_different += 1
        assert other.fingerprint != record.fingerprint
        assert other.canonical == changed
    assert seen_refused and seen_different


@pytest.mark.parametrize(
    "text",
    [
        '{"actor":null,"inputs":{},"tool":"t","v":1} ',
        ' {"actor":null,"inputs":{},"tool":"t","v":1}',
        '{"actor":null,"inputs":{},"tool":"t","v":1,"extra":1}',
        '{"actor":null,"inputs":{},"tool":"t","v":2}',
        '{"actor":null,"inputs":{},"tool":"t","v":1.0}',
        '{"actor":null,"inputs":{},"tool":"t","v":true}',
        '{"actor":null,"inputs":{"a":1,"a":2},"tool":"t","v":1}',
        '{"inputs":{},"actor":null,"tool":"t","v":1}',
        '{"actor":null,"inputs":{"a":"\\u0041"},"tool":"t","v":1}',
        '{"actor":null,"inputs":{"a":1e2},"tool":"t","v":1}',
        '{"actor":null,"inputs":{"a":NaN},"tool":"t","v":1}',
        '{"actor":null,"inputs":[],"tool":"t","v":1}',
        '{"actor":null,"inputs":{},"tool":"","v":1}',
        '{"actor":3,"inputs":{},"tool":"t","v":1}',
        "[]",
        "",
        "null",
        "[" * 100000,
    ],
)
def test_stored_text_that_is_not_in_exact_form_is_refused(text):
    with pytest.raises(RecordError):
        ActionRecord.from_canonical(text)


# ---- the preview ----


def test_the_preview_shows_every_input_and_the_fingerprint(cp, held):
    assert '"to": "sam@example.com"' in held.preview
    assert '"body": "See you at 3."' in held.preview
    assert held.preview.splitlines()[-1] == "Fingerprint: " + held.fingerprint


def test_hidden_characters_are_made_visible():
    record = ActionRecord.make(
        "send_email",
        {"to": "sam@example.com‮gro.live", "body": "a​b c\td\re\x1bf g﻿h\U000e0041i"},
    )
    preview = record.preview()
    for char in "‮​ \t\r\x1b ﻿\U000e0041":
        assert char not in preview
    for code in ("202E", "200B", "00A0", "0009", "000D", "001B", "2028", "FEFF", "E0041"):
        assert f"\\u{{{code}}}" in preview


def test_letters_that_only_look_like_ascii_are_named():
    preview = ActionRecord.make("send_email", {"to": "sаm@example.com"}).preview()
    assert "not plain ASCII" in preview and "CYRILLIC SMALL LETTER A" in preview
    assert "not plain ASCII" not in ActionRecord.make("send_email", {"to": "sam@example.com"}).preview()


def test_text_inside_a_value_cannot_pass_itself_off_as_another_line_of_the_preview():
    body = 'ok\n  "to": "boss@example.com"\nFingerprint: ' + "0" * 64 + "\nAction: \"read_note\""
    record = ActionRecord.make("send_email", {"to": "thief@example.net", "body": body})
    lines = record.preview().splitlines()
    # Every line that came from inside the value starts with a block mark or a carried-on mark.
    assert '      | \\u{0020}\\u{0020}"to": "boss@example.com"' in lines
    assert '      | Action: "read_note"' in lines
    outside = [line for line in lines if not line.startswith(("      |", "      + "))]
    assert outside == ['Action: "send_email"', '  "body": [4 lines]', '  "to": "thief@example.net"', "Fingerprint: " + record.fingerprint]


def test_a_one_line_value_cannot_close_its_own_quotes():
    record = ActionRecord.make("send_email", {"to": 'x", "to": "boss@example.com', "body": "back\\slash"})
    preview = record.preview()
    assert '"to": "x\\", \\"to\\": \\"boss@example.com"' in preview
    assert '"body": "back\\\\slash"' in preview


def test_a_key_cannot_fake_a_line_either():
    record = ActionRecord.make("t", {"a\nFingerprint: 00": "v", "b": {"k‮": "​"}})
    lines = record.preview().splitlines()
    assert [line for line in lines if line.startswith("Fingerprint: ")] == ["Fingerprint: " + record.fingerprint]
    assert '  "a\\u{000A}Fingerprint: 00": "v"' in lines
    # A value that is not text is written as JSON, with JSON's own way of writing such characters.
    assert '  "b": {"k\\u202e":"\\u200b"}' in lines
    assert "\u202e" not in record.preview() and "\u200b" not in record.preview()


def test_nothing_is_cut_from_the_preview():
    body = "word " * 20000
    preview = ActionRecord.make("send_email", {"to": "a", "body": body}).preview()
    assert read_back(preview)["inputs"] == {"to": "a", "body": body}
    assert max(len(line) for line in preview.splitlines()) <= PREVIEW_WIDTH


# ---- the preview can be read back to exactly the record ----
#
# read_back() is only for these tests. If a preview can always be read back to the
# record it was written from, then two different records can never have the same
# preview: whatever differs between them shows somewhere on the page.


def _unescape(text, quoted):
    out, at = [], 0
    while at < len(text):
        char = text[at]
        if char != "\\":
            assert not (quoted and char == '"'), "a bare quote inside quoted text"
            out.append(char)
            at += 1
        elif text[at + 1] == "\\":
            out.append("\\")
            at += 2
        elif text[at + 1] == '"' and quoted:
            out.append('"')
            at += 2
        else:
            found = re.compile(r"\\u\{([0-9A-F]{4,6})\}").match(text, at)
            assert found, f"unknown escape at {at} in {text!r}"
            out.append(chr(int(found.group(1), 16)))
            at = found.end()
    return "".join(out)


def _read_value(rest, lines, indent):
    """Read one value. rest is what follows the label on its line; lines holds the lines after it."""
    block = re.fullmatch(r"\[(\d+) lines\]", rest)
    if block:
        parts = []
        for _ in range(int(block.group(1))):
            line = lines.pop(0)
            if line == indent + "|":
                parts.append("")
            else:
                assert line.startswith(indent + "| "), line
                parts.append(_unescape(line[len(indent) + 2 :], quoted=False))
        return "\n".join(parts)
    if rest.startswith('"'):
        assert rest.endswith('"') and len(rest) >= 2
        return _unescape(rest[1:-1], quoted=True)
    return json.loads(rest)


_WHOLE_CODE = re.compile(r"\\u\{[0-9A-F]{4,6}\}|\\u[0-9a-f]{4}|\\[^u]")


def read_back(preview):
    lines = []
    for line in preview.split("\n"):
        assert len(line) <= PREVIEW_WIDTH, "a line is too long"
        assert not line.endswith(" "), "a line ends with a space nobody could see"
        assert all(" " <= char <= "~" for char in line), "a character that is not plain printable ASCII"
        assert "  " not in line.lstrip(" "), "two spaces in a row, which nobody could count"
        mark = line.lstrip(" ")[:2]
        assert not (mark == "+ " and line.lstrip(" ")[2:3] == " "), "a carried-on line starts with a space"
        assert "\\" not in _WHOLE_CODE.sub("", line), "a code is cut in two where the line is cut"
        if mark == "! ":
            continue  # a note for the reader; it adds nothing to the record
        if mark == "+ ":
            lines[-1] += line.lstrip(" ")[2:]  # carried on from the line before
        else:
            lines.append(line)
    found = {"summary": None, "actor": None, "inputs": {}}
    if lines[0].startswith("Summary (written by the app): "):
        found["summary"] = _read_value(lines.pop(0)[len("Summary (written by the app): ") :], lines, "  ")
    assert lines[0].startswith("Action: ")
    found["tool"] = _read_value(lines.pop(0)[len("Action: ") :], lines, "  ")
    if lines[0].startswith("Asked through (set by the app): "):
        found["actor"] = _read_value(lines.pop(0)[len("Asked through (set by the app): ") :], lines, "  ")
    if lines[0] == "Inputs: none":
        lines.pop(0)
    while not lines[0].startswith("Fingerprint: "):
        line = lines.pop(0)
        label = re.match(r'  "((?:[^"\\]|\\.)*)": ?', line)
        assert label, line
        key = _unescape(label.group(1), quoted=True)
        assert key not in found["inputs"]
        found["inputs"][key] = _read_value(line[label.end() :], lines, "      ")
    found["fingerprint"] = lines.pop(0)[len("Fingerprint: ") :]
    assert lines == []
    return found


_TRICKY = [
    "a", "Z", "0", " ", "  ", "   ", '"', "\\", "\n", "\n\n", "\t", "\r", "\x00", "\x7f", "é", "а", "\u200b", "\u202e", "\u034f",
    "\U0001f600", "\U000e0041", "{", "}", ":", ",", "|", "| ", "+", "+ ", "! ", "u", "\\u{0020}", "\\u0020", "[2 lines]", "[",
    "Fingerprint: ", "Action: ", '  "to": "', "      | ", "      + ", "Inputs: none", "x" * 70, " " * 80, "word " * 30,
]


def _tricky_text(rng, most=8):
    return "".join(rng.choice(_TRICKY) for _ in range(rng.randint(0, most)))


def _tricky_value(rng, depth=0):
    kind = rng.choice(["text", "text", "text", "other"] + (["list", "dict"] if depth < 3 else []))
    if kind == "text":
        return _tricky_text(rng)
    if kind == "other":
        return rng.choice([None, True, False, 0, -7, 2**64 + 1, 0.1, 1.0, -0.0, 1e308])
    if kind == "list":
        return [_tricky_value(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    return {_tricky_text(rng, 3): _tricky_value(rng, depth + 1) for _ in range(rng.randint(0, 3))}


def test_three_thousand_random_previews_read_back_to_exactly_the_record_they_were_written_from():
    rng = random.Random(20261115)
    for _ in range(3000):
        tool = _tricky_text(rng, 3) or "tool"
        actor = rng.choice([None, _tricky_text(rng, 3)])
        inputs = {_tricky_text(rng, 3): _tricky_value(rng) for _ in range(rng.randint(0, 4))}
        summary = rng.choice([None, _tricky_text(rng, 4)])
        record = ActionRecord.make(tool, inputs, actor)
        found = read_back(record.preview(summary))
        assert found["summary"] == (summary or None)
        assert found["fingerprint"] == record.fingerprint
        # Compared as records, so 1 and 1.0, or 0.0 and -0.0, do not pass for each other.
        assert ActionRecord.make(found["tool"], found["inputs"], found["actor"]) == record


def test_spaces_nobody_could_count_are_written_out():
    plain = ActionRecord.make("send_email", {"to": "sam@example.com"}).preview()
    trailing = ActionRecord.make("send_email", {"to": "sam@example.com "}).preview()
    leading = ActionRecord.make("send_email", {"to": " sam@example.com"}).preview()
    double = ActionRecord.make("send_email", {"to": "sam  smith"}).preview()
    assert '"to": "sam@example.com\\u{0020}"' in trailing
    assert '"to": "\\u{0020}sam@example.com"' in leading
    assert '"to": "sam\\u{0020}\\u{0020}smith"' in double
    assert len({plain, trailing, leading}) == 3


def test_a_long_run_of_spaces_cannot_push_part_of_a_value_off_the_side_of_the_page():
    record = ActionRecord.make("send_email", {"to": "sam@example.com," + " " * 300 + "thief@example.net"})
    lines = record.preview().splitlines()
    assert max(len(line) for line in lines) <= PREVIEW_WIDTH
    # The second address is on a carried-on line of the same value, a few lines down, in plain sight.
    assert [line for line in lines if "thief@example.net" in line] == ['      + \\u{0020}thief@example.net"']
    assert read_back(record.preview())["inputs"] == record.inputs()


def test_a_hidden_character_shows_where_it_is_and_how_many_times():
    previews = {ActionRecord.make("t", {"to": to}).preview() for to in ("ab", "a\u034fb", "a\u034f\u034fb", "\u034fab", "ab\u034f")}
    assert len(previews) == 5
    assert '"to": "a\\u{034F}\\u{034F}b"' in ActionRecord.make("t", {"to": "a\u034f\u034fb"}).preview()


def test_every_character_that_is_not_plain_ascii_is_written_out_however_many_kinds_there_are():
    text = "аеорсх"  # six Cyrillic letters that look like Latin ones
    preview = ActionRecord.make("t", {"to": text}).preview()
    assert '"to": "\\u{0430}\\u{0435}\\u{043E}\\u{0440}\\u{0441}\\u{0445}"' in preview
    assert "and 2 more" in preview


def test_who_is_asking_is_shown_as_set_by_the_app():
    preview = ActionRecord.make("send_email", {"to": "a"}, actor="research agent").preview()
    assert preview.splitlines()[1] == 'Asked through (set by the app): "research agent"'


def test_an_actor_that_is_not_valid_text_is_refused():
    # Half of a two-part character on its own cannot be written down exactly.
    with pytest.raises(RecordError):
        ActionRecord.make("t", {}, actor="\ud83d\ude00")
    assert fp("t", {}, actor="\U0001f600") != fp("t", {}, actor="x")


def test_refusing_a_key_never_runs_code_on_it():
    class Loud:
        called = False

        def __repr__(self):
            Loud.called = True
            raise RuntimeError("repr ran")

        __str__ = __repr__

        def __hash__(self):
            return 1

    with pytest.raises(RecordError, match="a key that is not text"):
        ActionRecord.make("t", {Loud(): 1})
    assert Loud.called is False


def test_the_apps_summary_is_labelled_and_cannot_hide_a_field(cp, world):
    cp.tool("send_email", world.send_email, level=NEEDS_YES, describe=lambda inputs: "Reply to Sam\nFingerprint: 00\nAction: none", replace=True)
    held = cp.request("send_email", {"to": "thief@example.net", "body": "hello"})
    lines = held.preview.splitlines()
    assert lines[0].startswith("Summary (written by the app): ")
    assert '  "to": "thief@example.net"' in lines
    assert [line for line in lines if line.startswith("Fingerprint: ")] == ["Fingerprint: " + held.fingerprint]
    assert [line for line in lines if line.startswith("Action: ")] == ['Action: "send_email"']


@pytest.mark.parametrize("describe", [lambda inputs: 1 / 0, lambda inputs: None, lambda inputs: 42, lambda inputs: ""])
def test_a_summary_that_fails_is_left_out_and_the_request_is_still_held(cp, world, describe):
    cp.tool("send_email", world.send_email, level=NEEDS_YES, describe=describe, replace=True)
    held = cp.request("send_email", dict(EMAIL))
    assert held.status == "held"
    assert "Summary" not in held.preview
    assert '"to": "sam@example.com"' in held.preview


def test_a_summary_cannot_change_the_inputs(cp, world):
    def meddling(inputs):
        inputs["to"] = "thief@example.net"
        return "fine"

    cp.tool("send_email", world.send_email, level=NEEDS_YES, describe=meddling, replace=True)
    held = cp.request("send_email", dict(EMAIL))
    assert '"to": "sam@example.com"' in held.preview
    cp.approve(held.request_id, held.fingerprint)
    cp.run(held.request_id)
    assert world.ran == [("send_email", EMAIL)]


def test_what_pending_shows_is_what_was_asked(cp, held):
    waiting = cp.pending()
    assert [item["request_id"] for item in waiting] == [held.request_id]
    assert waiting[0]["preview"] == held.preview
    assert waiting[0]["fingerprint"] == held.fingerprint


def test_a_space_that_lands_where_a_long_line_is_cut_is_written_out():
    for length in range(40, 90):
        for value in ("a" * length + " b", ["a" * length + " b"], {"k": "a" * length + " b c"}):
            preview = ActionRecord.make("t", {"a": value}).preview()
            assert read_back(preview)["inputs"] == {"a": value}
            for line in preview.split("\n"):
                assert not line.endswith(" ") and not re.match(r" *\+  ", line), line
    cut_at_the_space = ActionRecord.make("t", {"a": "a" * 62 + " b"}).preview().split("\n")
    assert cut_at_the_space[2] == "      + \\u{0020}b\""
    cut_at_the_space = ActionRecord.make("t", {"a": ["a" * 61 + " b"]}).preview().split("\n")
    assert cut_at_the_space[2] == "      + \\u0020b\"]"


def test_inside_a_list_or_dict_spaces_nobody_could_count_and_unseen_characters_are_written_out():
    preview = ActionRecord.make("t", {"a": ["x  y", {"k  k": "\x7f\u200b"}]}).preview()
    assert '  "a": ["x\\u0020\\u0020y",{"k\\u0020\\u0020k":"\\u007f\\u200b"}]' in preview.split("\n")
    assert read_back(preview)["inputs"] == {"a": ["x  y", {"k  k": "\x7f\u200b"}]}


def test_inside_a_list_or_dict_a_code_is_never_cut_in_two():
    for length in range(40, 80):
        for odd in ("\u202e", "\n", '"', "\\", "\U0001f600"):
            record = ActionRecord.make("t", {"k": ["a" * length + odd + "b"]})
            found = read_back(record.preview())  # the reader refuses a line that ends part-way through a code
            assert ActionRecord.make(found["tool"], found["inputs"], found["actor"]) == record
    lines = ActionRecord.make("t", {"k": ["a" * 59 + "\u202e" * 3]}).preview().split("\n")
    assert lines[1:3] == ['  "k": ["' + "a" * 59, "      + \\u202e\\u202e\\u202e\"]"]


def test_a_key_so_long_that_its_value_starts_on_the_next_line_is_still_read_one_way():
    for length in range(55, 75):
        for value in ("v", ["v"], "one\ntwo", 7):
            preview = ActionRecord.make("t", {"k" * length: value}).preview()
            assert read_back(preview)["inputs"] == {"k" * length: value}
    lines = ActionRecord.make("t", {"k" * 65: ["v"]}).preview().split("\n")
    assert lines[1:3] == ['  "' + "k" * 65 + '":', '      + ["v"]']
