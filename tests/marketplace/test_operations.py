import json
from unittest.mock import patch

import pytest

from kimi_cli.marketplace.errors import PluginNotFoundError
from kimi_cli.marketplace.manager import save_known_marketplaces
from kimi_cli.marketplace.operations import install_plugin_from_marketplace
from kimi_cli.marketplace.schemas import DirectorySource, KnownMarketplace


@pytest.fixture(autouse=True)
def isolate_share_dir(tmp_path):
    """Override get_share_dir to use a temp directory for each test."""
    fake_share = tmp_path / ".kimi"
    fake_share.mkdir(parents=True, exist_ok=True)
    with (
        patch("kimi_cli.marketplace.manager.get_share_dir", return_value=fake_share),
        patch(
            "kimi_cli.marketplace.cache.get_marketplace_cache_dir",
            return_value=fake_share / "marketplaces",
        ),
        patch("kimi_cli.plugin.manager.get_share_dir", return_value=fake_share),
    ):
        yield


def test_install_plugin_from_marketplace(tmp_path, isolate_share_dir):
    # 1. Create a materialized marketplace
    mp_dir = tmp_path / "my-marketplace"
    mp_dir.mkdir()
    catalog = {
        "name": "my-marketplace",
        "plugins": [{"name": "greeter", "description": "Says hello", "version": "1.0.0"}],
    }
    (mp_dir / "marketplace.json").write_text(json.dumps(catalog), encoding="utf-8")

    plugin_dir = mp_dir / "greeter"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "greeter", "version": "1.0.0", "tools": []}),
        encoding="utf-8",
    )

    # 2. Register in known_marketplaces
    save_known_marketplaces(
        {
            "my-mp": KnownMarketplace(
                source=DirectorySource(path=str(mp_dir)),
                install_location=str(mp_dir),
            )
        }
    )

    # 3. Install
    dest = install_plugin_from_marketplace(
        "greeter@my-mp",
        host_values={},
        host_name="kimi",
        host_version="0.1.0",
    )

    assert dest.name == "greeter"
    assert (dest / "plugin.json").exists()

    # Check runtime was written
    data = json.loads((dest / "plugin.json").read_text(encoding="utf-8"))
    assert data["runtime"]["host"] == "kimi"


def test_install_invalid_plugin_id(isolate_share_dir):
    with pytest.raises(PluginNotFoundError):
        install_plugin_from_marketplace(
            "no-at-sign",
            host_values={},
            host_name="kimi",
            host_version="0.1.0",
        )
