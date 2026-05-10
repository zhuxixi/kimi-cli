import json
from unittest.mock import patch

from kimi_cli.marketplace.reconciler import diff_marketplaces, reconcile_marketplaces
from kimi_cli.marketplace.schemas import DirectorySource, GitHubSource, KnownMarketplace, UrlSource


def test_all_missing():
    declared = {"a": KnownMarketplace(source=GitHubSource(repo="o/a"))}
    result = diff_marketplaces(declared, {})
    assert result.missing == ["a"]
    assert result.up_to_date == []
    assert result.source_changed == []
    assert result.extra == []


def test_all_up_to_date():
    km = KnownMarketplace(source=GitHubSource(repo="o/a"))
    declared = {"a": km}
    result = diff_marketplaces(declared, {"a": km})
    assert result.up_to_date == ["a"]
    assert result.missing == []


def test_source_changed():
    declared = {"a": KnownMarketplace(source=GitHubSource(repo="o/a"))}
    materialized = {"a": KnownMarketplace(source=UrlSource(url="https://x"))}
    result = diff_marketplaces(declared, materialized)
    assert result.source_changed == ["a"]


def test_extra():
    materialized = {"a": KnownMarketplace(source=GitHubSource(repo="o/a"))}
    result = diff_marketplaces({}, materialized)
    assert result.extra == ["a"]


def test_mixed():
    declared = {
        "new": KnownMarketplace(source=GitHubSource(repo="o/new")),
        "same": KnownMarketplace(source=GitHubSource(repo="o/same")),
        "changed": KnownMarketplace(source=GitHubSource(repo="o/changed-v2")),
    }
    materialized = {
        "same": KnownMarketplace(source=GitHubSource(repo="o/same")),
        "changed": KnownMarketplace(source=GitHubSource(repo="o/changed-v1")),
        "old": KnownMarketplace(source=GitHubSource(repo="o/old")),
    }
    result = diff_marketplaces(declared, materialized)
    assert result.missing == ["new"]
    assert result.up_to_date == ["same"]
    assert result.source_changed == ["changed"]
    assert result.extra == ["old"]


def test_reconcile_installs_missing(tmp_path):
    """Test that reconcile installs a missing marketplace from a local directory."""
    fake_share = tmp_path / ".kimi"
    fake_share.mkdir(parents=True, exist_ok=True)
    fake_cache = fake_share / "marketplaces"

    with (
        patch("kimi_cli.marketplace.reconciler.get_marketplace_cache_dir", return_value=fake_cache),
        patch("kimi_cli.marketplace.manager.get_share_dir", return_value=fake_share),
    ):
        # Create a local marketplace directory
        src = tmp_path / "src_marketplace"
        src.mkdir()
        (src / "marketplace.json").write_text(
            json.dumps({"name": "test-mp", "plugins": []}), encoding="utf-8"
        )

        declared = {
            "test-mp": KnownMarketplace(source=DirectorySource(path=str(src))),
        }

        result = reconcile_marketplaces(declared)
        assert result.installed == ["test-mp"]
        assert result.up_to_date == []
        assert result.failed == []

        # Verify it was materialized
        cache_dir = fake_cache / "test-mp"
        assert (cache_dir / "marketplace.json").exists()
