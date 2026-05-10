import json
from pathlib import Path

import pytest

from kimi_cli.marketplace.loader import load_plugin_from_path
from kimi_cli.plugin import PluginError


def test_load_with_manifest(tmp_path):
    plugin_dir = tmp_path / "my-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "my-plugin", "version": "1.0.0"}),
        encoding="utf-8",
    )
    (plugin_dir / "commands").mkdir()
    (plugin_dir / "skills").mkdir()

    loaded = load_plugin_from_path(plugin_dir)
    assert loaded.spec.name == "my-plugin"
    assert loaded.commands_path == plugin_dir / "commands"
    assert loaded.skills_path == plugin_dir / "skills"
    assert loaded.agents_path is None


def test_load_without_manifest(tmp_path):
    plugin_dir = tmp_path / "orphan"
    plugin_dir.mkdir()
    loaded = load_plugin_from_path(plugin_dir)
    assert loaded.spec.name == "orphan"
    assert loaded.spec.version == "unknown"


def test_load_missing_dir():
    with pytest.raises(PluginError):
        load_plugin_from_path(Path("/nonexistent"))
