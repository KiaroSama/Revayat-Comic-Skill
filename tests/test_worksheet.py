"""The worksheet protocol, and every way a reply can be wrong.

Merging must refuse rather than guess. A reply filed against the wrong region is
silent corruption: the page still builds, every gate still passes, and the
dialogue is simply attached to the wrong balloons.
"""

from __future__ import annotations

from pathlib import Path

import pageir as ir
import worksheet


def _fill(doc_path: Path, *, replace=None, drop=(), skip=(), extra=""):
    """Write a plausible `.done.txt` for every worksheet."""
    doc = ir.load_doc(doc_path)
    folder = ir.doc_dir(doc_path) / "worksheets"
    replace = replace or {}
    for page in doc["pages"]:
        source = folder / f"{page['id']}.txt"
        if not source.exists():
            continue
        lines = [line for line in source.read_text(encoding="utf-8").splitlines()]
        out, current = [], None
        for line in lines:
            header = worksheet.HEADER.match(line)
            if header:
                current = header.group("id")
            if line.startswith("src:") and current:
                out.append("src: やめろ！")
                continue
            if line.startswith("fa:") and current:
                if current in skip:
                    out.append("fa: ")
                elif current in drop:
                    out.append("fa: ")
                    out.append("drop: yes")
                else:
                    out.append(f"fa: {replace.get(current, 'بس کن! چه خبر است؟')}")
                continue
            out.append(line)
        text = "\n".join(out) + extra + "\n"
        (folder / f"{page['id']}.done.txt").write_text(text, encoding="utf-8",
                                                       newline="")


def _insert_field(doc_path: Path, region_id: str, field: str, page: str = "p0001"):
    """Add a field line directly after a region's `@@` header.

    Matching on the header *prefix* is not enough: the line is
    `@@ <id> <kind> <orientation>`, so splicing after `<id> <kind>` leaves the
    orientation trailing onto the inserted line and the field picks it up.
    """
    path = ir.doc_dir(doc_path) / "worksheets" / f"{page}.done.txt"
    out = []
    for line in path.read_text("utf-8").splitlines():
        out.append(line)
        header = worksheet.HEADER.match(line)
        if header and header.group("id") == region_id:
            out.append(field)
    path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="")


def test_a_worksheet_is_written_for_every_page_with_text(detected):
    report = worksheet.build_document(detected)
    assert report["count"] == 3
    assert len(report["fingerprint"]) == 64


def test_the_worksheet_names_the_images_to_look_at(detected):
    import crops

    crops.build_document(detected)
    worksheet.build_document(detected)
    text = (ir.doc_dir(detected) / "worksheets" / "p0001.txt").read_text("utf-8")
    assert "crops/p0001/overview.png" in text
    assert "crops/p0001/sheet01.png" in text


def test_a_field_continues_onto_the_next_line():
    blocks = worksheet.parse_worksheet(
        "@@ r001 speech\nsrc: one\ntwo\nfa: سلام\nدنیا\n"
    )
    assert blocks["r001"]["src"] == "one\ntwo"
    assert blocks["r001"]["fa"] == "سلام\nدنیا"


def test_comments_are_not_content():
    blocks = worksheet.parse_worksheet("@@ r001 speech\n# a note\nfa: سلام\n")
    assert blocks["r001"]["fa"] == "سلام"


def test_a_full_round_trip_merges(detected):
    worksheet.build_document(detected)
    _fill(detected)
    report = worksheet.merge_document(detected)
    assert report["ok"], report
    assert report["merged"] > 0

    doc = ir.load_doc(detected)
    assert all(region["target_text"] for _, region in ir.iter_regions(doc)
               if not region.get("dropped"))


def test_an_untranslated_page_is_named(detected):
    worksheet.build_document(detected)
    _fill(detected)
    (ir.doc_dir(detected) / "worksheets" / "p0002.done.txt").unlink()
    report = worksheet.merge_document(detected)
    assert report["missing_outputs"] == ["p0002"]
    assert not report["ok"]


