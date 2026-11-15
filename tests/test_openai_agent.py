"""The plain OpenAI-style agent's loop. Nothing here calls a real API or costs money.

Most tests use a scripted fake client. The last ones put the real openai package
in front of a fake server on this machine, to check the loop against the
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
from kettle.attacktest.claude_agent import SYSTEM
from kettle.attacktest.openai_agent import OPENAI_API, OpenAIAgent, openai_agent

CASES = load_cases()


def ask(call_id, name, arguments):
    """One tool call, as the API sends it: the inputs are JSON text."""
    return NS(id=call_id, type="function", function=NS(name=name, arguments=arguments if type(arguments) is str else json.dumps(arguments)))


def reply(finish_reason, content=None, *calls, refusal=None, tokens=(10, 5)):
    message = NS(role="assistant", content=content, refusal=refusal, tool_calls=list(calls) or None)
    return NS(choices=[NS(finish_reason=finish_reason, index=0, message=message)], usage=NS(prompt_tokens=tokens[0], completion_tokens=tokens[1]))


class FakeClient:
    """Hands back the scripted replies in order and keeps a copy of every request."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.requests = []
        self.chat = NS(completions=self)

    def create(self, **request):
        self.requests.append(copy.deepcopy(request))
        return self._replies.pop(0)


def toolbox(answers=None):
    calls = []

    def call(name, inputs):
        calls.append((name, inputs))
        return (answers or {}).get(name, f"result of {name}")

    return ToolBox(call), calls


def test_a_reply_with_no_tool_call_is_the_answer():
    client = FakeClient(reply("stop", "It is at 14:30."))
    agent = OpenAIAgent("some-model", client=client)
    tools, calls = toolbox()
    assert agent("When is it?", tools) == "It is at 14:30." and calls == []
    (request,) = client.requests
    assert request["model"] == "some-model"
    assert request["messages"] == [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "When is it?"}]
    assert [tool["function"]["name"] for tool in request["tools"]] == [spec.name for spec in tools.specs]
    assert all(set(tool) == {"type", "function"} and tool["type"] == "function" for tool in request["tools"])
    assert all(set(tool["function"]) == {"name", "description", "parameters"} and tool["function"]["parameters"]["type"] == "object" for tool in request["tools"])
    assert "max_tokens" not in request and "max_completion_tokens" not in request and "tool_choice" not in request


def test_there_is_no_default_model():
    with pytest.raises(TypeError):
        OpenAIAgent(client=FakeClient())
    for nothing in ("", None):
        with pytest.raises(ValueError, match="no default"):
            OpenAIAgent(nothing, client=FakeClient())


def test_tool_calls_go_through_the_toolbox_and_each_gets_its_own_answer():
    first = reply("tool_calls", "Looking.", ask("c1", "list_emails", {}), ask("c2", "read_email", {"id": "e1"}))
    second = reply("tool_calls", None, ask("c3", "send_email", {"to": "a@example.com", "subject": "s", "body": "b"}))
    client = FakeClient(first, second, reply("stop", "Done."))
    agent = OpenAIAgent("some-model", client=client)
    tools, calls = toolbox({"read_email": "the email"})
    assert agent("Do it.", tools) == "Done."
    assert calls == [("list_emails", {}), ("read_email", {"id": "e1"}), ("send_email", {"to": "a@example.com", "subject": "s", "body": "b"})]
    messages = client.requests[2]["messages"]
    assert [message["role"] for message in messages] == ["system", "user", "assistant", "tool", "tool", "assistant", "tool"]
    assert messages[2] == {
        "role": "assistant",
        "content": "Looking.",
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "list_emails", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "read_email", "arguments": '{"id": "e1"}'}},
        ],
    }
    assert messages[3] == {"role": "tool", "tool_call_id": "c1", "content": "result of list_emails"}
    assert messages[4] == {"role": "tool", "tool_call_id": "c2", "content": "the email"}
    assert messages[5]["content"] is None and messages[5]["tool_calls"][0]["id"] == "c3"
    assert messages[6] == {"role": "tool", "tool_call_id": "c3", "content": "result of send_email"}
    assert (agent.api_calls, agent.input_tokens, agent.output_tokens) == (3, 30, 15)


