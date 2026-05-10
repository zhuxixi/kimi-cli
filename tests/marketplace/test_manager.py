import json
from unittest.mock import patch

import pytest

from kimi_cli.marketplace.manager import (
    fetch_marketplace_catalog,
    get_known_marketplaces_path,
    get_marketplace_cache_dir,
    load_known_marketplaces,
    save_known_marketplaces,
)
from kimi_cli.marketplace.schemas import DirectorySource, GitHubSource, KnownMarketplace


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


def test_fetch_from_directory(tmp_path, isolate_share_dir):
    catalog = {"name": "local", "plugins": [{"name": "test-plugin"}]}
    mp_dir = tmp_path / "marketplace"
    mp_dir.mkdir()
    (mp_dir / "marketplace.json").write_text(json.dumps(catalog), encoding="utf-8")

    known = KnownMarketplace(source=DirectorySource(path=str(mp_dir)))
    result = fetch_marketplace_catalog("local", known)
    assert result.name == "local"
    assert len(result.plugins) == 1
    assert result.plugins[0].name == "test-plugin"


def test_fetch_directory_missing_file(isolate_share_dir):
    from kimi_cli.marketplace.errors import MarketplaceError

    known = KnownMarketplace(source=DirectorySource(path="/nonexistent"))
    with pytest.raises(MarketplaceError):
        fetch_marketplace_catalog("missing", known)


def test_fetch_github_uses_raw_url(isolate_share_dir):
    """Mock httpx.get to verify the URL constructed from github repo."""
    catalog = {"name": "official", "plugins": []}
    with patch("kimi_cli.marketplace.manager.httpx.get") as mock_get:
        mock_get.return_value.json.return_value = catalog
        mock_get.return_value.raise_for_status = lambda: None
        known = KnownMarketplace(source=GitHubSource(repo="owner/repo"))
        result = fetch_marketplace_catalog("official", known)
        mock_get.assert_called_once()
        assert "raw.githubusercontent.com" in str(mock_get.call_args[0][0])
        assert result.name == "official"
