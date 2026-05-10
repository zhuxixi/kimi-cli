# Plugin System Exploration — Marketplace Extension Points

## 1. Plugin CLI (`src/kimi_cli/cli/plugin.py`)

### Commands
- `kimi plugin install <target>` — Install from directory, .zip file, .zip URL, or git URL
- `kimi plugin list` — List installed plugins
- `kimi plugin remove <name>` — Remove an installed plugin
- `kimi plugin info <name>` — Show plugin details

### Key implementation details
- `_resolve_source(target)` normalizes any source to a local `Path`:
  - **HTTP(S) .zip URLs**: Downloaded via `httpx`, extracted, searched for `plugin.json`
  - **Git URLs**: Parsed by `_parse_git_url()` into `(clone_url, subpath, branch)`. Supports `.git/` suffix, GitHub/GitLab short URLs, `tree/{branch}/` and `/-/tree/{branch}/` prefixes. Clones with `--depth 1`, optionally `--branch`. If no subpath and no root `plugin.json`, lists available sub-directory plugins.
  - **Local .zip**: Extracted to temp, searched for `plugin.json`
  - **Local directory**: Used as-is
- `install_cmd()` loads config, collects host values (`api_key`, `base_url`) via `collect_host_values()`, warns if no provider configured, then calls `install_plugin()`.
- `list_cmd()` shows name, version, and status (`installed` if `runtime` present, else `not configured`).
- `info_cmd()` reads `plugin.json` directly from `~/.kimi/plugins/<name>/`.

### Extension points for marketplace
- **New commands needed**: `search`, `update`, `install-by-name` (registry lookup)
- `_resolve_source()` could be extended to resolve a plugin name against a marketplace registry URL
- The install command currently always requires a direct source; a marketplace would need a name→URL resolution layer

---

## 2. Plugin Manager (`src/kimi_cli/plugin/manager.py`)

### Core functions
- `get_plugins_dir()` → `~/.kimi/plugins/` (or `$KIMI_SHARE_DIR/plugins/`)
- `install_plugin(source, plugins_dir, host_values, host_name, host_version)`:
  1. Parse `plugin.json` from source
  2. Validate name (rejects path traversal like `../escape`)
  3. Stage to temp dir *inside* `plugins_dir` for atomic same-fs rename
  4. Copy source into staging
  5. Apply `inject_config()` (writes host credentials into plugin config file)
  6. Write `PluginRuntime` into `plugin.json`
  7. Swap: remove old dir, rename staged into place
  8. On failure: clean up staging, leave existing install intact
- `remove_plugin(name, plugins_dir)` — validates name, deletes directory
- `list_plugins(plugins_dir)` — iterates subdirs, parses `plugin.json`, skips invalid
- `refresh_plugin_configs(plugins_dir, host_values)` — re-injects credentials for all installed plugins at startup
- `collect_host_values(config, oauth)` — resolves `api_key` (static or OAuth) + `base_url` from default model/provider

### Extension points for marketplace
- `install_plugin()` is the canonical installation entrypoint; marketplace install would reuse it after downloading
- `list_plugins()` only shows local installations; marketplace would need a separate registry client
- No concept of "outdated" plugins — no version comparison against upstream
- Plugin name validation (`_validate_name`) should be reused for any marketplace operations

---

## 3. Plugin Data Models (`src/kimi_cli/plugin/__init__.py`)

### Schema (`plugin.json`)
```json
{
  "name": "required-string",
  "version": "required-string",
  "description": "",
  "config_file": null,
  "inject": {},
  "tools": [],
  "runtime": null
}
```

### Pydantic models
- `PluginSpec`: `name`, `version`, `description`, `config_file`, `inject`, `tools`, `runtime`
- `PluginRuntime`: `host`, `host_version` — written by host after installation
- `PluginToolSpec`: `name`, `description`, `command`, `parameters`
- `PluginError`: custom exception for all plugin failures

### Config injection
- `inject_config(plugin_dir, spec, values)`: reads plugin's config file (JSON), applies dot-path injection (e.g. `{"app.api_key": "api_key"}` → sets `config["app"]["api_key"] = values["api_key"]`)
- Validates `config_file` does not escape plugin directory
- Creates intermediate dicts if missing

### Extension points for marketplace
- `plugin.json` could be extended with marketplace metadata fields (author, tags, homepage, repository, license) — `extra="ignore"` on `PluginSpec` already allows forward compatibility
- No dependency or peer-dependency model exists
- No checksum/signature verification

---

## 4. Share Directory Structure (`~/.kimi/`)

### Location
- `get_share_dir()` → `$KIMI_SHARE_DIR` env var, else `Path.home() / ".kimi"`
- Created with `mkdir(parents=True, exist_ok=True)`

### Known subdirectories/files
- `~/.kimi/config.toml` — Main user config (loaded by `load_config()`)
- `~/.kimi/plugins/` — Plugin installations
- `~/.kimi/logs/kimi.log` — Application logs (loguru, rotated at 06:00, 10-day retention)
- `~/.kimi/sessions/` — Session storage
- `~/.kimi/mcp.json` — Global MCP config (referenced by `get_global_mcp_config_file()`)
- Legacy: `config.json` → auto-migrated to `config.toml` with `.bak` backup

### Extension points for marketplace
- New files/directories that could be added:
  - `~/.kimi/plugin-registry.json` or `~/.kimi/marketplace/` — cached registry index, install history
  - `~/.kimi/plugins/` is the single source of truth for installed plugins

---

## 5. Runtime Integration (`src/kimi_cli/app.py` → `src/kimi_cli/soul/agent.py`)

### `KimiCLI.create()` (app.py, lines 275–286)
After `Runtime.create()` returns:
```python
from kimi_cli.plugin.manager import collect_host_values, get_plugins_dir, refresh_plugin_configs
host_values = collect_host_values(config, oauth)
if host_values.get("api_key"):
    refresh_plugin_configs(get_plugins_dir(), host_values)
```
- This re-injects fresh credentials (especially OAuth tokens) into all installed plugins at every startup.
- Wrapped in broad `except Exception: logger.debug(...)` — failure is non-fatal.

### `load_agent()` (soul/agent.py, lines 453–465)
```python
from kimi_cli.plugin.manager import get_plugins_dir
from kimi_cli.plugin.tool import load_plugin_tools

plugin_tools = load_plugin_tools(get_plugins_dir(), runtime.config, approval=runtime.approval)
for plugin_tool in plugin_tools:
    if toolset.find(plugin_tool.name) is not None:
        logger.warning("Plugin tool '{name}' conflicts with existing tool, skipping")
        continue
    toolset.add(plugin_tool)
```
- Plugin tools are loaded **after** built-in tools but **before** MCP tools.
- Name conflicts with existing tools are logged and skipped.
- Each `PluginTool` receives the full `Config` and `Approval` instances.

### Extension points for marketplace
- Marketplace plugins would be installed to the same `~/.kimi/plugins/` directory and automatically picked up by existing `refresh_plugin_configs()` and `load_plugin_tools()` calls — **zero runtime changes required** for basic marketplace integration.
- If marketplace needs "enabled/disabled" state, the current code has no toggle — would need a registry/manifest of enabled plugins or a new field in `PluginSpec`.

---

## 6. Plugin Tool Execution (`src/kimi_cli/plugin/tool.py`)

### `PluginTool(CallableTool)`
- Runs plugin-declared command as subprocess via `asyncio.create_subprocess_exec`
- Parameters passed as JSON via stdin
- stdout captured as result; stderr logged at DEBUG
- **Runtime credential injection**: `_build_env()` calls `_get_host_values()` (fresh OAuth/static key) and maps inject keys to env vars
- Approval integration: asks `Approval` before executing
- 120-second timeout; `CancelledError` kills process and re-raises

### `load_plugin_tools(plugins_dir, config, approval)`
- Scans `plugins_dir/<name>/plugin.json`
- For each `spec.tools`, instantiates `PluginTool`
- Invalid tools are logged and skipped (non-fatal)

### Extension points for marketplace
- Tool execution model is solid; marketplace doesn't need to change this
- Could extend with sandboxing, but that's out of scope

---

## 7. Skill Discovery Integration (`src/kimi_cli/skill/__init__.py`)

### `resolve_skills_roots()`
Priority order (highest first):
1. `--skills-dir` overrides
2. Project skills dirs (`.kimi/skills`, `.claude/skills`, `.codex/skills`, `.agents/skills`)
3. User skills dirs (`~/.kimi/skills`, `~/.claude/skills`, `~/.codex/skills`, `~/.config/agents/skills`, `~/.agents/skills`)
4. `extra_skill_dirs` from config
5. **`get_plugins_dir()` — plugins are always discoverable as "extra" scope**
6. Built-in skills (bundled with kimi-cli)

