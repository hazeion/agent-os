# Mentat data layout contract

Status: current-only storage, updated October 19, 2026

The supported boundary is fresh/current SQLite schema 46, backup format 5 and
restore protocol 4. Older, future, malformed or unsafe storage fails closed
without conversion, deletion or overwriting operator data. The owner chose
this boundary in [ADR0002](docs/adr/0002-current-only-storage.md). Historical
Milestone 1 migration and old-format restore records describe retired behavior.

## Principles

Application files and immutable packaged seeds are separate from operator
storage. Durable JSON, private Console state, runtime scratch, backups, cache,
logs and configuration have distinct policies. Application replacement must
preserve current operator data; an older database is never upgraded implicitly.
Current restore remains previewed, confirmation-bound, validated and locked.
Hermes, Obsidian, Google and browser-owned state stay outside Mentat authority.

## Target root

`<data-root>` is the configured operator-writable directory.

| Target | Class and policy | Ordinary backup policy |
| --- | --- | --- |
| `<data-root>/*.json` | Fixed durable operator JSON inventory; packaged copies are public-safe seeds. | Included. |
| `<data-root>/private/` | Owner-private Console SQLite, referenced blobs and separate private connection metadata. | Console consistency unit included; credentials and remote connection definitions excluded. |
| `<data-root>/runtime/` | Ephemeral process state, uploads, input/export directories and snapshots. | Excluded. |
| `<data-root>/backups/` | Validated current archives and current recovery evidence. | Excluded to prevent recursive backups. |
| `<data-root>/cache/` | Rebuildable state. | Excluded. |
| `<data-root>/logs/` | Bounded, secret-free local logs. | Excluded. |
| `<data-root>/config/` | Non-secret installed-app configuration. | Included when fixed-inventory and supported. |

No class authorizes copying Hermes core files, an Obsidian vault, Google
credentials or arbitrary browser-named files into Mentat.

## Platform defaults and override precedence

When no explicit data-root override exists, the read-only resolver implemented
uses:

| Platform | Default data root | Support level |
| --- | --- | --- |
| macOS | `~/Library/Application Support/Mentat` | Tier one |
| Windows | `%LOCALAPPDATA%\Mentat` | Tier one |
| Linux | `$XDG_DATA_HOME/Mentat` when `XDG_DATA_HOME` is valid and non-empty; otherwise `~/.local/share/Mentat` | Preview |

The exact precedence is `--data-dir` → `MENTAT_DATA_DIR` →
`AGENT_OS_DATA_DIR` → `[paths].data_dir` in TOML → platform default. Relative
TOML paths continue to resolve from the file that declares them. An explicit
extra config file may participate at the existing TOML configuration layer,
but it does not outrank CLI or environment values.

Linux XDG base selection occurs inside the lowest-priority platform-default
layer; it does not outrank a Mentat-specific override. During the compatibility
window, `AGENT_OS_DATA_DIR` remains a legacy alias within the environment layer,
and `MENTAT_DATA_DIR` outranks `AGENT_OS_DATA_DIR`. An invalid, relative, or
empty `XDG_DATA_HOME` does not become the base; the resolver uses the documented
fallback instead.

The shared source-checkout `mentat.toml` keeps its explicit `data_dir = "data"`
development override. This storage cleanup does not change that default. A config-less load now selects the platform default
without creating it. Installed distributions must not ship the source-checkout
override as their default.

## Immutable packaged seeds and durable JSON

Tracked `data/*.json` files are immutable, public-safe packaged inputs. The
complete inventory is:

- `agent_messages.json`
- `agents.json`
- `attention.json`
- `calendar.json`
- `context_packs.json`
- `dashboard.json`
- `email.json`
- `projects.json`
- `tasks.json`

The initializer must copy a packaged seed only when its destination is missing
in an admitted fresh initialization. It must never overwrite an existing
operator file. Unsupported or invalid existing documents are errors, not
permission to recopy seeds. A current root with missing durable documents is
not repaired from defaults. Browser mutation stays within the existing named
JSON allowlist; being a seed does not grant browser write authority.

## Current private authority

