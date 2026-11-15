"""The checkpoint in one file. No model, no network, nothing real is sent.

Run it from the project folder:  .venv/bin/python examples/quickstart.py
"""

from kettle import FREE, NEEDS_YES, NEVER, Checkpoint

sent = []


def read_inbox():
    return "1 new email, from Sam"


def send_email(to, body):
    sent.append((to, body))  # a real app would send here
    return "sent"


cp = Checkpoint(":memory:")  # give a file name instead to keep the state and the log
cp.tool("read_inbox", read_inbox, level=FREE)
cp.tool("send_email", send_email, level=NEEDS_YES)
cp.tool("delete_account", level=NEVER)

# The model's side of the app gets cp.gate, which can only ask.
gate = cp.gate

print("1. A free tool runs straight away:")
print("  ", gate.request("read_inbox", {}).result)

print("\n2. A risky tool is held. Nothing has been sent:")
held = gate.request("send_email", {"to": "sam@example.com", "body": "See you at 3."})
print("   status:", held.status, "| sent so far:", sent)
print("\n   What the human is shown:\n")
print("   " + held.preview.replace("\n", "\n   "))

print("\n3. The human says yes to that exact action, and it runs once:")
cp.approve(held.request_id, held.fingerprint)
print("   first run: ", cp.run(held.request_id).status, "| sent:", sent)
print("   second run:", cp.run(held.request_id).status, "| sent:", sent)

print("\n4. A tool marked NEVER, and a tool that is not listed, are refused:")
print("  ", gate.request("delete_account", {}).reason)
print("  ", gate.request("transfer_everything", {}).reason)

print("\n5. The log of what happened:")
for entry in cp.log():
    print("  ", entry["seq"], entry["event"], entry["tool"] or "")
print("   log check:", cp.verify_log())
