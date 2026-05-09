"""Marketplace reconciliation: compare declared intent vs materialized state."""

from __future__ import annotations

from dataclasses import dataclass

from kimi_cli.marketplace.schemas import KnownMarketplace


@dataclass
class MarketplaceDiff:
    """Result of diffing declared vs materialized marketplaces."""

    missing: list[str]           # In declared, not in materialized
    up_to_date: list[str]        # Same in both
    source_changed: list[str]    # Same name, different source
    extra: list[str]             # In materialized, not in declared


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
