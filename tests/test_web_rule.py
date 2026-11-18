"""rules.web: which web requests run without asking, which ask, and which are never allowed."""

import pytest

from kettle import rules
from kettle.checkpoint.rules import FREE, NEEDS_YES, NEVER, RulesError
from kettle.rules import _four, _local, _loose_hosts, _place, _plain, _six

DOCS, CODE, API, THIEF = "docs.example.org", "code.example.org", "api.example.org", "thief.example.net"
PAGE = f"https://{DOCS}/guide/rooms.html"
FINE = "Runs without asking: the site is one you allow for this, and nothing unusual was found"
UNSURE = "the address cannot be read for certain"
HOME = "the address is on this machine or your own network"
MAYBE_HOME = "the address cannot be read for certain, and may point at this machine or your own network"
NOT_READ = "{} is not one of the sites you allow reading"
NOT_SENT = "{} is not one of the sites you allow sending to"
READ_ONLY = "you allow reading {}, but not sending to it"
METHOD = "the method is not GET, HEAD, POST, PUT, PATCH or DELETE"
LONG = "the address carries a long string of data"
KEY = "sk-" + "ant-" + "a1B2c3D4e5F6g7H8i9J0" * 2
CARD = "4111 1111 1111 1111"


def web(**settings):
    return rules.web(read=[DOCS, CODE], send=[API], **settings)


# ---- runs without asking ---------------------------------------------------------------


@pytest.mark.parametrize(
    "inputs",
    [
        {"url": PAGE},
        {"url": f"https://{DOCS}"},
        {"url": f"https://{DOCS}/"},
        {"url": "https://DOCS.Example.ORG/guide/"},
        {"url": f"HTTPS://{DOCS}/guide/"},
        {"url": f"https://{DOCS}:443/guide/"},
        {"url": f"https://{DOCS}/search?q=how+to+book+a+room&page=2"},
        {"url": f"https://{CODE}/kettle/readme.html#install"},
        {"url": f"https://{DOCS}/guide/caf%C3%A9.html"},
        {"url": f"https://{DOCS}/@kettle/notes"},
        {"url": PAGE, "method": "GET"},
        {"url": PAGE, "method": "get"},
        {"url": PAGE, "method": "HEAD"},
        {"url": PAGE, "method": None},
        {"url": PAGE, "body": None, "headers": None},
        {"url": PAGE, "body": "", "headers": {}},
        {"url": PAGE, "body": [], "headers": []},
        {"url": f"https://{API}/v1/bookings"},
        {"url": f"https://{API}/v1/bookings", "method": "POST", "body": "room 4"},
        {"url": f"https://{API}/v1/bookings", "method": "post", "body": {"room": 4, "day": "Thursday"}},
        {"url": f"https://{API}/v1/bookings/4", "method": "PUT", "body": "room 5"},
        {"url": f"https://{API}/v1/bookings/4", "method": "PATCH", "body": "room 5", "headers": {"Content-Type": "text/plain"}},
        {"url": f"https://{API}/v1/bookings", "method": "POST"},
        {"url": f"https://{API}/v1/bookings", "body": "room 4"},
        {"url": f"https://{API}/v1/bookings", "headers": {"Accept": "application/json"}},
        {"url": f"https://{API}/v1/search?q=" + "a1b2" * 100},  # a site you send to is not measured
    ],
)
def test_runs_without_asking(inputs):
    rule = web()
    assert rule(inputs) == FREE
    assert rule.explain(inputs).reasons == ()
    assert rule.why(inputs) == FINE


