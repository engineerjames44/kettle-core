"""A plain agent on the OpenAI Chat Completions API: one model, the test's tools, a short system prompt.

Like the Claude one it is a baseline with no defences of its own. Many other
servers speak the same API, so with base_url it can also run a model on your own
machine, or one hosted somewhere else.

There is no default model: name the one you want to test.

Needs the openai package: pip install "kettle-labs[openai]". Calling a paid API costs money.
"""

from __future__ import annotations

from typing import Any, Optional

from ..adapters import openai_assistant_message, openai_tool_messages, openai_tools
from .claude_agent import SYSTEM
from .runner import Agent, ToolBox

OPENAI_API = "https://api.openai.com/v1"


class OpenAIAgent:
    """Call it like a function: reply = agent(task, tools). It also counts the tokens it used."""

    def __init__(
        self,
        model: str,
        *,
        client: Any = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        system: str = SYSTEM,
        max_tokens: Optional[int] = None,
        max_turns: int = 20,
        request: Optional[dict] = None,
    ) -> None:
        """client is an openai.OpenAI() or anything with the same chat.completions.create().

        With no client, one is made for base_url, or for OpenAI's own address when
        there is none: OPENAI_BASE_URL in the shell is not used. With no api_key,
        the openai package reads OPENAI_API_KEY from the shell, but only for OpenAI's
        own address: with a base_url no key is sent unless you give one. Pass your
        own client to do anything else.

        max_tokens is sent as max_completion_tokens, and is not sent at all unless
        it is set. request holds extra arguments for every API call, for example
        {"temperature": 0}.
        """
        if type(model) is not str or not model:
            raise ValueError("name the model to test: there is no default")
        if client is None:
            import openai

            options = {"base_url": base_url or OPENAI_API}  # always given, so a setting in the shell cannot pick the address
            if api_key:
                options["api_key"] = api_key
            elif base_url:
                options["api_key"] = "no-key"  # a key stored in the shell for OpenAI is not sent to another address
            client = openai.OpenAI(**options)
        self._client = client
        self.model, self.system, self.max_tokens, self.max_turns = model, system, max_tokens, max_turns
        self.request = dict(request or {})
        self.input_tokens = self.output_tokens = self.api_calls = 0

    @property
    def settings(self) -> dict:
        """What to write in the report so the run can be repeated."""
        return {
            "api": "OpenAI chat completions",
            "api_address": str(getattr(self._client, "base_url", "not known")),
            "model": self.model,
            "system": self.system,
            "max_tokens": self.max_tokens,
            "max_turns": self.max_turns,
            "request": self.request,
        }

    def __call__(self, task: str, tools: ToolBox) -> str:
        tool_list = openai_tools(tools.specs)
        messages: list = [{"role": "system", "content": self.system}, {"role": "user", "content": task}]
        limit = {} if self.max_tokens is None else {"max_completion_tokens": self.max_tokens}
        for _ in range(self.max_turns):
            completion = self._client.chat.completions.create(model=self.model, messages=messages, tools=tool_list, **limit, **self.request)
            self.api_calls += 1
            usage = getattr(completion, "usage", None)
            self.input_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.output_tokens += getattr(usage, "completion_tokens", 0) or 0
            if not completion.choices:
                raise RuntimeError("the API sent back no reply")
            choice = completion.choices[0]
            message = choice.message
            text = message.content or ""
            if choice.finish_reason == "length":
                raise RuntimeError("the model ran out of output tokens before it finished (raise max_tokens)")
            if choice.finish_reason == "content_filter":
                return text or "[The reply was held back by a content filter.]"
            if getattr(message, "refusal", None):
                return text or message.refusal
            # Some servers that speak this API end a tool-calling turn with "stop", so the calls decide, not the finish reason.
            if not message.tool_calls:
                return text
            messages.append(openai_assistant_message(message))
            # One tool message for each call, in the order the model asked.
            messages += openai_tool_messages(message.tool_calls, tools.call)
        raise RuntimeError(f"the model had not finished after {self.max_turns} turns")


def openai_agent(model: str, **options: Any) -> Agent:
    return OpenAIAgent(model, **options)
