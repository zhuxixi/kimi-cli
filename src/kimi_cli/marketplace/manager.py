"""Marketplace configuration and cache path management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kimi_cli.marketplace.errors import MarketplaceError
from kimi_cli.marketplace.schemas import KnownMarketplace
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
        except Exception:
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