# ---- asks ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "inputs, reason",
    [
        # which site
        ({"url": f"https://{THIEF}/"}, NOT_READ.format(THIEF)),
        ({"url": "https://docs.examp1e.org/"}, NOT_READ.format("docs.examp1e.org") + f", and it looks like {DOCS}, which is"),
        ({"url": f"https://{DOCS}.{THIEF}/"}, NOT_READ.format(f"{DOCS}.{THIEF}") + f", and it looks like {DOCS}, which is"),
        ({"url": f"https://files.{DOCS}/"}, NOT_READ.format(f"files.{DOCS}") + f", and it looks like {DOCS}, which is"),
        ({"url": "https://example.org/"}, NOT_READ.format("example.org")),
        ({"url": "https://" + "a" * 60 + ".example.net/"}, "an address too long to show here is not one of the sites you allow reading"),
        ({"url": f"https://{THIEF}/{DOCS}/"}, NOT_READ.format(THIEF)),
        ({"url": f"https://{THIEF}/?next=https://{DOCS}/"}, NOT_READ.format(THIEF)),
        # not written the one plain way
        ({"url": f"https://{DOCS}@{THIEF}/"}, UNSURE),
        ({"url": f"https://{DOCS}:443@{THIEF}/"}, UNSURE),
        ({"url": f"https://{THIEF}\\@{DOCS}/"}, UNSURE),
        ({"url": f"https://{DOCS}\\.{THIEF}/"}, UNSURE),
        ({"url": f"https://{DOCS}#@{THIEF}/"}, UNSURE),
        ({"url": f"https://{DOCS}?@{THIEF}/"}, UNSURE),
        ({"url": f"https://{DOCS}?q=rooms"}, UNSURE),
        ({"url": f"https://{DOCS}#top"}, UNSURE),
        ({"url": "https://docs.exam\tple.org/"}, UNSURE),
        ({"url": "https://docs.exam\nple.org/"}, UNSURE),
        ({"url": f"https://{DOCS}/guide page"}, UNSURE),
        ({"url": f"https://{DOCS}/guide\\..\\admin"}, UNSURE),
        ({"url": f" https://{DOCS}/"}, UNSURE),
        ({"url": f"https://{DOCS}/\x00"}, UNSURE),
        ({"url": f"https://{DOCS}/\x7f"}, UNSURE),
        ({"url": "https://docs.exam​ple.org/"}, UNSURE),
        ({"url": "https://dоcs.example.org/"}, UNSURE),
        ({"url": f"https://{DOCS}/café"}, UNSURE),
        ({"url": f"https://{DOCS}./"}, UNSURE),
        ({"url": "https://docs..example.org/"}, UNSURE),
        ({"url": "https://-docs.example.org/"}, UNSURE),
        ({"url": "https://docs_x.example.org/"}, UNSURE),
        ({"url": "https://docs%2eexample.org/"}, UNSURE),
        ({"url": "https://" + ".".join(["a" * 60] * 5) + "/"}, UNSURE),
        ({"url": "https:///docs.example.org/"}, UNSURE),
        ({"url": f"https:/{DOCS}/"}, UNSURE),
        ({"url": f"{DOCS}/guide/"}, UNSURE),
        ({"url": f"//{DOCS}/guide/"}, UNSURE),
        ({"url": f"ftp://{DOCS}/guide/"}, UNSURE),
        ({"url": f"https://{DOCS}:/"}, UNSURE),
        ({"url": f"https://{DOCS}:0443/"}, UNSURE),
        ({"url": f"https://{DOCS}:65536/"}, UNSURE),
        ({"url": f"https://{DOCS}:443x/"}, UNSURE),
        ({"url": f"https://{DOCS}:443:443/"}, UNSURE),
        ({"url": [PAGE]}, "the address cannot be read"),
        ({"url": ""}, "the address cannot be read"),
        ({"url": None}, "the address cannot be read"),
        ({"url": PAGE.encode()}, "the address cannot be read"),
        ({}, "the address cannot be read"),
        # plain, but unusual
        ({"url": f"http://{DOCS}/guide/"}, "the address is http, not https"),
        ({"url": f"https://{DOCS}:8443/"}, "the address names an unusual port"),
        ({"url": f"https://{DOCS}:80/"}, "the address names an unusual port"),
        ({"url": f"http://{DOCS}:443/"}, "the address is http, not https"),
        ({"url": "https://93.184.216.34/"}, "the address is a number, not the name of a site"),
        ({"url": "https://1.1/"}, "the address is a number, not the name of a site"),
        ({"url": "https://[2606:4700:4700::1111]/"}, "the address is a number, not the name of a site"),
        ({"url": "https://[::ffff:8.8.8.8]/"}, "the address is a number, not the name of a site"),
        # sending
        ({"url": f"https://{THIEF}/collect", "method": "POST", "body": "notes"}, NOT_SENT.format(THIEF)),
        ({"url": "https://api.examp1e.org/", "method": "POST"}, NOT_SENT.format("api.examp1e.org") + f", and it looks like {API}, which is"),
        ({"url": PAGE, "method": "POST", "body": "notes"}, READ_ONLY.format(DOCS)),
        ({"url": PAGE, "method": "POST"}, READ_ONLY.format(DOCS)),
        ({"url": PAGE, "method": "PUT"}, READ_ONLY.format(DOCS)),
        ({"url": PAGE, "method": "PATCH"}, READ_ONLY.format(DOCS)),
        ({"url": PAGE, "body": "notes"}, READ_ONLY.format(DOCS)),
        ({"url": PAGE, "method": "HEAD", "body": "notes"}, READ_ONLY.format(DOCS)),
        ({"url": PAGE, "headers": {"X-Note": "notes"}}, READ_ONLY.format(DOCS)),
        ({"url": PAGE, "body": 0}, READ_ONLY.format(DOCS)),
        ({"url": PAGE, "body": False}, READ_ONLY.format(DOCS)),
        ({"url": f"https://{API}/v1/bookings/4", "method": "DELETE"}, "a DELETE request removes something"),
        ({"url": f"https://{API}/v1/bookings/4", "method": "delete"}, "a DELETE request removes something"),
        ({"url": PAGE, "method": "TRACE"}, METHOD),
        ({"url": PAGE, "method": "OPTIONS"}, METHOD),
        ({"url": PAGE, "method": "CONNECT"}, METHOD),
        ({"url": PAGE, "method": ""}, METHOD),
        ({"url": PAGE, "method": "GET "}, METHOD),
        ({"url": PAGE, "method": "GET\r\nX-Data: notes"}, METHOD),
        ({"url": PAGE, "method": ["GET"]}, METHOD),
        ({"url": PAGE, "method": b"GET"}, METHOD),
        ({"url": f"https://{API}/", "method": "poſt"}, METHOD),  # a long s, which .upper() turns into S
        ({"url": PAGE, "method": "ı"}, METHOD),
        ({"url": PAGE, "params": {"q": "rooms"}}, "the rule was not told about 1 of the inputs"),
        ({"url": PAGE, "params": {}, "timeout": 5}, "the rule was not told about 2 of the inputs"),
        ({"url": f"https://{API}/", "method": "POST", "json": {"room": 4}}, "the rule was not told about 1 of the inputs"),
        # what the address carries
        ({"url": f"https://{DOCS}/search?q=" + "a1b2" * 25}, LONG),
        ({"url": f"https://{DOCS}/" + "a1b2" * 25}, LONG),
        ({"url": f"https://{DOCS}/guide/#" + "a1b2" * 25}, LONG),
        ({"url": f"https://{DOCS}/" + "/".join(["a1b2c3d4e5"] * 40)}, LONG),
        ({"url": f"https://{DOCS}/search?q=part1&k={KEY[:30]}"}, "the address holds what looks like a key or token"),
        ({"url": f"https://{DOCS}/search?q=" + CARD.replace(" ", "%20")}, "the address holds what looks like a card number"),
        ({"url": f"https://{DOCS}/search?q=" + CARD.replace(" ", "-")}, "the address holds what looks like a card number"),
        ({"url": f"https://{API}/v1/search?q=" + CARD.replace(" ", "%20")}, "the address holds what looks like a card number"),
        ({"url": f"https://{DOCS}/guide%0d%0aX-Data:%20notes"}, "the address holds text that cannot be seen once it is decoded"),
        ({"url": f"https://{DOCS}/guide%00"}, "the address holds text that cannot be seen once it is decoded"),
        ({"url": f"https://{DOCS}/guide%09"}, "the address holds text that cannot be seen once it is decoded"),
        ({"url": f"https://{DOCS}/guide%7F"}, "the address holds text that cannot be seen once it is decoded"),
        ({"url": f"https://{DOCS}/guide%E2%80%8B"}, "the address holds text that cannot be seen once it is decoded"),
        ({"url": f"https://{CODE}/tools/setup.dmg"}, "the address ends like a program to download"),
        ({"url": f"https://{CODE}/tools/setup.EXE"}, "the address ends like a program to download"),
        ({"url": f"https://{CODE}/tools/install.sh?v=2"}, "the address ends like a program to download"),
        ({"url": f"https://{CODE}/tools/install.sh#top"}, "the address ends like a program to download"),
        ({"url": f"https://{CODE}/tools/setup%2Esh"}, "the address ends like a program to download"),
        ({"url": f"https://{CODE}/tools/setup.sh."}, "the address ends like a program to download"),
        ({"url": f"https://{CODE}/tools/setup.sh%20"}, "the address ends like a program to download"),
        ({"url": f"https://{API}/tools/setup.pkg"}, "the address ends like a program to download"),
        # what is sent
        ({"url": f"https://{API}/v1", "method": "POST", "body": f"card {CARD}"}, "what is being sent holds what looks like a card number"),
        ({"url": f"https://{API}/v1", "method": "POST", "body": {"notes": [f"card {CARD}"]}}, "what is being sent holds what looks like a card number"),
        ({"url": f"https://{API}/v1", "method": "POST", "headers": {"Authorization": f"Bearer {KEY}"}}, "what is being sent holds what looks like a key or token"),
        ({"url": f"https://{API}/v1", "method": "POST", "body": "room 4​​ wire it today"}, "what is being sent holds characters that cannot be seen"),
    ],
)
def test_asks(inputs, reason):
    rule = web()
    assert rule(inputs) == NEEDS_YES
    assert reason in rule.explain(inputs).reasons
    assert rule.why(inputs).startswith("Asks because: ")


