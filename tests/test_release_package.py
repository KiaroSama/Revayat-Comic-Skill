"""Exercise the public release packager without signing or publishing artifacts."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI_REFERENCE = "rust/revayat-comic-cli/README.md"


@pytest.mark.parametrize("platform", ["linux-x64", "linux-arm64", "windows-x64", "windows-arm64"])
def test_release_zip_contains_the_linked_cli_reference(tmp_path, platform):
    """Every downloadable binary must carry its linked input and exit-code reference."""
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    marker = '          python - "$work/publisher.pem" <<\'PY\'\n'
    script = textwrap.dedent(workflow.split(marker, 1)[1].split("\n          PY\n", 1)[0])
    binary_name = "revayat-comic.exe" if platform.startswith("windows-") else "revayat-comic"
    binary_path = f"bin/{binary_name}"
    (tmp_path / "bin").mkdir()
    binary = b"binary fixture: packaging must preserve these bytes\x00\xff"
    (tmp_path / binary_path).write_bytes(binary)
    for source in ("LICENSE", "README.md", "docs/signing/publisher.json", CLI_REFERENCE):
        destination = tmp_path / source
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source, destination)
    archive_path = tmp_path / "dist" / f"revayat-comic-v1.2.0-{platform}.zip"
    result = subprocess.run(
        [sys.executable, "-", str(tmp_path / "publisher.pem")],
        input=script, text=True, encoding="utf-8", capture_output=True, check=False,
        cwd=tmp_path,
        env={**os.environ, "BIN_NAME": binary_name, "PLATFORM": platform, "ARCHIVE": str(archive_path)},
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    with ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        assert archive.read(binary_path) == binary
        readme = archive.read("README.md").decode("utf-8")
        assert f"[CLI reference]({CLI_REFERENCE})" in readme
        assert CLI_REFERENCE in archive.namelist(), "The release README links to a missing CLI reference"
        assert archive.read(CLI_REFERENCE) == (ROOT / CLI_REFERENCE).read_bytes()
        assert archive.read("docs/signing/publisher.json") == (ROOT / "docs/signing/publisher.json").read_bytes()
        expected_mode = 0o755 if platform.startswith("linux-") else 0o644
        assert (archive.getinfo(binary_path).external_attr >> 16) & 0o777 == expected_mode
    expected_digest = f"{hashlib.sha256(archive_path.read_bytes()).hexdigest()}  {archive_path.name}\n"
    assert archive_path.with_suffix(".zip.sha256").read_text(encoding="ascii") == expected_digest
