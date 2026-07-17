# Mentat Data Layout Contract

Status: Milestone 1A contract approved

This document defines where Mentat-owned state belongs for the public beta. It
is a contract-only milestone: it does not change the current runtime default,
move operator data, add a dependency, or implement initialization, migration,
backup, restore, or installer behavior. Those changes begin in Milestone 1B and
must preserve this boundary.

## Principles

1. Application files and immutable packaged seeds are not operator storage.
2. Durable operator state, durable private state, ephemeral runtime state,
   backups, caches, logs, and installed-app configuration have separate classes.
3. An upgrade must not overwrite operator state or require writing inside an
   installed package or Git checkout.
4. Explicit development/operator overrides remain supported.
5. Migrations and restores preview exact effects, validate before mutation, and
   fail closed on conflicts or unsupported schema versions.
6. Secrets use owner-only storage and never enter browser or ordinary
   diagnostic/backup flows.
7. Hermes, Obsidian, Google, and browser-owned state remains outside Mentat's
   data-root authority.

## Target root

`<data-root>` is one platform-aware, operator-writable directory. The target
layout is:

| Target | Class and policy | Ordinary backup policy |
| --- | --- | --- |
| `<data-root>/*.json` | Durable project-owned operator state. After legacy preflight, each missing file is initialized from its corresponding immutable packaged seed. | Included. |
| `<data-root>/private/` | Durable private state, including Console history, SQLite metadata, content-addressed blobs, and the future remote Hermes endpoint and API credential. Owner-only permissions are required where the platform supports them. | The consistent Console set is included; credentials and connection secrets are excluded. |
| `<data-root>/runtime/` | Ephemeral process state, uploads, input/export directories, and snapshots. It is private and may be reconciled or collected. | Excluded. |
| `<data-root>/backups/` | Validated, versioned migration or operator backups. Backups are created only through bounded workflows and are not runtime scratch space. | Excluded to prevent recursive backups. |
| `<data-root>/cache/` | Rebuildable state. Deletion may reduce performance but must not destroy operator work. | Excluded. |
| `<data-root>/logs/` | Bounded, secret-free local logs if local logging is later enabled. Telemetry and analytics remain absent by default. | Excluded. |
| `<data-root>/config/` | Owner-controlled installed-app configuration that is safe to separate from secrets. Machine-specific source-checkout overrides remain supported during development. | Included when non-secret and schema-supported. |

No target directory is authorized to contain a direct copy of Hermes core
files, an Obsidian vault, Google credentials, or arbitrary files named by the
browser.

## Platform defaults and override precedence

When no explicit data-root override exists, the resolver implemented in
Milestone 1B must use:

| Platform | Default data root | Support level |
| --- | --- | --- |
| macOS | `~/Library/Application Support/Mentat` | Tier one |
| Windows | `%LOCALAPPDATA%\Mentat` | Tier one |
| Linux | `$XDG_DATA_HOME/Mentat` when `XDG_DATA_HOME` is valid and non-empty; otherwise `~/.local/share/Mentat` | Preview |

The exact precedence is `--data-dir` → `MENTAT_DATA_DIR` →
`[paths].data_dir` in TOML → platform default. Relative TOML paths continue to
resolve from the file that declares them. An explicit extra config file may
participate at the existing TOML configuration layer, but it does not outrank
CLI or environment values.

Linux XDG base selection occurs inside the lowest-priority platform-default
layer; it does not outrank a Mentat-specific override. During the compatibility
window, `AGENT_OS_DATA_DIR` remains a legacy alias within the environment layer,
and `MENTAT_DATA_DIR` outranks `AGENT_OS_DATA_DIR`. An invalid, relative, or
empty `XDG_DATA_HOME` does not become the base; the resolver uses the documented
fallback instead.

The shared source-checkout `mentat.toml` may keep its current `data_dir =
"data"` development override until Milestone 1B deliberately changes runtime
behavior. Installed distributions must not ship that override as their default.

## Immutable packaged seeds and durable JSON

The repository's tracked `data/*.json` files are immutable, public-safe seed
inputs. They are not live operator storage in an installed app. The complete
current seed set is:

- `agent_messages.json`
- `agents.json`
- `attention.json`
- `calendar.json`
- `context_packs.json`
- `dashboard.json`
- `email.json`
- `projects.json`
- `tasks.json`

At the target root, files with those names are durable operator copies. The
initializer must copy a packaged seed only when its destination is missing. It
must never overwrite an existing operator file, even when a packaged seed has
changed. An existing invalid or unsupported file is an error to report, not
permission to replace it. New default records require a versioned migration or
an explicit merge rule; silently recopying a seed is forbidden.

The server's allowlisted JSON mutation boundary still applies. Listing a file
as a seed does not make every file browser-writable.

## Current mutable-path inventory and target mapping

Milestone 1A records current locations so later slices cannot move only the
obvious files and strand private or ephemeral state.

### Durable project-owned JSON