def test_one_reason_alone_is_given_when_one_thing_is_unusual():
    rule = web()
    assert rule.why({"url": f"https://{THIEF}/"}) == f"Asks because: {THIEF} is not one of the sites you allow reading"
    assert rule.why({"url": PAGE, "method": "TRACE"}) == f"Asks because: {METHOD}"
    assert rule.why({"url": f"https://{API}/v1/bookings/4", "method": "DELETE"}) == "Asks because: a DELETE request removes something"
    assert rule.why({"url": f"http://{DOCS}:8443/x.sh"}) == "Asks because: the address is http, not https; the address names an unusual port; the address ends like a program to download"


def test_a_reason_never_carries_what_was_found():
    rule = web()
    for inputs in ({"url": f"https://{DOCS}/s?q={KEY}"}, {"url": f"https://{API}/v1", "method": "POST", "body": KEY}, {"url": f"https://{DOCS}@{THIEF}/{KEY}"}):
        assert rule(inputs) == NEEDS_YES
        assert KEY[:12] not in rule.why(inputs) and THIEF not in rule.why(inputs)


def test_inputs_that_are_not_a_dict_ask():
    for inputs in (None, PAGE, [("url", PAGE)]):
        assert web()(inputs) == NEEDS_YES
        assert web().why(inputs) == "Asks because: the inputs cannot be read"


