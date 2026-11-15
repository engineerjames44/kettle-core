"""A separate process that tries to use a yes. Run by test_workers.py.

usage: _worker.py DB REQUEST_ID OUT_FILE GO_FILE MODE
MODE is "run" (carry out the request) or "crash" (the process dies inside the tool).
Prints the decision status.
"""

import os
import sys
import time

from kettle import NEEDS_YES, Checkpoint

db, request_id, out_file, go_file, mode = sys.argv[1:6]


def send_email(to, body):
    # One line per real send. O_APPEND so lines from different processes never overwrite each other.
    handle = os.open(out_file, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    os.write(handle, f"{os.getpid()} {to}\n".encode())
    os.close(handle)
    if mode == "crash":
        os._exit(17)
    return "sent"


checkpoint = Checkpoint(db)
checkpoint.tool("send_email", send_email, level=NEEDS_YES)
deadline = time.time() + 30
while not os.path.exists(go_file) and time.time() < deadline:
    time.sleep(0.001)
print(checkpoint.run(request_id).status)
