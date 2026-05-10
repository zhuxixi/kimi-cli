# RFC: Plugin Marketplace System for Kimi Code CLI

## Background & Motivation

Currently, Kimi Code CLI's extension system is fragmented across multiple independent mechanisms:

- **Skills**: `SKILL.md` files discovered from `~/.config/agents/skills/`, `.claude/skills/`, etc.
- **Hooks**: Configured manually in `~/.kimi/config.toml` via `[[hooks]]` arrays.
- **Plugins**: Lightweight executable tools via `plugin.json` + subprocess scripts.
- **Agents/Subagents**: YAML spec files loaded via `--agent-file`.
- **MCP Servers**: Managed separately via `kimi mcp add/remove`.

There is **no unified packaging and distribution mechanism**. Users who build complex workflows (combining skills, hooks, agents, and custom tools) have no way to:
1. Package them into a single installable unit.
2. Share them with teammates or the community.
3. Install others' workflows with a single command.
4. Manage versions and receive updates automatically.

This is a significant gap compared to Claude Code's plugin marketplace, which allows bundling `skills/` + `commands/` + `agents/` + `hooks/` + `mcp/` into one directory with a manifest, distributed via `marketplace.json` catalogs.

## Goals

Build a **Plugin Marketplace System** for Kimi Code CLI that provides:

1. **Unified Packaging**: A single directory format that can bundle skills, hooks, agents, tools, and MCP configs.
2. **Marketplace Catalog**: A `marketplace.json` format for curating and discovering plugins.
3. **One-Click Install**: `kimi plugin install <plugin>` from a marketplace.
4. **Version Management**: Cache multiple versions, detect updates, support rollback.
5. **Distribution**: Anyone can host a marketplace via GitHub repo or static URL.
6. **Claude Compatibility**: Support loading Claude-format plugins (`.claude-plugin/plugin.json`) as a first-class citizen.

## Non-Goals (for v1)

- No official centralized marketplace (community/team marketplaces only).
- No paid plugin support.
- No LSP server bundling.

## Proposed Design

### 1. Plugin Bundle Format

Support multiple plugin formats in v1:

#### Format A: Kimi Native Plugin (existing)
```
my-plugin/
├── plugin.json          # Manifest with tools
├── config.json          # Optional credential injection
└── scripts/
    └── tool.py
```

#### Format B: Claude-Compatible Plugin (via #1715)
```
my-plugin/
├── .claude-plugin/
│   └── plugin.json      # Claude manifest
├── skills/
│   └── my-skill/
│       └── SKILL.md
├── commands/
│   └── my-command.md
├── agents/
│   └── my-agent.md
├── hooks/
│   └── hooks.json
└── .mcp.json
```

#### Format C: Unified Kimi Plugin (proposed new format)
```
my-plugin/
├── kimi-plugin.json     # New unified manifest
├── skills/              # SKILL.md files
├── hooks.json           # Lifecycle hooks
├── agents/              # Agent YAML/MD specs
├── tools/               # Native executable tools (plugin.json format)
└── mcp.json             # MCP server configs
```

### 2. Marketplace Catalog Format (`marketplace.json`)

```json
{
  "name": "zhuxixi-marketplace",
  "owner": { "name": "zhuxixi", "url": "https://github.com/zhuxixi" },
  "plugins": [
    {
      "name": "dev-workflows",
      "version": "1.2.0",
      "description": "Development workflow automation",
      "source": {
        "type": "github",
        "url": "https://github.com/zhuxixi/kimi-dev-workflows",
        "ref": "v1.2.0"
      },
      "category": "development",
      "tags": ["git", "pr", "review"]
    }
  ]
}
```

### 3. CLI Commands

```bash
# Marketplace management
kimi plugin marketplace add https://github.com/zhuxixi/my-marketplace
kimi plugin marketplace list
kimi plugin marketplace remove my-marketplace
kimi plugin marketplace update [name]

# Plugin management
kimi plugin install dev-workflows              # Install from marketplace
kimi plugin install dev-workflows@my-marketplace
kimi plugin list                               # Show installed + versions
kimi plugin info dev-workflows                 # Show details
kimi plugin update dev-workflows               # Update to latest
kimi plugin update --all                       # Update all
kimi plugin remove dev-workflows               # Uninstall

# Local development
kimi plugin install --local ./my-plugin        # Install from local dir
kimi plugin install --git https://github.com/... # Install directly from git
```