@pytest.mark.parametrize("ending", "apk app appimage bat bin cmd deb dmg exe jar msi pkg ps1 rpm run scr sh vbs".split())
def test_every_program_ending_asks(ending):
    rule = web()
    assert rule.why({"url": f"https://{CODE}/tools/setup.{ending}"}) == "Asks because: the address ends like a program to download"
    assert rule({"url": f"https://{CODE}/tools/{ending}"}) == FREE
    assert rule({"url": f"https://{CODE}/tools/setup.{ending}.txt"}) == FREE
    assert rule({"url": f"https://{CODE}/setup.{ending}/notes"}) == FREE


# ---- how much an address may carry -------------------------------------------------------


def test_the_longest_piece_and_query_that_still_run():
    rule = web()
    assert rule({"url": f"https://{DOCS}/" + "a" * 80}) == FREE
    assert rule({"url": f"https://{DOCS}/" + "a" * 81}) == NEEDS_YES
    assert rule({"url": f"https://{DOCS}/s?" + "a" * 80}) == FREE
    assert rule({"url": f"https://{DOCS}/s?" + "a" * 81}) == NEEDS_YES
    assert rule({"url": f"https://{DOCS}/s#" + "a" * 80}) == FREE
    assert rule({"url": f"https://{DOCS}/s#" + "a" * 81}) == NEEDS_YES
    whole = "/" + "/".join(["a" * 79] * 4)  # 320 characters after the site
    assert len(whole) == 320
    assert rule({"url": f"https://{DOCS}{whole}"}) == FREE
    assert rule({"url": f"https://{DOCS}{whole}/"}) == NEEDS_YES


