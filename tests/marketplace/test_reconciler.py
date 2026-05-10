import json
import zipfile
from unittest.mock import patch

import pytest

from kimi_cli.marketplace.reconciler import (
    _find_marketplace_json,
    _safe_unpack_zip,
    _validate_name,
    diff_marketplaces,
    reconcile_marketplaces,
)
from kimi_cli.marketplace.schemas import DirectorySource, GitHubSource, KnownMarketplace, UrlSource


def test_all_missing():
    declared = {"a": KnownMarketplace(source=GitHubSource(repo="o/a"))}
    result = diff_marketplaces(declared, {})
    assert result.missing == ["a"]
    assert result.up_to_date == []
    assert result.source_changed == []
    assert result.extra == []


def test_all_up_to_date():
    km = KnownMarketplace(source=GitHubSource(repo="o/a"))
    declared = {"a": km}
    result = diff_marketplaces(declared, {"a": km})
    assert result.up_to_date == ["a"]
    assert result.missing == []


def test_source_changed():
    declared = {"a": KnownMarketplace(source=GitHubSource(repo="o/a"))}
    materialized = {"a": KnownMarketplace(source=UrlSource(url="https://x"))}
    result = diff_marketplaces(declared, materialized)
    assert result.source_changed == ["a"]


def test_extra():
    materialized = {"a": KnownMarketplace(source=GitHubSource(repo="o/a"))}
    result = diff_marketplaces({}, materialized)
    assert result.extra == ["a"]


def test_mixed():
    declared = {
        "new": KnownMarketplace(source=GitHubSource(repo="o/new")),
        "same": KnownMarketplace(source=GitHubSource(repo="o/same")),
        "changed": KnownMarketplace(source=GitHubSource(repo="o/changed-v2")),
    }
    materialized = {
        "same": KnownMarketplace(source=GitHubSource(repo="o/same")),
        "changed": KnownMarketplace(source=GitHubSource(repo="o/changed-v1")),
        "old": KnownMarketplace(source=GitHubSource(repo="o/old")),
    }
    result = diff_marketplaces(declared, materialized)
    assert result.missing == ["new"]
    assert result.up_to_date == ["same"]
    assert result.source_changed == ["changed"]
    assert result.extra == ["old"]


def test_reconcile_installs_missing(tmp_path):
    """Test that reconcile installs a missing marketplace from a local directory."""
    fake_share = tmp_path / ".kimi"
    fake_share.mkdir(parents=True, exist_ok=True)
    fake_cache = fake_share / "marketplaces"

    with (
        patch("kimi_cli.marketplace.reconciler.get_marketplace_cache_dir", return_value=fake_cache),
        patch("kimi_cli.marketplace.manager.get_share_dir", return_value=fake_share),
    ):
        # Create a local marketplace directory
        src = tmp_path / "src_marketplace"
        src.mkdir()
        (src / "marketplace.json").write_text(
            json.dumps({"name": "test-mp", "plugins": []}), encoding="utf-8"
        )

        declared = {
            "test-mp": KnownMarketplace(source=DirectorySource(path=str(src))),
        }

        result = reconcile_marketplaces(declared)
        assert result.installed == ["test-mp"]
        assert result.up_to_date == []
        assert result.failed == []

        # Verify it was materialized
        cache_dir = fake_cache / "test-mp"
        assert (cache_dir / "marketplace.json").exists()


def test_validate_name_rejects_traversal():
    with pytest.raises(ValueError):
        _validate_name("..")
    with pytest.raises(ValueError):
        _validate_name("foo/../bar")
    with pytest.raises(ValueError):
        _validate_name("foo\\..\\bar")
    with pytest.raises(ValueError):
        _validate_name("")
    with pytest.raises(ValueError):
        _validate_name(".")
    # Valid names should pass
    _validate_name("foo-bar")
    _validate_name("foo_bar")
    _validate_name("foo.bar")


def test_safe_unpack_zip_rejects_path_traversal(tmp_path):
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../../../etc/passwd", "root:x:0:0")
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(RuntimeError, match="unsafe path"):
        _safe_unpack_zip(zip_path, dest)


def test_safe_unpack_zip_allows_safe_paths(tmp_path):
    zip_path = tmp_path / "good.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("marketplace.json", '{"name": "test"}')
        zf.writestr("sub/dir/file.txt", "hello")
    dest = tmp_path / "dest"
    dest.mkdir()
    _safe_unpack_zip(zip_path, dest)
    assert (dest / "marketplace.json").exists()
    assert (dest / "sub" / "dir" / "file.txt").exists()


def test_find_marketplace_json_direct(tmp_path):
    (tmp_path / "marketplace.json").write_text("{}")
    assert _find_marketplace_json(tmp_path) == tmp_path / "marketplace.json"


def test_find_marketplace_json_nested(tmp_path):
    nested = tmp_path / "repo-main"
    nested.mkdir()
    (nested / "marketplace.json").write_text("{}")
    assert _find_marketplace_json(tmp_path) == nested / "marketplace.json"


def test_find_marketplace_json_missing(tmp_path):
    with pytest.raises(RuntimeError, match="marketplace.json not found"):
        _find_marketplace_json(tmp_path)


def test_reconcile_uses_branch_from_github_source(tmp_path):
    """Verify that GitHubSource.branch is passed to git clone."""
    fake_share = tmp_path / ".kimi"
    fake_share.mkdir(parents=True, exist_ok=True)
    fake_cache = fake_share / "marketplaces"

    with (
        patch("kimi_cli.marketplace.reconciler.get_marketplace_cache_dir", return_value=fake_cache),
        patch("kimi_cli.marketplace.manager.get_share_dir", return_value=fake_share),
        patch("kimi_cli.marketplace.reconciler.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""

        declared = {
            "test-mp": KnownMarketplace(source=GitHubSource(repo="owner/repo", branch="develop")),
        }
        reconcile_marketplaces(declared)

        # Find the git clone call and verify branch
        clone_calls = [c for c in mock_run.call_args_list if c.args[0][0] == "git"]
        assert len(clone_calls) == 1
        assert "--branch" in clone_calls[0].args[0]
        assert "develop" in clone_calls[0].args[0]


def test_clone_strips_dot_git_suffix(tmp_path):
    """Verify that repo names ending in .git have the suffix stripped."""
    fake_share = tmp_path / ".kimi"
    fake_share.mkdir(parents=True, exist_ok=True)
    fake_cache = fake_share / "marketplaces"

    with (
        patch("kimi_cli.marketplace.reconciler.get_marketplace_cache_dir", return_value=fake_cache),
        patch("kimi_cli.marketplace.manager.get_share_dir", return_value=fake_share),
        patch("kimi_cli.marketplace.reconciler.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""

        declared = {
            "test-mp": KnownMarketplace(source=GitHubSource(repo="owner/repo.git")),
        }
        reconcile_marketplaces(declared)

        clone_calls = [c for c in mock_run.call_args_list if c.args[0][0] == "git"]
        assert len(clone_calls) == 1
        url_arg = [a for a in clone_calls[0].args[0] if a.startswith("https://")][0]
        assert url_arg == "https://github.com/owner/repo.git"
        assert ".git.git" not in url_arg
