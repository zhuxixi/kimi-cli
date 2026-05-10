"""Marketplace configuration and cache path management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from kimi_cli.marketplace.errors import MarketplaceError
from kimi_cli.marketplace.schemas import KnownMarketplace, MarketplaceCatalog
from kimi_cli.share import get_share_dir

KNOWN_MARKETPLACES_FILE = "known_marketplaces.json"


def get_marketplace_cache_dir() -> Path:
    """Return the root marketplace cache directory (~/.kimi/marketplaces/)."""
    return get_share_dir() / "marketplaces"


def get_known_marketplaces_path() -> Path:
    """Return the path to known_marketplaces.json."""
    return get_share_dir() / KNOWN_MARKETPLACES_FILE


def load_known_marketplaces() -> dict[str, KnownMarketplace]:
    """Load known_marketplaces.json from disk.

    Returns an empty dict if the file does not exist or is malformed.
    """
    path = get_known_marketplaces_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result: dict[str, KnownMarketplace] = {}
    for name, raw in data.items():
        try:
            result[name] = KnownMarketplace.model_validate(raw)
        except (OSError, ValueError):
            continue
    return result


def save_known_marketplaces(config: dict[str, KnownMarketplace]) -> None:
    """Save known_marketplaces.json to disk atomically."""
    path = get_known_marketplaces_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {name: km.model_dump() for name, km in config.items()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _github_repo_to_raw_url(repo: str, branch: str = "main") -> str:
    """Convert owner/repo to raw GitHub content URL for marketplace.json."""
    return f"https://raw.githubusercontent.com/{repo}/{branch}/marketplace.json"


def _fetch_url(url: str) -> dict[str, Any]:
    """Fetch JSON from a URL."""
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise MarketplaceError(f"Failed to fetch {url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MarketplaceError(f"Invalid JSON from {url}: {exc}") from exc


def fetch_marketplace_catalog(name: str, known: KnownMarketplace) -> MarketplaceCatalog:
    """Fetch and parse a marketplace catalog from its source."""
    source = known.source

    if source.source == "github":
        branch = getattr(source, "branch", None) or "main"
        raw_url = _github_repo_to_raw_url(source.repo, branch=branch)
        data = _fetch_url(raw_url)
    elif source.source == "url":
        data = _fetch_url(source.url)
    elif source.source == "directory":
        path = Path(source.path).expanduser().resolve()
        catalog_path = path / "marketplace.json"
        if not catalog_path.exists():
            raise MarketplaceError(f"marketplace.json not found in {path}")
        try:
            data = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MarketplaceError(f"Failed to read {catalog_path}: {exc}") from exc
    else:
        raise MarketplaceError(f"Unsupported marketplace source: {source.source}")

    try:
        return MarketplaceCatalog.model_validate(data)
    except Exception as exc:
        raise MarketplaceError(f"Invalid marketplace.json for '{name}': {exc}") from exc
