import json
from pathlib import Path
from unittest.mock import patch

import pytest

from kimi_cli.marketplace.manager import (
    get_known_marketplaces_path,
    get_marketplace_cache_dir,
    load_known_marketplaces,
    save_known_marketplaces,
)
from kimi_cli.marketplace.schemas import GitHubSource, KnownMarketplace


@pytest.fixture(autouse=True)
def isolate_share_dir(tmp_path):
    """Override get_share_dir to use a temp directory for each test."""
    fake_share = tmp_path / ".kimi"
    fake_share.mkdir(parents=True, exist_ok=True)
    with patch("kimi_cli.marketplace.manager.get_share_dir", return_value=fake_share):
        yield


def test_get_marketplace_cache_dir(isolate_share_dir):
    d = get_marketplace_cache_dir()
    assert d.name == "marketplaces"


def test_load_empty(isolate_share_dir):
    assert load_known_marketplaces() == {}


def test_save_and_load(isolate_share_dir):
    config = {
        "official": KnownMarketplace(
            source=GitHubSource(repo="anthropics/claude-plugins-official"),
            install_location=str(get_marketplace_cache_dir() / "official"),
        )
    }
    save_known_marketplaces(config)
    loaded = load_known_marketplaces()
    assert len(loaded) == 1
    assert "official" in loaded
    assert loaded["official"].source.repo == "anthropics/claude-plugins-official"


def test_load_invalid_entry_skipped(isolate_share_dir):
    path = get_known_marketplaces_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    bad_data = {"good": {"source": {"source": "github", "repo": "a/b"}}, "bad": "not-a-dict"}
    path.write_text(json.dumps(bad_data), encoding="utf-8")
    loaded = load_known_marketplaces()
    assert len(loaded) == 1
    assert "good" in loaded
