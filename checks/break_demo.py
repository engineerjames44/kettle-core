"""Break the demo one way at a time, and see whether its tests notice.

    .venv/bin/python checks/break_demo.py             every break (under a minute)
    .venv/bin/python checks/break_demo.py served      only the breaks with "served" in their name

`python -m kettle.demo` says three things about itself: it is served to this machine
only, the checkpoint decides and the page only draws, and the fourth tab shows a saved
run as it was saved. Each break here makes one of those untrue in a copy of the
package, and tests/test_demo.py is run against the copy.

Only tests/test_demo.py is run. The checkpoint itself has its own break script.
"""

from _runner import nth, rep, run

TESTS = ["test_demo.py"]

D, SAVED = "demo/app.py", "demo/opus-run-2026-11-15.json"

VISIT = 'self.headers.get("X-Demo-Visit", "")[:64]'

MUTANTS = [
    # ---- served to this machine only
    ("served: it listens on every address", D, rep('HOST, PORT = "127.0.0.1", 8765', 'HOST, PORT = "0.0.0.0", 8765')),
    ("served: the page is handed to any site that asks", D, rep('if self.path == "/" and self.local():', 'if self.path == "/":')),
    ("served: any port on this machine passes as the demo", D, rep('return self.headers.get("Host") in (f"{HOST}:{port}", f"localhost:{port}")', 'return (self.headers.get("Host") or "").split(":")[0] in (HOST, "localhost")')),
    ("served: the buttons do not check where the call came from", D, rep("return self.local() and secrets.compare_digest(", "return secrets.compare_digest(")),
    ("served: the buttons do not check the token", D, rep("return self.local() and secrets.compare_digest(sent, self.server.token.encode())", "return self.local()")),
    ("served: an empty token passes", D, rep("return self.local() and secrets.compare_digest(sent, self.server.token.encode())", "return self.local() and (not sent or secrets.compare_digest(sent, self.server.token.encode()))")),
    ("served: the state can be read with no token", D, rep('if self.path == "/api/state" and self.trusted():', 'if self.path == "/api/state" and self.local():')),
    ("served: every page gets the same token", D, rep("self.token = secrets.token_urlsafe(16)", 'self.token = ""')),
    ("served: a refused call still makes a run", D, rep("        if not self.trusted():\n            return self.send_error(403)\n        try:", '        self.server.session_for(self.headers.get("X-Demo-Visit", ""))\n        if not self.trusted():\n            return self.send_error(403)\n        try:')),
    ("served: a call that is not JSON is not refused", D, rep("            assert type(asked) is dict\n", "            asked = asked if type(asked) is dict else {}\n")),
    ("served: a path that is not known answers", D, rep("        else:\n            return self.send_error(404)\n        self.send_state(session)", "        self.send_state(session)")),
    ("served: two pages share one run", D, rep(VISIT, '""')),
    # ---- the command
    ("command: a taken port is an error", D, rep("        if port == 0:\n            raise\n        return Demo(0)", "        raise")),
    ("command: the browser opens when told not to", D, rep("    if not args.no_browser:", "    if True:")),
    ("command: the browser never opens", D, rep("    if not args.no_browser:", "    if False:")),
    ("command: the address printed is not the one served", D, rep('print(f"Kettle demo: {server.url}  (Ctrl+C to stop)", flush=True)', 'print(f"Kettle demo: http://{HOST}:{PORT}  (Ctrl+C to stop)", flush=True)')),
    ("command: the browser is sent to another address", D, rep("        webbrowser.open(server.url)", '        webbrowser.open(f"http://{HOST}:{PORT}")')),
    ("command: Ctrl+C is an error", D, rep("    except KeyboardInterrupt:\n        print()", "    except ZeroDivisionError:\n        print()")),
    ("command: the page is read from the folder it is run in", D, rep('PAGE = Path(__file__).with_name("page.html")', 'PAGE = Path("page.html")')),
    ("command: the saved run is read from the folder it is run in", D, rep('SAVED = Path(__file__).with_name("opus-run-2026-11-15.json")', "SAVED = Path(SAVED_AS) if False else Path('results/2026-11-15/2026-11-15T184338Z/results.json')")),
    # ---- the checkpoint decides, the page only draws
    ("stories: a yes for another action is taken", D, rep("            decision = self.cp.approve(request_id, fingerprint)", '            decision = self.cp.approve(request_id, next((item["fingerprint"] for item in self.cp.pending() if item["request_id"] == request_id), fingerprint))')),
    ("stories: anything that is not a no is a yes", D, rep('yes=asked.get("yes") is True', 'yes=bool(asked.get("yes"))')),
    ("stories: a no still runs it", D, rep("            decision = self.cp.deny(request_id)", "            decision = self.cp.run(self.cp.approve(request_id, fingerprint).request_id)")),
    ("stories: the ending is rigged, a yes to the attacker runs nothing", D, rep("        if yes:\n            decision = self.cp.approve(request_id, fingerprint)", '        if yes and not step["planted"]:\n            decision = self.cp.approve(request_id, fingerprint)')),
    ("stories: what ran is the script's word, not the world's", D, rep('step.update(status=decision.status, reason=decision.reason, answer="yes" if yes else "no", ran=self.world.happened[before:])', 'step.update(status=decision.status, reason=decision.reason, answer="yes" if yes else "no", ran=[] if step["planted"] else self.world.happened[before:])')),
    ("stories: a never tool is held instead", D, lambda t: nth(t, 'level=NEVER)', 'level=NEEDS_YES)', 1)),
    ("stories: the .env file can be read", D, rep('return NEVER if inputs["path"].endswith(".env") else FREE', "return FREE")),
    ("stories: a new account is not marked", D, rep('level=NEEDS_YES, watch=["account"])', "level=NEEDS_YES)")),
    ("stories: everything held is marked as new", D, rep('"first_time": name in item["first_time"]}', '"first_time": name in item["first_time"] or name in ("account", "remote", "card")}')),
    ("stories: who wrote what is told from the start", D, rep("            if done:  # who wrote what is only told at the end", "            if True:  # who wrote what is only told at the end", "without = with_no_checkpoint(story) if done else None", "without = with_no_checkpoint(story)")),
    ("stories: the edited file is pointed out from the start", D, rep('if done or name != "tell"}', "}")),
    ("stories: the log is said to be whole without a look", D, rep("        ok, words = self.cp.verify_log()", '        ok, words = "yes", ""')),
    ("stories: the rules shown are not the rules that ran", D, rep('"code": inspect.getsource(story.rules),', '"code": inspect.getsource(STORIES[0].rules),')),
    ("stories: the side with no checkpoint is left out", D, rep("shown.update(planted=step[\"planted\"], without=without[number])", 'shown.update(planted=step["planted"], without=[])')),
    # ---- the fourth tab
    ("saved run: the copy in the package is not the report", SAVED, lambda t: nth(t, '"ran"', '"held"', 1)),
    ("saved run: a reply is reworded", D, rep('            "reply": run["reply"],', '            "reply": run["reply"].replace("usual", "normal"),')),
    ("saved run: an outcome is redrawn", D, rep('                "outcome": each["outcome"],', '                "outcome": "held, owner said no" if each["attackers"] else each["outcome"],')),
    ("saved run: the sides are swapped", D, rep('runs.setdefault(run["repeat"], {"repeat": run["repeat"]})[run["setup"]] = side(run)', 'runs.setdefault(run["repeat"], {"repeat": run["repeat"]})[{"none": "kettle", "kettle": "none"}[run["setup"]]] = side(run)')),
    ("saved run: a run is left out", D, rep('"runs": [runs[repeat] for repeat in sorted(runs)],', '"runs": [runs[repeat] for repeat in sorted(runs)][1:],')),
    ("saved run: the trail is not worked out", D, rep('trails = trails_of(run, case, case_set) if run["setup"] == "kettle" else {}', "trails = {}")),
    ("saved run: the trail count is not taken from the trail", D, rep('"named": sum(names_the_plant(trail) for trail in held)', '"named": 0')),
    ("saved run: the tab can be stepped like a story", D, rep("self.visits[visit] = Replay() if story is REAL else Session(story or STORIES[0])", "self.visits[visit] = Session(STORIES[0] if story is REAL or not story else story)")),
    ("saved run: the link is to another file", D, rep('SAVED_AT = "https://github.com/engineerjames44/kettle-core/blob/main/" + SAVED_AS', 'SAVED_AT = "https://github.com/engineerjames44/kettle-core/blob/main/results"')),
]

if __name__ == "__main__":
    run(MUTANTS, TESTS)
