"""The bounded chapter context: what a translator is told, and what stops
them being told the wrong thing.

Split out of `test_providers.py`, which had grown past the size a file stays
readable at. The subject here is one thing — the package `context build`
produces and the preflight that decides whether it may be produced at all.
"""

from __future__ import annotations

import json
from pathlib import Path


import context
import pageir as ir
import qa
import translate
import worksheet


# --- the bounded chapter context ---------------------------------------------
# Consistency across pages is what this exists for. The three properties that
# make it usable are boundedness, determinism and locked-decisions-win, and all
# three are cheap to break by accident.

def test_the_context_package_is_bounded(translated):
    import context

    doc = ir.load_doc(translated)
    package = context.build(doc, doc["pages"][-1]["id"], budget=120)
    used = package["budget"]["characters_used"]
    assert used <= 120
    assert len(package["context"]["translation_memory"]) <= context.MAX_PREVIOUS
    assert package["budget"]["truncated"] is True


def test_the_context_package_is_deterministic(translated):
    """A resumed run must continue, not restart. Two builds of the same page
    from the same document have to be byte-identical, which rules out anything
    ordered by frequency, time or dict iteration over mutable state."""

    import context

    doc = ir.load_doc(translated)
    page = doc["pages"][-1]["id"]
    first = json.dumps(context.build(doc, page), sort_keys=True,
                       ensure_ascii=False)
    second = json.dumps(context.build(ir.load_doc(translated), page),
                        sort_keys=True, ensure_ascii=False)
    assert first == second


def test_constraints_and_context_are_kept_apart(translated):
    """A locked glossary term is a fact; a previous line is information.
    Flattening the two is how a locked term gets quietly improved."""
    import context

    doc = ir.load_doc(translated)
    # The REAL schema: `glossary.entries`, with `target`. The first version of
    # this test invented `meta.glossary` and `context.build` read the same wrong
    # key, so the two agreed with each other and neither agreed with the
    # glossary stage. A test that builds its own fixture can validate a schema
    # that does not exist anywhere else.
    doc["glossary"] = {"entries": {
        "セキレイ": {"target": "سکیره‌ای", "locked": True},
        "loose": {"target": "آزاد"},
        "empty": {"target": "", "locked": True},
    }}
    package = context.build(doc, doc["pages"][0]["id"])
    assert package["constraints"]["glossary"]["セキレイ"] == "سکیره‌ای"
    assert "loose" not in package["constraints"]["glossary"]
    assert "empty" not in package["constraints"]["glossary"]
    assert "one source region becomes exactly one translated region" in \
        package["constraints"]["rules"]
    assert "glossary" not in package["context"]


def test_the_context_carries_lines_not_summaries(translated):
    """It never condenses dialogue. Fewer lines, never shorter ones."""
    import context

    doc = ir.load_doc(translated)
    package = context.build(doc, doc["pages"][-1]["id"])
    originals = {(r.get("target_text") or "").strip()
                 for _, r in ir.iter_regions(doc)}
    for row in package["context"]["translation_memory"]:
        assert row["fa"] in originals


def test_the_next_page_is_mentioned_but_not_translated(translated):
    import context

    doc = ir.load_doc(translated)
    package = context.build(doc, doc["pages"][0]["id"])
    for row in package["context"]["next_page"]:
        # A bounded look at the SOURCE is allowed and needed — a page that ends
        # mid-sentence needs the words it continues into. A reading of that
        # page is not: nobody has examined it yet.
        assert set(row) <= {"region", "kind", "speaker", "source", "truncated"}
        assert "fa" not in row and "target" not in row
        assert len(row.get("source", "")) <= context.NEXT_SOURCE_CHARS


def test_the_last_page_has_no_next(translated):
    import context

    doc = ir.load_doc(translated)
    assert context.build(doc, doc["pages"][-1]["id"])["context"]["next_page"] == []


# --- R05: the context package must be true and bounded -----------------------

