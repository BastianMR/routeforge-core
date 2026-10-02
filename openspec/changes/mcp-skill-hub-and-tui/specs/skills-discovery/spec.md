# skills-discovery

## Purpose

Skill discovery loads skills from sources beyond the `routeforge.skills.builtin` Python package. Operators extend the gateway by dropping a `.toml` manifest into a configured plugins directory. Loaded plugins are persisted in SQLite so restarts remember them.

## ADDED Requirements

### Requirement: Plugin manifests

The system MUST support plugin manifests as TOML files in the directory configured by `ROUTE_FORGE_PLUGINS_DIR` (default `~/.routeforge/plugins/`).

#### Scenario: Valid manifest loads a plugin

- **WHEN** a file `~/.routeforge/plugins/web-scrape.toml` exists with
  ```toml
  module = "my_skills.scraper"
  attr = "WebScrapeSkill"
  info = { name = "web-scrape", description = "...", requires_account = true, provider_group = "scrape" }
  ```
- **AND** the Python module `my_skills.scraper` is importable
- **AND** `my_skills.scraper.WebScrapeSkill` is a subclass of `routeforge.skills.base.Skill`
- **THEN** the registry MUST register the skill under name `web-scrape`

#### Scenario: Invalid manifest is rejected

- **WHEN** a manifest is missing required fields (`module`, `attr`, `info.name`)
- **THEN** the system MUST log a warning with the file path and field name, and MUST NOT register the skill

#### Scenario: Import failure marks plugin as disabled

- **WHEN** the manifest references a module that cannot be imported
- **THEN** the system MUST log the failure, write the error message to `plugins.error`, set `enabled=0` in the `plugins` table, and MUST NOT crash

### Requirement: Plugin persistence

Loaded plugins MUST be persisted in the `plugins` SQLite table.

#### Scenario: Restart re-imports enabled plugins

- **WHEN** the gateway starts and the `plugins` table contains rows with `enabled=1`
- **THEN** the registry MUST re-import and re-register each enabled plugin in source-path order

#### Scenario: Restart skips disabled plugins

- **WHEN** the gateway starts and the `plugins` table contains rows with `enabled=0`
- **THEN** the registry MUST NOT attempt to re-import those plugins

#### Scenario: Plugin removal from disk does not auto-unload

- **WHEN** a plugin's source file disappears between restarts
- **THEN** on next startup the system MUST mark the row `enabled=0`, write the error to `plugins.error`, and surface the condition in `routeforge skills list` as `missing_source: true`

### Requirement: Plugin install

The CLI MUST support `routeforge plugins install <github-url>` to clone a git repository into the plugins directory.

#### Scenario: Successful install

- **WHEN** the user runs `routeforge plugins install https://github.com/me/my-skills`
- **THEN** the system MUST clone the repo into `~/.routeforge/plugins/my-skills/`, scan the new directory for manifests, register discovered plugins, and print a summary

#### Scenario: Install without git available

- **WHEN** `git` is not on `PATH`
- **THEN** the system MUST exit with a clear error message and a non-zero exit code

### Requirement: Plugin listing

The CLI MUST support `routeforge plugins list` to show every known plugin with its source, module path, enabled flag, and last loaded timestamp.

#### Scenario: List output

- **WHEN** the user runs `routeforge plugins list`
- **THEN** the output MUST be a table with columns: `name`, `source`, `module`, `enabled`, `loaded_at`, and an optional `error` column when `enabled=0`

### Requirement: Security boundary

Plugins execute arbitrary Python code. The system MUST treat them as trusted local code and MUST NOT auto-execute anything fetched from the network without an explicit install command.

#### Scenario: No network calls during discovery

- **WHEN** the gateway starts and scans `~/.routeforge/plugins/`
- **THEN** the system MUST NOT make network requests

#### Scenario: Install requires explicit URL

- **WHEN** the user runs `routeforge plugins install <url>`
- **THEN** the system MUST echo the URL and require a `--yes` flag (or interactive confirmation) before cloning
