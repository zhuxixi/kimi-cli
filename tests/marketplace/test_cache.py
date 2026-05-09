import time
from pathlib import Path
from unittest.mock import patch

from kimi_cli.marketplace.cache import (
    calculate_version,
    cleanup_orphaned,
    get_plugin_version_cache_dir,
    mark_orphaned,
)


def test_get_plugin_version_cache_dir():
    with patch(
        "kimi_cli.marketplace.cache.get_marketplace_cache_dir",
        return_value=Path("/fake/marketplaces"),
    ):
        path = get_plugin_version_cache_dir("my-plugin@official", "1.0.0")
        assert path == Path("/fake/marketplaces/cache/official/my-plugin/1.0.0")


def test_calculate_version_manifest():
    assert calculate_version("2.1.0", None) == "2.1.0"


def test_calculate_version_unknown():
    assert calculate_version(None, None) == "unknown"


def test_calculate_version_git_sha(tmp_path):
    from unittest.mock import patch

    fake_path = tmp_path / "repo"
    fake_path.mkdir()
    (fake_path / ".git").mkdir()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "abcdef1234567890abcdef1234567890abcdef12\n"
        mock_run.return_value.returncode = 0
        result = calculate_version(None, fake_path)
        assert result == "abcdef123456"


def test_mark_and_cleanup_orphaned(tmp_path):
    vdir = tmp_path / "cache" / "mp" / "plugin" / "v1"
    vdir.mkdir(parents=True)
    mark_orphaned(vdir)
    assert (vdir / ".orphaned_at").exists()

    removed = cleanup_orphaned(tmp_path / "cache", grace_seconds=0)
    assert removed == 1
    assert not vdir.exists()


def test_cleanup_respects_grace_period(tmp_path):
    vdir = tmp_path / "cache" / "mp" / "plugin" / "v1"
    vdir.mkdir(parents=True)
    mark_orphaned(vdir)
    removed = cleanup_orphaned(tmp_path / "cache", grace_seconds=999999)
    assert removed == 0
    assert vdir.exists()