def _reply(doc_path, page_id, *, folder=None, text=None):
    """Write a finished worksheet for one page."""
    import worksheet

    root = ir.doc_dir(doc_path)
    folder = Path(folder) if folder else root / "worksheets"
    sheet = folder / f"{page_id}.txt"
    body = text if text is not None else ir.read_text(sheet)
    ir.write_text(folder / f"{page_id}.done.txt", body)
    return worksheet


def test_the_reading_direction_reaches_the_translator(translated):
    """The importer writes `reading_direction`; the package read `direction`,
    which is never set, so every chapter was announced as right-to-left. A
    left-to-right webtoon handed to a translator as RTL gets its balloons
    described in the wrong order."""
    import context

    doc = ir.load_doc(translated)
    doc["meta"]["reading_direction"] = "ltr"
    ir.save_doc(doc, translated)

    package = context.build(ir.load_doc(translated), doc["pages"][0]["id"])
    assert package["constraints"]["policy"]["direction"] == "ltr"


def test_a_revised_reply_is_reported_as_unmerged(translated):
    """The guard asked "does this page have any Persian yet". Once a reply had
    been merged once, editing it and NOT merging again left the page looking
    finished, and the next page's context quietly used the stale text."""
    import context
    import worksheet

    doc_path = translated
    worksheet.build_document(doc_path)
    doc = ir.load_doc(doc_path)
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]
    root = ir.doc_dir(doc_path)

    for page_id in (first, second):
        _reply(doc_path, page_id)
    worksheet.merge_document(doc_path)
    doc = ir.load_doc(doc_path)
    assert context.unmerged_before(doc_path, doc, second)[0] == []

    sheet = root / "worksheets" / f"{first}.done.txt"
    ir.write_text(sheet, ir.read_text(sheet) + "\nnote: rethought this one\n")
    assert context.unmerged_before(doc_path, ir.load_doc(doc_path), second)[0] == [first]


def test_a_reply_that_only_partly_applied_is_reported_as_unmerged(translated):
    """A reply carrying an id that is not on the page is not a merged page; it
    is a page whose reader answered something else. Some regions landed, so the
    old "has any Persian" test said it was done."""
    import context
    import worksheet

    doc_path = translated
    worksheet.build_document(doc_path)
    doc = ir.load_doc(doc_path)
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]
    root = ir.doc_dir(doc_path)

    _reply(doc_path, second)
    sheet = ir.read_text(root / "worksheets" / f"{first}.txt")
    _reply(doc_path, first,
           text=sheet + "\n@@ p9999r001 speech horizontal\nfa: از کجا آمد؟\n")

    report = worksheet.merge_document(doc_path)
    assert report["unknown_regions"], "the fixture did not produce a bad id"
    assert context.unmerged_before(doc_path, ir.load_doc(doc_path), second)[0] == [first]


def test_a_custom_worksheet_folder_is_honoured_by_the_guard(detected, tmp_path):
    """`worksheet build --out` puts the sheets somewhere else and `merge` takes
    the same argument, but the guard only ever looked in the default folder — so
    with a custom folder it reported "nothing unmerged" every time.

    Run against a chapter with no Persian in it yet, so the only thing that can
    make the guard speak is finding the reply."""
    import context
    import worksheet

    elsewhere = tmp_path / "my-sheets"
    worksheet.build_document(detected, elsewhere)
    doc = ir.load_doc(detected)
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]
    ir.write_text(elsewhere / f"{first}.done.txt",
                  ir.read_text(elsewhere / f"{first}.txt"))

    assert context.unmerged_before(detected, doc, second)[0] == [], (
        "the default folder holds no reply, so there is nothing to report there")
    assert context.unmerged_before(detected, doc, second,
                                   worksheets=elsewhere)[0] == [first]


