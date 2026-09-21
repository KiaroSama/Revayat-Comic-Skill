# Native document companion: implementation sources

Inspected on 2026-09-21. The user approved native guidance and an editable Word
translation/review companion. The primary comic remains CBZ/PDF/images.

## Installed material and provenance boundary

The installed `skill-docx@Kiaro-Claude-Code-Templates` and
`skill-pdf-processing-pro@Kiaro-Claude-Code-Templates` packages were version
`1.0.0`. Both complete SKILL files were read. Relevant Word creation/XML
guidance, the Office validator, PDF OCR guidance, the shipped PDF form analyzer,
and referenced-helper availability were inspected without executing them.

| Package | Observed licensing and completeness | Decision |
| --- | --- | --- |
| docx | The plugin manifest says MIT, but SKILL frontmatter says proprietary and the bundled `LICENSE.txt` restricts copying, derivative works and distribution of the payload. | Do not redistribute its prompt, scripts, schemas or templates. Use independently authored code grounded in public OOXML documentation. |
| PDF Processing Pro | The plugin manifest and originating repository declare MIT. Only `scripts/analyze_form.py` ships; seven helpers advertised by SKILL are absent, as are its referenced requirements file and the forms guide's flattening helper. | Do not copy the incomplete toolkit or advertise those helpers. Route comic work to existing Revayat capabilities. |

The absent advertised helpers are `fill_form.py`, `validate_form.py`,
`extract_tables.py`, `extract_text.py`, `merge_pdfs.py`, `split_pdf.py` and
`validate_pdf.py`. The separate form guide also names absent `flatten_form.py`.
These observations concern the inspected installation, not every future release.

The inspected SKILL SHA-256 values were:

- docx: `1c4df72061111588437a86cd1551b8183c131048efb8861cab659804d5bdcbd4`
- PDF Processing Pro: `bd9fe31ecb1513a088c2a823657b4819a038939bbfd97fb4ee00fb6d24702b53`

## Independent public standards

Microsoft documents a WordprocessingML main story as document/body/paragraph/
run/text elements and describes the package relationship to the main document.
This supports a small stdlib ZIP/XML exporter; no JavaScript office runtime is
necessary for this transcript. [Document structure](https://learn.microsoft.com/en-us/office/open-xml/word/structure-of-a-wordprocessingml-document),
[package structure](https://learn.microsoft.com/en-us/office/open-xml/general/how-to-create-a-package).

Paragraph direction and run direction are distinct properties. Run RTL also
selects complex-script formatting and must not be indiscriminately applied to
strong Latin text. The native exporter stores logical Unicode and separates
strong-direction runs instead of using the image renderer's reshaped/display
text. [Paragraph BiDi](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.bidi),
[run RTL](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.righttolefttext).

Actual Word rendering exposed a separate alignment issue: Word interprets the
legacy `jc` left/right values relative to paragraph BiDi. The exporter uses the
leading edge (`left` with `bidi`), which places Persian at the physical right
margin. [Microsoft's implementation note, MS-OE376 2.3.1.13](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oe376/26ecf09a-0f0b-4574-9907-ebd1ddf3015f).

Font properties distinguish ASCII/high-ANSI and complex-script faces; language
properties distinguish Latin and complex-script proofing. The implementation
specifies complex-script font/size and Persian run language without embedding
fonts. Viewer substitution remains a presentation consideration.
[Run fonts](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.runfonts),
[run languages](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.languages).

The exporter writes all seven page-margin attributes explicitly; omission may
be tolerated by Word but is not the standard's requirement.
[Microsoft's page-margin conformance note](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oe376/5a1cdacc-ee75-4453-8118-de48e5e370d6).

## Native scope and validation

The companion records PageIR page/region identity, source and Persian variants,
existing decisions and notes, and the snapshot digest. It is deliberately
editable, so Word pagination is not asserted to equal comic pagination. It does
not mark translations reviewed, update primary-export metadata, import Word
edits, generate tracked changes, or reconstruct artwork in Word.

The installed PDF guide's whole-document 300-DPI OCR example is not a suitable
preservation baseline for comic scans. Revayat already has bounded pagewise
import, native image extraction where justified, separate PDF-point geometry,
and visible/package integrity checks. Optional reading copies and OCR remain
separate from the immutable source.

The shipped guide is original project guidance and references only actual
Revayat helpers. Structural tests and source-byte preservation checks address
the machine contract. A compatible renderer must still be used for visual
Persian inspection; no structural result is represented as that visual result
or as a bilingual quality judgment.