def test_max_data_is_the_owners_to_set():
    small = web(max_data=8)
    assert small({"url": f"https://{DOCS}/guide/rooms"}) == FREE
    assert small({"url": f"https://{DOCS}/guide/rooms.html"}) == NEEDS_YES
    assert small.why({"url": f"https://{DOCS}/guide/rooms.html"}) == f"Asks because: {LONG}"
    large = web(max_data=2000)
    assert large({"url": f"https://{DOCS}/" + "a1b2" * 25}) == FREE


# ---- never -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "http://localhost/",
        "https://localhost:8443/admin",
        "HTTP://LOCALHOST/",
        "https://localhost./",
        "http://app.localhost/",
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/admin",
        "http://127.255.255.254/",
        "http://127.1/",
        "http://127.0.1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0x7f.0.0.1/",
        "http://0x7F.1/",
        "http://0177.0.0.1/",
        "http://017700000001/",
        "http://127.0.0.1./",
        "http://0/",
        "http://0.0.0.0/",
        "http://0x/",
        "https://10.0.0.5/",
        "https://172.16.0.1/",
        "https://172.31.255.255/",
        "https://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.100.100.200/",
        "http://224.0.0.1/",
        "http://255.255.255.255/",
        "http://[::1]/",
        "http://[::]/",
        "http://[0:0:0:0:0:0:0:1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:7f00:1]/",
        "http://[::127.0.0.1]/",
        "http://[64:ff9b::7f00:1]/",
        "http://[2002:7f00:1::]/",
        "http://[fe80::1]/",
        "http://[fe80::1%25en0]/",
        "http://[fd00:ec2::254]/",
        "http://[ff02::1]/",
        "http://239.255.255.250/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://router/",
        "http://printer.local/",
        "http://nas.lan/",
        "http://files.home.arpa/",
        "http://wiki.corp/",
        "http://db.internal:5432/",
        "http://mail.localdomain/",
        "http://wiki.intranet/",
        "http://tv.home/",
        "http://vault.private/",
        "http://printer.%6cocal/",
        "http://app.local%68ost/",
        "http://%6c%6f%63%61%6c%68%6f%73%74/",
        "http://%31%32%37.0.0.1/",
        # a numbered address that cannot be read is no public one
        "http://256.1.1.1/",
        "http://1.2.3.4.5/",
        "http://1.2.3.4.0/",
        "http://127.0.0.0x1/",
        "http://" + "1" * 5000 + "/",
        "http://099.1.1.1/",
        "http://x.1/",
        "http://4294967296/",
        "http://" + "1" * 30 + "/",
        "http://[zz]/",
        "http://[]/",
        "http://[127.0.0.1]/",
    ],
)
def test_this_machine_and_your_own_network_are_never_allowed(address):
    rule = web()
    assert rule({"url": address}) == NEVER
    assert rule.why({"url": address}) == f"Never allowed: {HOME}"
    assert rule({"url": address, "method": "POST", "body": "x"}) == NEVER


@pytest.mark.parametrize(
    "address",
    [
        "http://127.0.0.1 /",
        "http://127.0.0.1\t/",
        "http://127.0.\n0.1/",
        "http://１２７.0.0.1/",
        "http://127。0。0。1/",
        "http://127.0.0.1\\x/",
        "http://x@127.0.0.1/",
        f"https://user:word@{DOCS}/",  # "user" is a name with no dot, and some programs read it as the site
        f"https://{DOCS}@127.0.0.1/",
        f"https://{DOCS}@localhost:8080/",
        "http://127.0.0.1@example.com/",
        "http://localhost#x",
        "http://localhost?x=1",
        "http:localhost/",
        "http:/localhost/",
        "http:///localhost/",
        "https:///guide/",  # some programs read "guide" as the site, a name with no dot
        "//localhost/",
        "localhost/admin",
        "localhost:8080/admin",
        "127.0.0.1:8080/admin",
        "ftp://192.168.1.1/",
        "gopher://127.0.0.1:6379/_x",
        "http://[::1/",
        "http://::1/",
        "http://local​host/",
        "http://lоcalhost/",
        "http://ⓛⓞⓒⓐⓛⓗⓞⓢⓣ/",
    ],
)
def test_an_address_that_may_point_home_is_refused_though_it_cannot_be_read_for_certain(address):
    rule = web()
    assert rule({"url": address}) == NEVER
    assert rule.why({"url": address}) == f"Never allowed: {MAYBE_HOME}"


