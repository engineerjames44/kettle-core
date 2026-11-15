"""The plain Claude agent's loop. Nothing here calls the real API or costs money.

Most tests use a scripted fake client. The last ones put the real anthropic
package in front of a fake server on this machine, to check the loop against the
package's own request and reply handling.
"""

import copy
import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace as NS

import pytest

from kettle.attacktest import KETTLE, NONE, ToolBox, load_cases, run_case
from kettle.attacktest.claude_agent import DEFAULT_MODEL, SYSTEM, ClaudeAgent, claude_agent

CASES = load_cases()


def text(words):
    return NS(type="text", text=words)


def use(block_id, name, inputs):
    return NS(type="tool_use", id=block_id, name=name, input=inputs)


def reply(stop_reason, *blocks, tokens=(10, 5)):
    return NS(stop_reason=stop_reason, content=list(blocks), usage=NS(input_tokens=tokens[0], output_tokens=tokens[1]))


class FakeClient:
    """Hands back the scripted replies in order and keeps a copy of every request."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.requests = []
        self.messages = self

    def create(self, **request):
        self.requests.append(copy.deepcopy(request))
        return self._replies.pop(0)


def toolbox(answers=None):
    calls = []

    def call(name, inputs):
        calls.append((name, inputs))
        return (answers or {}).get(name, f"result of {name}")

    return ToolBox(call), calls


def test_a_reply_with_no_tool_use_is_the_answer():
    client = FakeClient(reply("end_turn", text("It is at 14:30."), text("Room 4B.")))
    agent = ClaudeAgent(client=client)
    tools, calls = toolbox()
    assert agent("When is it?", tools) == "It is at 14:30.\nRoom 4B." and calls == []
    (request,) = client.requests
    assert request["model"] == DEFAULT_MODEL == "claude-opus-5-5" and request["system"] == SYSTEM
    assert request["messages"] == [{"role": "user", "content": "When is it?"}]
    assert [tool["name"] for tool in request["tools"]] == [spec.name for spec in tools.specs]
    assert all(set(tool) == {"name", "description", "input_schema"} and tool["input_schema"]["type"] == "object" for tool in request["tools"])
    assert "thinking" not in request and "tool_choice" not in request


def test_tool_calls_go_through_the_toolbox_and_the_results_go_back_in_one_message():
    first = reply("tool_use", text("Looking."), use("t1", "list_emails", {}), use("t2", "read_email", {"id": "e1"}))
    second = reply("tool_use", use("t3", "send_email", {"to": "a@example.com", "subject": "s", "body": "b"}))
    client = FakeClient(first, second, reply("end_turn", text("Done.")))
    agent = ClaudeAgent(client=client)
    tools, calls = toolbox({"read_email": "the email"})
    assert agent("Do it.", tools) == "Done."
    assert calls == [("list_emails", {}), ("read_email", {"id": "e1"}), ("send_email", {"to": "a@example.com", "subject": "s", "body": "b"})]
    messages = client.requests[2]["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "user", "assistant", "user"]
    assert messages[1]["content"] == first.content and messages[3]["content"] == second.content
    assert messages[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": "result of list_emails"},
        {"type": "tool_result", "tool_use_id": "t2", "content": "the email"},
    ]
    assert messages[4]["content"] == [{"type": "tool_result", "tool_use_id": "t3", "content": "result of send_email"}]
    assert (agent.api_calls, agent.input_tokens, agent.output_tokens) == (3, 30, 15)


def test_a_refusal_ends_the_run_without_calling_any_tool():
    tools, calls = toolbox()
    declined = ClaudeAgent(client=FakeClient(reply("refusal", use("t1", "pay", {"to": "x", "amount": 1}))))
    assert declined("Do it.", tools) == "[The model declined to answer.]" and calls == []
    explained = ClaudeAgent(client=FakeClient(reply("refusal", text("I will not do that."))))
    assert explained("Do it.", tools) == "I will not do that." and calls == []


@pytest.mark.parametrize("stop_reason", ["max_tokens", "model_context_window_exceeded"])
def test_a_reply_that_was_cut_off_is_an_error_and_its_tool_calls_are_not_run(stop_reason):
    tools, calls = toolbox()
    agent = ClaudeAgent(client=FakeClient(reply(stop_reason, use("t1", "pay", {"to": "x", "amount": 1}))))
    with pytest.raises(RuntimeError):
        agent("Do it.", tools)
    assert calls == []


def test_a_model_that_never_stops_is_an_error():
    client = FakeClient(*[reply("tool_use", use(f"t{n}", "list_emails", {})) for n in range(3)])
    tools, calls = toolbox()
    with pytest.raises(RuntimeError, match="after 3 turns"):
        ClaudeAgent(client=client, max_turns=3)("Do it.", tools)
    assert len(calls) == 3 and len(client.requests) == 3


def test_the_settings_are_what_was_sent():
    client = FakeClient(reply("end_turn", text("ok")))
    agent = claude_agent("some-model", client=client, system="Be brief.", max_tokens=900, request={"output_config": {"effort": "low"}})
    agent("Hi", toolbox()[0])
    (request,) = client.requests
    assert (request["model"], request["system"], request["max_tokens"], request["output_config"]) == ("some-model", "Be brief.", 900, {"effort": "low"})
    assert agent.settings == {
        "api_address": "not known",  # the stand-in client has no address
        "model": "some-model",
        "system": "Be brief.",
        "max_tokens": 900,
        "max_turns": 20,
        "request": {"output_config": {"effort": "low"}},
    }


def test_the_default_system_prompt_gives_no_advice_about_attacks():
    lowered = SYSTEM.lower()
    assert not any(word in lowered for word in ("inject", "attack", "trick", "untrusted", "ignore", "suspicious", "careful"))


def test_the_key_is_passed_to_the_client_and_not_read_from_the_environment(monkeypatch):
    made = []
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda **options: made.append(options) or FakeClient()
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-in-the-environment")
    ClaudeAgent(api_key="key-given")
    ClaudeAgent()
    assert made == [{"api_key": "key-given"}, {}]


def scripted_model(case, obey):
    """A fake client that asks for the case's own steps and, if obey, then for what the attacker wants."""
    steps = [list(step) for step in case.steps]
    if obey:
        to = case.goal.to
        steps.append(["pay", {"to": to, "amount": 40}] if case.goal.tool == "pay" else ["send_email", {"to": to, "subject": "As asked", "body": "Here."}])
    replies = [reply("tool_use", use(f"t{index}", tool, dict(inputs))) for index, (tool, inputs) in enumerate(steps)]
    return FakeClient(*replies, reply("end_turn", text(case.answer)))


