"""Load plugin metadata from a directory, auto-detecting components."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kimi_cli.plugin import PLUGIN_JSON, PluginError, PluginSpec, parse_plugin_json


@dataclass
class LoadedPlugin:
    """A plugin loaded from disk with detected components."""

    spec: PluginSpec
    path: Path
    commands_path: Path | None = None
    agents_path: Path | None = None
    skills_path: Path | None = None
    hooks_path: Path | None = None
    output_styles_path: Path | None = None
    errors: list[str] = field(default_factory=list)


def load_plugin_from_path(path: Path) -> LoadedPlugin:
    """Load a plugin from a directory, detecting all available components.

    Fail-open: missing components are reported as errors but do not prevent loading.
    """
    if not path.is_dir():
        raise PluginError(f"Plugin path is not a directory: {path}")

    manifest_path = path / PLUGIN_JSON
    if not manifest_path.exists():
        # Create a minimal fallback spec
        spec = PluginSpec(
            name=path.name,
            version="unknown",
            description=f"Plugin from {path}",
        )
    else:
        try:
            spec = parse_plugin_json(manifest_path)
        except PluginError as exc:
            raise PluginError(f"Failed to load plugin from {path}: {exc}") from exc

    loaded = LoadedPlugin(spec=spec, path=path)

    # Auto-detect directories
    for attr, dirname in [
        ("commands_path", "commands"),
        ("agents_path", "agents"),
        ("skills_path", "skills"),
        ("hooks_path", "hooks"),
        ("output_styles_path", "output-styles"),
    ]:
        candidate = path / dirname
        if candidate.is_dir():
            setattr(loaded, attr, candidate)

    return loaded