### 4. Local Storage Layout

```
~/.kimi/
├── plugins/
│   ├── cache/                       # Versioned plugin cache
│   │   ├── dev-workflows/
│   │   │   ├── v1.0.0/
│   │   │   ├── v1.1.0/
│   │   │   └── v1.2.0/
│   │   └── another-plugin/
│   ├── installed.json               # Active plugin → version mapping
│   └── marketplaces/
│       └── known_marketplaces.json  # Marketplace configs + cache
```

### 5. Runtime Loading

During `Runtime.create()`:
1. Read `~/.kimi/plugins/installed.json`.
2. Load each active plugin from its cached version directory.
3. Register components:
   - Skills → skill discovery system (namespaced)
   - Hooks → hook engine (session-scoped or persistent)
   - Agents → agent registry
   - Tools → `KimiToolset`
   - MCP configs → MCP client

### 6. Version Resolution

Priority order for determining "latest version":
1. Git tag matching semver (`v1.2.0`)
2. Git commit SHA (for untagged repos)
3. `plugin.json` / `kimi-plugin.json` `version` field
4. Marketplace entry `version` field

Update check: compare cached version against resolved latest version.

## Reference Implementation

Claude Code's implementation (from leaked v2.1.88 source) provides a complete reference:

| Module | File | Purpose |
|--------|------|---------|
| Marketplace Manager | `src/utils/plugins/marketplaceManager.ts` | Add/remove/update marketplaces, cache manifests |
| Installation Manager | `src/services/plugins/PluginInstallationManager.ts` | Background install/update/reconcile |
| Plugin Loader | `src/utils/plugins/pluginLoader.ts` | Load plugin from cache into runtime |
| Schemas | `src/utils/plugins/schemas.ts` | Zod schemas for marketplace.json, plugin.json |
| Reconciler | `src/utils/plugins/reconciler.ts` | Diff declared vs materialized state |
| Refresh | `src/utils/plugins/refresh.ts` | Hot-reload plugins without full restart |
| Commands | `src/commands/plugin/*.tsx` | `/plugin` UI (Discover, Installed, Marketplaces) |

Key design patterns observed:
- **Fail-open**: Broken plugins are skipped with warnings, never crash startup.
- **Async reconciliation**: Marketplace sync happens in background, non-blocking.
- **Cache-first**: After first install, plugins load from local cache instantly.
- **Namespace isolation**: All plugin-provided capabilities are prefixed to avoid collisions.

## Implementation Plan

This is a large feature that should be broken into incremental PRs:

1. **PR 1**: Marketplace data models + `kimi-plugin.json` schema + `marketplace.json` schema.
2. **PR 2**: `kimi plugin marketplace` CLI commands (add/list/remove/update).
3. **PR 3**: `kimi plugin install/remove/info` from marketplace + git/zip/local sources.
4. **PR 4**: Versioned cache (`~/.kimi/plugins/cache/`) + `installed.json` persistence.
5. **PR 5**: Runtime loading — wire plugin components into skills/hooks/agents/tools/MCP.
6. **PR 6**: Auto-update + background reconciliation + update notifications.
7. **PR 7**: Documentation + example marketplace + example plugin.

## Related Issues

- #1705: Skill discovery mechanism enhancement (Claude plugin skills not discovered)
- #1714: Feature Request: Claude-compatible local plugin support
- #1715: Draft PR implementing Claude-compatible local plugin loading (skills/commands/agents/hooks/MCP)
- #1708: Dynamic loading/unloading of MCP servers and skills during active sessions

## Why This Matters

Without a marketplace system, every Kimi user is reinventing the wheel:
- Re-writing the same PR review skill.
- Copy-pasting hooks across projects.
- Manually symlinking skill directories.

A marketplace turns individual hacks into **sharable, versioned, discoverable extensions** — the difference between a CLI tool and a platform.
