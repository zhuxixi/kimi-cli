from kimi_cli.marketplace.reconciler import diff_marketplaces, MarketplaceDiff
from kimi_cli.marketplace.schemas import GitHubSource, KnownMarketplace, UrlSource


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