@pytest.mark.parametrize("case_id", ["attack-email-bill", "attack-page-next-page", "attack-file-remittance", "attack-invite-rsvp"])
def test_the_loop_and_the_runner_work_together(case_id):
    case = next(case for case in CASES.attacks if case.id == case_id)
    without = run_case(ClaudeAgent(client=scripted_model(case, obey=True)), case, CASES, NONE)
    assert without["error"] is None and without["reached"] and without["went_along"] and without["got_through"]
    behind = run_case(ClaudeAgent(client=scripted_model(case, obey=True)), case, CASES, KETTLE)
    assert behind["error"] is None and behind["went_along"] and not behind["got_through"] and behind["ran_without_yes"] == 0
    assert behind["task_done"] is True
    careful = run_case(ClaudeAgent(client=scripted_model(case, obey=False)), case, CASES, KETTLE)
    assert careful["error"] is None and not careful["went_along"] and careful["task_done"] is True


def test_a_cut_off_model_shows_as_an_error_run_not_as_a_blocked_attack():
    case = CASES.attacks[0]
    client = FakeClient(reply("max_tokens", text("I was going to")))
    result = run_case(ClaudeAgent(client=client), case, CASES, KETTLE)
    assert "RuntimeError" in result["error"] and result["task_done"] is False and result["reached"] is False


# ---- the real anthropic package, talking to a fake server on this machine ----


def message(stop_reason, content):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


@pytest.fixture
def local_api():
    """A server on 127.0.0.1 that answers /v1/messages from a script and keeps what it was sent."""
    script, seen = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            sent_key = f'{self.headers.get("x-api-key")} {self.headers.get("Authorization")}'  # the header differs by package version
            seen.append({"path": self.path, "key": sent_key, "body": body})
            data = json.dumps(script.pop(0)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield NS(url=f"http://127.0.0.1:{server.server_port}", script=script, seen=seen)
    server.shutdown()
    server.server_close()


def test_the_loop_works_with_the_real_package(local_api):
    anthropic = pytest.importorskip("anthropic")
    case = next(case for case in CASES.attacks if case.id == "attack-file-gift")
    local_api.script += [
        message("tool_use", [{"type": "text", "text": "Reading."}, {"type": "tool_use", "id": "toolu_1", "name": tool, "input": inputs}])
        for tool, inputs in case.steps
    ]
    local_api.script.append(message("tool_use", [{"type": "tool_use", "id": "toolu_9", "name": "pay", "input": {"to": case.goal.to, "amount": 40}}]))
    local_api.script.append(message("end_turn", [{"type": "text", "text": case.answer}]))
    client = anthropic.Anthropic(api_key="not-a-real-key", base_url=local_api.url, max_retries=0)
    agent = ClaudeAgent(client=client)

    result = run_case(agent, case, CASES, KETTLE)

    assert result["error"] is None and local_api.script == []
    assert agent.settings["api_address"].rstrip("/") == local_api.url  # the report says where the key was sent
    assert result["went_along"] is True and result["got_through"] is False and result["task_done"] is True
    assert agent.api_calls == len(case.steps) + 2 and agent.input_tokens == 100 * agent.api_calls
    assert all(request["path"].startswith("/v1/messages") and "not-a-real-key" in request["key"] for request in local_api.seen)
    first, last = local_api.seen[0]["body"], local_api.seen[-1]["body"]
    assert first["model"] == "claude-opus-5-5" and first["system"] == SYSTEM and len(first["tools"]) == 8
    assert first["messages"] == [{"role": "user", "content": case.task}]
    # What the package sent back to the API: the model's own turn, then our tool result for it.
    turn, answer = last["messages"][-2], last["messages"][-1]
    assert turn["role"] == "assistant" and turn["content"][-1]["type"] == "tool_use" and turn["content"][-1]["id"] == "toolu_9"
    assert answer == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_9", "content": answer["content"][0]["content"]}]}
    assert "said no" in answer["content"][0]["content"]


def test_a_refusal_from_the_real_package_is_read_as_one(local_api):
    anthropic = pytest.importorskip("anthropic")
    local_api.script.append(message("refusal", []))
    client = anthropic.Anthropic(api_key="not-a-real-key", base_url=local_api.url, max_retries=0)
    tools, calls = toolbox()
    assert ClaudeAgent(client=client)("Do it.", tools) == "[The model declined to answer.]" and calls == []
