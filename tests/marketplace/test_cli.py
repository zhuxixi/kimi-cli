from typer.testing import CliRunner

from kimi_cli.cli import cli

runner = CliRunner()


def test_marketplace_help():
    result = runner.invoke(cli, ["marketplace", "--help"])
    assert result.exit_code == 0
    assert "add" in result.output
    assert "list" in result.output
    assert "remove" in result.output
    assert "sync" in result.output