### `discover_skills()`
- Subdirectory form: `<dir>/<name>/SKILL.md`
- Flat form: `<dir>/<name>.md`
- Plugins that include a `SKILL.md` are automatically surfaced as skills in the system prompt under the "Extra" heading.

### Extension points for marketplace
- Marketplace plugins that ship with `SKILL.md` get automatic skill discovery — no extra work needed
- Could consider a dedicated "Marketplace" scope heading instead of grouping under "Extra"

---

## 8. CLI Registration (`src/kimi_cli/cli/_lazy_group.py`)

- `LazySubcommandGroup` loads `plugin` subcommand lazily from `kimi_cli.cli.plugin`
- Adding new marketplace commands (`search`, `update`) would be done in `src/kimi_cli/cli/plugin.py` — the lazy loading already handles this

---

## 9. Test Structure

### `tests/core/test_plugin.py` (653 lines)
- `parse_plugin_json`: minimal, full, missing fields, malformed JSON, runtime, unknown fields, tools
- `inject_config`: writes value, creates nested path, missing key, missing file, no-op, path traversal rejection
- `write_runtime`: preserves original fields
- `_parse_git_url`: 20+ parameterized cases covering .git URLs, short URLs, tree/branch, GitLab `/-/tree/`, edge cases
- `_resolve_source`: git subpath, not found, suggests plugins, root plugin, path traversal, zip URL download/extract, query strings, GitHub archive zip, download failure, invalid archive

### `tests/core/test_plugin_manager.py` (282 lines)
- `install_plugin`: happy path, inject verification, runtime verification
- Missing `plugin.json`
- Rollback on failure (missing host key)
- Reinstall (upgrade) behavior
- `list_plugins` and empty dir
- `remove_plugin` and nonexistent
- Path traversal name rejection
- `skill_discovery_includes_plugins_dir`: verifies `resolve_skills_roots` includes plugins dir
- `collect_host_values`: static key, OAuth token, no default model, empty key

### `tests/core/test_plugin_tool.py` (196 lines)
- Tool execution and stdout capture
- Nonzero exit handling
- Empty stdin
- Env var injection at runtime
- `load_plugin_tools` discovery and empty/skip cases

---

## 10. Summary of Key Extension Points for a Marketplace System

| Layer | Extension Point | Current State | What's Needed |
|-------|----------------|---------------|---------------|
| **CLI** | `src/kimi_cli/cli/plugin.py` | install/list/remove/info | Add `search`, `update`, `install-by-name` commands |
| **Registry client** | Does not exist | N/A | New module for fetching index, resolving name→URL, caching |
| **Storage** | `~/.kimi/plugins/` | Simple directory of plugin dirs | Could add `~/.kimi/plugin-index.json` for cached registry metadata |
| **Config** | `Config` model | No plugin registry settings | Add optional `plugin_registry_url`, `plugin_channel` fields |
| **Install** | `install_plugin()` | Only local source | Wrap with registry download step before calling existing `install_plugin()` |
| **Runtime load** | `load_agent()` in `soul/agent.py` | Scans `~/.kimi/plugins/` automatically | No change needed — marketplace plugins live in same dir |
| **Credential refresh** | `KimiCLI.create()` in `app.py` | Calls `refresh_plugin_configs()` | No change needed |
| **Skill discovery** | `resolve_skills_roots()` | Includes plugins dir as "extra" | No change needed; could add "Marketplace" scope heading |
| **Metadata** | `plugin.json` schema | Minimal fields | Could add optional marketplace fields (already tolerated via `extra="ignore"`) |
| **Versioning** | None | No update checking | Add version comparison logic; store "installed from" URL in runtime |

### Critical observations
1. **The existing plugin architecture is already well-structured for marketplace integration.** The `~/.kimi/plugins/` directory is the single source of truth, and both runtime credential refresh and tool loading scan it automatically.
2. **The smallest viable marketplace** would only need: (a) a registry client module, (b) `kimi plugin search` and `kimi plugin install <name>` CLI commands, and (c) cached index storage. The rest of the pipeline (install, inject, load, execute) already works.
3. **No config schema changes are strictly required** to start, but adding `plugin_registry_url` to `Config` would let users point to custom registries.
4. **Plugin metadata is forward-compatible** because `PluginSpec.model_config = ConfigDict(extra="ignore")`. New marketplace fields can be added to `plugin.json` without breaking parsing.

---

# Appendix: Claude Code Marketplace Source Code Reference

> Extracted from leaked Claude Code v2.1.88 source (`@anthropic-ai/claude-code` npm package, 2026-03-31). This section documents the architecture, schemas, and design patterns used by Claude Code's plugin marketplace system for reference when designing Kimi's marketplace.

---

## A.1 Plugin Manifest Schema (`schemas.ts`)

Claude's `plugin.json` (`PluginManifestSchema`) is a **deeply merged union** of many partial schemas:

```typescript
PluginManifestSchema = z.object({
  // Metadata (required)
  name, version, description, author, homepage, repository, license, keywords, dependencies,
  // Optional components
  hooks,        // hooks.json path or inline
  commands,     // commands/ path or inline metadata
  agents,       // agents/ path or inline
  skills,       // skills/ path or inline
  outputStyles, // output-styles/ path
  channels,     // release channels (stable, beta)
  mcpServers,   // .mcp.json or inline
  lspServers,   // .lsp.json or inline
  settings,     // default agent, etc.
  userConfig,   // user-configurable fields with schema
})
```

Key design: **every component is optional**. A plugin can be just a manifest + one skill, or a full bundle with tools + hooks + agents + MCP.

---

## A.2 Marketplace Catalog Schema (`marketplace.json`)

```typescript
PluginMarketplaceSchema = z.object({
  name: MarketplaceNameSchema(),      // kebab-case, no spaces, anti-impersonation
  owner: PluginAuthorSchema(),        // curator info
  plugins: z.array(PluginMarketplaceEntrySchema()),
  forceRemoveDeletedPlugins: z.boolean().optional(),
  metadata: {
    pluginRoot: z.string().optional(), // base path for relative plugin sources
    version: z.string().optional(),
    description: z.string().optional(),
  },
  allowCrossMarketplaceDependenciesOn: z.array(z.string()).optional(),
})
```

**Marketplace Entry** (each plugin in the catalog):
```typescript
PluginMarketplaceEntrySchema = PluginManifestSchema.partial().extend({
  name: z.string(),
  source: PluginSourceSchema(),
  category: z.string().optional(),
  tags: z.array(z.string()).optional(),
  strict: z.boolean().default(true),
})
```

The `strict` field is important:
- `strict: true` (default): plugin directory MUST contain its own `plugin.json`
- `strict: false`: the marketplace entry itself serves as the manifest (useful for simple plugins)

---

## A.3 Source Type Support

### Marketplace Source (where the catalog lives)
| Type | Example |
|------|---------|
| `url` | `https://example.com/marketplace.json` |
| `github` | `{repo: "owner/repo", ref: "main", path: ".claude-plugin/marketplace.json", sparsePaths: [".claude-plugin"]}` |
| `git` | `{url: "https://git.company.com/repo", ref: "main"}` |
| `npm` | `{package: "@scope/marketplace-pkg"}` |
| `file` | `{path: "/path/to/marketplace.json"}` |
| `directory` | `{path: "/path/to/dir-with-marketplace"}` |
| `hostPattern` | `{hostPattern: "^github\\.mycompany\\.com$"}` |
| `pathPattern` | `{pathPattern: "^/opt/approved/"}` |
| `settings` | Inline marketplace defined in `settings.json` |

### Plugin Source (where the plugin code lives)
| Type | Example |
|------|---------|
| relative path | `"./plugins/my-plugin"` (relative to marketplace root) |
| `npm` | `{package: "my-plugin", version: "^1.0.0", registry: "https://npm.company.com"}` |
| `pip` | `{package: "my-plugin", version: ">=2.0.0"}` |
| `url` | `{url: "https://github.com/owner/repo.git", ref: "main", sha: "abc123..."}` |
| `github` | `{repo: "owner/repo", ref: "v1.2.0", sha: "abc123..."}` |

**SHA pinning**: `git` and `github` sources support optional `sha` for exact commit pinning.

---

## A.4 Security Design

### Marketplace Name Protection
```typescript
const ALLOWED_OFFICIAL_MARKETPLACE_NAMES = new Set([
  'claude-code-marketplace',
  'claude-code-plugins',
  'claude-plugins-official',
  'anthropic-marketplace',
  'anthropic-plugins',
  'agent-skills',
  'life-sciences',
  'knowledge-work-plugins',
])
```

- Non-ASCII characters blocked (homograph attack prevention)
- Pattern matching blocks names like `official-claude-plugins`, `anthropic-marketplace-new`
- Reserved names must come from `github.com/anthropics/*`

