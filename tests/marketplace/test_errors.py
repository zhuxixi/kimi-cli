import pytest

from kimi_cli.marketplace.errors import (
    InstallError,
    MarketplaceError,
    MarketplaceNotFoundError,
    PluginNotFoundError,
    SourceResolutionError,
)


def test_marketplace_error_is_exception():
    with pytest.raises(MarketplaceError):
        raise MarketplaceError("fail")


def test_marketplace_not_found():
    with pytest.raises(MarketplaceNotFoundError):
        raise MarketplaceNotFoundError("not found")


def test_plugin_not_found():
    with pytest.raises(PluginNotFoundError):
        raise PluginNotFoundError("missing")


def test_source_resolution():
    with pytest.raises(SourceResolutionError):
        raise SourceResolutionError("bad source")


def test_install_error():
    with pytest.raises(InstallError):
        raise InstallError("install failed")
