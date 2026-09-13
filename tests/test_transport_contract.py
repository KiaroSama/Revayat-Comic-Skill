"""What a transport owes a client that gets something wrong.

Every test here sends something malformed and then something valid, across a
real process boundary, and asks the same question twice: did the bad message
produce an answer the client can act on, and did it leave the conversation
usable? A server that dies, hangs, or answers with a line no parser will read
has turned one client mistake into an outage.

The CLI half is the same contract through the other door: a stage that cannot
do what it was asked prints a report and exits non-zero, and the next command
still works.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import pageir as ir
import server


CLI = Path(server.__file__).resolve().parent / "revayat-comic.py"


def _cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(CLI), *args], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=300)


# --------------------------------------------------------------------------- #
# The MCP transport
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("line,why", [
    ("{", "truncated JSON"),
    ('"hello"', "a string where an object belongs"),
    ("[1, 2]", "an array where an object belongs"),
    ('{"jsonrpc": "2.0", "id": {}, "method": "ping"}', "an id no client can match"),
    ('{"jsonrpc": "2.0", "id": Infinity, "method": "ping"}', "an id that is not finite"),
    ('{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": 7}', "params that are not an object"),
    ('{"jsonrpc": "2.0", "id": 1, "method": "nope"}', "a method that does not exist"),
])
def test_a_malformed_message_is_answered_and_the_next_one_still_works(
        stdio_client, line, why):
    """Answered, not crashed — and the answer has to be JSON the client can
    read, which is why `Infinity` is here: Python accepts it on the way in and
    writes it back out, so a reply carrying one is a line no strict parser will
    take and the request it answers is matched to nothing."""
    answer = stdio_client.raw(line)

    assert "error" in answer, (why, answer)
    assert json.dumps(answer), "the reply is not serialisable JSON"

    alive = stdio_client.request("ping")
    assert alive.get("result") == {}, (why, alive)


def test_an_oversized_line_is_refused_before_it_is_read(stdio_client):
    """Reading a megabyte to reject it afterwards is the cost the sender was
    hoping for."""
    answer = stdio_client.raw(json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "ping",
         "params": {"pad": "x" * (server.MAX_BODY_BYTES + 10)}}))

    assert answer["error"]["code"] == -32600
    assert "bytes" in answer["error"]["message"]
    assert stdio_client.request("ping").get("result") == {}


@pytest.mark.parametrize("args,why", [
    ([{"doc": "x"}], "an object where an argument belongs"),
    ([None], "a null where an argument belongs"),
    ([["--doc"]], "a nested list"),
])
def test_an_argument_that_is_not_an_argument_is_refused(stdio_client, args, why):
    """`str()` on an object produces `{'doc': 'x'}` as one argument, and on
    `None` the four letters `None` — a path a stage then tries to open. The
    shape is the caller's mistake and saying which element is wrong costs
    nothing."""
    called = stdio_client.request("tools/call", name="revayat_qa",
                                  arguments={"args": args})
    body = json.loads(called["result"]["content"][0]["text"])

    assert body["ok"] is False, (why, body)
    assert "args[0]" in body["error"], body

    alive = stdio_client.request("ping")
    assert alive.get("result") == {}


def test_a_failing_stage_does_not_corrupt_the_next_answer(stdio_client,
                                                          detected):
    """An ordinary error — a document that is not there — is a result with a
    reason in it, and the conversation carries on."""
    broken = stdio_client.request(
        "tools/call", name="revayat_qa",
        arguments={"args": ["check", "--doc", "no/such/comic.json"]})
    body = json.loads(broken["result"]["content"][0]["text"])
    assert body["ok"] is False and body["stage"] == "qa"

    good = stdio_client.request(
        "tools/call", name="revayat_qa",
        arguments={"args": ["check", "--doc", str(detected)]})
    assert good["id"] == broken["id"] + 1, "the ids went out of step"
    report = json.loads(good["result"]["content"][0]["text"])
    assert report["stage"] == "qa" and report["report"]


def test_no_credential_is_echoed_back_through_the_transport(stdio_client,
                                                            monkeypatch):
    """`doctor` reports whether the machine is ready, which includes whether a
    key is configured. Whether, never which."""
    answer = stdio_client.request("tools/call", name="revayat_doctor",
                                  arguments={})
    text = answer["result"]["content"][0]["text"]

    assert "sk-" not in text


# --------------------------------------------------------------------------- #
# The command line
# --------------------------------------------------------------------------- #

def test_a_stage_that_cannot_find_its_document_says_so_and_exits_non_zero():
    done = _cli("qa", "check", "--doc", "no/such/comic.json")

    assert done.returncode != 0
    assert (done.stderr.strip() or done.stdout.strip()), "it failed silently"


def test_a_bad_flag_names_the_flag():
    done = _cli("qa", "check", "--doc", "x", "--not-a-flag")

    assert done.returncode != 0
    assert "--not-a-flag" in done.stderr


def test_an_ordinary_run_still_works_after_a_failed_one(detected):
    """The contract that matters: a mistake is not a state."""
    assert _cli("qa", "check", "--doc", "no/such/comic.json").returncode != 0

    done = _cli("qa", "check", "--doc", str(detected))

    assert json.loads(done.stdout)["stats"], done.stdout


def test_doctor_runs_and_reports_without_a_document():
    done = _cli("doctor")

    assert done.returncode in (0, 1), done.stderr
    report = json.loads(done.stdout)
    assert report["python"] and report["required"]
    assert "sk-" not in done.stdout


def test_the_pipeline_runs_end_to_end_through_the_command_line(sample_cbz,
                                                               tmp_path):
    """The real entry point, from an archive to a package, with no in-process
    shortcut anywhere in it."""
    work = tmp_path / "work"
    doc = work / "comic.json"
    imported = _cli("import", str(sample_cbz), "--out", str(work),
                    "--source-language", "ja")
    assert imported.returncode == 0, imported.stderr
    assert _cli("detect", "--doc", str(doc)).returncode == 0
    assert _cli("mask", "--doc", str(doc)).returncode == 0

    loaded = ir.load_doc(doc)
    for _page, region in ir.iter_regions(loaded):
        region["source_text"] = "やめろ"
        region["target_text"] = "بس کن"
    ir.save_doc(loaded, doc)

    assert _cli("clean", "--doc", str(doc)).returncode == 0
    assert _cli("typeset", "--doc", str(doc)).returncode == 0
    out = tmp_path / "chapter.cbz"
    done = _cli("export", "--doc", str(doc), "--out", str(out), "--draft")

    assert done.returncode == 0, done.stderr
    assert out.is_file()
    checked = _cli("qa", "package", "--doc", str(doc), "--file", str(out))
    assert json.loads(checked.stdout)["pages_found"] == len(loaded["pages"])
