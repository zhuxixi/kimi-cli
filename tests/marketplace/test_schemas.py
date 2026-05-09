import pytest
from kimi_cli.marketplace.schemas import (
    DirectorySource,
    GitHubSource,
    MarketplaceCatalog,
    PluginEntry,
    UrlSource,
)


def test_github_source():
    s = GitHubSource(repo="anthropics/claude-plugins-official")
    assert s.source == "github"
    assert s.repo == "anthropics/claude-plugins-official"


def test_url_source():
    s = UrlSource(url="https://example.com/marketplace.json")
    assert s.source == "url"
    assert s.url == "https://example.com/marketplace.json"


def test_directory_source():
    s = DirectorySource(path="/path/to/marketplace")
    assert s.source == "directory"
    assert s.path == "/path/to/marketplace"


def test_marketplace_catalog():
    catalog = MarketplaceCatalog(
        name="official",
        owner="anthropics",
        plugins=[
            PluginEntry(name="deploy", description="Deploy tools"),
        ],
    )
    assert catalog.name == "official"
    assert len(catalog.plugins) == 1
    assert catalog.plugins[0].name == "deploy"


def test_plugin_entry_defaults():
    entry = PluginEntry(name="test")
    assert entry.description == ""
    assert entry.version == ""
    assert entry.source.source == "directory"
