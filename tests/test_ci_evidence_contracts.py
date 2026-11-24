"""Cheap report/config admission mutations; no workflow or target execution."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

import test_ci_guards

check_skips = test_ci_guards.check_skips  # Reuse the existing fixture unchanged.

ROOT = Path(__file__).resolve().parents[1]


def test_main_ci_is_automatically_attached_to_pr_updates_and_main():
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    events = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert re.search(r"^  pull_request:\s*$", events, re.M), "new PR heads have no main CI"
    assert re.search(r"^  push:\s*\n    branches: \[main\]", events, re.M)
    assert not re.search(r"^    (?:paths|paths-ignore|branches-ignore):", events, re.M)
    assert "  workflow_dispatch:" in events


def test_native_ci_installs_and_requires_both_rust_backends():
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "  native-python:" in text, "compiled crates are never loaded by Python CI"
    job = text.split("  native-python:", 1)[1]
    assert "./rust/hotcore-rs ./rust/pixcore-rs" in job
    for crate in (
        "hotcore", "pixcore", "maskcore", "textcore", "detectcore",
        "qacore", "cleancore", "layoutcore", "packcore",
    ):
        assert f"./rust/{crate}-rs" in job, crate
        assert f"tests/test_{crate}_parity.py" in job, crate
    assert "hotcore.BACKEND == pixcore.BACKEND == 'rust'" in job
    assert "ubuntu-latest, macos-latest, windows-latest" in job
    assert "RUSTUP_TOOLCHAIN: stable" in job.split("    steps:", 1)[0]
    modules = re.search(r"modules = \(([^\n]+)\)", job)
    assert modules and {name.strip() for name in modules[1].split(",")} == set(KERNELS)
    assert "if m.BACKEND != 'rust'" in job and "assert not missing" in job


KERNELS = (
    "hotcore", "pixcore", "maskcore", "textcore", "detectcore",
    "qacore", "cleancore", "layoutcore", "packcore",
)


def cargo_file(crate, name="Cargo.toml"):
    return tomllib.loads((ROOT / "rust" / crate / name).read_text(encoding="utf-8"))


def test_rust_toolchain_pins_compiler_and_checks():
    toolchain = tomllib.loads((ROOT / "rust-toolchain.toml").read_text(encoding="utf-8"))["toolchain"]
    assert toolchain["channel"] == "1.100.0"
    assert set(toolchain["components"]) == {"rustfmt", "clippy"}


@pytest.mark.parametrize("crate", [*(f"{kernel}-rs" for kernel in KERNELS), "revayat-comic-cli"])
def test_cargo_manifests_set_edition_and_compiler_floor(crate):
    package = cargo_file(crate)["package"]
    assert package["edition"] == "2024"
    assert package["rust-version"] == "1.100.0"


@pytest.mark.parametrize("kernel", KERNELS)
def test_pyo3_wheel_features_allow_rust_only_build(kernel):
    crate = f"{kernel}-rs"
    manifest = cargo_file(crate)
    pyo3 = manifest["dependencies"]["pyo3"]
    assert pyo3["version"] == "0.30.1"
    assert pyo3["optional"] is True
    assert "abi3-py312" in pyo3["features"]
    assert manifest["features"]["default"] == ["python"]
    assert manifest["features"]["python"] == ["dep:pyo3"]
    locked = {p["version"] for p in cargo_file(crate, "Cargo.lock")["package"] if p["name"] == "pyo3"}
    assert locked == {"0.30.1"}


def test_standalone_cli_has_all_kernels_without_pyo3():
    crate = "revayat-comic-cli"
    dependencies = cargo_file(crate)["dependencies"].values()
    kernels = {dep["package"]: dep for dep in dependencies if isinstance(dep, dict) and "path" in dep}
    assert kernels.keys() == {f"{kernel}-rs" for kernel in KERNELS}
    for name, dependency in kernels.items():
        assert dependency["path"] == f"../{name}"
        assert dependency["default-features"] is False
    assert "pyo3" not in {p["name"] for p in cargo_file(crate, "Cargo.lock")["package"]}


def test_rust_ci_checks_both_kernel_feature_modes_and_standalone_cli():
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    job = text.split("  rust-crates:", 1)[1].split("  native-python:", 1)[0]
    assert 'toolchain: "1.100.0"' in job and "toolchain: stable" in job
    assert "1.97.0" not in job
    kernels, cli = job.split("name: Verify the standalone Rust CLI", 1)
    for kernel in KERNELS:
        assert f"rust/{kernel}-rs" in kernels
        assert f'"{kernel}-rs"' in cli, f"doctor must verify {kernel}-rs"
    assert 'cargo fmt --manifest-path "$crate/Cargo.toml" -- --check' in kernels
    for command in ("clippy", "test"):
        modes = [line for line in kernels.splitlines() if f"cargo {command} " in line]
        assert len(modes) == 2 and sum("--no-default-features" in line for line in modes) == 1
        assert all("--locked" in line for line in modes)
        if command == "clippy":
            assert all("--all-targets" in line and "-- -D warnings" in line for line in modes)
    for value in (
        "rust/revayat-comic-cli/Cargo.toml", "cargo fmt", "cargo clippy", "--all-targets",
        "cargo test", "--locked", "cargo tree", "pyo3", "cargo build --release",
        "./rust/revayat-comic-cli/target/release/revayat-comic", '"doctor", "--json"',
        'report["ok"] is True',
    ):
        assert value in cli


def test_release_builds_only_four_native_64_bit_targets():
    path = ROOT / ".github/workflows/release.yml"
    assert path.is_file(), "release workflow is missing"
    workflow = path.read_text(encoding="utf-8")
    build = workflow.split("  build:", 1)[1].split("  signing:", 1)[0]
    assert re.search(r"^permissions:\n  contents: read\n\n", workflow, re.M)
    matrix = set(re.findall(r"^\s+- platform: (\S+)\n\s+os: (\S+)$", build, re.M))
    assert matrix == {
        ("linux-x64", "ubuntu-24.04"), ("linux-arm64", "ubuntu-24.04-arm"),
        ("windows-x64", "windows-2025"), ("windows-arm64", "windows-11-arm"),
    }
    assert len(re.findall(r"^\s+os:", build, re.M)) == 4
    assert not re.search(r"\b(?:macos|i[3-6]86|win32|x86-unknown|386)\b", workflow, re.I)
    for value in ("cargo test", "cargo build --release", "1.100.0", "pyo3", "ldd", "python3", "doctor", "--json"):
        assert value in build


def test_release_signing_and_provenance_stay_behind_tag_gate():
    path = ROOT / ".github/workflows/release.yml"
    assert path.is_file(), "release workflow is missing"
    workflow = path.read_text(encoding="utf-8")
    build, signing_and_publish = workflow.split("  signing:\n", 1)
    signing, publish = signing_and_publish.split("  publish:\n", 1)
    assert "REVAYAT_SIGNING_PRIVATE_KEY_PEM" not in build
    assert "name: revayat-signing" in signing and "name: revayat-signing" in publish
    assert re.match(r"    if: startsWith\(github.ref, 'refs/tags/v'\)\n", publish)
    key_step = next(step for step in signing.split("      - ") if "secrets.REVAYAT_SIGNING_PRIVATE_KEY_PEM" in step)
    assert "if: startsWith(github.ref, 'refs/tags/v')" in key_step
    assert "openssl dgst -sha256 -sign" in key_step and "openssl dgst -sha256 -verify" in key_step
    assert "tampered.zip" in key_step and "trap " in key_step
    assert "SHA256SUMS" in publish and "SHA256SUMS.sig" in publish
    assert "openssl dgst -sha256 -sign" in publish and "openssl dgst -sha256 -verify" in publish
    assert "tampered" in publish and "trap " in publish
    assert re.search(r"uses: actions/attest-build-provenance@[a-f0-9]{40} # v4\.\d+\.\d+", publish)


def test_publisher_metadata_contains_only_public_material():
    text = (ROOT / "docs/signing/publisher.json").read_text(encoding="utf-8")
    assert "PRIVATE KEY" not in text
    metadata = json.loads(text)
    assert metadata["schema_version"] == 1
    assert metadata["publisher"] == "Revayat Comic"
    assert metadata["publisher_email"] == "Kiaro.Sama.Dev@gmail.com"
    assert metadata["signature_algorithm"] == "rsa-pkcs1-v1_5-sha256"
    assert metadata["key_bits"] == 3072
    pem = metadata["public_key_pem"]
    assert re.fullmatch(r"-----BEGIN PUBLIC KEY-----\n(?:[A-Za-z0-9+/=]+\n)+-----END PUBLIC KEY-----\n?", pem)
    der = base64.b64decode("".join(pem.splitlines()[1:-1]), validate=True)
    assert metadata["public_key_sha256"] == hashlib.sha256(der).hexdigest()


def test_bilingual_readme_badges_keep_order_and_current_release_links():
    colors = (
        "16a34a", "2563eb", "ea580c", "0d9488", "8b5cf6", "9a3412", "0891b2", "4f46e5",
        "0284c7", "ca8a04", "15803d", "b45309", "334155", "7c3aed", "c2410c", "d04a9a",
    )
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    new_files = subprocess.check_output(
        ["git", "ls-files", "-z", "--others", "--exclude-standard", "--", "rust-toolchain.toml",
         "docs/signing/publisher.json", ".github/workflows/release.yml", "rust/revayat-comic-cli/"], cwd=ROOT,
    ).decode("utf-8").split("\0")
    paths = set(tracked + new_files) - {""}
    size = f"{sum((ROOT / name).stat().st_size for name in paths) / 1_000_000:.1f}"
    for readme in ("README.md", "README.fa.md"):
        text = (ROOT / readme).read_text(encoding="utf-8")
        block = text.split('<div align="center">', 1)[1].split("</div>", 1)[0]
        badges = re.findall(r"\[!\[[^\n]*?\]\((https://img\.shields\.io/[^)]+)\)\]\(([^)]+)\)", block)
        assert tuple(re.split("[=&-]", url)[-1] for url, _ in badges) == colors, readme
        assert badges[2] == (
            "https://img.shields.io/github/v/tag/KiaroSama/Revayat-Comic-Skill?label=version&color=ea580c",
            "https://github.com/KiaroSama/Revayat-Comic-Skill/tags",
        ), readme
        assert badges[5] == ("https://img.shields.io/badge/Rust-1.100.0-9a3412", "rust-toolchain.toml"), readme
        assert badges[9][0] == f"https://img.shields.io/badge/repo%20size-{size}%20MB-ca8a04", readme
        assert badges[15][1] == "#donate", readme


def runtime_floors(text):
    floors = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([a-zA-Z0-9_.-]+)>=([0-9]+(?:\.[0-9]+)*)", line)
        if not match:
            raise ValueError(f"unsupported runtime requirement: {line}")
        name = re.sub(r"[-_.]+", "-", match[1]).lower()
        if name in floors:
            raise ValueError(f"duplicate runtime requirement: {name}")
        floors[name] = match[2]
    return floors


def floor_mismatches(requirements, job):
    pins = dict(re.findall(r'"([a-z0-9.-]+)==([0-9.]+)"', job))
    bad = []
    for name, floor in runtime_floors(requirements).items():
        # OpenCV uses a fourth distribution/build component for release 4.8.1.
        expected = "4.8.1.78" if name == "opencv-python-headless" and floor == "4.8.1" else floor
        actual = pins.get(name, "")
        def release(version):
            values = [int(value) for value in version.split(".")] if version else []
            while values and values[-1] == 0:
                values.pop()
            return values
        if not actual or release(actual) != release(expected):
            bad.append(name)
    return bad


def full_suite_problem(job):
    # Inspect the WHOLE full-suite job: a Python argument array can put its
    # selector on another line. Remove only module-launch syntax, not selectors.
    if not re.search(r'pytest["\']?\s*(?:,\s*["\']|\s+)tests(?:["\']|\s)', job):
        return "full tests directory is not selected"
    text = re.sub(r'\bpython\s+-m\s+[\w.]+|["\']-m["\']\s*,\s*["\']pytest["\']', 'module', job)
    if re.search(r'(?:[\s"\'])(?:-k|-m|--deselect|--ignore(?:-glob)?)(?=[\s"\'=])', text):
        return "full-suite job contains test selection"
    return None


def report(tmp_path, node="test_typeset::test_raqm_shapes_persian_and_agrees_with_the_fallback", message=None):
    from xml.etree.ElementTree import Element, SubElement, ElementTree
    root = Element("testsuites")
    case = SubElement(SubElement(root, "testsuite"), "testcase", classname=node.split("::")[0], name=node.split("::")[1])
    if message is not None:
        SubElement(case, "skipped", message=message)
    path = tmp_path / "evidence.xml"
    ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


@pytest.mark.parametrize("job", ["test", "minimum-dependencies", "cbr"])
@pytest.mark.parametrize("node,message", [
    ("test_readers::test_pdf", "could not import pymupdf"),
    ("test_typeset::test_fallback", "could not import arabic_reshaper"),
    ("test_typeset::test_fallback", "could not import bidi"),
    ("test_typeset::test_raqm_shapes_persian_and_agrees_with_the_fallback", "no RAQM"),
    ("test_readers::test_a_real_rar_round_trips", "no unrar backend"),
])
def test_required_linux_capabilities_cannot_skip(tmp_path, check_skips, job, node, message):
    assert check_skips.offenders(report(tmp_path, node, message), "Linux", job)


@pytest.mark.parametrize("runner", ["Windows", "macOS"])
def test_only_named_platform_raqm_skip_is_accepted(tmp_path, check_skips, runner):
    path = report(tmp_path, message="no RAQM in this Pillow")
    assert check_skips.offenders(path, runner, "test") == []
    assert check_skips.offenders(path, runner, "unrelated-job")
    path = report(tmp_path, "test_typeset::test_unrelated", "no RAQM")
    assert check_skips.offenders(path, runner, "test")


@pytest.mark.parametrize("text", ["", "<testsuites/>", "<testsuites><testsuite/></testsuites>", "<testsuites>"])
def test_missing_empty_or_truncated_evidence_fails(tmp_path, check_skips, text):
    path = tmp_path / "bad.xml"
    path.write_text(text, encoding="utf-8")
    assert check_skips.main(["check_skips.py", str(path)]) == 1


def test_real_cbr_evidence_requires_the_real_case(tmp_path, check_skips, monkeypatch):
    monkeypatch.setenv("RUNNER_OS", "Linux")
    monkeypatch.setenv("GITHUB_JOB", "cbr")
    assert check_skips.main(["check_skips.py", str(report(tmp_path, "test_readers::test_the_real_rar_fixture_is_text_and_decodes"))]) == 1
    assert check_skips.main(["check_skips.py", str(report(tmp_path, "test_readers::test_a_real_rar_round_trips"))]) == 0


def test_missing_capability_can_only_skip_in_deliberate_minimal_job(tmp_path, check_skips):
    path = report(tmp_path, "test_readers::test_pdf", "could not import pymupdf")
    assert check_skips.offenders(path, "Linux", "minimal-runtime") == []
    assert check_skips.offenders(path, "Linux", "test")


def test_changed_runtime_floor_cannot_keep_the_old_ci_pin():
    assert floor_mismatches("pillow>=10.1", '"pillow==10.0.0"') == ["pillow"]
    assert floor_mismatches("pillow>=10.0", '"pillow==10.0.0"') == []
    assert floor_mismatches("opencv-python-headless>=4.8.1", '"opencv-python-headless==4.8.1.78"') == []
    assert floor_mismatches("opencv-python-headless>=4.9.0", '"opencv-python-headless==4.8.1.78"')


@pytest.mark.parametrize("selector", ["-k", "-m", "--deselect", "--ignore"])
def test_multiline_argument_arrays_cannot_hide_full_suite_selection(selector):
    job = f'run = [sys.executable, "-m", "pytest", "tests",\n "{selector}", "some-case"]'
    assert full_suite_problem(job) == "full-suite job contains test selection"
    assert full_suite_problem('python -m pytest tests -q --timeout=300\n --junitxml=x.xml') is None


def test_weekly_cbr_has_one_execution_and_retains_its_report():
    text = (ROOT / ".github/workflows/integration.yml").read_text(encoding="utf-8")
    job = text.split("  cbr:", 1)[1].split("  full_resolution:", 1)[0]
    assert job.count("python -m pytest tests/test_readers.py") == 1
    assert '"-m", "pytest"' not in job
    assert "--junitxml=junit-cbr.xml" in job and "check_skips.py junit-cbr.xml" in job
    assert "if: always()" in job and "actions/upload-artifact@" in job