### Source Validation
- `strictKnownMarketplaces`: allowlist of host/path patterns
- `blocklist`: explicit blocklist
- `managedPlugins`: enterprise MDM can force-enable plugins
- `isSourceAllowedByPolicy()`: checks all policies before install

---

## A.5 Local Storage Layout

```
~/.claude/
└── plugins/
    ├── known_marketplaces.json          # Declared marketplace configs
    │   # { "my-marketplace": { source: {...}, autoUpdate: true } }
    ├── marketplaces/                    # Cached catalogs
    │   ├── my-marketplace.json          # Fetched from URL
    │   └── github-marketplace/          # Git clone
    │       └── .claude-plugin/
    │           └── marketplace.json
    └── cache/                           # Versioned plugin cache (v1+)
        └── plugin-name/
            ├── v1.0.0/                  # Full plugin directory
            └── v1.1.0/
```

**Installed state** is tracked in user settings (`settings.json`):
```json
{
  "enabledPlugins": {
    "plugin-name@marketplace-name": true,
    "another@builtin": false
  }
}
```

---

## A.6 Core Workflows

### Marketplace Reconciliation (Startup)
```
getDeclaredMarketplaces()       ← from settings (user + project)
loadKnownMarketplacesConfig()   ← from known_marketplaces.json
diffMarketplaces()              ← compare
declared vs materialized
  → missing: clone/download new
  → sourceChanged: re-clone
  → upToDate: skip
reconcileMarketplaces()         ← execute (idempotent, additive)
```

### Plugin Installation
```
1. Resolve PluginSource from marketplace entry
2. Fetch code:
   - github/git → git clone --depth 1 (or sparse-checkout)
   - npm → npm pack + extract
   - local → copy/symlink
3. calculatePluginVersion() → semver | git SHA | marketplace version
4. Write to cache: ~/.claude/plugins/cache/<name>/<version>/
5. Update enabledPlugins in settings
6. Register to runtime (skills/hooks/agents/tools/mcp)
```

### Plugin Loading (`pluginLoader.ts`)
```
loadPluginManifest()     ← validate plugin.json (or generate default)
loadPluginHooks()        ← validate hooks.json
validateComponentPaths() ← parallel pathExists for all declared components
→ LoadedPlugin object
→ Register each component to its subsystem
```

---

## A.7 Version Management

**Version resolution priority:**
1. `plugin.json` `version` field (semver)
2. Git commit SHA (for git/github sources)
3. Marketplace entry `version` field

**Cache eviction:**
- Old versions kept for 7 days (grace period for concurrent sessions)
- Marked "orphaned" after new version installed
- Auto-cleaned after grace period

**Update detection:**
- Compare cached version against resolved latest version
- Background check at startup (non-blocking)
- Notification shown if updates available: `/reload-plugins` to activate

---

## A.8 Key Design Patterns

| Pattern | Implementation |
|---------|---------------|
| **Fail-open** | Broken plugins skipped with warnings, never crash startup |
| **Async reconciliation** | Marketplace sync happens in background, non-blocking |
| **Cache-first** | After first install, load from local cache instantly |
| **Namespace isolation** | `plugin-name:server` for MCP, `plugin-name:skill` for skills |
| **Discriminated unions** | Zod `z.discriminatedUnion('source', [...])` for type-safe source parsing |
| **Lazy schemas** | `lazySchema(() => ...)` avoids circular import issues |
| **Additive only** | Reconciler never deletes; only adds/updates |
| **Grace period** | Old plugin versions kept for 7 days to avoid breaking running sessions |

---

## A.9 Mapping to Kimi's Architecture

| Claude Code | Kimi Code CLI | Mapping Strategy |
|-------------|---------------|------------------|
| `~/.claude/plugins/` | `~/.kimi/plugins/` | ✅ Same pattern |
| `plugin.json` manifest | `plugin.json` manifest | ✅ Extend with `extra="ignore"` |
| `marketplace.json` catalog | **Not exists** | 🆕 New file format |
| `known_marketplaces.json` | **Not exists** | 🆕 New persistent config |
| `settings.json` enabledPlugins | `config.toml` | 🆕 Add `enabled_plugins` table |
| Version cache (`cache/<name>/<version>/`) | Flat install | 🆕 Versioned subdirs |
| Background reconcile | Sync at startup | 🆕 Async task |
| `PluginSourceSchema` (8 types) | Local only | 🆕 Extend source types |
| `PluginManifest` (10 component types) | Tools only | 🆕 Add skills/hooks/agents/mcp |

---

## A.10 Recommended Kimi MVP Marketplace Design

Based on the above analysis, the minimal viable marketplace for Kimi needs:

1. **Data models** (`src/kimi_cli/marketplace/schemas.py`)
   - `MarketplaceCatalog` — `marketplace.json` format
   - `MarketplaceSource` — discriminated union of source types
   - `InstalledPluginRecord` — name + version + source + enabled

2. **Storage** (`~/.kimi/marketplace/`)
   - `known_marketplaces.json` — declared catalogs
   - `marketplaces/` — cached catalog files
   - `installed.json` — active plugin → version mapping

3. **CLI commands** (`src/kimi_cli/cli/plugin.py`)
   - `kimi plugin marketplace add <url>`
   - `kimi plugin marketplace list`
   - `kimi plugin marketplace remove <name>`
   - `kimi plugin install <plugin>[@<marketplace>]`
   - `kimi plugin update [plugin]`
   - `kimi plugin update --all`

4. **Registry client** (`src/kimi_cli/marketplace/client.py`)
   - Fetch catalog from URL/GitHub/local
   - Cache to disk
   - Resolve plugin name → source

5. **Versioned cache** (`src/kimi_cli/marketplace/cache.py`)
   - Install to `~/.kimi/plugins/cache/<name>/<version>/`
   - Symlink `~/.kimi/plugins/<name>/` → active version
   - Keep old versions with grace period

6. **Runtime integration** (minimal)
   - `load_plugin_tools()` already scans `~/.kimi/plugins/` — symlink handles this
   - Skill discovery already includes plugins dir — symlink handles this
   - Credential refresh already scans all plugins — no change needed

The key insight: **Kimi's existing plugin system already handles runtime loading. The marketplace layer only needs to solve "download + cache + version + enable/disable".**


---

# Appendix B: Detailed Module Reference

> Deeper dive into individual modules not covered in Appendix A.

---

## B.1 Plugin Loading (`pluginLoader.ts`)

### `createPluginFromPath()` — Central assembly function

This is the main function that turns a plugin directory into a `LoadedPlugin` object. It performs these steps:

1. **Load manifest**: Reads `.claude-plugin/plugin.json` or creates a default manifest with fallback name
2. **Create base `LoadedPlugin`**: name, manifest, path, source, repository, enabled
3. **Auto-detect directories in parallel**:
   - `commands/` → sets `commandsPath`
   - `agents/` → sets `agentsPath`
   - `skills/` → sets `skillsPath`
   - `output-styles/` → sets `outputStylesPath`
4. **Validate manifest-declared paths**: For each component declared in manifest (e.g. `commands: {"about": {"source": "./README.md"}}`), check path exists in parallel
5. **Load hooks**: If `hooks/hooks.json` exists, parse and validate with `PluginHooksSchema`
6. **Return**: `{plugin: LoadedPlugin, errors: PluginError[]}`

**Fail-open design**: Missing components are reported as `PluginError` but do NOT prevent the plugin from loading.

### `validatePluginPaths()` — Parallel path validation

```typescript
const checks = await Promise.all(
  relPaths.map(async relPath => {
    const fullPath = join(pluginPath, relPath)
    return { relPath, fullPath, exists: await pathExists(fullPath) }
  })
)
```

- All `pathExists` checks run in parallel
- Results processed sequentially to keep log ordering deterministic
- Missing paths become `type: 'path-not-found'` errors

### `loadPluginManifest()` — Manifest with fallback

```typescript
if (!await pathExists(manifestPath)) {
  return { name: fallbackName, description: `Plugin from ${source}` }
}
const result = PluginManifestSchema().safeParse(parsedJson)
if (!result.success) throw Error(`Invalid manifest: ${errors}`)
```

- No manifest → auto-generates minimal default
- Invalid manifest → throws (hard failure, plugin skipped)

---

## B.2 Plugin Operations (`pluginOperations.ts`)

### Scope System

Claude has 5 installation scopes:

| Scope | Description | Persistence |
|-------|-------------|-------------|
| `user` | User-wide (default) | `~/.claude/settings.json` |
| `project` | Per-repository | `.claude/settings.json` |
| `local` | Session-only (from `--plugin-dir`) | Not persisted |
| `managed` | Enterprise MDM enforced | `managed-settings.json` |
| `builtin` | Built-in plugins shipping with CLI | N/A |

**Key rule**: Installation is global (on disk), but **enabled/disabled is per-scope**.

