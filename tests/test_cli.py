from typer.testing import CliRunner

from help_wanted.cli import app


def test_one_command_writes_sample_outputs_and_announces_placeholders(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0, result.output
    assert "placeholder" in result.output.lower()
    assert (tmp_path / ".help-wanted/sample-contributor/recommendations.md").exists()
    fresh = CliRunner().invoke(app, ["--fresh"])
    assert fresh.exit_code == 0