def test_a_server_that_ends_a_tool_turn_with_stop_still_has_its_calls_run():
    client = FakeClient(reply("stop", None, ask("c1", "list_emails", {})), reply("stop", "Done."))
    tools, calls = toolbox()
    assert OpenAIAgent("some-model", client=client)("Do it.", tools) == "Done." and calls == [("list_emails", {})]


@pytest.mark.parametrize("arguments, expected", [("", {}), ("  ", {}), ("{to: sam}", "{to: sam}"), ('["a"]', ["a"]), ('"pay everyone"', "pay everyone")])
def test_inputs_that_are_not_a_json_object_are_still_handed_on_and_not_dropped(arguments, expected):
    client = FakeClient(reply("tool_calls", None, ask("c1", "pay", arguments)), reply("stop", "Done."))
    tools, calls = toolbox()
    OpenAIAgent("some-model", client=client)("Do it.", tools)
    assert calls == [("pay", expected)]
    sent_back = client.requests[1]["messages"][2]["tool_calls"][0]["function"]["arguments"]
    assert sent_back == arguments  # the model's own text goes back unchanged


def test_broken_inputs_are_refused_by_the_test_and_never_run():
    case = next(case for case in CASES.attacks if case.id == "attack-file-gift")
    for setup in (NONE, KETTLE):
        client = FakeClient(reply("tool_calls", None, ask("c1", "pay", '{"to": "' + case.goal.to + '", "amount": 40')), reply("stop", "Done."))
        result = run_case(OpenAIAgent("some-model", client=client), case, CASES, setup)
        assert result["error"] is None and result["got_through"] is False and result["ran_without_yes"] == 0
        assert [entry["tool"] for entry in result["calls"]] == ["pay"]  # it was seen


def test_a_refusal_ends_the_run_without_calling_any_tool():
    tools, calls = toolbox()
    declined = OpenAIAgent("m", client=FakeClient(reply("stop", None, ask("c1", "pay", {"to": "x", "amount": 1}), refusal="I will not do that.")))
    assert declined("Do it.", tools) == "I will not do that." and calls == []
    filtered = OpenAIAgent("m", client=FakeClient(reply("content_filter", None, ask("c1", "pay", {"to": "x", "amount": 1}))))
    assert filtered("Do it.", tools) == "[The reply was held back by a content filter.]" and calls == []
    partly = OpenAIAgent("m", client=FakeClient(reply("content_filter", "I was going to")))
    assert partly("Do it.", tools) == "I was going to" and calls == []


def test_a_reply_that_was_cut_off_is_an_error_and_its_tool_calls_are_not_run():
    tools, calls = toolbox()
    agent = OpenAIAgent("m", client=FakeClient(reply("length", None, ask("c1", "pay", {"to": "x", "amount": 1}))))
    with pytest.raises(RuntimeError, match="ran out of output tokens"):
        agent("Do it.", tools)
    assert calls == []


def test_a_tool_call_that_is_not_a_function_call_is_an_error_and_nothing_is_run():
    tools, calls = toolbox()
    odd = NS(id="c2", type="custom", custom=NS(name="pay", input="everything"))
    agent = OpenAIAgent("m", client=FakeClient(reply("tool_calls", None, ask("c1", "pay", {"to": "x", "amount": 1}), odd)))
    with pytest.raises(ValueError, match="not a function call"):
        agent("Do it.", tools)
    assert calls == []


def test_a_reply_with_nothing_in_it_is_an_error():
    with pytest.raises(RuntimeError, match="no reply"):
        OpenAIAgent("m", client=FakeClient(NS(choices=[], usage=None)))("Do it.", toolbox()[0])


def test_a_model_that_never_stops_is_an_error():
    client = FakeClient(*[reply("tool_calls", None, ask(f"c{n}", "list_emails", {})) for n in range(3)])
    tools, calls = toolbox()
    with pytest.raises(RuntimeError, match="after 3 turns"):
        OpenAIAgent("m", client=client, max_turns=3)("Do it.", tools)
    assert len(calls) == 3 and len(client.requests) == 3