### Core Operations

```typescript
export type PluginOperationResult = {
  success: boolean
  message: string
  pluginId?: string
  pluginName?: string
  scope?: PluginScope
  reverseDependents?: string[]  // Plugins that depend on this one
}
```

- `installPlugin(pluginId, scope)` — Downloads, caches, registers; resolves dependencies; warns if reverse dependents exist
- `uninstallPlugin(pluginId, scope)` — Removes from disk if no other scope needs it; warns about broken dependents
- `enablePlugin(pluginId, scope)` — Sets `enabledPlugins[pluginId] = true` in settings
- `disablePlugin(pluginId, scope)` — Sets `enabledPlugins[pluginId] = false`
- `updatePlugin(pluginId)` — Re-downloads latest version, swaps cache

---

## B.3 Refresh / Hot Reload (`refresh.ts`)

### Three-Layer Model

```
Layer 1: Intent    → settings (user wants what)
Layer 2: Material  → ~/.claude/plugins/ (what's on disk)
Layer 3: Active    → AppState (what's running now)
```

### `refreshActivePlugins()`

Triggered by:
- `/reload-plugins` command (user-initiated)
- `print.ts` auto-refresh (headless mode before first query)
- `performBackgroundPluginInstallations()` (after marketplace install completes)

**Sequence**:
1. `clearAllCaches()` — wipe ALL memoized plugin data
2. `loadAllPlugins()` — re-read installed_plugins.json + disk
3. `getPluginCommands()` — re-parse all command markdown files
4. `getAgentDefinitionsWithOverrides()` — re-load agent specs
5. `loadPluginMcpServers()` — re-parse .mcp.json for each enabled plugin
6. `loadPluginLspServers()` — re-parse .lsp.json
7. Update AppState with new counts
8. Bump `mcp.pluginReconnectKey` → triggers MCP connection manager re-init

**NOT called by**: UI `needsRefresh` effect — that just shows a notification; user must explicitly run `/reload-plugins`.

---

## B.4 Installed Plugins Manager (`installedPluginsManager.ts`)

### File Format Evolution

**V1** (`installed_plugins.json`):
```json
{
  "plugin-name@marketplace": {
    "installPath": "/path/to/cache/...",
    "version": "1.0.0"
  }
}
```

**V2** (same file, version field):
```json
{
  "version": 2,
  "plugins": {
    "plugin-name@marketplace": [
      {
        "scope": "user",
        "installPath": "/path",
        "version": "1.0.0",
        "installedAt": "2024-01-15T..."
      }
    ]
  }
}
```

### Migration

- Runs once per session at startup
- If `installed_plugins_v2.json` exists: copy to `installed_plugins.json`, delete V2
- If V1 file found: convert in-place to V2
- Cleanup legacy cache directories

### In-Memory Snapshot

```typescript
let inMemoryInstalledPlugins: InstalledPluginsFileV2 | null = null
```

- Captured at startup
- Background updates modify disk ONLY, not memory
- Running session uses the snapshot to avoid mid-session surprises

---

## B.5 Version Calculation (`pluginVersioning.ts`)

### Algorithm

```typescript
async function calculatePluginVersion(pluginId, source, manifest, installPath, providedVersion, gitCommitSha):
  1. if manifest?.version: return manifest.version           // Semver from plugin.json
  2. if providedVersion: return providedVersion               // From marketplace entry
  3. if gitCommitSha: return gitCommitSha.substring(0, 12)   // Pre-captured SHA
  4. if installPath: return await getGitCommitSha(installPath) // Read from .git
  5. return 'unknown'
```

### Special case: git-subdir

When a plugin lives in a subdirectory of a monorepo:
```typescript
const normPath = source.path
  .replace(/\\/g, '/')
  .replace(/^\.\//, '')
  .replace(/\/+$/, '')
const pathHash = sha256(normPath).substring(0, 8)
return `${shortSha}-${pathHash}`  // e.g. "a1b2c3d4e5f6-8a3f9b2c"
```

This prevents two plugins at different subdirs of the same commit from colliding in cache.

---

## B.6 Cache & Orphaned Cleanup (`cacheUtils.ts`)

### Grace Period (7 days)

```typescript
const ORPHANED_AT_FILENAME = '.orphaned_at'
const CLEANUP_AGE_MS = 7 * 24 * 60 * 60 * 1000

// On update/uninstall:
await writeFile(join(versionPath, '.orphaned_at'), `${Date.now()}`)

// Background cleanup:
if (orphanedAtExists && (now - orphanedAt) > CLEANUP_AGE_MS) {
  await rm(versionPath, { recursive: true })
}
```

**Why 7 days?** Concurrent Claude sessions may hold file handles to the old version. Deleting immediately would break them.

### Cache Clearing Functions

```typescript
function clearAllCaches():
  clearPluginCache()          // loadAllPlugins memoize
  clearPluginCommandCache()   // getPluginCommands memoize
  clearPluginAgentCache()     // getAgentDefinitions memoize
  clearPluginHookCache()      // loadPluginHooks memoize
  clearPluginOptionsCache()   // plugin settings
  clearPluginOutputStyleCache()
  clearCommandsCache()        // global command registry
  clearAgentDefinitionsCache()
  clearPromptCache()
  resetSentSkillNames()
```

---

## B.7 Marketplace Manager (`marketplaceManager.ts`)

### `loadKnownMarketplacesConfig()`

Reads `~/.claude/plugins/known_marketplaces.json`:
```json
{
  "my-marketplace": {
    "source": { "source": "github", "repo": "owner/repo" },
    "installLocation": ".../marketplaces/my-marketplace",
    "lastUpdated": "2024-01-15T10:30:00.000Z"
  }
}
```

**Two variants**:
- `loadKnownMarketplacesConfig()` — throws on corruption (for write paths)
- `loadKnownMarketplacesConfigSafe()` — returns `{}` on any error (for read-only paths)

### `getDeclaredMarketplaces()`

Builds the "intent layer" from merged settings:
```typescript
return {
  ...implicit,      // official marketplace if any enabled plugin references it
  ...getAddDirExtraMarketplaces(),  // from --add-dir
  ...getInitialSettings().extraKnownMarketplaces,  // from settings.json
}
```

Precedence: local > project > user > implicit

### `saveMarketplaceToSettings()`

Writes to the correct settings source:
- If marketplace declared in `localSettings` → write there
- If in `projectSettings` → write there
- Otherwise → `userSettings`

---

## B.8 Installation Helpers (`pluginInstallationHelpers.ts`)

### `cacheAndRegisterPlugin()`

The canonical "install a plugin to disk" function:

```typescript
async function cacheAndRegisterPlugin(pluginId, entry, scope, projectPath, localSourcePath):
  // 1. Download/copy to versioned cache
  const cacheResult = await cachePlugin(source, { manifest: entry })
  
  // 2. Calculate version
  const version = await calculatePluginVersion(...)
  
  // 3. Write to installed_plugins.json
  await addInstalledPlugin(pluginId, scope, cacheResult.path, version)
  
  // 4. Resolve dependencies (auto-install if needed)
  const depResult = await resolveDependencyClosure(pluginId, lookup, alreadyEnabled)
  if (!depResult.ok) return { success: false, message: formatResolutionError(depResult) }
  
  // 5. Install each dependency
  for (const depId of depResult.closure) {
    await installResolvedPlugin(depId, ...)
  }
```

### `validatePathWithinBase()`

```typescript
function validatePathWithinBase(basePath, relativePath):
  const resolved = resolve(basePath, relativePath)
  if (!resolved.startsWith(resolve(basePath) + sep)):
    throw Error("Path traversal detected")
  return resolved
```

Used everywhere to prevent `../../../etc/passwd` escapes.

---

## B.9 ZIP Cache Mode (`zipCache.ts`)

For headless/server deployments where the filesystem is read-only or slow:

```
CLAUDE_CODE_PLUGIN_USE_ZIP_CACHE=1
CLAUDE_CODE_PLUGIN_CACHE_DIR=/mnt/plugins-cache
```

**Storage**:
```
/mnt/plugins-cache/
├── known_marketplaces.json
├── installed_plugins.json
├── marketplaces/
│   └── official-marketplace.json
└── plugins/
    └── official-marketplace/
        └── plugin-a/
            └── 1.0.0.zip
```

**Limitations**:
- Headless mode only
- Only github/git/url marketplace sources
- Only `strict:true` marketplace entries
- Auto-update is non-blocking background

---

## B.10 Plugin Policy (`pluginPolicy.ts`)

Enterprise/org policy support:

```typescript
function isPluginBlockedByPolicy(pluginId: string): boolean {
  const policyEnabled = getSettingsForSource('policySettings')?.enabledPlugins
  return policyEnabled?.[pluginId] === false
}
```

