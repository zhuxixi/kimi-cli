"""Versioned plugin cache and orphaned version garbage collection."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from kimi_cli.marketplace.manager import get_marketplace_cache_dir


def get_plugin_version_cache_dir(plugin_id: str, version: str) -> Path:
    """Return the version-scoped cache directory for a plugin.

    Format: ~/.kimi/marketplaces/cache/<marketplace>/<plugin>/<version>/
    """
    name, marketplace = _parse_plugin_id(plugin_id)
    return get_marketplace_cache_dir() / "cache" / marketplace / name / version


def _parse_plugin_id(plugin_id: str) -> tuple[str, str]:
    """Parse 'name@marketplace' into (name, marketplace)."""
    if "@" not in plugin_id:
        return plugin_id, "unknown"
    name, marketplace = plugin_id.rsplit("@", 1)
    return name, marketplace


def calculate_version(manifest_version: str | None, install_path: Path | None) -> str:
    """Calculate a plugin version string.

    Priority:
    1. manifest.version (semver from plugin.json)
    2. git commit SHA (first 12 chars)
    3. "unknown"
    """
    if manifest_version:
        return manifest_version
    if install_path and (install_path / ".git").exists():
        try:
            result = subprocess.run(
                ["git", "-C", str(install_path), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()[:12]
        except subprocess.CalledProcessError:
            pass
    return "unknown"


def mark_orphaned(version_dir: Path) -> None:
    """Mark a version directory as orphaned (will be GC'd later)."""
    (version_dir / ".orphaned_at").write_text(
        str(int(time.time())), encoding="utf-8"
    )


def cleanup_orphaned(cache_root: Path | None = None, grace_seconds: int = 604800) -> int:
    """Remove orphaned version directories older than grace_seconds (default 7 days).

    Returns the number of directories removed.
    """
    if cache_root is None:
        cache_root = get_marketplace_cache_dir() / "cache"
    if not cache_root.exists():
        return 0

    now = int(time.time())
    removed = 0

    for version_dir in cache_root.rglob("*"):
        if not version_dir.is_dir():
            continue
        orphan_file = version_dir / ".orphaned_at"
        if not orphan_file.exists():
            continue
        try:
            orphaned_at = int(orphan_file.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            continue
        if now - orphaned_at >= grace_seconds:
            shutil.rmtree(version_dir, ignore_errors=True)
            removed += 1

    return removed
