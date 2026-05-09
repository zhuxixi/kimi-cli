import json
from pathlib import Path
from unittest.mock import patch

import pytest

from kimi_cli.marketplace.manager import (
    get_known_marketplaces_path,
    load_known_marketplaces,
    save_known_marketplaces,
)
from kimi_cli.marketplace.operations import install_plugin_from_marketplace
from kimi_cli.marketplace.reconciler import reconcile_marketplaces
from kimi_cli.marketplace.schemas import DirectorySource, KnownMarketplace
from kimi_cli.plugin.manager import get_plugins_dir, list_plugins


@pytest.fixture(autouse=True)
def isolate_share_dir(tmp_path):
    """Override get_share_dir to use a temp directory for each test."""
    fake_share = tmp_path / ".kimi"
    fake_share.mkdir(parents=True, exist_ok=True)
    with patch("kimi_cli.marketplace.manager.get_share_dir", return_value=fake_share):
        with patch("kimi_cli.marketplace.cache.get_marketplace_cache_dir", return_value=fake_share / "marketplaces"):
            with patch("kimi_cli.plugin.manager.get_share_dir", return_value=fake_share):
                yield


def test_full_lifecycle(tmp_path, isolate_share_dir):
    # 1. Create a marketplace
    mp_dir = tmp_path / "my-marketplace"
    mp_dir.mkdir()
    catalog = {
        "name": "my-marketplace",
        "plugins": [
            {"name": "greeter", "description": "Says hello", "version": "1.0.0"}
        ],
    }
    (mp_dir / "marketplace.json").write_text(json.dumps(catalog), encoding="utf-8")

    plugin_dir = mp_dir / "greeter"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "greeter", "version": "1.0.0", "tools": []}),
        encoding="utf-8",
    )

    # 2. Add marketplace
    save_known_marketplaces({
        "my-mp": KnownMarketplace(
            source=DirectorySource(path=str(mp_dir)),
        )
    })

    # 3. Sync
    declared = load_known_marketplaces()
    result = reconcile_marketplaces(declared)
    assert "my-mp" in result.installed or "my-mp" in result.up_to_date

    # 4. Install from marketplace
    install_plugin_from_marketplace(
        "greeter@my-mp",
        host_values={},
        host_name="kimi",
        host_version="0.1.0",
    )

    # 5. Verify in plugins dir
    plugins = list_plugins(get_plugins_dir())
    assert any(p.name == "greeter" for p in plugins)