def test_a_dropped_region_id_is_named(detected):
    worksheet.build_document(detected)
    _fill(detected)
    path = ir.doc_dir(detected) / "worksheets" / "p0001.done.txt"
    doc = ir.load_doc(detected)
    victim = doc["pages"][0]["regions"][0]["id"]
    text = path.read_text("utf-8").replace(f"@@ {victim} ", "@@ zzz_removed ")
    path.write_text(text, encoding="utf-8", newline="")

    report = worksheet.merge_document(detected)
    assert victim in report["missing_regions"]
    assert "zzz_removed" in report["unknown_regions"]


def test_a_repeated_region_id_is_named(detected):
    worksheet.build_document(detected)
    _fill(detected)
    doc = ir.load_doc(detected)
    victim = doc["pages"][0]["regions"][0]["id"]
    path = ir.doc_dir(detected) / "worksheets" / "p0001.done.txt"
    path.write_text(
        path.read_text("utf-8") + f"\n@@ {victim} speech\nsrc: x\nfa: دوباره\n",
        encoding="utf-8", newline="",
    )
    report = worksheet.merge_document(detected)
    assert victim in report["duplicate_regions"]


def test_an_empty_translation_is_named(detected):
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    victim = doc["pages"][0]["regions"][0]["id"]
    _fill(detected, skip=[victim])
    report = worksheet.merge_document(detected)
    assert victim in report["empty_translation"]


def test_drop_marks_a_region_as_having_no_text(detected):
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    victim = next(r["id"] for _, r in ir.iter_regions(doc) if r["kind"] == "sfx")
    _fill(detected, drop=[victim])
    report = worksheet.merge_document(detected)
    assert victim in report["dropped"]
    assert ir.find_region(ir.load_doc(detected), victim)["dropped"] is True


def test_the_reader_can_reclassify_a_region(detected):
    worksheet.build_document(detected)
    _fill(detected)
    doc = ir.load_doc(detected)
    victim = doc["pages"][0]["regions"][0]["id"]
    _insert_field(detected, victim, "kind: narration")
    worksheet.merge_document(detected)
    assert ir.find_region(ir.load_doc(detected), victim)["kind"] == "narration"


def test_an_invalid_kind_is_refused_not_applied(detected):
    worksheet.build_document(detected)
    _fill(detected)
    doc = ir.load_doc(detected)
    victim = doc["pages"][0]["regions"][0]["id"]
    _insert_field(detected, victim, "kind: balloon")
    report = worksheet.merge_document(detected)
    assert any(victim in entry for entry in report["bad_kind"])
    assert not report["ok"]


def test_speakers_reach_the_document(detected):
    worksheet.build_document(detected)
    _fill(detected)
    doc = ir.load_doc(detected)
    victim = doc["pages"][0]["regions"][0]["id"]
    _insert_field(detected, victim, "speaker: هاروکا")
    worksheet.merge_document(detected)
    assert ir.find_region(ir.load_doc(detected), victim)["speaker"] == "هاروکا"


# --- Staleness --------------------------------------------------------------

def test_rebuilding_refuses_when_finished_worksheets_no_longer_match(detected):
    worksheet.build_document(detected)
    _fill(detected)
    worksheet.merge_document(detected)

    doc = ir.load_doc(detected)
    doc["pages"][0]["regions"][0]["bbox"] = [1, 1, 30, 30]
    ir.save_doc(doc, detected)

    report = worksheet.build_document(detected)
    assert report["refused"] == "stale-worksheets"
    assert report["stale"]


def test_force_overrides_the_refusal(detected):
    worksheet.build_document(detected)
    _fill(detected)
    doc = ir.load_doc(detected)
    doc["pages"][0]["regions"][0]["bbox"] = [1, 1, 30, 30]
    ir.save_doc(doc, detected)
    assert "refused" not in worksheet.build_document(detected, force=True)