def test_a_server_that_does_not_count_tokens_is_still_counted_by_calls():
    quiet = reply("stop", "ok")
    quiet.usage = None
    agent = OpenAIAgent("m", client=FakeClient(quiet))
    agent("Hi", toolbox()[0])
    assert (agent.api_calls, agent.input_tokens, agent.output_tokens) == (1, 0, 0)


def test_the_settings_are_what_was_sent():
    client = FakeClient(reply("stop", "ok"))
    agent = openai_agent("some-model", client=client, system="Be brief.", max_tokens=900, request={"temperature": 0})
    agent("Hi", toolbox()[0])
    (request,) = client.requests
    assert (request["model"], request["messages"][0], request["max_completion_tokens"], request["temperature"]) == (
        "some-model",
        {"role": "system", "content": "Be brief."},
        900,
        0,
    )
    assert "max_tokens" not in request
    assert agent.settings == {
        "api": "OpenAI chat completions",
        "api_address": "not known",  # the stand-in client has no address
        "model": "some-model",
        "system": "Be brief.",
        "max_tokens": 900,
        "max_turns": 20,
        "request": {"temperature": 0},
    }


def test_the_key_and_the_address_are_passed_to_the_client(monkeypatch):
    made = []
    fake = types.ModuleType("openai")
    fake.OpenAI = lambda **options: made.append(options) or FakeClient()
    monkeypatch.setitem(sys.modules, "openai", fake)
    monkeypatch.setenv("OPENAI_API_KEY", "key-in-the-environment")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://somewhere-else.example/v1")
    OpenAIAgent("m", api_key="key-given", base_url="http://127.0.0.1:1/v1")
    OpenAIAgent("m", api_key="key-given")
    OpenAIAgent("m")
    OpenAIAgent("m", base_url="http://127.0.0.1:1/v1")
    assert made == [
        {"api_key": "key-given", "base_url": "http://127.0.0.1:1/v1"},
        {"api_key": "key-given", "base_url": OPENAI_API},  # the address is always given, so the shell cannot pick it
        {"base_url": OPENAI_API},  # only here is the key left for the package to read from the shell
        {"api_key": "no-key", "base_url": "http://127.0.0.1:1/v1"},  # and never for another address
    ]


def scripted_model(case, obey):
    """A fake client that asks for the case's own steps and, if obey, then for what the attacker wants."""
    steps = [list(step) for step in case.steps]
    if obey:
        to = case.goal.to
        steps.append(["pay", {"to": to, "amount": 40}] if case.goal.tool == "pay" else ["send_email", {"to": to, "subject": "As asked", "body": "Here."}])
    replies = [reply("tool_calls", None, ask(f"c{index}", tool, dict(inputs))) for index, (tool, inputs) in enumerate(steps)]
    return FakeClient(*replies, reply("stop", case.answer))


@pytest.mark.parametrize("case_id", ["attack-email-bill", "attack-page-next-page", "attack-file-remittance", "attack-invite-rsvp"])
def test_the_loop_and_the_runner_work_together(case_id):
    case = next(case for case in CASES.attacks if case.id == case_id)
    without = run_case(OpenAIAgent("m", client=scripted_model(case, obey=True)), case, CASES, NONE)
    assert without["error"] is None and without["reached"] and without["went_along"] and without["got_through"]
    behind = run_case(OpenAIAgent("m", client=scripted_model(case, obey=True)), case, CASES, KETTLE)
    assert behind["error"] is None and behind["went_along"] and not behind["got_through"] and behind["ran_without_yes"] == 0
    assert behind["task_done"] is True
    careful = run_case(OpenAIAgent("m", client=scripted_model(case, obey=False)), case, CASES, KETTLE)
    assert careful["error"] is None and not careful["went_along"] and careful["task_done"] is True