- Policy-blocked plugins cannot be installed or enabled by users
- Used at install chokepoint, enable op, and UI filters

---

## B.11 Dependency Resolution (`dependencyResolver.ts`)

### Semantics

"Apt-style" presence guarantee, not a module graph:
> Plugin A depending on Plugin B means "B's namespaced components must be available when A runs."

### `resolveDependencyClosure()`

```typescript
async function resolveDependencyClosure(rootId, lookup, alreadyEnabled, allowedCrossMarketplaces):
  // DFS walk with cycle detection
  // Cross-marketplace deps BLOCKED by default (security boundary)
  // Already-enabled deps are skipped (no surprise settings writes)
```

**Error types**:
- `cycle` — circular dependency chain
- `not-found` — dependency not in marketplace
- `cross-marketplace` — dependency in different marketplace (not allowed)

**Escape hatches**:
1. Manually install the cross-marketplace dep first (then it is in `alreadyEnabled`)
2. Root marketplace's `allowCrossMarketplaceDependenciesOn` allowlist

### `verifyAndDemote()`

Load-time fixed-point check:
- If a plugin's dependencies are unsatisfied, it is "demoted" (disabled for this session)
- Does NOT write to settings — purely session-local

---

## B.12 Command Loading (`loadPluginCommands.ts`)

### Namespacing Logic

```typescript
function getCommandNameFromFile(filePath, baseDir, pluginName):
  // For skills: skills/my-skill/SKILL.md -> "plugin:my-skill"
  // For nested: commands/deploy/production.md -> "plugin:deploy:production"
  const relativePath = fileDirectory.slice(baseDir.length).replace(/^\//, '')
  const namespace = relativePath.split('/').join(':')
  return namespace ? `${pluginName}:${namespace}:${commandBaseName}` : `${pluginName}:${commandBaseName}`
```

**Supported formats**:
- Simple markdown files: `commands/build.md` -> `/plugin:build`
- Nested directories: `commands/deploy/prod.md` -> `/plugin:deploy:prod`
- Skills: `skills/my-skill/SKILL.md` -> `/plugin:my-skill`

### Frontmatter Support

Commands can declare frontmatter:
```yaml
---
description: Build the project
model: claude-sonnet-4
tools: [Bash, FileRead]
allowed-tools: [Bash, FileRead, FileWrite]
---
```

---

## B.13 Hook Loading (`loadPluginHooks.ts`)

### Event Mapping

Claude hooks support 20+ events:
```typescript
PreToolUse, PostToolUse, PostToolUseFailure, PermissionDenied,
Notification, UserPromptSubmit, SessionStart, SessionEnd,
Stop, StopFailure, SubagentStart, SubagentStop,
PreCompact, PostCompact, PermissionRequest, Setup,
TeammateIdle, TaskCreated, TaskCompleted,
Elicitation, ElicitationResult, ConfigChange,
WorktreeCreate, WorktreeRemove, InstructionsLoaded,
CwdChanged, FileChanged
```

### Registration

```typescript
export const loadPluginHooks = memoize(async () => {
  const { enabled } = await loadAllPluginsCacheOnly()
  for (const plugin of enabled) {
    const matchers = convertPluginHooksToMatchers(plugin)
    registerHookCallbacks(matchers)
  }
})
```

- Memoized (cached until `clearPluginHookCache()`)
- Hooks include `pluginRoot`, `pluginName`, `pluginId` context

### Hot Reload

```typescript
let lastPluginSettingsSnapshot: string | undefined

function setupHotReload():
  settingsChangeDetector.subscribe(() => {
    const current = jsonStringify(getSettings_DEPRECATED().enabledPlugins)
    if (current !== lastPluginSettingsSnapshot) {
      clearPluginHookCache()
      lastPluginSettingsSnapshot = current
    }
  })
```

When `enabledPlugins` changes in settings, hooks are automatically reloaded.

---

## B.14 MCP Integration (`mcpPluginIntegration.ts`)

### Two formats

1. **`.mcp.json`** — JSON config with `mcpServers` object
2. **`.mcpb` / `.dxt`** — Binary MCP Bundle (compressed + manifest)

### MCPB Loading

```typescript
async function loadMcpServersFromMcpb(plugin, mcpbPath, errors):
  const result = await loadMcpbFile(mcpbPath, plugin.path, pluginId, onProgress)
  if (result.status === 'needs-config'):
    // User must configure via /plugin -> Manage plugins -> Configure
    return null
  return { [result.manifest.name]: result.mcpConfig }
```

### User Configuration

Plugins can declare user-configurable fields:
```json
{
  "userConfig": {
    "schema": {
      "apiKey": { "type": "string", "description": "API key" },
      "endpoint": { "type": "string", "default": "https://api.example.com" }
    }
  }
}
```

User values are stored per-plugin and substituted into MCP configs at load time.

---

## B.15 Official Marketplace GCS Mirror (`officialMarketplaceGcs.ts`)

### Problem

GitHub API rate limits + git clone overhead on every startup.

### Solution

Anthropic publishes the official marketplace as a content-addressed ZIP to GCS:
```
https://downloads.claude.ai/claude-code-releases/plugins/claude-plugins-official/{sha}.zip
```

### Workflow

```typescript
async function fetchOfficialMarketplaceFromGcs(installLocation, cacheDir):
  // 1. Read local .gcs-sha sentinel
  // 2. Fetch `latest` pointer (~40 bytes, Cache-Control: max-age=300)
  // 3. If SHA changed:
  //    a. Download ~3.5MB zip
  //    b. Extract to temp dir
  //    c. Atomic swap: rm old, rename temp
  //    d. Write new .gcs-sha
  // 4. Return SHA on success, null on failure
```

**Defense in depth**:
- Path validation: refuses to extract outside `marketplacesCacheDir`
- On failure: caller falls back to git clone
- Telemetry: logs `noop` | `updated` | `failed` with timing

---

## B.16 Summary Table: All Plugin/Marketplace Modules

| Module | File | Purpose |
|--------|------|---------|
| **CLI** | `src/commands/plugin/*.tsx` | `/plugin` interactive UI (Discover, Installed, Marketplaces, Errors) |
| **CLI ops** | `src/services/plugins/pluginOperations.ts` | Install/uninstall/enable/disable/update library functions |
| **Installation** | `src/services/plugins/PluginInstallationManager.ts` | Background startup install + progress tracking |
| **Loader** | `src/utils/plugins/pluginLoader.ts` | `createPluginFromPath()`, manifest loading, path validation |
| **Refresh** | `src/utils/plugins/refresh.ts` | `/reload-plugins`, hot reload, AppState updates |
| **Reconciler** | `src/utils/plugins/reconciler.ts` | Diff + reconcile declared vs materialized marketplaces |
| **Manager** | `src/utils/plugins/marketplaceManager.ts` | known_marketplaces.json + catalog fetch/cache |
| **Helpers** | `src/utils/plugins/marketplaceHelpers.ts` | Formatting, graceful degradation, source display |
| **Install helpers** | `src/utils/plugins/pluginInstallationHelpers.ts` | `cacheAndRegisterPlugin()`, path traversal guard |
| **Installed** | `src/utils/plugins/installedPluginsManager.ts` | installed_plugins.json V1/V2 + migration |
| **Versioning** | `src/utils/plugins/pluginVersioning.ts` | calculatePluginVersion() with git-subdir hash |
| **Cache** | `src/utils/plugins/cacheUtils.ts` | clearAllCaches(), orphaned cleanup (7-day grace) |
| **ZIP cache** | `src/utils/plugins/zipCache.ts` | Headless ZIP-based plugin storage |
| **Policy** | `src/utils/plugins/pluginPolicy.ts` | Enterprise policy blocking |
| **Deps** | `src/utils/plugins/dependencyResolver.ts` | resolveDependencyClosure(), verifyAndDemote() |
| **Commands** | `src/utils/plugins/loadPluginCommands.ts` | Parse markdown commands with namespacing |
| **Hooks** | `src/utils/plugins/loadPluginHooks.ts` | Convert plugin hooks to native matchers |
| **Agents** | `src/utils/plugins/loadPluginAgents.ts` | Load agent markdown definitions |
| **MCP** | `src/utils/plugins/mcpPluginIntegration.ts` | .mcp.json + .mcpb loading |
| **LSP** | `src/utils/plugins/lspPluginIntegration.ts` | Language server plugin loading |
| **GCS** | `src/utils/plugins/officialMarketplaceGcs.ts` | Fast official marketplace via CDN |
| **Schemas** | `src/utils/plugins/schemas.ts` | Zod schemas for ALL formats |
| **Builtin** | `src/plugins/builtinPlugins.ts` | Built-in plugin registry (`@builtin`) |
| **Telemetry** | `src/utils/telemetry/pluginTelemetry.ts` | Install/update/fetch event logging |


