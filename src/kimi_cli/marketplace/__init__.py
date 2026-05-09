"""Marketplace system for Kimi CLI plugins.

Public API for discovering, installing, and managing plugins from remote catalogs.
"""

from kimi_cli.marketplace.cache import (
    calculate_version,
    cleanup_orphaned,
    get_plugin_version_cache_dir,
)
from kimi_cli.marketplace.errors import (
    InstallError,
    MarketplaceError,
    MarketplaceNotFoundError,
    PluginNotFoundError,
    SourceResolutionError,
)
from kimi_cli.marketplace.loader import LoadedPlugin, load_plugin_from_path
from kimi_cli.marketplace.manager import (
    fetch_marketplace_catalog,
    get_known_marketplaces_path,
    get_marketplace_cache_dir,
    load_known_marketplaces,
    save_known_marketplaces,
)
from kimi_cli.marketplace.operations import install_plugin_from_marketplace
from kimi_cli.marketplace.reconciler import (
    MarketplaceDiff,
    ReconcileResult,
    diff_marketplaces,
    reconcile_marketplaces,
)
from kimi_cli.marketplace.schemas import (
    DirectorySource,
    GitHubSource,
    KnownMarketplace,
    MarketplaceCatalog,
    PluginEntry,
    UrlSource,
)

__all__ = [
    # Schemas
    "MarketplaceCatalog",
    "PluginEntry",
    "KnownMarketplace",
    "GitHubSource",
    "UrlSource",
    "DirectorySource",
    # Errors
    "MarketplaceError",
    "MarketplaceNotFoundError",
    "PluginNotFoundError",
    "SourceResolutionError",
    "InstallError",
    # Manager
    "load_known_marketplaces",
    "save_known_marketplaces",
    "get_known_marketplaces_path",
    "get_marketplace_cache_dir",
    "fetch_marketplace_catalog",
    # Reconciler
    "diff_marketplaces",
    "reconcile_marketplaces",
    "MarketplaceDiff",
    "ReconcileResult",
    # Cache
    "get_plugin_version_cache_dir",
    "calculate_version",
    "cleanup_orphaned",
    # Operations
    "install_plugin_from_marketplace",
    # Loader
    "load_plugin_from_path",
    "LoadedPlugin",
]