`<data-root>/private/console/mentat.sqlite3` owns canonical Agents, private
runtime bindings, provider settings, Projects, Tasks, Conversations, Runs,
AgentEvents, dispatch and workflow evidence. It must have the exact current
schema and complete structural journal 1 through 46. Those rows describe the
current format; they do not implement older-root upgrades. Fresh initialization
preserves random approval/confirmation epochs and separate authority receipts.
Existing current rows retain all semantic, foreign-key, retention and receipt
checks. Unknown external outcomes never retry automatically.

Fresh Task and Project setup may consume the exact packaged/root seed documents
once and commit rows with their authority receipts. After those receipts exist,
SQLite is the sole live authority; stale `tasks.json` and `projects.json` are
never synchronized or used as fallback. Run initialization claims an empty
current Run store; nonempty JSON history is not imported. Existing SQL Run
authority ignores stale history. Backup derives its bounded history projection
from canonical SQL and validates it against that snapshot.

Referenced attachment/artifact bytes belong in
`<data-root>/private/console/blobs/sha256/`. They remain content-addressed,
private, reference-aware and subject to active-Run and grace protections.
Retired `agent-registry.sqlite3`, runtime SQLite/history/blob layouts and old
migration artifacts are not convergence or recovery inputs. Presence checks may
refuse unsupported storage; no path reads old registry bytes or falls back to it.
Current Agent authority and its private binding remain embedded in SQLite.

Remote connection selection stays in
`<data-root>/private/remote-hermes-connection-v1.json`, with validated mode,
endpoint metadata, binding and credential-source reference. Credential values
remain outside browser payloads and ordinary backup. Setup uses an operator
credential source, not an old embedded-credential conversion workflow.

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

### Backup, cache and development output

Current archives belong below `<data-root>/backups/`. Old migration artifacts
are unsupported historical files, not live authority or current recovery input.
`data/runtime/browser-smoke-profile/` and smoke screenshots are disposable test
evidence. Keep them in cache or isolated temporary storage, never durable
operator state or ordinary backups. Local logs remain bounded and secret-free.

### Machine-local configuration

The source checkout currently supports tracked `mentat.toml` plus gitignored
`mentat.local.toml`, `mentat.local.env`, and the generated Windows helper
`mentat.local.env.bat`. The compatibility loader also reads legacy
`agent-os.toml`, `agent-os.local.toml`, and `AGENT_OS_*` environment aliases,
including `AGENT_OS_DATA_DIR`. Within their existing layers, Mentat-named files
and variables outrank legacy aliases: the file order is legacy shared, Mentat
shared, legacy local, Mentat local, then an explicit extra config; and
`MENTAT_DATA_DIR` outranks `AGENT_OS_DATA_DIR`. These configuration aliases remain supported. Retiring older storage formats
does not remove explicit operator overrides.

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

## Initialization and read-only admission

Path/config resolution is read-only; `--print-config` uses only this read-only path. Fixed JSON documents
must have the expected list/object type and be no larger than 16 MiB. Component
checks reject symlinks and Windows reparse points; descriptor reads preserve the
configured lexical root and normalize only trusted macOS system aliases.

Startup inspects current SQLite and document format before directory hardening,
locks, seed copying, writable SQLite, WAL setup or lifecycle cleanup. An older,
future or malformed root is refused unchanged. Missing storage may initialize;
existing legacy documents/private layouts are not inferred to be fresh. The
explicit packaged-seed development override remains supported.

Fresh initialization creates required owner-only directory classes under one
cross-process lock, records its owned fresh reservation and copies only missing
seeds. Each bounded no-follow seed is written and synced beside its destination,
then published through an atomic hard-link operation that fails if the
destination appeared. Exact owned interrupted initialization states may be
reconciled under the pinned lock. The complete document inventory, current
manifest and root identity verify before the fresh reservation is removed.
Ordinary startup never refreshes existing files because packaged seeds changed.

The data root must not overlap the packaged-seed tree except for the explicit
exact development override. POSIX operations pin directory descriptors; Windows
pins no-reparse, non-delete-sharing handle chains. No source path replacement,
ancestor redirect or raced destination may claim success. Private locks validate
current/fresh storage before creating or hardening their lock hierarchy.