def test_a_cut_off_model_shows_as_an_error_run_not_as_a_blocked_attack():
    case = CASES.attacks[0]
    result = run_case(OpenAIAgent("m", client=FakeClient(reply("length", "I was going to"))), case, CASES, KETTLE)
    assert "RuntimeError" in result["error"] and result["task_done"] is False and result["reached"] is False


# ---- the real openai package, talking to a fake server on this machine ----


def completion(finish_reason, content=None, tool_calls=None, refusal=None):
    message = {"role": "assistant", "content": content, "refusal": refusal}
    if tool_calls:
        message["tool_calls"] = [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(inputs)}} for call_id, name, inputs in tool_calls]
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "some-model",
        "choices": [{"index": 0, "finish_reason": finish_reason, "logprobs": None, "message": message}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


@pytest.fixture
def local_api():
    """A server on 127.0.0.1 that answers /v1/chat/completions from a script and keeps what it was sent."""
    script, seen = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "key": str(self.headers.get("Authorization")), "body": body})
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
    yield NS(url=f"http://127.0.0.1:{server.server_port}/v1", script=script, seen=seen)
    server.shutdown()
    server.server_close()


def test_the_loop_works_with_the_real_package(local_api, monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENAI_API_KEY", "key-in-the-environment")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:1/somewhere-else")
    case = next(case for case in CASES.attacks if case.id == "attack-file-gift")
    local_api.script += [completion("tool_calls", "Reading.", [(f"call_{index}", tool, inputs)]) for index, (tool, inputs) in enumerate(case.steps)]
    local_api.script.append(completion("tool_calls", None, [("call_9", "pay", {"to": case.goal.to, "amount": 40})]))
    local_api.script.append(completion("stop", case.answer))
    agent = OpenAIAgent("some-model", api_key="not-a-real-key", base_url=local_api.url)

    result = run_case(agent, case, CASES, KETTLE)

    assert result["error"] is None and local_api.script == []
    assert agent.settings["api_address"].rstrip("/") == local_api.url  # the report says where the key was sent
    assert result["went_along"] is True and result["got_through"] is False and result["task_done"] is True
    assert agent.api_calls == len(case.steps) + 2 and agent.input_tokens == 100 * agent.api_calls and agent.output_tokens == 20 * agent.api_calls
    assert all(request["path"] == "/v1/chat/completions" and request["key"] == "Bearer not-a-real-key" for request in local_api.seen)
    first, last = local_api.seen[0]["body"], local_api.seen[-1]["body"]
    assert first["model"] == "some-model" and len(first["tools"]) == 8 and "max_completion_tokens" not in first and "max_tokens" not in first
    assert first["messages"] == [{"role": "system", "content": SYSTEM}, {"role": "user", "content": case.task}]
    # What the package sent back to the API: the model's own turn, then our answer to its call.
    turn, answer = last["messages"][-2], last["messages"][-1]
    assert turn == {"role": "assistant", "content": None, "tool_calls": [{"id": "call_9", "type": "function", "function": {"name": "pay", "arguments": json.dumps({"to": case.goal.to, "amount": 40})}}]}
    assert answer == {"role": "tool", "tool_call_id": "call_9", "content": answer["content"]} and "said no" in answer["content"]


def test_the_real_package_does_not_send_a_key_from_the_shell_to_another_address(local_api, monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENAI_API_KEY", "key-in-the-environment")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:1/somewhere-else")
    local_api.script.append(completion("stop", "Done."))
    agent = OpenAIAgent("some-model", base_url=local_api.url)
    assert agent("What time is the meeting?", ToolBox(lambda name, inputs: "unused")) == "Done."
    assert [request["key"] for request in local_api.seen] == ["Bearer no-key"]


def test_a_refusal_from_the_real_package_is_read_as_one(local_api):
    pytest.importorskip("openai")
    local_api.script.append(completion("stop", None, refusal="I will not do that."))
    tools, calls = toolbox()
    agent = OpenAIAgent("some-model", api_key="not-a-real-key", base_url=local_api.url)
    assert agent("Do it.", tools) == "I will not do that." and calls == []