def test_the_package_reports_its_real_size(translated):
    """`budget.characters_used` counted the dialogue and nothing else, while the
    glossary, the speakers and the notes went in unbounded beside it. The
    advertised 3000 characters described a package of over 200,000."""
    import context

    doc = ir.load_doc(translated)
    doc["meta"]["scene"] = "س" * 4000
    doc["meta"]["style_notes"] = ["ی" * 4000]
    doc["meta"]["series_notes"] = ["ز" * 4000]
    doc["glossary"] = {"entries": {
        f"term{n}": {"target": "ت" * 60, "locked": True} for n in range(200)
    }}
    ir.save_doc(doc, translated)

    package = context.build(ir.load_doc(translated), doc["pages"][1]["id"],
                            budget=3000)
    budget = package["budget"]
    real = len(ir.dumps(package))

    assert "package_characters" in budget, "the real size is not reported"
    assert abs(budget["package_characters"] - real) <= len(str(real)) * 4
    assert budget["sections"], "the per-section sizes are not reported"


def test_a_locked_term_is_never_dropped_to_fit(translated):
    """Truncating a canonical constraint is the one thing the budget may not
    do: a locked term that silently vanishes is a name the chapter then spells
    two ways."""
    import context

    doc = ir.load_doc(translated)
    doc["glossary"] = {"entries": {
        f"term{n}": {"target": "ت" * 80, "locked": True} for n in range(300)
    }}
    ir.save_doc(doc, translated)

    package = context.build(ir.load_doc(translated), doc["pages"][1]["id"],
                            budget=1)
    assert len(package["constraints"]["glossary"]) == 300
    assert package["budget"].get("constraints_over_budget") is True


# --- the title's standing decisions travel as constraints --------------------

def test_a_title_policy_reaches_the_translator_as_a_constraint():
    """`constraints` is what a person decided and `context` is what informs a
    choice. Honorifics and name policy are decisions — putting them in
    `context` invites a translator to re-take them per page."""
    doc = {
        "meta": {"title_policy": {"honorifics": "keep -senpai, drop -san",
                                  "profanity": "full strength",
                                  "slang": "  "}},
        "pages": [{"id": "p0001", "regions": []}],
    }
    package = context.build(doc, "p0001")
    policy = package["constraints"]["policy"]

    assert policy["honorifics"] == "keep -senpai, drop -san"
    assert policy["profanity"] == "full strength"
    assert "slang" not in policy              # an empty entry is not a decision
    assert "title_policy" not in package["context"]


def test_no_title_policy_invents_nothing():
    """Absent means nobody decided, and then the page decides."""
    package = context.build({"meta": {}, "pages": [{"id": "p0001",
                                                    "regions": []}]}, "p0001")
    assert set(package["constraints"]["policy"]) == {
        "sfx", "direction", "source_language"}


def test_the_rules_forbid_assigning_register_by_stereotype():
    """Forcing every narration into past tense, every older character into
    formal language and every shout into impolite grammar is the failure mode
    the register table reads like."""
    rules = " ".join(
        context.build({"meta": {}, "pages": [{"id": "p0001", "regions": []}]},
                      "p0001")["constraints"]["rules"])
    assert "not from a character's age, rank or gender" in rules
    assert "narration is not automatically past tense" in rules
    assert "a line break first" in rules


# --- R3: one preflight, one effective policy, a usable look ahead ------------

def _unmerged_reply(doc_path, page_id, persian="بس کن"):
    """A finished reply for one page, written but not merged."""
    folder = ir.doc_dir(doc_path) / "worksheets"
    sheet = ir.read_text(folder / f"{page_id}.txt")
    ir.write_text(folder / f"{page_id}.done.txt",
                  sheet.replace("fa: ", f"fa: {persian}"))


def test_automatic_translation_refuses_what_the_cli_refuses(detected):
    """`translate_document` built its own package and asked nothing, so the
    automatic route did silently what the manual route was written to refuse:
    translate page 2 while page 1's Persian was still only a file on disk."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]
    _unmerged_reply(detected, first)

    report = translate.translate_document(
        detected, provider="fake-translation", pages=[second])

    assert report["refused"], report
    assert report["refused"][0]["unmerged"] == [first]
    assert "worksheet merge" in report["next"]


def test_an_explicit_override_is_recorded_rather_than_assumed(detected):
    """Translating a batch that cannot see each other is a decision somebody
    may make on purpose, and a later reader has to see that it was made."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]
    _unmerged_reply(detected, first)

    state = context.preflight(Path(detected), ir.load_doc(detected), second,
                              allow_unmerged=True)
    assert state["ok"] and state["unmerged"] == [first]

    report = translate.translate_document(
        detected, provider="fake-translation", pages=[second],
        allow_unmerged=True)
    assert not report["refused"]