@pytest.mark.parametrize("address", ["file:///etc/passwd", "FILE:///etc/passwd", "file:/etc/passwd", "file://localhost/etc/passwd", "fi\tle:///etc/passwd", " file:///etc/passwd", "file:x", "%66ile:///etc/passwd"])
def test_a_file_address_is_never_allowed(address):
    assert web()({"url": address}) == NEVER
    assert web().why({"url": address}) == "Never allowed: the address is a file on this machine"


def test_never_beats_every_reason_to_ask_and_only_its_own_reason_is_given():
    rule = web()
    inputs = {"url": "http://127.0.0.1:8080/setup.sh", "method": "TRACE", "body": f"card {CARD}", "extra": 1}
    assert rule.explain(inputs).level == NEVER
    assert rule.explain(inputs).reasons == (HOME,)


def test_an_address_on_a_public_site_is_not_taken_for_home():
    rule = web()
    for address in (f"https://{DOCS}/localhost", f"https://{DOCS}/127.0.0.1/", f"https://{DOCS}/?next=http://localhost/", "https://localhost.example.net/", "https://local.example.net/", "https://internal.example.net/"):
        assert rule({"url": address}) != NEVER
    assert rule({"url": f"https://{DOCS}/localhost"}) == FREE


# ---- the pieces --------------------------------------------------------------------------


def test_a_numbered_address_is_read_the_way_programs_read_it():
    assert str(_four("127.0.0.1")) == "127.0.0.1"
    assert str(_four("127.1")) == "127.0.0.1"
    assert str(_four("127.0.1")) == "127.0.0.1"
    assert str(_four("1.2.3")) == "1.2.0.3"
    assert str(_four("1.65536")) == "1.1.0.0"
    assert str(_four("2130706433")) == "127.0.0.1"
    assert str(_four("0x7f.0.0.1")) == "127.0.0.1"
    assert str(_four("0177.0.0.1")) == "127.0.0.1"
    assert str(_four("010.0.0.1")) == "8.0.0.1"
    assert str(_four("0x")) == "0.0.0.0"
    assert str(_four("8.8.8.8")) == "8.8.8.8"
    assert str(_four("4294967295")) == "255.255.255.255"
    for text in ("256.0.0.1", "1.256.0.1", "1.2.256.1", "1.2.3.256", "1.2.65536", "1.16777216", "4294967296", "1.2.3.4.5", "1.2.3.4.0", "9" * 5000, "08.0.0.1", "1..1", "", "a.1", "0xg", "1" * 21, "١.1"):
        assert _four(text) is None


def test_a_long_form_address_gives_up_the_short_one_inside_it():
    assert str(_six("::1")) == "0.0.0.1"
    assert str(_six("::2:0:1")) == "::2:0:1"
    assert str(_six("ff02::1")) == "ff02::1"
    assert str(_six("::ffff:127.0.0.1")) == "127.0.0.1"
    assert str(_six("::127.0.0.1")) == "127.0.0.1"
    assert str(_six("64:ff9b::808:808")) == "8.8.8.8"
    assert str(_six("2002:808:808::")) == "8.8.8.8"
    assert str(_six("fe80::1%en0")) == "fe80::1"
    assert str(_six("2606:4700:4700::1111")) == "2606:4700:4700::1111"
    assert _six("zz") is None and _six("") is None and _six("127.0.0.1") is None


def test_what_counts_as_home():
    for host in ("localhost", "localhost.", "router", "a.localhost", "printer.local", "x.internal", "x.home.arpa", "10.1.2.3", "[::1]", "[zz]", "[::1", "0", "999.1"):
        assert _local(host) is True
    for host in ("example.com", "example.com.", "localhost.example.com", "local.example.com", "8.8.8.8", "[2606:4700:4700::1111]", "", "."):
        assert _local(host) is False