The current live source-checkout uses the nine tracked `data/*.json` files
listed above. In an installed layout, their operator copies belong directly
under `<data-root>` and the packaged copies remain read-only seeds.

### Durable private state

| Current surface | Target class | Notes |
| --- | --- | --- |
| `data/runtime/agent-console-runs.json` | `<data-root>/private/` | Redacted retained Console history; durable according to its retention policy. |
| `data/runtime/mentat.sqlite3` plus its WAL/SHM files | `<data-root>/private/` | Attachment, blob, and run-reference metadata with schema-version checks. |
| `data/runtime/blobs/sha256/` | `<data-root>/private/` | Content-addressed attachment/artifact bytes protected by references and grace periods. |
| Future remote connection selection and credential | `<data-root>/private/` | Server-only, owner-only, and excluded from ordinary backups and diagnostics. |

The private class is durable but not public. Paths, storage keys, hashes,
credentials, and private file bytes remain server-side and must not become
ordinary browser metadata.

### Ephemeral runtime state

| Current surface | Target class | Notes |
| --- | --- | --- |
| `data/runtime/server-state.json` | `<data-root>/runtime/` | PID and lifecycle state; validated before use and safe to recreate. |
| `data/runtime/uploads/` | `<data-root>/runtime/` | Staged upload scratch governed by attachment validation and expiry. |
| `data/runtime/agent-console-exports/` | `<data-root>/runtime/` | Run-owned assistant export discovery directories. |
| `data/runtime/agent-console-inputs/` | `<data-root>/runtime/` | Private, run-scoped extension-bearing input snapshots. |
| `data/runtime/artifact-snapshots/` | `<data-root>/runtime/` | Temporary no-follow artifact snapshots. |
| `data/runtime/workspace-snapshots/` | `<data-root>/runtime/` | Temporary validated workspace snapshots. |

Runtime cleanup must remain bounded, reference-aware where applicable, and
safe against symlinks. An ordinary backup must not rely on these paths.

### Backups, migrations, caches, and development output

| Current surface | Target class | Notes |
| --- | --- | --- |
| `data/runtime/migrations/` | `<data-root>/backups/` | Existing rename-migration backups move conceptually to the validated backup class. |
| `data/runtime/browser-smoke-profile/` | `<data-root>/cache/` or an isolated test-temporary root | Rebuildable browser automation profile; never operator data. |
| Browser-smoke screenshots under `data/runtime/` | Test artifact outside durable operator state | Generated evidence must remain gitignored and contain no private operator data. |

There is no general cache directory today and no bounded persistent log file is
enabled today. Their target classes are reserved so later features do not put
rebuildable or diagnostic state beside durable data.

### Machine-local configuration

The source checkout currently supports tracked `mentat.toml` plus gitignored
`mentat.local.toml`, `mentat.local.env`, and the generated Windows helper
`mentat.local.env.bat`. The compatibility loader also reads legacy
`agent-os.toml`, `agent-os.local.toml`, and `AGENT_OS_*` environment aliases,
including `AGENT_OS_DATA_DIR`. Within their existing layers, Mentat-named files
and variables outrank legacy aliases: the file order is legacy shared, Mentat
shared, legacy local, Mentat local, then an explicit extra config; and
`MENTAT_DATA_DIR` outranks `AGENT_OS_DATA_DIR`. Milestone 1B must preserve these
inputs during a documented deprecation/migration window rather than silently
stranding an operator override.

Environment variables and CLI flags are process inputs, not data-root files.
Installed-app non-secret settings belong in `<data-root>/config/`; secrets
belong in `<data-root>/private/`. Repository-local overrides remain a supported
development mechanism, but installers must not require writes into their
application directory.

### Browser-owned state

The following state is outside the data root and is scoped to the browser
profile/origin:

- `mentat-theme`: selected visual theme;
- `mentat-reminder:<task>:<reminder>:<at>`: local reminder-delivery
  deduplication;
- `mentat-agent-pulse-dismissed-v1`: local dismissal state; and
- browser notification permission: browser/OS-owned permission requested only
  by an explicit operator action.

Browser storage is advisory UI state. It is not authoritative operator data,
is not included in Mentat backups, and must not contain credentials, private
paths, attachment identifiers that grant access, or Hermes secrets.

### External state

The following surfaces stay outside Mentat's data root and mutation authority:

- Hermes core files such as `~/.hermes/state.db`, `~/.hermes/cron/jobs.json`,
  `~/.hermes/config.yaml`, and `~/.hermes/skills/`;
- the configured Obsidian vault and its Markdown notes;
- Google Calendar events and Hermes-owned Google authentication/token state;
  and
- browser profiles, notification permission, and OS credential facilities.

Approved fixed Hermes adapter operations remain governed by
[ARCHITECTURE.md](ARCHITECTURE.md); this data layout never authorizes direct
file writes or copying external secrets into Mentat.

## Initialization contract

Milestone 1B initialization must:

1. resolve one data root using the approved precedence;
2. detect supported legacy state before copying any packaged seed;
3. when legacy state exists, leave every potentially colliding destination
   absent and return a migration-required result instead of manufacturing a
   clean seeded destination;