def test_a_page_merged_by_an_older_build_is_named_not_waved_through(detected):
    """"Does this page hold any Persian" is not evidence that a reply was
    consumed whole — it says yes to one that was merged and then edited."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]
    _unmerged_reply(detected, first)
    worksheet.merge_document(detected)

    doc = ir.load_doc(detected)
    doc["pages"][0].pop("worksheet_digest", None)      # as an older build left it
    ir.save_doc(doc, detected)

    behind, unverified = context.unmerged_before(
        Path(detected), ir.load_doc(detected), second)
    assert behind == [] and unverified == [first]


def test_the_worksheet_folder_is_remembered(detected, tmp_path):
    """A reader who keeps replies elsewhere got an empty answer from every
    guard: the default folder was not there, so nothing was unmerged, so
    nothing was refused."""
    elsewhere = tmp_path / "replies"
    worksheet.build_document(detected, elsewhere)

    doc = ir.load_doc(detected)
    assert doc["meta"]["worksheets"] == str(elsewhere)
    assert context.worksheet_folder(Path(detected), doc) == elsewhere


def test_a_policy_that_names_a_different_policy_is_a_conflict():
    """A title whose policy reads "translate" while the document says "keep"
    had the reader translating effects the renderer then left in the artwork."""
    meta = {"sfx_policy": "keep", "title_policy": {"sfx": "translate them all"}}
    assert "sfx_policy" in (ir.sfx_conflict(meta) or "")
    assert ir.sfx_conflict({"sfx_policy": "translate",
                            "title_policy": {"sfx": "translate them all"}}) is None
    # Prose that names nothing is guidance, not a second instruction.
    assert ir.sfx_conflict({"sfx_policy": "keep",
                            "title_policy": {"sfx": "Persian onomatopoeia"}}) is None


def test_the_conflict_reaches_the_translator_and_the_gate(translated):
    doc = ir.load_doc(translated)
    doc["meta"]["title_policy"] = {"sfx": "translate every effect"}
    doc["meta"]["sfx_policy"] = "keep"
    ir.save_doc(doc, translated)

    package = context.build(ir.load_doc(translated), doc["pages"][0]["id"])
    assert "sfx_conflict" in package["constraints"]["policy"]
    assert "policy-conflict" in {
        item["code"] for item in qa.check_document(translated)["findings"]}


def test_the_look_ahead_carries_enough_source_to_finish_a_sentence(translated):
    """Kinds and speakers alone could not do the job they were there for: a
    page that ends mid-sentence needs the words it continues into, and
    `{"kind": "speech"}` is not those words."""
    doc = ir.load_doc(translated)
    doc["pages"][1]["regions"][0]["source_text"] = (
        "や" * (context.NEXT_SOURCE_CHARS + 40))
    ir.save_doc(doc, translated)

    ahead = context.build(ir.load_doc(translated),
                          doc["pages"][0]["id"])["context"]["next_page"]
    assert ahead and ahead[0]["source"]
    assert len(ahead[0]["source"]) == context.NEXT_SOURCE_CHARS
    assert ahead[0]["truncated"] is True
    # The SOURCE, never a reading of it: the page ahead has not been examined.
    assert "target" not in ahead[0] and "fa" not in ahead[0]


def test_an_over_budget_glossary_says_what_to_do_about_it(translated):
    doc = ir.load_doc(translated)
    doc["glossary"] = {"entries": {
        f"name{index}": {"target": "نام" * 20, "locked": True}
        for index in range(40)}}
    ir.save_doc(doc, translated)

    package = context.build(ir.load_doc(translated),
                            doc["pages"][0]["id"], budget=200)
    assert package["budget"]["constraints_over_budget"] is True
    assert "--budget" in package["budget"]["constraints_action"]
    # And they are all still there: a locked term that vanished to fit is a
    # name the chapter then spells two ways.
    assert len(package["constraints"]["glossary"]) == 40