def test_merging_a_stale_worksheet_is_refused(detected):
    worksheet.build_document(detected)
    _fill(detected)
    doc = ir.load_doc(detected)
    doc["pages"][0]["regions"][0]["bbox"] = [2, 2, 30, 30]
    ir.save_doc(doc, detected)

    report = worksheet.merge_document(detected)
    assert "p0001" in report["stale_worksheets"]
    assert not report["ok"]


def test_status_counts_what_is_left(detected):
    worksheet.build_document(detected)
    _fill(detected)
    (ir.doc_dir(detected) / "worksheets" / "p0003.done.txt").unlink()
    report = worksheet.status(detected)
    assert report["pages_with_text"] == 3 and report["translated"] == 2
    assert report["remaining"] == ["p0003"]


def test_a_locked_glossary_entry_is_printed_in_the_worksheet(detected):
    doc = ir.load_doc(detected)
    doc["glossary"] = {"entries": {"ハルカ": {"target": "هاروکا", "role": "character",
                                            "locked": True}}}
    ir.save_doc(doc, detected)
    worksheet.build_document(detected)
    text = (ir.doc_dir(detected) / "worksheets" / "p0001.txt").read_text("utf-8")
    assert "هاروکا" in text and "binding" in text


# --- Adding what the detector missed ----------------------------------------

_ADDED = "\n@@ +bump sfx horizontal\nbox: 300 900 120 40\nsrc: BUMP\nfa: تلپ\n"


def test_a_reader_can_add_a_region_the_detector_never_found(detected):
    """The counterpart to `drop`, and a page needs both.

    Free lettering is the detector's weak case, adjacent balloons sometimes come
    back welded into one region, and a panel is occasionally taken for a balloon
    and swallows everything drawn inside it. Each of those loses text that is
    plainly there — measured on a real chapter, where a `BUMP` effect went
    undetected because the panel around it had been claimed as a balloon.
    """
    worksheet.build_document(detected)
    _fill(detected, extra=_ADDED)
    report = worksheet.merge_document(detected)

    assert report["ok"], report
    assert report["bad_added_regions"] == []
    assert len(report["added"]) == len(ir.load_doc(detected)["pages"])

    page = ir.load_doc(detected)["pages"][0]
    added = [r for r in page["regions"] if r["detector"] == "reader"]
    assert len(added) == 1
    region = added[0]
    assert region["bbox"] == [300, 900, 120, 40]
    assert region["kind"] == "sfx"
    assert region["target_text"] == "تلپ"
    assert region["balloon"] is None
    assert region["id"] not in {r["id"] for r in page["regions"] if r is not region}
    # It has to take its place in the reading order, not sit outside it.
    assert region["reading_order"] >= 1
    orders = [r["reading_order"] for r in page["regions"] if not r.get("dropped")]
    assert len(set(orders)) == len(orders)


def test_an_added_region_without_a_box_is_refused_not_guessed(detected):
    """There is no sane default for *where*, so the merge says so and fails."""
    worksheet.build_document(detected)
    _fill(detected, extra="\n@@ +bump sfx horizontal\nsrc: BUMP\nfa: تلپ\n")
    report = worksheet.merge_document(detected)

    assert not report["ok"]
    assert any("box" in message for message in report["bad_added_regions"])
    assert all(r["detector"] != "reader"
               for _, r in ir.iter_regions(ir.load_doc(detected)))


def test_adding_a_region_does_not_make_its_own_worksheet_stale(detected):
    """A new region changes the document fingerprint, so without re-stamping the
    very worksheet that added it would be rejected on the next merge — telling
    the reader to re-translate work they had only just added to."""
    worksheet.build_document(detected)
    _fill(detected, extra=_ADDED)
    assert worksheet.merge_document(detected)["ok"]

    again = worksheet.merge_document(detected)
    assert again["stale_worksheets"] == []


def test_merging_the_same_sheet_twice_updates_the_added_region(detected):
    """A worksheet is merged more than once — after a correction, after a
    shortened translation. Without a stable identity for the added box, the
    second merge made a second copy and then reported the first as a region the
    sheet had forgotten. Measured: three merges, three `bump` regions.
    """
    worksheet.build_document(detected)
    _fill(detected, extra=_ADDED)
    first = worksheet.merge_document(detected)
    assert first["ok"], first

    second = worksheet.merge_document(detected)
    assert second["ok"], second
    assert second["added"] == []
    assert second["missing_regions"] == []

    page = ir.load_doc(detected)["pages"][0]
    assert len([r for r in page["regions"] if r["detector"] == "reader"]) == 1


