"""Marketplace and plugin manifest schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GitHubSource(BaseModel):
    source: str = "github"
    repo: str


class UrlSource(BaseModel):
    source: str = "url"
    url: str


class DirectorySource(BaseModel):
    source: str = "directory"
    path: str


MarketplaceSource = GitHubSource | UrlSource | DirectorySource


class PluginEntry(BaseModel):
    """A plugin listed in a marketplace catalog."""

    name: str
    description: str = ""
    version: str = ""
    author: str = ""
    homepage: str = ""
    source: MarketplaceSource = Field(default_factory=lambda: DirectorySource(path="."))


class MarketplaceCatalog(BaseModel):
    """Top-level catalog file (marketplace.json)."""

    name: str
    owner: str = ""
    description: str = ""
    plugins: list[PluginEntry] = Field(default_factory=list)


class KnownMarketplace(BaseModel):
    """Persisted entry in known_marketplaces.json."""

    source: MarketplaceSource
    install_location: str = ""
    last_updated: str = ""