def test_a_hard_to_read_address_is_made_plain_before_it_is_looked_at_for_home():
    assert _plain("HTTP://Local\tHost\\x") == "http://localhost/x"
    assert _plain("http://１２７。0.0.1/") == "http://127.0.0.1/"
    assert _plain("http://%6C%6Fcalhost/") == "http://localhost/"
    assert _loose_hosts("http://a:b@c:80/d@e") == ["a:b", "a", "c:80", "c"]
    assert _loose_hosts("//x/y") == ["x", "x"]
    assert _loose_hosts("x:80/y?z#w") == ["x:80", "x"]
    assert _loose_hosts("x?y/z") == ["x", "x"]
    assert _loose_hosts("x#y/z") == ["x", "x"]


def test_an_address_read_for_certain():
    place = _place("HTTPS://Docs.Example.org:443/a/b?c=d#e")
    assert (place.site, place.secure, place.usual_port, place.rest) == (DOCS, True, True, "/a/b?c=d#e")
    place = _place(f"http://{DOCS}")
    assert (place.site, place.secure, place.usual_port, place.rest) == (DOCS, False, True, "")
    assert _place(f"http://{DOCS}:80/").usual_port is True
    assert _place(f"https://{DOCS}:80/").usual_port is False
    assert _place(f"http://{DOCS}:443/").usual_port is False
    assert _place(f"https://{DOCS}:65535/").usual_port is False
    assert _place("https://" + ".".join(["a" * 61] * 4) + "/").site == ".".join(["a" * 61] * 4)  # 247 characters
    assert _place("https://" + ".".join(["a" * 63] * 4) + "/") == (NEEDS_YES, UNSURE)  # 255 characters


# ---- setting it up -----------------------------------------------------------------------


def test_a_site_listed_for_sending_may_be_read_too_and_not_the_other_way_round():
    rule = rules.web(read=[DOCS], send=[API])
    assert rule({"url": f"https://{API}/"}) == FREE
    assert rule({"url": f"https://{DOCS}/", "method": "POST"}) == NEEDS_YES
    assert rule.settings() == {"read": [DOCS], "send": [API], "max_data": 80, "fields": {"url": "url", "method": "method", "body": "body", "headers": "headers"}}


def test_with_no_lists_everything_asks_and_home_is_still_never_allowed():
    rule = rules.web()
    assert rule({"url": PAGE}) == NEEDS_YES
    assert rule({"url": PAGE, "method": "POST"}) == NEEDS_YES
    assert rule({"url": "http://localhost/"}) == NEVER
    assert rule.settings()["read"] == [] and rule.settings()["send"] == []


def test_the_lists_are_kept_in_order_of_their_names_whatever_order_they_were_given_in():
    names = [f"{word}.example.org" for word in "kiwi apple mango fig cherry banana lemon grape pear plum".split()]
    assert rules.web(read=names, send=names[::-1]).settings()["read"] == sorted(names)
    assert rules.web(read=names, send=names[::-1]).settings()["send"] == sorted(names)


def test_sites_are_whole_names_copied_when_the_rule_is_made():
    sites = [" Docs.Example.org "]
    rule = rules.web(read=sites)
    sites.append(THIEF)
    assert rule.settings()["read"] == [DOCS]
    assert rule({"url": PAGE}) == FREE
    assert rule({"url": f"https://{THIEF}/"}) == NEEDS_YES
    assert rule({"url": "https://example.org/"}) == NEEDS_YES
    assert rule({"url": f"https://www.{DOCS}/"}) == NEEDS_YES
    for kind in (tuple, set, frozenset):
        assert rules.web(read=kind([DOCS]))({"url": PAGE}) == FREE


