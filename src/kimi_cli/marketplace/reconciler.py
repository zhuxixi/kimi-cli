"""Marketplace reconciliation: compare declared intent vs materialized state."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from kimi_cli.marketplace.manager import get_marketplace_cache_dir
from kimi_cli.marketplace.schemas import KnownMarketplace


@dataclass
class MarketplaceDiff:
    """Result of diffing declared vs materialized marketplaces."""

    missing: list[str]  # In declared, not in materialized
    up_to_date: list[str]  # Same in both
    source_changed: list[str]  # Same name, different source
    extra: list[str]  # In materialized, not in declared


def diff_marketplaces(
    declared: dict[str, KnownMarketplace],
    materialized: dict[str, KnownMarketplace],
) -> MarketplaceDiff:
    """Compare declared (intent) vs materialized (on-disk) marketplaces."""
    missing: list[str] = []
    up_to_date: list[str] = []
    source_changed: list[str] = []
    extra: list[str] = []

    for name in declared:
        if name not in materialized:
            missing.append(name)
        elif declared[name].source == materialized[name].source:
            up_to_date.append(name)
        else:
            source_changed.append(name)

    for name in materialized:
        if name not in declared:
            extra.append(name)

    return MarketplaceDiff(
        missing=missing,
        up_to_date=up_to_date,
        source_changed=source_changed,
        extra=extra,
    )


@dataclass
class ReconcileResult:
    installed: list[str]
    updated: list[str]
    failed: list[tuple[str, str]]
    up_to_date: list[str]


def _clone_github_repo(repo: str, dest: Path, branch: str | None = None) -> None:
    """Clone a GitHub repo into dest."""
    repo = repo.removesuffix(".git")
    url = f"https://github.com/{repo}.git"
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url, str(dest)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {result.stderr.strip()}")


def _download_url(url: str, dest: Path) -> None:
    """Download a URL to a local file."""
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=60.0)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"download failed: {exc}") from exc


def _validate_name(name: str) -> None:
    """Reject names that could escape the intended directory."""
    if not name or name == "." or name == "..":
        raise ValueError(f"invalid marketplace name: {name!r}")
    for part in name.replace("\\", "/").split("/"):
        if part == "..":
            raise ValueError(f"marketplace name contains path traversal: {name!r}")


def _safe_unpack_zip(zip_path: Path, dest: Path) -> None:
    """Unpack a zip file, rejecting members that escape the destination."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            member_path = (dest / member).resolve()
            if not member_path.is_relative_to(dest.resolve()):
                raise RuntimeError(f"zip contains unsafe path: {member}")
        zf.extractall(dest)


def _find_marketplace_json(root: Path) -> Path:
    """Find marketplace.json in root or one level deep."""
    direct = root / "marketplace.json"
    if direct.exists():
        return direct
    for subdir in root.iterdir():
        if subdir.is_dir():
            nested = subdir / "marketplace.json"
            if nested.exists():
                return nested
    raise RuntimeError("marketplace.json not found in archive")


def _materialize_marketplace(name: str, known: KnownMarketplace) -> None:
    """Clone or copy a marketplace source into the cache directory."""
    _validate_name(name)
    cache_dir = get_marketplace_cache_dir()
    install_location = cache_dir / name
    install_location.parent.mkdir(parents=True, exist_ok=True)

    # Remove old materialization if it exists
    shutil.rmtree(install_location, ignore_errors=True)

    source = known.source
    if source.source == "github":
        _clone_github_repo(
            source.repo, install_location, branch=getattr(source, "branch", None) or "main"
        )
    elif source.source == "url":
        parsed = urlparse(source.url)
        if parsed.path.lower().endswith(".zip"):
            tmp = Path(tempfile.mkdtemp())
            try:
                zip_path = tmp / "marketplace.zip"
                _download_url(source.url, zip_path)
                _safe_unpack_zip(zip_path, install_location)
                _find_marketplace_json(install_location)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        else:
            install_location.mkdir(parents=True, exist_ok=True)
            catalog_path = install_location / "marketplace.json"
            _download_url(source.url, catalog_path)
    elif source.source == "directory":
        src_path = Path(source.path).expanduser().resolve()
        if not src_path.exists():
            raise RuntimeError(f"directory does not exist: {src_path}")
        shutil.copytree(src_path, install_location)
    else:
        raise RuntimeError(f"unsupported source: {source.source}")


def reconcile_marketplaces(
    declared: dict[str, KnownMarketplace],
) -> ReconcileResult:
    """Materialize declared marketplaces onto disk.

    Only adds/updates; never removes extra marketplaces.
    """
    from kimi_cli.marketplace.manager import load_known_marketplaces, save_known_marketplaces

    materialized = load_known_marketplaces()
    diff = diff_marketplaces(declared, materialized)

    result = ReconcileResult(
        installed=[],
        updated=[],
        failed=[],
        up_to_date=diff.up_to_date,
    )

    # Process missing
    for name in diff.missing:
        try:
            _materialize_marketplace(name, declared[name])
            materialized[name] = KnownMarketplace.model_validate(declared[name].model_dump())
            materialized[name].install_location = str(get_marketplace_cache_dir() / name)
            result.installed.append(name)
        except Exception as exc:
            result.failed.append((name, str(exc)))

    # Process source-changed
    for name in diff.source_changed:
        try:
            _materialize_marketplace(name, declared[name])
            materialized[name] = KnownMarketplace.model_validate(declared[name].model_dump())
            materialized[name].install_location = str(get_marketplace_cache_dir() / name)
            result.updated.append(name)
        except Exception as exc:
            result.failed.append((name, str(exc)))

    # Process up_to_date: ensure install_location is valid
    for name in diff.up_to_date:
        install_location = get_marketplace_cache_dir() / name
        if not materialized[name].install_location or not install_location.exists():
            try:
                _materialize_marketplace(name, declared[name])
                materialized[name].install_location = str(install_location)
            except Exception as exc:
                result.failed.append((name, str(exc)))

    save_known_marketplaces(materialized)
    return result