4. create required directories with owner-only permissions where supported;
5. reject a symlink or unsafe non-directory at a required private boundary;
6. copy a packaged seed only when its destination is missing and no legacy
   reservation applies;
7. validate each existing or newly copied document before startup uses it;
8. avoid dirtying the package, installation, or Git checkout; and
9. leave an interrupted temporary copy distinguishable and safe to reconcile.

Legacy detection and destination reservation occur before any durable JSON
initialization. A source-checkout operator who explicitly keeps the repo-local
data override may continue using it; selecting the new platform root must not
silently hide legacy work behind fresh seeds. A later migration slice may define
a provenance-verified pristine-seed replacement rule, but only with exact
preview, backup, confirmation, locked revalidation, and destination verification.

Repeat startup is idempotent. It does not refresh, merge, or normalize existing
operator files merely because the packaged seed differs.

## Migration and schema contract

A legacy repo-local migration must be an explicit, locked workflow. Before any
mutation it must produce an exact migration preview that lists every source,
destination, classification, schema version, conflict, and excluded item.

The migration must:

1. validate source containment, file type, schema, and privacy class;
2. refuse source or destination conflicts rather than choosing a winner;
3. create and validate a validated pre-migration backup before changing the
   source or destination;
4. bind confirmation to the preview and revalidate under the migration lock;
5. copy to private same-filesystem temporary paths and use atomic replacement
   where implemented;
6. verify destination content and schema before reporting success;
7. preserve the legacy source until verification and documented cleanup; and
8. report partial failure without claiming completion when verification or
   rollback is incomplete.

Every durable data set has a supported schema version, even when an individual
legacy JSON file currently has no embedded version field. Migration code owns
the mapping from legacy state to the current schema. Mentat must refuse a newer
unsupported schema version and must not attempt a best-effort downgrade.
Applied version steps are ordered, idempotent, and recorded without secrets.

Interrupted migration startup must detect reservations or temporary state,
verify what happened, and either safely resume an explicitly supported step or
fail closed with recovery instructions. It must not infer success from a
partially populated destination.

## Backup and restore contract

Backups are versioned, bounded, validated snapshots written below
`<data-root>/backups/` or to an explicitly selected safe destination. Creating
a backup does not mutate the source. A successful backup includes a manifest,
Mentat/data schema versions, classifications, and integrity metadata without
absolute private paths or secrets.

Every target class has this explicit ordinary-backup policy:

- durable operator JSON is included;
- the durable private Console set is included as one consistency unit: a
  WAL-safe SQLite snapshot, retained Console history, and all referenced blobs
  are captured under a shared lock or equivalent consistency boundary;
- ephemeral runtime state is excluded;
- backup files are excluded so backups never recurse;
- cache state is excluded because it is rebuildable;
- local logs are excluded; and
- non-secret installed-app configuration is included when its schema is
  supported.

The Console consistency unit must not capture a live SQLite file with unmatched
WAL/SHM state or copy the database, history, and blobs at unrelated points in
time. Staged/unreferenced scratch is excluded. The future remote Hermes endpoint
and API credential, tokens, and other credentials are excluded from ordinary
backups even though their private storage is durable. A future secret-aware
export would require a separately approved encrypted design.

Restore requires a restore preview, destination validation, conflict reporting,
a pre-restore recovery backup, confirmation bound to the preview, locked atomic
replacement, and post-restore schema/integrity verification. A newer unsupported
backup fails closed. Runtime scratch, caches, logs, browser storage, and external
Hermes/Obsidian/Google state are not restored as operator data.

## Secret and privacy boundary

Private directories and files use owner-only permissions where supported. The
initializer must establish and perform read-back verification of owner-only
access before any private or secret-bearing content is written. If enforcement
or verification fails on a platform/filesystem that claims this support, the
private boundary fails closed: Mentat does not write Console content or a remote
credential there, and reports a bounded error without paths or private content.
On an unsupported filesystem, privacy-dependent features remain unavailable
until an approved secure boundary exists; the implementation must not silently
degrade to broader access.
The future remote Hermes endpoint and API credential remain server-side and are
excluded from browser payloads, browser storage, tracked files, logs,
diagnostics, crash text, ordinary backups, and test fixtures. Error messages and
audit records may contain only bounded, normalized, secret-free identifiers.

Tracked seeds and documentation remain public-safe. They must not contain real
operator names, local paths, account identifiers, tokens, private messages, or
runtime history.

## Implementation sequence

- Milestone 1A (this slice): canonical inventory and tested contract only.
- Milestone 1B: platform-aware resolver, installed/source-checkout configuration
  behavior, owner-only directory creation, and missing-only initialization.
- Later bounded slices: legacy migration, schema evolution, backup/restore, and
  installer/uninstall preservation, each with its own approved contract and
  failure-path evidence.

Until Milestone 1B lands, the source checkout continues using the current
repo-local `data/` default. Documentation must describe that as current behavior,
not as the installed public-beta layout.