def test_moving_an_added_box_moves_the_region_and_forgets_its_balloon(detected):
    """Re-drawing the box is how a reader corrects one that clipped a letter."""
    worksheet.build_document(detected)
    _fill(detected, extra=_ADDED)
    assert worksheet.merge_document(detected)["ok"]

    path = ir.doc_dir(detected) / "worksheets" / "p0001.done.txt"
    path.write_text(path.read_text("utf-8").replace("box: 300 900 120 40",
                                                    "box: 290 890 150 60"),
                    encoding="utf-8")
    assert worksheet.merge_document(detected)["ok"]

    page = ir.load_doc(detected)["pages"][0]
    added = [r for r in page["regions"] if r["detector"] == "reader"]
    assert len(added) == 1
    assert added[0]["bbox"] == [290, 890, 150, 60]
    assert added[0]["balloon"] is None      # `mask` derives it again from the new box


def test_the_kind_on_an_added_header_is_honoured(detected):
    """`@@ +eh speech horizontal` says speech. Reading only the `kind:` field
    left every added region an sfx, which for a split balloon means no interior
    is found and Persian can be set over the outline."""
    worksheet.build_document(detected)
    _fill(detected, extra="\n@@ +eh speech horizontal\nbox: 300 900 120 40\n"
                          "src: EH?\nfa: ها؟\n")
    assert worksheet.merge_document(detected)["ok"]

    page = ir.load_doc(detected)["pages"][0]
    added = [r for r in page["regions"] if r["detector"] == "reader"][0]
    assert added["kind"] == "speech"
    assert added["orientation"] == "horizontal"