---

# Appendix C: Additional Modules

> Supplementary modules discovered after initial documentation.

---

## C.1 Plugin Directories (`pluginDirectories.ts`)

### Directory Layout

```
~/.claude/plugins/                    # or CLAUDE_CODE_PLUGIN_CACHE_DIR
├── known_marketplaces.json
├── installed_plugins.json
├── marketplaces/
│   └── <marketplace-name>/
│       └── ... (cloned repo or extracted catalog)
└── cache/
    └── <marketplace-name>/
        └── <plugin-name>/
            └── <version>/
                └── .claude-plugin/
                    └── plugin.json
```

### Seed Directory Support

Enterprise/container 场景支持只读 seed 层：

```typescript
function getPluginSeedDirs(): string[] {
  const raw = process.env.CLAUDE_CODE_PLUGIN_SEED_DIR
  if (!raw) return []
  return raw.split(delimiter).filter(Boolean).map(expandTilde)
}
```

- Seed 结构与主目录完全一致
- 多 seed 用 PATH 分隔符分层（`:` Unix / `;` Windows）
- 第一个包含目标 marketplace/plugin 的 seed 获胜
- 避免重复 clone，适合预装镜像

### Per-Plugin Data Directory

```typescript
function getPluginDataDir(pluginId: string): string {
  const dir = join(getPluginsDirectory(), 'data', sanitizePluginId(pluginId))
  mkdirSync(dir, { recursive: true })
  return dir
}
```

- **Persistent** —  survives plugin updates（与 version-scoped 安装目录不同）
- 通过 `${CLAUDE_PLUGIN_DATA}` 变量暴露给 plugin
- 仅在最后一个 scope 卸载时才删除

---

## C.2 Plugin Options Storage (`pluginOptionsStorage.ts`)

### Sensitive vs Non-Sensitive Split

```
┌─────────────────────┬─────────────────────────────┐
│ sensitive: true     │ sensitive: false / default  │
├─────────────────────┼─────────────────────────────┤
│ secureStorage       │ settings.json               │
│ (macOS keychain /   │ pluginConfigs[pluginId]     │
│  .credentials.json) │   .options                  │
└─────────────────────┴─────────────────────────────┘
```

**写入顺序**：secureStorage **先**，settings.json **后**。
- 如果 keychain 失败 → throw，不碰 settings.json（旧明文保留作 fallback）
- 如果 settings.json 失败 → 至少 secret 已安全存储

### Variable Substitution

| Variable | 替换为 | 生命周期 |
|----------|--------|----------|
| `${CLAUDE_PLUGIN_ROOT}` | version-scoped 安装目录 | 每次更新重建 |
| `${CLAUDE_PLUGIN_DATA}` | persistent 数据目录 |  survives updates |
| `${user_config.KEY}` | 用户配置的选项值 | 按 plugin 存储 |

**安全处理**：
- MCP/LSP/hook 环境变量中：正常替换敏感值
- skill/agent 内容中：敏感值替换为 `[sensitive option 'KEY' not available in skill content]`
- 防止 secret 泄漏到模型 prompt

---

## C.3 MCPB Handler (`mcpbHandler.ts`)

### MCPB = MCP Bundle (Binary Format)

Anthropic 定义的打包格式，将 MCP server + manifest + 资源文件打包成单个 `.mcpb`/`.dxt` 文件。

**内部结构**（ZIP 压缩）：
```
archive.mcpb
├── manifest.json       # DXT manifest (name, version, author, server, user_config)
├── server/             # MCP server 可执行文件/脚本
│   └── ...
└── ... (other assets)
```

### Caching Strategy

```
<plugin-path>/.mcpb-cache/
├── <source-hash>.metadata.json   # 缓存元数据
└── <content-hash>/               # 解压后的内容
    ├── manifest.json
    └── server/
```

- **local files**: 比较 mtime，有变化则重新提取
- **URLs**: 显式更新时重新下载（无自动刷新）
- **content-addressed**: SHA256 前 16 位作为版本标识

### User Config Flow

```
1. loadMcpbFile() → 解压并解析 manifest
2. manifest.user_config 存在？
   ├─ 是 → loadMcpServerUserConfig(pluginId, serverName)
   │       ├─ 有完整配置 → generateMcpConfig() 并返回
   │       └─ 缺少/无效 → 返回 {status: 'needs-config'}
   └─ 否 → generateMcpConfig() 直接返回
```

用户通过 `/plugin` → Manage plugins → Configure 补全配置后再次调用。

---

## C.4 Auto-Update (`pluginAutoupdate.ts`)

### Workflow

```
startup → autoUpdateMarketplacesAndPluginsInBackground()
  ├── skip? (shouldSkipPluginAutoupdate() checks config flag)
  ├── getAutoUpdateEnabledMarketplaces()
  │     └── official marketplace defaults to true
  │     └── third-party defaults to false
  ├── refreshMarketplace(name) for each  (git pull / re-download)
  └── updatePluginsForMarketplaces(marketplaceNames)
        └── updatePluginOp(pluginId, scope) per installation
```

### Update Semantics

- **Non-inplace**: 新版本的 cache dir 创建后，installed_plugins.json 指向新版本
- **Needs restart**: 更新是 disk-only，当前 session 仍用旧版本
- **Grace period**: 旧版本被 `.orphaned_at` 标记，7 天后 GC

### Notification

```typescript
onPluginsAutoUpdated((updatedPlugins: string[]) => {
  // REPL shows: "Plugins updated: [a, b]. Run /reload-plugins to apply."
})
```

---

## C.5 Background Installation (`PluginInstallationManager.ts`)

### Startup Sequence

```
main.tsx startup
  └── performBackgroundPluginInstallations(setAppState)
        ├── diffMarketplaces(declared, materialized)
        ├── reconcileMarketplaces({ onProgress })
        │     ├── 'installing'  → UI spinner
        │     ├── 'installed'   → done
        │     └── 'failed'      → error message
        └── After reconcile:
              ├─ new installs  → refreshActivePlugins() (auto-apply)
              └─ updates only  → setAppState({ needsRefresh: true })
```

### Why Two Different Post-Reconcile Behaviors?

| 场景 | 行为 | 原因 |
|------|------|------|
| 新 marketplace 安装 | `refreshActivePlugins()` | 初始 cache-only load 会报 "Plugin not found"，必须立即刷新 |
| 现有 marketplace 更新 | `needsRefresh = true` | 更新不紧急，让用户选择何时 `/reload-plugins` |

---

## C.6 File Read Status Summary

### Core Architecture (Read ✅)

| File | Status | Section |
|------|--------|---------|
| `schemas.ts` | ✅ | A.1, A.2 |
| `marketplaceManager.ts` | ✅ | A.3, B.7 |
| `reconciler.ts` | ✅ | A.4 |
| `pluginLoader.ts` | ✅ | A.5, B.1 |
| `pluginOperations.ts` | ✅ | B.2 |
| `refresh.ts` | ✅ | B.3 |
| `installedPluginsManager.ts` | ✅ | B.4 |
| `pluginVersioning.ts` | ✅ | B.5 |
| `cacheUtils.ts` | ✅ | B.6 |
| `pluginInstallationHelpers.ts` | ✅ | B.8 |
| `zipCache.ts` | ✅ | B.9 |
| `pluginPolicy.ts` | ✅ | B.10 |
| `dependencyResolver.ts` | ✅ | B.11 |
| `loadPluginCommands.ts` | ✅ | B.12 |
| `loadPluginHooks.ts` | ✅ | B.13 |
| `mcpPluginIntegration.ts` | ✅ | B.14 |
| `officialMarketplace.ts` | ✅ | A.3 |
| `officialMarketplaceGcs.ts` | ✅ | B.15 |
| `marketplaceHelpers.ts` | ✅ | B.7 (referenced) |
| `pluginDirectories.ts` | ✅ | C.1 |
| `pluginOptionsStorage.ts` | ✅ | C.2 |
| `mcpbHandler.ts` | ✅ | C.3 |
| `pluginAutoupdate.ts` | ✅ | C.4 |
| `PluginInstallationManager.ts` | ✅ | C.5 |

### Not Read (Non-Critical)

