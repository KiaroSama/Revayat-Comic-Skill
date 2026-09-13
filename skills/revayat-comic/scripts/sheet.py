"""The sheet a reader fills in: the header, the glossary table, the blocks.

Printing only. What a filled-in sheet means when it comes back is
`worksheet.py`'s job, and the two were one file until the second half grew past
the size a file stays readable at.
"""

from __future__ import annotations

from typing import Any

import pageir as ir

#: Written into every sheet this build produces, so a reply that comes back
#: without it is recognisable as one an older build handed out — whose
#: fingerprint was computed a different way and cannot be compared with this
#: one. See `worksheet._stamp_state`.
STAMP_SCHEME = "2"

_DIRECTION_WORDS = {
    "rtl": "right to left (Japanese order: the rightmost balloon is first)",
    "ltr": "left to right",
}


def _rows(pairs: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """One line per entry, wide enough for the longest of them.

    Nothing is clipped. The columns used to be a fixed 21 characters, so a
    long name was printed as most of itself — a binding spelling that was
    not the spelling, which is worse than no table at all.
    """
    source_width = max(len(source) for source, _ in pairs)
    target_width = max(len(entry.get("target", "")) for _, entry in pairs)
    lines = [
        f"#   {'source':<{source_width}}  {'Persian':<{target_width}}  role",
        f"#   {'-' * source_width}  {'-' * target_width}  {'-' * 18}",
    ]
    for source, entry in pairs:
        lines.append(
            f"#   {source:<{source_width}}  "
            f"{entry.get('target', ''):<{target_width}}  "
            f"{entry.get('role', '')}"
        )
    return lines


def _glossary_table(doc: dict[str, Any], limit: int = 40) -> list[str]:
    """The names table, with the binding rows separated from the guesses.

    Everything with a `target` used to be printed under a heading saying it
    was binding, including the entries the scan proposed and nobody had
    approved. A translator told a guess is binding spells the rest of the
    chapter to match it. And the whole thing stopped at 40 rows with
    nothing said, so enough guesses pushed the one approved term off the
    end — which is why the cap now falls on the guesses only.
    """
    entries = doc.get("glossary", {}).get("entries", {})
    with_target = [(source, entry) for source, entry in entries.items()
                   if entry.get("target")]
    binding = [pair for pair in with_target if pair[1].get("locked")]
    suggested = [pair for pair in with_target if not pair[1].get("locked")]
    if not with_target:
        return []

    lines: list[str] = []
    if binding:
        lines += [
            "# Names and terms — these are binding. Use exactly the "
            "Persian given.",
            "#",
        ]
        lines += _rows(binding)
        lines.append("#")

    room = max(0, limit - len(binding))
    shown = suggested[:room]
    if shown:
        lines += [
            "# Proposed by the scan and not binding — nobody has approved "
            "these.",
            "# Use one if it is right; if it is wrong, just translate "
            "normally.",
            "#",
        ]
        lines += _rows(shown)
        lines.append("#")
    hidden = len(suggested) - len(shown)
    if hidden:
        lines.append(f"#   … and {hidden} more suggestion(s) not shown.")
        lines.append("#")
    return lines


def page_worksheet(doc: dict[str, Any], page: dict[str, Any], fingerprint: str) -> str:
    meta = doc["meta"]
    direction = meta.get("reading_direction", "rtl")
    regions = page.get("regions", [])

    lines = [
        f"# {meta.get('title') or 'comic'} — page {page['id']} "
        f"({page['index'] + 1} of {len(doc['pages'])})",
        # This PAGE's fingerprint. A document-wide one made a correction on
        # any page declare every other page's finished reply stale.
        f"# fingerprint: {fingerprint}",
        # Says the stamp above is a PAGE fingerprint under the current
        # algorithm. A reply that comes back without this line was
        # handed out by a build that hashed the whole document, and
        # comparing the two would call every old reply stale.
        f"# scheme: {STAMP_SCHEME}",
        # The overview is downscaled to fit OVERVIEW_MAX_SIDE, so on a tall page
        # a box measured on it is NOT in the page's pixels. Everything used to
        # say it was, which meant a visually correct box erased a different part
        # of the artwork. The conversion is printed here, where the reader is.
        *([
            f"# This page is {page['width']}x{page['height']}. overview.png is "
            f"drawn at {page.get('overview_scale', 1.0):.3f} of that, so divide "
            f"any box you measure on it by that number before writing a `box:`.",
            "#",
        ] if page.get("overview_scale", 1.0) < 0.999 else []),
        "#",
        "# Look at these before writing anything:",
        f"#   {page.get('overview', '(run crops first)')}",
    ]
    for sheet in page.get("sheets", []):
        lines.append(f"#   {sheet}")
    lines += [
        "#",
        f"# Source language: {meta.get('source_language')}   "
        f"target: {meta.get('target_language')}",
        f"# Reading order: {_DIRECTION_WORDS.get(direction, direction)}",
        f"# Sound effects: {meta.get('sfx_policy', 'keep')}",
        "#",
    ]
    # Standing decisions for this title, if somebody has made any. On the page
    # the reader is looking at, because a policy filed somewhere else is a
    # policy that gets re-decided per chapter.
    policy = ir.title_policy(meta)
    if policy:
        lines.append("# This title has settled:")
        for key, value in policy.items():
            lines.append(f"#   {key}: {value}")
        lines.append("#")
    lines += [
        "# Fill in `src:` with what the balloon actually says, and `fa:` with the",
        "# Persian. Keep every `@@` line exactly as it is. A field continues on",
        "# the following lines until the next field or the next `@@`.",
        "#",
        "# Optional corrections — use them when the crop shows the detector was",
        "# wrong. You can see the page; it could not.",
        "#   kind:    speech | thought | narration | sfx | sign | unknown",
        "#   speaker: a short stable name, the same one every time",
        "#   fa_full: the FULL-meaning Persian, when `fa:` above is a",
        "#            shortened variant that had to fit the balloon. Both are",
        "#            kept, and `qa` puts the pair in front of a reviewer.",
        "#   reviewed: a lint code you have looked at and settled, so the",
        "#             gate stops asking — e.g. `reviewed: zwnj-review` on a",
        "#             line where `می` is wine and not the verb prefix",
        "#   propose: a name or term this balloon MENTIONS but does not say —",
        "#            `propose: Anna` for \"did you see Anna?\". Several are",
        "#            separated by commas. This is NOT who is talking.",
        "#   drop:    yes   — there is no text here at all",
        "#   keep:    yes   — there IS text, leave it in the artwork",
        "#   erase:   yes   — remove this and put nothing back (a watermark,",
        "#                    a site stamp, a scan credit). Only for marks you",
        "#                    have the right to remove.",
        "#",
        "# Something the detector missed entirely? Add it. Free lettering is",
        "# the weak case, adjacent balloons sometimes come back as one region,",
        "# and a whole panel is occasionally taken for a balloon — so a page can",
        "# be missing text that is plainly there in overview.png.",
        "#",
        "#   @@ +bump sfx horizontal",
        "#   box: 742 436 58 24        <- x y w h, in the page's own pixels,",
        "#                                measured on overview.png — see the",
        "#                                scale note above if there is one",
        "#   src: BUMP",
        "#   fa: تلپ",
        "#",
        "# Add `polarity: dark` when the lettering is white on black. After a",
        "# merge that added regions, run `mask` again before `clean`.",
        "#",
    ]
    lines += _glossary_table(doc)

    for region in regions:
        lines.append("")
        lines.append(f"@@ {region['id']} {region['kind']} {region['orientation']}")
        if region.get("panel"):
            lines.append(f"# panel {region['panel']}, "
                         f"reading order {region.get('reading_order')}")
        if region.get("confidence", 1.0) < 0.5:
            lines.append("# low-confidence detection — check the crop; "
                         "`drop: yes` if there is no text")
        lines.append(f"src: {region.get('source_text', '')}")
        lines.append(f"fa: {region.get('target_text', '')}")
        if region.get("speaker"):
            lines.append(f"speaker: {region['speaker']}")
        if region.get("proposed"):
            lines.append(f"propose: {', '.join(region['proposed'])}")
        if region.get("target_full"):
            lines.append(f"fa_full: {region['target_full']}")
        if region.get("review_ack"):
            lines.append(f"reviewed: {', '.join(region['review_ack'])}")
        # Decisions already taken are written back out. An ABSENT field resets
        # them at the next merge, so a rebuilt worksheet silently undid every
        # `drop`, `keep` and `erase` a reader had reviewed — and the notes with
        # them. A worksheet has to be a faithful picture of the page.
        if region.get("dropped"):
            lines.append("drop: yes")
        if region.get("keep"):
            lines.append("keep: yes")
        if region.get("erase"):
            lines.append("erase: yes")
        for note in region.get("review", []):
            lines.append(f"note: {note}")
    return "\n".join(lines) + "\n"
