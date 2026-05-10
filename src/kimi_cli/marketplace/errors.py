"""Marketplace exception hierarchy."""


class MarketplaceError(Exception):
    """Base exception for marketplace operations."""


class MarketplaceNotFoundError(MarketplaceError):
    """Raised when a marketplace cannot be found or loaded."""


class PluginNotFoundError(MarketplaceError):
    """Raised when a plugin is not found in a marketplace."""


class SourceResolutionError(MarketplaceError):
    """Raised when a plugin source cannot be resolved."""


class InstallError(MarketplaceError):
    """Raised when plugin installation fails."""
