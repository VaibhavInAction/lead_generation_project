"""CLI smoke tests: the app loads, --version works, doctor runs end to end."""

from typer.testing import CliRunner

from leadforge import __version__
from leadforge.cli.app import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_doctor_runs(tmp_path, monkeypatch) -> None:
    # Run in a temp dir so doctor's dir/db checks don't touch the repo.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    result = runner.invoke(app, ["doctor"])
    assert "python" in result.output
    assert "database" in result.output
    # Environment-dependent checks may warn, but nothing should hard-fail here.
    assert result.exit_code == 0
