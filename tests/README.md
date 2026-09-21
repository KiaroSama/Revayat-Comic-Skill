# Running the regression suite

Install the pipeline requirements and `tests/requirements.txt` with the same
Python interpreter. The latter contains fontTools, used only to generate temporary
fonts with individual missing codepoints. These fonts are never committed or installed.

The full suite requires DejaVu Sans 2.37. Set `REVAYAT_TEST_FONT` to its TTF path,
or place it at `fonts/round5/DejaVuSans.ttf` for local testing. Obtain it from the
[upstream release](https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37).
The SHA-256 of the face used by CI is
`7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954`.
The normal system Persian face is tested independently as well.

Run `python -m pytest tests -q --timeout=300 --junitxml=junit.xml`, followed by
`python tests/e2e_pipeline.py`. Use the project's guarded runner where installed.
On a restricted machine, give pytest a fresh `--basetemp` whose parent exists
and is writable. The CI matrix installs its own fonts and runs the complete suite
on each supported OS/Python combination and on the literal dependency floors.

`test_publication_faults.py` uses 48x64 generated pages to inject failures on
both sides of each journal, backup, promotion and metadata boundary. It also kills
a real child process during publication and exercises explicit recovery.
`test_anchored_ink.py` renders onto an independent expanded canvas; no numeric
font-size assumption stands in for ink containment. The default shaper and forced
fallback both run; the Linux lane separately requires actual RAQM availability.

Fonts, generated pages, test packages and logs remain temporary. File-processing
tests on an operator's real comic are separate from these portable regression fixtures.
