"""CLI runs leave separate UTF-8 logs, including sanitized failures."""

import pytest

import pageir as ir


def test_cli_logging_records_outcomes_without_arguments_or_secret_values(tmp_path):
    @ir.cli
    def command(argv):
        if "--fail" in argv:
            raise ValueError("private-test-value")
        return 0

    args = ["--doc", str(tmp_path / "comic.json"), "--token", "private-test-value"]
    assert command(args) == 0
    with pytest.raises(ValueError):
        command([*args, "--fail"])
    logs = list((tmp_path / "logs").glob("*.log"))
    assert len(logs) == 2
    content = "\n".join(path.read_text(encoding="utf-8") for path in logs)
    assert "[INFO]" in content and "[ERROR]" in content
    assert "exit=0" in content and "ValueError" in content
    assert "private-test-value" not in content and "--token" not in content
    assert "UTC]" in content
    # All handlers are closed; this also exercises Windows file ownership.
    for path in logs:
        path.unlink()


def test_successful_argparse_exit_is_logged_as_success(tmp_path):
    @ir.cli
    def command(argv):
        raise SystemExit(0)

    with pytest.raises(SystemExit) as ended:
        command(["--doc", str(tmp_path / "comic.json")])
    assert ended.value.code == 0
    content = next((tmp_path / "logs").glob("*.log")).read_text(encoding="utf-8")
    assert "exit=0" in content
    assert "[ERROR]" not in content
