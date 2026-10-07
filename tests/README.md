# Running the regression suite

Install the runtime and developer requirements with the same Python interpreter:

```bash
python -m pip install -r skills/revayat-comic/requirements.txt -r tests/requirements.txt
```

The self-contained skill manifest contains runtime packages only. The test manifest
contains pytest, pytest-timeout, Ruff and fontTools. Tool floors are not the core
runtime compatibility minima: the literal-floor CI lane pins every runtime package,
then resolves developer tools separately. fontTools generates temporary fonts with
individual missing codepoints; these fonts are never committed or installed.

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

`stdio_client.py` owns live JSON-lines clients through the same real-base-interpreter
launch gate, Windows Job Object/pinned-member waits or POSIX process group as
`process_support.py`. Replies and writes have 30-second wall and 20-second idle
ceilings; close has a 20-second wall ceiling. Both pipes drain concurrently. Replies
are strict UTF-8 with an LF terminator and at most 4 MiB; queued stdout is bounded,
and stderr retains only its last 64 KiB. Timeout, malformed reply, EOF and normal
close terminate remaining descendants, reap the gate, join pipe workers and close
all pipes. Cleanup itself is finite (five-second owner waits and a shared five-second
worker join). The tiny lifecycle controls need no comic/image setup. One-shot byte
regressions retain malformed-frame/healthy-next-request assertions through the shared
owner; each E2E stage has a 180-second wall/60-second idle ceiling.

The seven full-suite lanes still discover the entire `tests` directory. PDF and
fallback packages cannot skip in lanes installing them; Linux also requires RAQM,
CJK and the real RAR reader. The named Windows/macOS RAQM/CJK/RAR gaps remain
accepted. Empty/truncated JUnit is not evidence. Weekly CBR runs the reader file
once, retains `junit-cbr.xml` on failure too, and requires its actual real-RAR case
to pass. Synthetic report/config mutations cover capability loss, floor drift,
OpenCV's distribution suffix and hidden multiline test selectors without a second
workflow execution. Runtime-only CLI/E2E lanes remain separate from developer tools.

Fonts, generated pages, test packages and logs remain temporary. File-processing
tests on an operator's real comic are separate from these portable regression fixtures.
