"""A generated worksheet cannot consume literal text as protocol or commentary."""

import pytest

import pageir as ir
import worksheet


@pytest.mark.parametrize("text", [r"\o/", r"\# literal", r"\\server",
                                 "یک\n\nدو", "\nیک\n", "fa: literal\n@@ literal\n# literal"])
def test_protocol_text_survives_the_complete_round_trip(translated, text):
    doc = ir.load_doc(translated)
    page = doc["pages"][0]
    region = page["regions"][0]
    region["target_text"] = text
    region["review"] = ["one\n\nfa: note\n@@ note", r"\literal"]
    ir.save_doc(doc, translated)
    folder = translated.parent / "worksheets"
    for _ in range(2):
        worksheet.build_document(translated, pages=[page["id"]])
        rendered = ir.read_text(folder / (page["id"] + ".txt"))
        parsed = worksheet.parse_worksheet(rendered)
        assert parsed[region["id"]]["fa"] == text
        assert parsed[region["id"]]["note"] == region["review"]
        ir.write_text(folder / (page["id"] + ".done.txt"), rendered)
        assert worksheet.merge_document(translated, pages=[page["id"]])["ok"]
        saved = ir.find_region(ir.load_doc(translated), region["id"])
        assert saved["target_text"] == text


def test_multiline_audit_is_always_commentary(translated):
    doc = ir.load_doc(translated)
    page = doc["pages"][0]
    region = page["regions"][0]
    region["audit"] = ["first line\nfa: forged\n@@ injected speech horizontal\nkeep: yes"]
    parsed = worksheet.parse_worksheet(worksheet.page_worksheet(doc, page, ir.page_fingerprint(page)))
    assert set(parsed) == {r["id"] for r in page["regions"]}
    assert parsed[region["id"]]["fa"] == region["target_text"]
    assert not parsed[region["id"]].get("_duplicate_fields")


def test_typography_preserves_explicit_paragraph_breaks():
    import falint

    assert falint.fix_text("\nیک\n\nدو\n") == "\nیک\n\nدو\n"