| File | Why Not Read |
|------|-------------|
| `src/commands/plugin/*.tsx` (18 files) | React/ink UI components; Kimi CLI 有自己的 TUI 框架 |
| `fetchTelemetry.ts` | 遥测事件上报，非架构核心 |
| `installCounts.ts` | 安装计数统计 |
| `hintRecommendation.ts`, `lspRecommendation.ts` | 推荐提示逻辑 |
| `pluginIdentifier.ts`, `parseMarketplaceInput.ts` | 小型字符串解析工具 |
| `walkPluginMarkdown.ts` | 文件遍历工具 |
| `performStartupChecks.tsx`, `pluginStartupCheck.ts` | 启动健康检查 |
| `validatePlugin.ts`, `pluginFlagging.ts` | 验证/标记工具 |
| `managedPlugins.ts` | managed scope 的薄包装 |
| `officialMarketplaceStartupCheck.ts` | 官方 marketplace 启动检查 |
| `orphanedPluginFilter.ts` | 孤儿版本过滤 |
| `pluginBlocklist.ts` | blocklist 逻辑 |
| `headlessPluginInstall.ts` | headless 安装专用 |
| `addDirPluginSettings.ts` | `--add-dir` 参数处理 |
| `loadPluginAgents.ts` | agent 加载（与 commands 类似） |
| `loadPluginOutputStyles.ts` | output style 加载 |
| `lspPluginIntegration.ts` | LSP 集成（与 MCP 类似） |
| `zipCacheAdapters.ts` | ZIP 缓存适配器 |
| `services/plugins/pluginCliCommands.ts` | CLI 命令注册 |

---

> **结论**：核心架构模块（~25 个文件，占全部代码量的 ~80% 设计价值）已全部阅读并记录。剩余 ~50 个文件以 UI、遥测、小型工具函数为主，对 Kimi CLI marketplace 的 clean-room 设计参考价值有限。如需继续深挖某个具体领域（如 UI 交互、遥测设计、LSP 集成），可以指定方向继续阅读。


---

# Appendix D: `/plugin` Interactive UI Design

> Complete walkthrough of Claude Code's TUI for plugin/marketplace management.
> This is a React/ink-based terminal UI, but the **interaction patterns, state machines,
> and page flows** are directly portable to Kimi CLI's TUI framework.

---

## D.1 Command Entry & Args (`parseArgs.ts`)

The `/plugin` command supports both interactive (no args) and direct-action modes:

```
/plugin                          → Open interactive menu (4 tabs)
/plugin install                  → Open "Discover" tab
/plugin install plugin@marketplace → Direct install
/plugin install owner/repo       → Install from GitHub repo (marketplace shorthand)
/plugin manage                   → Open "Installed" tab
/plugin uninstall <plugin>       → Direct uninstall
/plugin enable <plugin>          → Direct enable
/plugin disable <plugin>         → Direct disable
/plugin validate <path>          → Validate manifest/directory
/plugin marketplace add <url>    → Add marketplace
/plugin marketplace remove <name> → Remove marketplace
/plugin marketplace update       → Update all marketplaces
/plugin marketplace list         → List configured marketplaces
```

**ParsedCommand type**:
```typescript
type ParsedCommand =
  | { type: 'menu' }
  | { type: 'help' }
  | { type: 'install'; marketplace?: string; plugin?: string }
  | { type: 'manage' }
  | { type: 'uninstall'; plugin?: string }
  | { type: 'enable'; plugin?: string }
  | { type: 'disable'; plugin?: string }
  | { type: 'validate'; path?: string }
  | { type: 'marketplace'; action?: 'add'|'remove'|'update'|'list'; target?: string }
```

---

## D.2 Main Layout — 4 Tabs (`PluginSettings.tsx`)

```
┌─────────────────────────────────────────────────────────────┐
│  Manage Claude Code plugins                                 │
│                                                             │
│  [ Discover ] [ Installed ] [ Marketplaces ] [ Errors ]     │
│                                                             │
│  ⚠ Make sure you trust a plugin before installing...        │
│                                                             │
│  ┌─ Content area (switches by tab) ─────────────────────┐  │
│  │                                                       │  │
│  │  ... (list, details, forms, etc.)                   │  │
│  │                                                       │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ↑/↓ Navigate  ·  Enter Confirm  ·  / Search  ·  q Back    │
└─────────────────────────────────────────────────────────────┘
```

**Tabs**:

| Tab | ID | Purpose |
|-----|-----|---------|
| **Discover** | `discover` | Browse ALL plugins across ALL marketplaces |
| **Installed** | `installed` | Manage installed plugins (enable/disable/uninstall/update/configure) |
| **Marketplaces** | `marketplaces` | Add/remove/update marketplaces |
| **Errors** | `errors` | View plugin loading errors with actionable guidance |

**Trust Warning**: Always shown below tab bar (unless hidden by policy).

---

## D.3 Tab: Discover (`DiscoverPlugins.tsx` + `BrowseMarketplace.tsx`)

### State Machine

```
'marketplace-list' → select marketplace → 'plugin-list' → select plugin → 'plugin-details'
                                                          ↓
                                                   'plugin-options' (if needs config)
```

### DiscoverPlugins (Cross-Marketplace)

- Loads ALL marketplaces with graceful degradation
- Aggregates plugins from all marketplaces into one flat list
- Shows install counts (fetched from telemetry API)
- **Search**: `/` to activate, type to filter by name/description/marketplace
- **Pagination**: Continuous scroll (see `usePagination`)
- **Status indicators**:
  - `✓` = Already installed
  - `⊘` = Blocked by policy
  - Nothing = Available to install

### BrowseMarketplace (Single Marketplace)

- Same structure as Discover but scoped to one marketplace
- Shows `installedCount / totalPlugins` header
- Direct navigation from ManageMarketplaces → "Browse plugins"

### Plugin Details View

```
┌─ Plugin Name ──────────────────────────────────────────────┐
│  by Author · Marketplace: official                          │
│                                                             │
│  Description text...                                        │
│                                                             │
│  > Install                                                  │
│  > Configure (if has userConfig)                            │
│  > View on GitHub                                           │
│  > Back                                                     │
└─────────────────────────────────────────────────────────────┘
```

- **Menu options built dynamically** by `buildPluginDetailsMenuOptions()`
- Options vary based on: installed?, enabled?, has config?, has MCP?

---

## D.4 Tab: Installed (`ManagePlugins.tsx`)

### Unified List

Claude merges **plugins** and **MCP servers** into a single unified list:

```
┌─ Installed Plugins ─────────────────────────────────────────┐
│                                                             │
│  ▶ my-plugin        Plugin · official · ✓ enabled           │
│    └─ my-server     MCP · ✓ connected                       │
│  ▶ another-plugin   Plugin · custom · ⊘ disabled            │
│    └─ server-a      MCP · ✗ failed                          │
│  ▶ ⚠ flagged-plugin Plugin · official · removed             │
│  ▶ ✗ broken-plugin  Plugin · custom · failed to load · 2 errors│
│                                                             │
│  ↑/↓ Navigate  ·  Enter Details  ·  Space Toggle  ·  u Update│
│  c Configure  ·  d Uninstall  ·  / Search                   │
└─────────────────────────────────────────────────────────────┘
```

**UnifiedInstalledItem types** (from `UnifiedInstalledCell.tsx`):

| Type | Visual | States |
|------|--------|--------|
| `plugin` | `[Plugin]` badge | `enabled` ✓ / `disabled` ⊘ / `will-enable` → / `will-disable` → / `errors` ✗ N errors |
| `flagged-plugin` | `[Plugin]` + ⚠ | `removed` |
| `failed-plugin` | `[Plugin]` + ✗ | `failed to load · N errors` |
| `mcp` (top-level) | `[MCP]` | `connected` ✓ / `disabled` ⊘ / `connecting…` ◌ / `Enter to auth` ▲ / `failed` ✗ |
| `mcp` (indented) | `└ [MCP]` | Same as above, indented under parent plugin |

### Plugin Details (ManagePlugins)

```
┌─ my-plugin ─────────────────────────────────────────────────┐
│  Plugin · official · ✓ enabled                              │
│                                                             │
│  > [ ] Disable          (or [x] Enable if disabled)         │
│  > Update (1.0.0 → 1.1.0)                                   │
│  > Configure                                                │
│  > Uninstall                                                │
│  > View data directory (123 KB)                             │
│  > View MCP servers                                         │
│  > Back                                                     │
└─────────────────────────────────────────────────────────────┘
```

**Pending toggles**: Space/Enter on "Enable/Disable" doesn't apply immediately —
it marks `pendingEnable`/`pendingDisable`, shows `→ will enable`/`→ will disable`
in the list, and applies on exit. This allows batching multiple changes before
a `/reload-plugins`.

### View States in ManagePlugins

```typescript
type ViewState =
  | 'plugin-list'           // Main list
  | 'plugin-details'        // Details + action menu
  | 'configuring'           // Generic config screen
  | { type: 'plugin-options'; schema: PluginOptionSchema }
  | 'confirm-project-uninstall'
  | { type: 'confirm-data-cleanup'; size: { bytes, human } }
  | { type: 'flagged-detail'; plugin: FlaggedPluginInfo }
  | { type: 'failed-plugin-details'; plugin: FailedPluginInfo }
  | { type: 'mcp-detail'; client: MCPServerConnection }
  | { type: 'mcp-tools'; client: MCPServerConnection }
  | { type: 'mcp-tool-detail'; client; tool: Tool }
```