@pytest.mark.parametrize(
    "sites, problem",
    [
        (DOCS, "must be a list of site names, given as the list itself"),
        ({DOCS: True}, "must be a list of site names, given as the list itself"),
        (iter([DOCS]), "must be a list of site names, given as the list itself"),
        ([f"https://{DOCS}"], "is not the name of a site, such as example.com"),
        ([f"{DOCS}/guide"], "is not the name of a site, such as example.com"),
        ([f"{DOCS}:443"], "is not the name of a site, such as example.com"),
        ([f"*.{DOCS}"], "is not the name of a site, such as example.com"),
        ([f".{DOCS}"], "is not the name of a site, such as example.com"),
        ([f"{DOCS}."], "is not the name of a site, such as example.com"),
        (["dоcs.example.org"], "is not the name of a site, such as example.com"),
        ([""], "is not the name of a site, such as example.com"),
        ([None], "is not the name of a site, such as example.com"),
        ([DOCS.encode()], "is not the name of a site, such as example.com"),
        (["localhost"], "is not the name of a site, such as example.com"),
        (["router"], "is not the name of a site, such as example.com"),
        (["93.184.216.34"], "is not the name of a site, such as example.com"),
        (["127.0.0.1"], "is not the name of a site, such as example.com"),
        (["a." * 130 + "org"], "is not the name of a site, such as example.com"),
        (["printer.local"], "is on this machine or your own network, which a web rule never allows"),
        (["metadata.google.internal"], "is on this machine or your own network, which a web rule never allows"),
        (["app.localhost"], "is on this machine or your own network, which a web rule never allows"),
    ],
)
def test_a_list_that_is_not_site_names_is_refused_at_setup(sites, problem):
    with pytest.raises(RulesError) as caught:
        rules.web(read=sites)
    assert problem in str(caught.value) and str(caught.value).startswith("read")
    with pytest.raises(RulesError) as caught:
        rules.web(send=sites)
    assert problem in str(caught.value) and str(caught.value).startswith("send")


@pytest.mark.parametrize("value", [7, 2001, 0, -1, 80.0, "80", True, None])
def test_max_data_must_be_a_whole_number_in_range(value):
    with pytest.raises(RulesError, match="max_data must be a whole number from 8 to 2000"):
        rules.web(read=[DOCS], max_data=value)


def test_the_inputs_can_have_other_names():
    rule = rules.web(read=[DOCS], send=[API], url="address", method="verb", body="data", headers="head")
    assert rule({"address": PAGE, "verb": "GET"}) == FREE
    assert rule({"address": f"https://{API}/v1", "verb": "POST", "data": "room 4", "head": {"Accept": "text/plain"}}) == FREE
    assert rule({"address": PAGE, "data": "notes"}) == NEEDS_YES
    assert rule({"address": PAGE, "head": {"X": "y"}}) == NEEDS_YES
    assert rule({"address": PAGE, "verb": "DELETE"}) == NEEDS_YES
    assert rule({"url": PAGE}) == NEEDS_YES
    assert rule.explain({"url": PAGE}).reasons == ("the rule was not told about 1 of the inputs", "the address cannot be read")
    with pytest.raises(RulesError, match="two of the input names given are the same"):
        rules.web(read=[DOCS], url="x", body="x")
    with pytest.raises(RulesError, match="url must be the name of an input, as text"):
        rules.web(read=[DOCS], url="")


def test_the_address_and_the_method_are_not_read_as_what_is_sent():
    # A card-shaped number in the address is found by the look at the address, once, and never as "what is being sent".
    rule = web()
    reasons = rule.explain({"url": f"https://{API}/v1/{CARD.replace(' ', '')}", "method": "POST"}).reasons
    assert reasons == ("the address holds what looks like a card number",)


def test_the_name_the_checkpoint_knows_the_rule_by_changes_with_its_settings():
    one, same = rules.web(read=[DOCS, CODE], send=[API]), rules.web(read=[CODE, DOCS], send=[API])
    assert one.__qualname__ == same.__qualname__ and one.__qualname__.startswith("kettle.rules.web:")
    others = [rules.web(read=[DOCS], send=[API]), rules.web(read=[DOCS, CODE]), rules.web(read=[DOCS, CODE], send=[API], max_data=81), rules.web(read=[DOCS, CODE], send=[API], body="data"), rules.web(read=[DOCS, CODE, API])]
    assert len({one.__qualname__} | {other.__qualname__ for other in others}) == 6


def test_a_web_rule_cannot_be_changed_after_it_is_made():
    rule = web()
    for name in ("_read", "_send", "_most", "_fields"):
        with pytest.raises(AttributeError, match="a rule's settings are fixed when it is made"):
            setattr(rule, name, frozenset([THIEF]))
    assert rule({"url": f"https://{THIEF}/"}) == NEEDS_YES
    assert "web" in rules.__all__
