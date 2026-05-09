"""Marketplace plugin operations: install, uninstall, update."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from kimi_cli.marketplace.cache import calculate_version, get_plugin_version_cache_dir
from kimi_cli.marketplace.errors import (
    InstallError,
    MarketplaceNotFoundError,
    PluginNotFoundError,
)
from kimi_cli.marketplace.manager import load_known_marketplaces
from kimi_cli.marketplace.schemas import PluginEntry
from kimi_cli.plugin import (
    PLUGIN_JSON,
    PluginError,
    PluginRuntime,
    inject_config,
    parse_plugin_json,
    write_runtime,
)
from kimi_cli.plugin.manager import get_plugins_dir


def _find_plugin_entry(marketplace_name: str, plugin_name: str) -> PluginEntry:
    """Find a plugin entry in a materialized marketplace."""
    marketplaces = load_known_marketplaces()
    if marketplace_name not in marketplaces:
        raise MarketplaceNotFoundError(f"Marketplace '{marketplace_name}' not found")

    mp_path = Path(marketplaces[marketplace_name].install_location)
    catalog_path = mp_path / "marketplace.json"
    if not catalog_path.exists():
        raise MarketplaceNotFoundError(f"marketplace.json not found for '{marketplace_name}'")

    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketplaceNotFoundError(f"Failed to read catalog: {exc}") from exc

    for entry in catalog.get("plugins", []):
        if entry.get("name") == plugin_name:
            return PluginEntry.model_validate(entry)

    raise PluginNotFoundError(
        f"Plugin '{plugin_name}' not found in marketplace '{marketplace_name}'"
    )


def install_plugin_from_marketplace(
    plugin_id: str,
    *,
    host_values: dict[str, str],
    host_name: str,
    host_version: str,
) -> Path:
    """Install a plugin from a marketplace into the active plugins directory.

    Args:
        plugin_id: Format "name@marketplace".
        host_values: Values to inject into plugin config.
        host_name: Host name for runtime metadata.
        host_version: Host version for runtime metadata.

    Returns:
        Path to the installed plugin directory in ~/.kimi/plugins/.
    """
    if "@" not in plugin_id:
        raise PluginNotFoundError(f"Invalid plugin_id '{plugin_id}'; expected 'name@marketplace'")

    plugin_name, marketplace_name = plugin_id.rsplit("@", 1)

    # 1. Find the plugin entry in the marketplace catalog
    entry = _find_plugin_entry(marketplace_name, plugin_name)

    # 2. Locate the plugin source directory inside the materialized marketplace
    marketplaces = load_known_marketplaces()
    mp_location = Path(marketplaces[marketplace_name].install_location)
    source_candidates = [
        mp_location / plugin_name,
        mp_location / "plugins" / plugin_name,
        mp_location,
    ]
    source_dir: Path | None = None
    for candidate in source_candidates:
        if (candidate / PLUGIN_JSON).exists():
            source_dir = candidate
            break

    if source_dir is None:
        raise InstallError(
            f"Could not find plugin '{plugin_name}' directory in marketplace '{marketplace_name}'"
        )

    # 3. Parse manifest to get version
    try:
        spec = parse_plugin_json(source_dir / PLUGIN_JSON)
    except PluginError as exc:
        raise InstallError(f"Failed to parse plugin.json: {exc}") from exc

    version = calculate_version(spec.version or entry.version or None, source_dir)

    # 4. Copy to versioned cache
    version_dir = get_plugin_version_cache_dir(plugin_id, version)
    version_dir.parent.mkdir(parents=True, exist_ok=True)
    if version_dir.exists():
        shutil.rmtree(version_dir)
    shutil.copytree(source_dir, version_dir)

    # 5. Install into active plugins directory
    plugins_dir = get_plugins_dir()
    dest = plugins_dir / plugin_name

    # Stage to temp dir for atomic swap
    plugins_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{plugin_name}-", dir=plugins_dir))
    try:
        staging_plugin = staging / plugin_name
        shutil.copytree(version_dir, staging_plugin)

        # Apply inject + runtime
        inject_config(staging_plugin, spec, host_values)
        runtime = PluginRuntime(host=host_name, host_version=host_version)
        write_runtime(staging_plugin, runtime)

        # Swap
        if dest.exists():
            shutil.rmtree(dest)
        staging_plugin.rename(dest)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return dest