---

## D.5 Tab: Marketplaces (`ManageMarketplaces.tsx`)

### List View

```
┌─ Marketplaces ──────────────────────────────────────────────┐
│                                                             │
│  ▶ claude-plugins-official   github:anthropics/...          │
│    12 plugins · 3 installed · auto-update: on               │
│  ▶ my-custom-marketplace     https://example.com/...        │
│    5 plugins · 1 installed · auto-update: off               │
│                                                             │
│  [Add marketplace]                                          │
│                                                             │
│  ↑/↓ Navigate  ·  Enter Details  ·  u Update  ·  r Remove  │
│  a Toggle auto-update                                       │
└─────────────────────────────────────────────────────────────┘
```

### Marketplace Details

```
┌─ claude-plugins-official ───────────────────────────────────┐
│  github:anthropics/claude-plugins-official                  │
│                                                             │
│  > Browse plugins                                           │
│  > Update marketplace (git pull)                            │
│  > Toggle auto-update [x]                                   │
│  > Remove marketplace                                       │
│  > Back                                                     │
└─────────────────────────────────────────────────────────────┘
```

### Add Marketplace (`AddMarketplace.tsx`)

```
┌─ Add Marketplace ───────────────────────────────────────────┐
│                                                             │
│  Enter marketplace source:                                  │
│  > ________________________                                 │
│                                                             │
│  Examples:                                                  │
│    owner/repo         (GitHub shorthand)                    │
│    https://...        (URL to marketplace.json)             │
│    ./path/to/dir      (Local directory)                     │
│                                                             │
│  Enter Confirm  ·  Esc Cancel                               │
└─────────────────────────────────────────────────────────────┘
```

**Input parsing**: `parseMarketplaceInput()` auto-detects:
- `owner/repo` → `github` source
- `https://...` → `url` source
- `file://...` / `./path` → `directory` source

---

## D.6 Tab: Errors

```
┌─ Plugin Errors ─────────────────────────────────────────────┐
│                                                             │
│  ⚠ my-plugin                                               │
│    path-not-found: commands/build.md                        │
│    → Check that the path in your manifest is correct        │
│                                                             │
│  ✗ another-plugin                                           │
│    manifest-validation-error: .claude-plugin/plugin.json    │
│    → Check manifest file follows the required schema        │
│                                                             │
│  ↑/↓ Navigate  ·  Enter for guidance  ·  d Dismiss          │
└─────────────────────────────────────────────────────────────┘
```

**ErrorRowAction**: Each error can have an associated action:
- `navigate` → jump to relevant tab/view
- `remove-extra-marketplace` → remove stale marketplace config
- `remove-installed-marketplace` → remove installed marketplace
- `managed-only` → show "managed by administrator" message
- `none` → display only

---

## D.7 Pagination (`usePagination.ts`)

**Continuous scrolling** (not page-based):

```typescript
const pagination = usePagination({
  totalItems: plugins.length,
  selectedIndex: selectedIndex,  // driven by ↑/↓
  maxVisible: 5,                 // default visible rows
})
```

**Behavior**:
- Selected item always stays visible
- Window auto-scrolls to keep selection in view
- Shows scroll indicator when more items above/below
- `scrollPosition: { current, total, canScrollUp, canScrollDown }`

**Why continuous scroll over pages?**
- Feels more natural in a terminal list
- No "page left/right" keybinding needed
- Selected index is the single source of truth

---

## D.8 Search (`useSearchInput` + `SearchBox`)

```
┌─ Discover Plugins ──────────────────────────────────────────┐
│  /deploy_________________________________________ [Search]  │
│                                                             │
│  ▶ deploy-helper    Plugin · official · ✓ installed         │
│    deploy-script    Plugin · custom                         │
│                                                             │
│  Esc Exit search                                            │
└─────────────────────────────────────────────────────────────┘
```

- `/` activates search mode
- Real-time filtering as user types
- `Esc` exits search, restores full list
- Resets `selectedIndex` to 0 on query change

---

## D.9 Trust Warning (`PluginTrustWarning.tsx`)

Always shown at top of plugin UI:

```
⚠ Make sure you trust a plugin before installing, updating, or using it.
  Anthropic does not control what MCP servers, files, or other software
  are included in plugins and cannot verify that they will work as intended
  or that they won't change. See each plugin's homepage for more information.
```

- Can be customized by enterprise policy via `getPluginTrustMessage()`
- Non-dismissible, always visible

---

## D.10 Options Configuration (`PluginOptionsFlow.tsx` + `PluginOptionsDialog.tsx`)

### Post-Install Config Prompt

When a plugin has `manifest.userConfig` or `.mcpb` channels with `user_config`:

```
┌─ Configure my-plugin ───────────────────────────────────────┐
│  Plugin options                                             │
│                                                             │
│  API Key:                                                   │
│  > ________________________                                 │
│                                                             │
│  Endpoint:                                                  │
│  > https://api.example.com__________                        │
│                                                             │
│  Enter Save  ·  Esc Skip  ·  Tab Next field                 │
└─────────────────────────────────────────────────────────────┘
```

### Security Rules

- **Sensitive fields** (`sensitive: true`):
  - Never pre-populated in dialog
  - Stored in secureStorage (keychain / `.credentials.json`)
  - Not substituted into skill/agent content (model prompt safe)
- **Non-sensitive fields**:
  - Pre-populated with saved values
  - Stored in `settings.json`
- **Reconfigure**: Empty sensitive field + existing saved value = keep existing

### Multi-Step Flow

```typescript
// Steps built at mount:
[
  { key: 'top-level', title: 'Configure Plugin', ... },       // manifest.userConfig
  { key: 'channel:server1', title: 'Configure Server 1', ... }, // MCPB channel 1
  { key: 'channel:server2', title: 'Configure Server 2', ... }, // MCPB channel 2
]
```

Each step is a `PluginOptionsDialog`. After saving one step, auto-advance to next.

---

## D.11 Keyboard Shortcuts Reference

### Global (all tabs)

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate list |
| `Enter` | Confirm / open details |
| `Esc` / `q` | Back / exit |
| `/` | Toggle search |

### Discover / Browse

| Key | Action |
|-----|--------|
| `Enter` on plugin | Open details → Install |
| `i` | Install selected |

### Installed

| Key | Action |
|-----|--------|
| `Space` / `Enter` on enable/disable | Toggle (pending) |
| `u` | Update selected plugin |
| `c` | Configure selected plugin |
| `d` | Uninstall selected plugin |
| `Enter` on plugin | Open details menu |

### Marketplaces

| Key | Action |
|-----|--------|
| `u` | Update marketplace (git pull) |
| `r` | Remove marketplace |
| `a` | Toggle auto-update |
| `Enter` | Open details / browse plugins |

### Search Mode

| Key | Action |
|-----|--------|
| `Esc` | Exit search |
| Any text | Filter list |

---

## D.12 UI State Machine Summary

```
PluginSettings (root)
├── Tab: discover
│   └── DiscoverPlugins
│       ├── 'plugin-list' → 'plugin-details' → install → options?
│       └── Search mode overlay
├── Tab: installed
│   └── ManagePlugins
│       ├── 'plugin-list'
│       ├── 'plugin-details' → enable/disable/update/configure/uninstall
│       ├── 'plugin-options' → configure dialog
│       ├── 'confirm-project-uninstall'
│       ├── 'confirm-data-cleanup'
│       ├── 'flagged-detail'
│       ├── 'failed-plugin-details'
│       └── MCP sub-views (detail, tools, tool-detail)
├── Tab: marketplaces
│   └── ManageMarketplaces
│       ├── 'list' → 'details' → browse/update/toggle/remove
│       └── AddMarketplace (text input)
├── Tab: errors
│   └── Error list with guidance
└── ValidatePlugin (standalone, non-interactive)
```

---

## D.13 Key Design Patterns to Port

1. **Tab-based navigation** — 4 tabs, always visible, immediate switch
2. **Unified list** — Plugins + MCP servers in one scrollable list, visually grouped
3. **Pending actions** — Enable/disable are batched (not applied immediately), shown as "will enable/disable"
4. **Graceful degradation** — Failed marketplaces don't crash the whole UI; shown as warnings
5. **Trust warning always visible** — Non-dismissible security reminder
6. **Search as overlay** — `/` toggles, Esc exits, real-time filter
7. **Continuous scroll pagination** — Selected item always visible, auto-scroll window
8. **Error → Guidance → Action** — Every error has human-readable message + guidance + optional action
9. **Options dialog security** — Sensitive fields never pre-populated, secureStorage first, model-safe substitution
10. **Plugin details menu is dynamic** — Options vary based on plugin state (installed?, enabled?, has config?, has update?)