def test_dropping_a_region_forgets_what_an_earlier_run_did_to_it(detected):
    """Otherwise the stale `fill` speaks for a region nobody is cleaning."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    victim = [r for r in page["regions"] if not r.get("dropped")][0]
    victim["fill"] = "flat"
    victim["typeset"] = {"status": "ok", "size": 20}
    ir.save_doc(doc, detected)

    _fill(detected, drop=(victim["id"],))
    worksheet.merge_document(detected)

    after = [r for _, r in ir.iter_regions(ir.load_doc(detected))
             if r["id"] == victim["id"]][0]
    assert after["dropped"] is True
    assert after["fill"] == "none"
    assert after["typeset"] == {}


# --- keep --------------------------------------------------------------------
# `keep: yes` says "there IS text here and it stays in the artwork" — a shop
# sign, a logo, an effect. It is not `drop`, which says there is no text, and
# the difference is the whole point: `drop` made the terminal census file real
# lettering as a false detection.

def _apply(block, **region):
    """Run one worksheet block against one region and hand both back."""
    target = ir.new_region("p0001r001", [10, 10, 40, 20], kind="sfx")
    target.update(region)
    report = {"dropped": [], "kept": [], "reclassified": [], "bad_kind": []}
    worksheet._apply(target, block, report)
    return target, report


def test_keep_reaches_kept_by_policy_not_dropped():
    region, report = _apply({"keep": "yes", "src": "BUMP"})
    assert region["keep"] is True and region["dropped"] is False
    assert report["kept"] == ["p0001r001"]
    # Under every policy, including the one that would otherwise translate it.
    assert ir.region_state(region, "keep") == "kept_by_policy"
    assert ir.region_state(region, "translate") == "kept_by_policy"


def test_keep_is_a_review_so_it_locks_the_region():
    """A reader who writes `keep: yes` has looked at the region and decided.
    Without `locked` that decision reads as "never reviewed": `qa` warns
    `low-confidence-region` on it and the next `detect` run is free to
    renumber it away."""
    region, _ = _apply({"keep": "yes", "src": "BUMP"}, confidence=0.2)
    assert region["locked"] is True


def test_keep_still_takes_kind_speaker_and_note():
    """Found by audit: the keep branch returned before the shared metadata, so
    a reclassification, a speaker and a note written beside `keep: yes` were
    all silently discarded."""
    region, report = _apply(
        {"keep": "yes", "src": "STOP", "kind": "sign",
         "speaker": "\u0647\u0627\u0631\u0648\u06a9\u0627", "note": "shop front, left as drawn"},
    )
    assert region["kind"] == "sign"
    assert region["speaker"] == "\u0647\u0627\u0631\u0648\u06a9\u0627"
    assert region["review"] == ["shop front, left as drawn"]
    assert report["reclassified"] == ["p0001r001 -> sign"]
    assert region["keep"] is True


def test_keep_clears_a_previous_run_s_fill_and_typeset():
    region, _ = _apply({"keep": "yes", "src": "BUMP"},
                       fill="inpaint", typeset={"status": "ok", "size": 20})
    assert region["fill"] == "none" and region["typeset"] == {}


def test_dropping_a_region_that_was_kept_takes_the_keep_off():
    region, _ = _apply({"fa": "\u062a\u0631\u0633"}, keep=True)
    assert "keep" not in region
    assert ir.region_state(region, "translate") == "translated"


# --- R04: a worksheet must not lose a decision -------------------------------

def _sheets(doc_path):
    return ir.doc_dir(doc_path) / "worksheets"


def _add_fields(text, region_id, *fields):
    """Extra field lines inside a region's EXISTING block.

    Appending a second `@@ <id>` block instead would make the reply answer
    about that region twice, which is a duplicate and now refused — correctly,
    but it is not what these tests are about.
    """
    out = []
    for line in text.splitlines():
        out.append(line)
        if line.startswith(f"@@ {region_id} "):
            out.extend(fields)
    return "\n".join(out) + "\n"


def _page_of(doc_path, page_id):
    """Just one page, for comparing what a refused reply left behind."""
    doc = ir.load_doc(doc_path)
    return ir.dumps(next(p for p in doc["pages"] if p["id"] == page_id))


def _finish(doc_path, page_id, body=None):
    """Copy a page's worksheet to its `.done.txt`, optionally replacing it."""
    folder = _sheets(doc_path)
    text = body if body is not None else ir.read_text(folder / f"{page_id}.txt")
    ir.write_text(folder / f"{page_id}.done.txt", text)
    return text


def test_a_page_the_detector_found_nothing_on_still_gets_a_worksheet(detected):
    """Both `build` and `merge` skipped a page with no regions, so the one
    recovery the protocol offers — `@@ +slug` for text the detector missed —
    could not be used on exactly the page that needed it most. A page where
    detection failed completely was simply unreachable."""
    doc = ir.load_doc(detected)
    blank = doc["pages"][1]
    blank["regions"] = []
    ir.save_doc(doc, detected)

    report = worksheet.build_document(detected)
    assert (_sheets(detected) / f"{blank['id']}.txt").exists(), (
        f"no worksheet for a page with no detections: {report}")

    _finish(detected, doc["pages"][0]["id"])
    _finish(detected, doc["pages"][2]["id"])
    _finish(detected, blank["id"],
            ir.read_text(_sheets(detected) / f"{blank['id']}.txt")
            + "\n@@ +missed speech horizontal\nbox: 100 100 300 120\n"
              "src: やめろ\nfa: بس کن\n")

    merged = worksheet.merge_document(detected)
    assert merged["added"], f"the added region was not merged: {merged}"
    assert ir.load_doc(detected)["pages"][1]["regions"], "the page is still empty"


