"""CLI commands for marketplace management."""

from __future__ import annotations

from typing import Annotated

import typer

from kimi_cli.marketplace.errors import MarketplaceError
from kimi_cli.marketplace.manager import (
    load_known_marketplaces,
    save_known_marketplaces,
)
from kimi_cli.marketplace.reconciler import reconcile_marketplaces
from kimi_cli.marketplace.schemas import (
    DirectorySource,
    GitHubSource,
    KnownMarketplace,
    UrlSource,
)

cli = typer.Typer(help="Manage plugin marketplaces.")


@cli.command("add")
def add_cmd(
    source: Annotated[
        str,
        typer.Argument(help="Marketplace source: owner/repo, URL, or directory path"),
    ],
    name: Annotated[
        str | None,
        typer.Option(help="Custom name for the marketplace"),
    ] = None,
) -> None:
    """Add a new marketplace source."""
    # Auto-detect source type
    if "/" in source and not source.startswith(("http", "https", ".", "~/", "/")):
        # GitHub shorthand: owner/repo
        parsed_source = GitHubSource(repo=source)
        auto_name = name or source.replace("/", "-")
    elif source.startswith(("http://", "https://")):
        parsed_source = UrlSource(url=source)
        auto_name = name or source.split("/")[-1].replace(".json", "") or "custom"
    else:
        from pathlib import Path

        parsed_source = DirectorySource(path=str(Path(source).expanduser().resolve()))
        auto_name = name or Path(source).name or "local"

    mp_name = name or auto_name

    config = load_known_marketplaces()
    if mp_name in config:
        typer.echo(f"Error: Marketplace '{mp_name}' already exists", err=True)
        raise typer.Exit(1)

    config[mp_name] = KnownMarketplace(source=parsed_source)
    save_known_marketplaces(config)
    typer.echo(f"Added marketplace '{mp_name}'")


@cli.command("list")
def list_cmd() -> None:
    """List configured marketplaces."""
    config = load_known_marketplaces()
    if not config:
        typer.echo("No marketplaces configured.")
        return

    for name, entry in config.items():
        source_str = _source_display(entry.source)
        typer.echo(f"  {name}: {source_str}")


@cli.command("remove")
def remove_cmd(
    name: Annotated[str, typer.Argument(help="Marketplace name to remove")],
) -> None:
    """Remove a marketplace."""
    config = load_known_marketplaces()
    if name not in config:
        typer.echo(f"Error: Marketplace '{name}' not found", err=True)
        raise typer.Exit(1)

    del config[name]
    save_known_marketplaces(config)
    typer.echo(f"Removed marketplace '{name}'")


@cli.command("sync")
def sync_cmd() -> None:
    """Sync all declared marketplaces (clone/fetch missing and updated)."""
    config = load_known_marketplaces()
    if not config:
        typer.echo("No marketplaces to sync.")
        return

    typer.echo("Syncing marketplaces...")
    try:
        result = reconcile_marketplaces(config)
    except MarketplaceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    for name in result.installed:
        typer.echo(f"  + {name}")
    for name in result.updated:
        typer.echo(f"  ~ {name}")
    for name, reason in result.failed:
        typer.echo(f"  ✗ {name}: {reason}", err=True)
    for name in result.up_to_date:
        typer.echo(f"  = {name} (up to date)")


def _source_display(source) -> str:
    if source.source == "github":
        return f"github:{source.repo}"
    if source.source == "url":
        return source.url
    if source.source == "directory":
        return source.path
    return "unknown"
