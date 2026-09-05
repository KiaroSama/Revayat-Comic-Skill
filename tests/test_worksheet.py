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