Current schema admission uses a bounded owned-copy main/WAL snapshot without
source SHM writes. It permits later WAL appends and sidecar turnover after a
coherent capture; unsafe primary identity or a changed captured prefix refuses.
This is format admission, not archival consistency. The writable connection
revalidates exact current state before WAL setup. No schema-upgrade or legacy
migration command is available.

## Backup and restore contract

Only `mentat-backup-v5-<id>.zip` archives and restore protocol 4 are supported.
Older/future archive versions and older/incomplete restore reservations are
refused before source mutation. A current archive contains canonical manifest,
the nine fixed durable JSON documents and one validated private Console set:
current SQLite, SQL-derived retained Console history and exactly referenced
ready blobs. The unit has history bytes, database bytes and blobs; there is no
standalone registry member. Current schema/receipt/row and foreign-key integrity
must verify before backup or restore can succeed.

Every target class has an explicit backup policy:

- durable operator JSON is included;
- the durable private Console set is one consistency unit: a
  WAL-safe SQLite snapshot, retained Console history and all referenced blobs
  captured under a
  shared lock or equivalent consistency boundary;
- ephemeral runtime state, backup files, cache state and local logs are excluded;
- non-secret installed-app configuration is included only when supported; and
- remote connection definitions, credentials, browser storage and external state
  remain excluded.

Capture never copies a live database alongside unrelated WAL/SHM or blobs.
Staged/unreferenced scratch is excluded. Retained attachment admission remains
capped at 100 distinct ready blobs and 24 MiB of referenced bytes. The private
unit's current size, count and schema bounds remain enforced. The manifest and
browser summaries contain no private absolute paths or secret values.

Restore preview is read-only and binds the exact archive and destination bytes
and identities. Confirmation revalidates under the pinned root lock, publishes
verified pre-restore recovery evidence and records an owner-private reservation
before exact atomic replacement. Private restore stages and exchanges the
complete Console directory, keeps the previous set until verification, rotates
restored authority/approval epochs and sanitizes current ephemeral authentication
and execution state. It never resumes work, reconstructs a lost token or repeats
an uncertain external operation. Unknown/spent capacity evidence remains durable.

Only exact recognized current old/new/staged interruption states may resume.
Unknown state, malformed evidence or partial verification fails closed. An exact
owned uncommitted temporary requires its separate preview/confirmation cleanup;
startup blocks incomplete restore state. Application-only uninstall or
replacement preserves the external current data root, not older-format support.

```bash
mentat backup --data-dir "/path/to/mentat-data"
mentat restore --data-dir "/path/to/mentat-data" "/path/to/mentat-backup-v5-ID.zip"
mentat restore --data-dir "/path/to/mentat-data" "/path/to/mentat-backup-v5-ID.zip" --confirm TOKEN_FROM_PREVIEW
```

### Current Task recovery export

`mentat task-export` previews an offline SQLite-to-JSON recovery action.
Confirmation binds the authoritative current export and destination identity,
refuses an active server, atomically replaces only `tasks.json` and verifies the
exact bytes. It adds or strips no optional newline at the shared document limit.
A post-write failure is partial, not success or a no-write result. Live Task
paths continue using SQLite. This export is not a complete older-build data
root: `--compatible-root`, schema5 sibling export and downgrade/import commands
are retired.

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
The remote Hermes endpoint and API credential remain server-side. Setup and CLI
accept only endpoint metadata plus a credential-source reference; the API-key
value is read from the selected environment variable or owner-only env file and
is never accepted in browser requests. Mentat never returns either private
endpoint or credential data in browser payloads sourced from stored state or
upstream responses. They
are excluded from browser storage, tracked files, logs, diagnostics, crash
text, ordinary backups, and test fixtures. Error messages and audit records may
contain only bounded, normalized, secret-free identifiers.

Tracked seeds and documentation remain public-safe. They must not contain real
operator names, local paths, account identifiers, tokens, private messages, or
runtime history.
