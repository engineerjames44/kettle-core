"""A checkpoint in front of the tools of a tool loop. No model, no network, nothing real is sent.

Run it from the project folder:  .venv/bin/python examples/with_checkpoint.py

A script plays the model, so you can see the whole loop without an API key. Its
replies are in the shape the Anthropic Messages API sends. With a real model you
keep the three numbered lines and put your API call where the script is.

You are asked in the terminal before the email goes. Type yes, or anything else to refuse.
"""

from kettle import FREE, NEEDS_YES, Checkpoint
from kettle.adapters import anthropic_tool_results, ask_in_terminal, through

sent = []


def read_notes():
    return "Send the meeting time (3pm) to sam@example.com."


def send_email(to, body):
    sent.append((to, body))  # a real app would send here
    return "sent"


cp = Checkpoint(":memory:")  # give a file name instead to keep the state and the log
cp.tool("read_notes", read_notes, level=FREE)
cp.tool("send_email", send_email, level=NEEDS_YES, watch=["to"])  # watch: mark a recipient that is new

# (1) Every tool call goes through the checkpoint. A held one is shown to you in the terminal.
call = through(cp.gate, ask_in_terminal(cp))

# What the model sends back, turn by turn.
SCRIPT = [
    [{"type": "tool_use", "id": "call_1", "name": "read_notes", "input": {}}],
    [{"type": "tool_use", "id": "call_2", "name": "send_email", "input": {"to": "sam@example.com", "body": "The meeting is at 3pm."}}],
    [{"type": "text", "text": "Done."}],
]

messages = [{"role": "user", "content": "Read my notes and do what they say."}]
for content in SCRIPT:  # with a real model: content = client.messages.create(...).content
    results = anthropic_tool_results(content, call)  # (2) run what the model asked for
    if not results:
        break  # the model asked for no tool, so it is done
    messages += [{"role": "assistant", "content": content}, {"role": "user", "content": results}]  # (3) send the results back
    for result in results:
        print("The model is told:", result["content"])

print()
print("Emails sent:", sent)
print("Log check:", cp.verify_log())