def test_a_rebuilt_worksheet_carries_the_decisions_back(detected):
    """`build` writes `src`, `fa` and `speaker` and nothing else, so a rebuild
    after a merge dropped every `drop`, `keep`, `erase` and `note` — and because
    an absent field RESETS those on the next merge, rebuilding silently undid
    reviewed decisions. A worksheet has to round-trip."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    first, second, third = [region["id"] for region in page["regions"]][:3]

    sheet = ir.read_text(_sheets(detected) / f"{page['id']}.txt")
    sheet = _add_fields(sheet, first, "drop: yes")
    sheet = _add_fields(sheet, second, "keep: yes")
    sheet = _add_fields(sheet, third, "erase: yes")
    _finish(detected, page["id"], sheet)
    for other in doc["pages"][1:]:
        _finish(detected, other["id"])
    worksheet.merge_document(detected)

    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    assert ir.find_region(doc, first).get("dropped") is True
    assert ir.find_region(doc, second)["keep"] is True
    assert ir.find_region(doc, third)["erase"] is True

    rebuilt = worksheet.page_worksheet(doc, page, ir.fingerprint(doc))
    assert "drop: yes" in rebuilt, "a dropped region came back as ordinary"
    assert "keep: yes" in rebuilt, "a kept region came back as ordinary"
    assert "erase: yes" in rebuilt, "an erased region came back as ordinary"


def test_merging_the_same_reply_twice_changes_nothing(detected):
    """A merge that is not idempotent punishes the ordinary act of running it
    again: the review note was appended a second time, so a page re-merged three
    times carried the same sentence three times."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    region_id = page["regions"][0]["id"]

    _finish(detected, page["id"], _add_fields(
        ir.read_text(_sheets(detected) / f"{page['id']}.txt"), region_id,
        "src: やめろ", "fa: بس کن", "note: check the speaker on this one"))
    for other in doc["pages"][1:]:
        _finish(detected, other["id"])

    worksheet.merge_document(detected)
    once = ir.dumps(ir.load_doc(detected))
    worksheet.merge_document(detected)
    twice = ir.dumps(ir.load_doc(detected))

    notes = ir.find_region(ir.load_doc(detected), region_id).get("review", [])
    assert notes.count("check the speaker on this one") == 1, notes
    assert once == twice, "merging the same reply twice changed the document"


def test_a_reply_with_a_duplicate_block_does_not_half_apply(detected):
    """A page reply is one answer about one page. When part of it is malformed,
    applying the rest leaves the page in a state nobody wrote: some regions
    carry the new reply, the others carry the old one, and the report only says
    a block was duplicated."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    first, second = [region["id"] for region in page["regions"]][:2]
    # This page only: the other two pages have sound replies and merge normally,
    # which is exactly what should happen.
    before = _page_of(detected, page["id"])

    sheet = _add_fields(ir.read_text(_sheets(detected) / f"{page['id']}.txt"),
                        first, "src: A", "fa: الف")
    # A second block for `second`, which is the duplicate under test.
    _finish(detected, page["id"], sheet
            + f"\n@@ {second} speech horizontal\nsrc: C\nfa: ج\n")
    for other in doc["pages"][1:]:
        _finish(detected, other["id"])

    report = worksheet.merge_document(detected)
    assert report["duplicate_regions"], "the fixture did not duplicate a block"
    assert _page_of(detected, page["id"]) == before, (
        "a reply with a duplicate block was partly applied anyway")


def test_a_reply_with_contradictory_actions_does_not_half_apply(detected):
    """`keep: yes` and `erase: yes` on one region are opposite instructions.
    They are already reported — but the rest of the page was applied around
    them, so the document moved on a reply nobody would have sent."""
    worksheet.build_document(detected)
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    first, second = [region["id"] for region in page["regions"]][:2]
    before = _page_of(detected, page["id"])

    sheet = _add_fields(ir.read_text(_sheets(detected) / f"{page['id']}.txt"),
                        first, "src: A", "fa: الف")
    sheet = _add_fields(sheet, second, "keep: yes", "erase: yes")
    _finish(detected, page["id"], sheet)
    for other in doc["pages"][1:]:
        _finish(detected, other["id"])

    report = worksheet.merge_document(detected)
    assert report["conflicting_actions"], "the fixture did not conflict"
    assert _page_of(detected, page["id"]) == before, (
        "a contradictory reply was partly applied anyway")
