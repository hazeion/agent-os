# Mentat Data Layout Contract

Status: Milestone 1 durable-data boundary complete through 1F upgrade/uninstall preservation coverage

This document defines where Mentat-owned state belongs for the public beta. It
began as the contract-only Milestone 1A. Milestone 1B implements deterministic
path resolution, bounded read-only preflight, owner-only directory creation,
and missing-only packaged-seed initialization. Milestone 1C implements an
explicit, previewed, migration-specific-backup workflow for the nine durable
JSON documents. It does not change the source-checkout runtime default, move
private/runtime data, add a dependency, or implement general restore or
installer behavior. Milestone 1D versions those unchanged JSON shapes through
one sidecar manifest and explicit bootstrap migration. Milestone 1E-A adds the
first general backup/restore format for that same fixed durable JSON set.
Milestone 1E-B adds the durable private Console move, exact legacy migration,
and WAL-safe retained history/SQLite/referenced-blob consistency unit.
Milestone 1F proves that versioned application replacement and application-only
uninstall/reinstall preserve that external durable boundary without choosing an
installer format.

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
| `<data-root>/private/` | Durable private state, including Console history, SQLite metadata, content-addressed blobs, and the remote Hermes connection selection/API credential. Owner-only permissions are required where the platform supports them. | The consistent Console set is included; credentials and connection secrets are excluded. |
| `<data-root>/runtime/` | Ephemeral process state, uploads, input/export directories, and snapshots. It is private and may be reconciled or collected. | Excluded. |
| `<data-root>/backups/` | Validated, versioned migration or operator backups. Backups are created only through bounded workflows and are not runtime scratch space. | Excluded to prevent recursive backups. |
| `<data-root>/cache/` | Rebuildable state. Deletion may reduce performance but must not destroy operator work. | Excluded. |
| `<data-root>/logs/` | Bounded, secret-free local logs if local logging is later enabled. Telemetry and analytics remain absent by default. | Excluded. |
| `<data-root>/config/` | Owner-controlled installed-app configuration that is safe to separate from secrets. Machine-specific source-checkout overrides remain supported during development. | Included when non-secret and schema-supported. |

No target directory is authorized to contain a direct copy of Hermes core
files, an Obsidian vault, Google credentials, or arbitrary files named by the
browser.

## Platform defaults and override precedence

When no explicit data-root override exists, the read-only resolver implemented
in Milestone 1B-A uses:

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

The shared source-checkout `mentat.toml` keeps its current `data_dir = "data"`
development override until a later writable Milestone 1 slice deliberately
changes runtime behavior. A config-less load now selects the platform default
without creating it. Installed distributions must not ship the source-checkout
override as their default.

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
| Legacy `data/runtime/agent-console-runs.json` | `<data-root>/private/console/agent-console-runs.json` | Redacted retained Console history; durable according to its retention policy. |
| Legacy `data/runtime/mentat.sqlite3` plus WAL/SHM | `<data-root>/private/console/mentat.sqlite3` | Attachment, blob, and run-reference metadata; live WAL/SHM remain SQLite-owned beside the database. |
| Legacy `data/runtime/blobs/sha256/` | `<data-root>/private/console/blobs/sha256/` | Content-addressed attachment/artifact bytes protected by references and grace periods. |
| Remote connection selection and credential | `<data-root>/private/remote-hermes-connection-v1.json` | Versioned, server-only, owner-only, atomically replaced, and excluded from ordinary backups and diagnostics. A missing record means local mode. |

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

Milestone 1B-A implements the read-only portion of this contract: it resolves
one root, validates the fixed nine-file seed inventory, and reports existing,
initialization-ready, migration-required, conflict, development-override, or
unsafe states. Known documents must be regular, have the expected current
top-level list/object shape, and be no larger than 16 MiB. Component checks
reject symlinks and Windows reparse points; POSIX file reads use no-follow
descriptor walking after normalizing only the standard macOS system aliases.
It neither creates nor modifies filesystem entries. `--print-config` uses only
this read-only path and remains side-effect-free.

Milestone 1B-B implements the writable initialization portion. A config-less
installed launch now initializes before lifecycle cleanup, Console
reconciliation, or runtime-state writes. A source checkout that keeps the
tracked `data_dir = "data"` override remains a no-op development layout. If a
source checkout explicitly selects the platform default, its repo-local data is
reserved as legacy state and startup fails closed for the later migration
workflow instead of hiding it behind fresh seeds.

The initializer:

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

Execution uses a persistent owner-only `.mentat-initialization.lock`, repeats
the complete preflight after acquiring the operating-system file lock, and
creates the six approved directory classes with owner-only POSIX modes. Each
missing seed is read through the bounded no-follow boundary, written and synced
to a same-directory `.<name>.mentat-init-<nonce>.tmp`, then published with an
atomic hard-link operation that fails if the destination appeared. The
temporary link is removed after success or an ordinary caught failure. A
process interruption may leave the distinctly named temporary file; fixed-name
preflight ignores it and a repeat run can safely complete the missing seed.

The target must not be an ancestor or descendant of the packaged seed root;
exact equality is the only development no-op. Existing filesystem identity and
conservative Darwin case-folding and Unicode normalization prevent an aliased
macOS override from bypassing that rule. Nearest existing ancestors are also
walked and compared by filesystem identity before an existing alias or missing
suffix is accepted. Only proven filesystem identity or exact native path
equality establishes the development no-op; conservative aliases otherwise
fail closed as overlap.
Existing lock files must be
single-link regular files owned by the current POSIX operator before Mentat
changes their mode or writes a Windows lock byte. Windows initialization pins
every data-root component with non-delete-sharing, no-reparse handles while
opening the lock and temporary files with final-component reparse protection;
this prevents a junction substitution from redirecting the write boundary.
Windows lock contention uses an explicit bounded 120-second wait instead of
the CRT's shorter implicit retry window.

On Windows, no-reparse, non-delete-sharing handle chains also pin the packaged
seed root and any distinct existing legacy root from the first preflight
through seed reads and final verification. The seed-file open still protects
its final component. Directory guards request only traverse and read-attributes
access—never directory-list access—so Windows enforces the omitted
delete-sharing permission against rename as well as deletion without rejecting
a traverse-only ancestor. A junction or directory substitution therefore
cannot redirect a validated packaged read between inspection and copying.

Legacy detection and destination reservation occur before any ordinary durable
JSON initialization. A source-checkout operator who explicitly keeps the repo-local
data override may continue using it; selecting the new platform root must not
silently hide legacy work behind fresh seeds. A later schema or merge slice may
define additional provenance or merge rules, but only with exact preview, backup,
confirmation, locked revalidation, and destination verification.

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

Milestone 1C implements that migration contract for the fixed nine-file,
currently unversioned JSON inventory only. Its public preview names every
document, whether the source is legacy or a packaged-seed fallback, the
destination filename, the `durable_operator` classification, the
`unversioned-json-v1` schema label, the action, and the excluded private runtime
class. It deliberately returns no filesystem paths, file content, hashes, or
backup names. The opaque token binds the exact roots, source bytes,
classifications, exclusions, expected-empty initial destination, and protocol
version. Root binding uses exact normalized absolute spellings, not a
case-folded overlap key. Legacy and packaged-fallback source snapshots require
single-link regular files so a hard link cannot import bytes from outside the
selected roots.

Execution shares the initialization lock and repeats the full preview after
locking. It durably publishes and validates a versioned ZIP under `backups/`
before publishing the first destination, records a fixed reservation under
`config/`, copies only to missing destinations, verifies every byte, preserves
the legacy source, and writes a completion receipt last. A matching interrupted
reservation can resume verified copies; a changed source, backup, reservation,
partial destination, linked control, or raced operator destination fails
closed. Ordinary startup suppresses legacy detection only when the receipt and
immutable backup evidence verify and every live destination remains a safe,
owner-only document with the supported top-level shape. Later legitimate task,
project, setting, and Context Pack mutations do not invalidate the receipt.
Those atomic writes establish the replacement file's mode before commit. A
process interruption may leave an exact per-document writer temporary; a
completed receipt ignores it only when it remains bounded, owner-only,
single-link, and regular, while lookalikes or unsafe entries fail closed.
Receipt recognition runs under the shared initialization lock and a pinned
target identity; a substituted path fails closed and is never seed-initialized.
After validating the receipt, startup also establishes or revalidates the data
root and all six required directory boundaries while the root remains pinned:
missing directories are created, broad POSIX modes are tightened where
supported, and files, symbolic links, or reparse points fail closed. The root
identity and receipt are checked again before startup accepts completion.
An incomplete reservation, promoted backup, or exact migration temporary blocks
startup for every selected data-root source until the operator re-runs preview.

The migration is an explicit CLI operation and never runs during ordinary
startup. Substitute the intended installed data root and, when needed, an
alternate legacy checkout directory:

```bash
python server.py --data-dir "/path/to/mentat-data" --preview-legacy-migration
python server.py --data-dir "/path/to/mentat-data" --confirm-legacy-migration TOKEN_FROM_PREVIEW
```

Add `--legacy-data-dir "/path/to/checkout/data"` to both commands when the
source is not this checkout's `data/` directory. Re-run the preview after any conflict or
state change. A `resume_required` preview returns the same state-bound token
only when the reservation, backup, and partial copies still verify. The source
is intentionally retained; no cleanup command is authorized by this slice.

Milestone 1D implements schema versioning without wrapping or rewriting the
nine consumer-visible JSON documents. A missing manifest means supported legacy
document version 0. A clean all-seed initialization records version 1 in the
owner-only `config/data-schema.json` sidecar. Existing version-0 roots remain
readable until the operator explicitly upgrades them, so an update does not
silently mutate operator state.

The explicit schema preview lists every fixed document's from/to version and
action plus the excluded private/runtime classes. Its opaque token binds the
exact target spelling, live bytes, ordered step, and expected missing manifest,
while public output contains no paths, content, hashes, backup names, or secret
metadata. Confirmation re-previews beneath the shared pinned-root lock, creates
and verifies an owner-only versioned ZIP before publishing metadata, and then
atomically publishes the missing manifest. A matching interrupted backup can
resume only when its bytes exactly match the deterministic archive. An exact,
owner-only orphan manifest/backup temporary produces a bounded
`recovery_required` preview; confirming that state-bound plan removes only the
revalidated non-authoritative temporary, after which the operator previews the
migration again. Changed data, invalid artifacts, multiple/lookalike
temporaries, or a raced manifest fail closed. The recognized publication state
may be either a pre-link temporary or the exact same-inode, two-link
temporary/final pair left after missing-only promotion; confirmation always
removes only the temporary name.
Inventory covers the complete root/config/backup reserved namespace before a
recoverable state is selected, so an exact temporary cannot mask a lookalike in
another category. At confirmation, enumeration, bounded reads, promotion-pair
checks, unlink, and absence verification all remain relative to the same pinned
root/child descriptors; a renamed root cannot redirect recovery to a replacement.
After unlink, the complete pinned inventory must equal its confirmation-bound
pre-state minus exactly that temporary, and any promoted final must retain the
same inode and bytes, before reconciliation can be reported. The resulting
`ready`, exact `resume_required`, or fully valid `already_current` state and all
nine confirmation-bound live bytes must also verify; any failure after deletion
is reported as partial, never as an untouched block.

Clean initialization records a hidden, owner-only fresh-schema reservation
before the first seed copy. Retry completes that reservation after a partial
copy or after all copies but before manifest publication; a pre-existing
version-0 root without the reservation is never inferred to be fresh merely
because its bytes equal packaged seeds. The reservation is removed only after
the current manifest verifies. Exact reservation writer temporaries are
reconciled under the same pinned lock. Exact seed and fresh-manifest pre-link or
same-inode post-link publication states are reconciled before copying resumes,
and the reservation is removed last only after every live document, required
artifact, and absence of fresh-init temporaries verifies.
The same complete pinned inventory is repeated before each fresh reconciliation,
manifest publication, and final reservation removal.
Fresh schema finalization now occurs before the layout initializer releases its
root descriptor and cross-process lock. The final data preflight, exact allowed
schema transition, and selected-path identity are checked again before startup
can report success. The guarded root's device/file identity is carried across
the final reacquisition, so a different inode with the same schema status is
not accepted.

Normal top-level JSON reads and writes take the same process-reentrant,
cross-process mutation lock before any per-file lock, so nested writers cannot
invert the lock order and the
backup and metadata checkpoint cannot race a dashboard task/project/settings
write. The configured root remains an absolute lexical spelling rather than a
symlink-resolved destination, and lock acquisition walks every component without
following redirects (with only the platform's trusted macOS aliases normalized).
The server preserves that spelling through its allowlisted child handoff. On
POSIX the outer lock's pinned root descriptor is reused for the JSON read,
temporary creation, and atomic replace; on Windows the guarded handle chain is
retained. The source development override omits the on-disk lock for lower-level
JSON helpers, while server reads and writes retain it so they cannot race a
restore; both retain process-local ordering, component validation, and pinned I/O. A
substituted final root or ancestor is never written and cannot
claim success. The manifest records the ordered
`durable-json-v0-to-v1` identity step
and immutable backup evidence. Later legitimate JSON mutations remain valid as
long as every live document stays fixed-inventory, owner-only, single-link,
bounded, valid JSON with its supported top-level shape. The writer opens each
file without following its final entry, validates the private regular-file
boundary, bounds reads and serialized output, enforces the fixed top-level type,
and refuses nested development-to-installed lock-mode escalation. Product reads
use the same guarded root and policy; installed mutations never infer a missing
durable document from an empty default. Atomic writes retain and verify the
temporary's exact bytes and identity through commit, verify the committed entry,
and remove every uncommitted temporary on failure. Startup performs a
read-only schema gate before layout repair, lifecycle, or runtime/private
writes, then validates the manifest and backup under the pinned lock. A current
schema with a missing or unsafe document therefore fails closed instead of
being seed-repaired. Valid current roots still traverse the locked layout
initializer so every required private/runtime/backup/cache/log/config directory
is created or hardened and redirected boundaries are refused. A
newer manifest format or per-document version is read and refused distinctly
before temporary/reservation classification; Mentat never attempts a
best-effort downgrade or an older recovery mutation.

Use the same installed data root for preview and confirmation:

```bash
python server.py --data-dir "/path/to/mentat-data" --preview-schema-migration
python server.py --data-dir "/path/to/mentat-data" --confirm-schema-migration TOKEN_FROM_PREVIEW
```

This schema-specific recovery ZIP is not the later general backup/restore
product. Private SQLite evolution, arbitrary restore, and JSON record-shape
changes remain outside Milestone 1D.

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
time. Staged/unreferenced scratch is excluded. The remote Hermes endpoint
and API credential, tokens, and other credentials are excluded from ordinary
backups even though their private storage is durable. A future secret-aware
export would require a separately approved encrypted design.

Restore requires a restore preview, destination validation, conflict reporting,
a pre-restore recovery backup, confirmation bound to the preview, locked atomic
replacement, and post-restore schema/integrity verification. A newer unsupported
backup fails closed. Runtime scratch, caches, logs, browser storage, and external
Hermes/Obsidian/Google state are not restored as operator data.

Milestone 1E-A implements the schema-governed durable-operator portion of this
contract. Milestone 1E-B extends the current deterministic owner-only format as
`mentat-backup-v2-<id>.zip`, with one canonical manifest, the nine fixed
`data/*.json` entries, canonical retained history, a supported-schema SQLite
snapshot captured through SQLite's backup API and pruned to retained run
references, and exactly the verified ready blobs referenced by that snapshot.
The manifest records format and data-schema versions, classifications, sizes,
integrity metadata, and every excluded class. It contains no absolute paths,
credentials, unreferenced/staged Console bytes, runtime state, caches, logs, browser state,
external state, or nested backup files. Backup creation holds the shared pinned
data-root mutation lock, validates current schema and exact live bytes, publishes
missing-only below `backups/`, verifies the committed archive, and rechecks that
the source did not change. Restore parsing validates the single-disk end record,
exact entry count, and a tight central-directory bound before constructing a ZIP
reader; JSON trees are decoded one document at a time for shape validation and
discarded rather than retained with the raw snapshot.

Restore accepts that exact canonical version-2 archive and the prior canonical
version-1 JSON-only format on an initialized
current-schema target. Preview is read-only, reports replace/unchanged actions,
refuses newer or malformed input, and binds an opaque token to the safe archive
identity and bytes plus exact target identity and live bytes. Confirmation
revalidates beneath the shared pinned-root lock, imports exact source evidence,
publishes a validated backup of the pre-restore documents, and records an
owner-only reservation before any live replacement. Every document replacement
is exact, size/type validated, owner-only, atomic, and post-commit verified. A
recognized interrupted state may resume only while the selected source,
internal evidence, recovery archive, reservation, and every live document still
match the token-bound old-or-new set. Unknown state fails closed, and startup
blocks while any reservation or restore temporary remains. An exact uncommitted
temporary has its own previewed, confirmed cleanup path and is never silently
deleted.

For version 2, private restore exchanges a complete staged Console directory,
keeps the old directory until new-state verification, and resumes only exact
recognized old/new/staged states. Version-1 restore preserves the current
private Console unit. The current schema manifest and its bootstrap evidence stay at the destination:
they describe the supported document schema and remain valid across legitimate
document mutations. Migration receipts, schema backups, and all excluded
directories are not replaced. A clean-install recovery initializes the target
layout and current schema first, then runs restore. Version 2 completes the
private Console consistency unit; version 1 remains a supported JSON-only
legacy format.

Current source-checkout CLI form (the unified installed `mentat backup` and
`mentat restore` commands remain Milestone 3):

```bash
python server.py --data-dir "/path/to/mentat-data" --create-backup
python server.py --data-dir "/path/to/mentat-data" --preview-restore --restore-backup "/path/to/mentat-backup-v2-ID.zip"
python server.py --data-dir "/path/to/mentat-data" --confirm-restore TOKEN_FROM_PREVIEW --restore-backup "/path/to/mentat-backup-v2-ID.zip"
```

Legacy private Console state is never moved silently. Preview and confirmation
use the same configured data root; confirmation preserves the runtime source,
publishes the verified private destination, and writes its receipt last:

```bash
python server.py --data-dir "/path/to/mentat-data" --preview-private-migration
python server.py --data-dir "/path/to/mentat-data" --confirm-private-migration TOKEN_FROM_PREVIEW
```

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
The remote Hermes endpoint and API credential remain server-side. Mentat
accepts them only in the operator's explicit setup request and never returns
them in browser payloads sourced from stored state or upstream responses. They
are excluded from browser storage, tracked files, logs, diagnostics, crash
text, ordinary backups, and test fixtures. Error messages and audit records may
contain only bounded, normalized, secret-free identifiers.

Tracked seeds and documentation remain public-safe. They must not contain real
operator names, local paths, account identifiers, tokens, private messages, or
runtime history.

## Implementation sequence

- Milestone 1A: canonical inventory and tested contract only; complete.
- Milestone 1B-A: platform-aware resolver, source labels, and bounded read-only
  seed/legacy/conflict preflight; complete without filesystem writes.
- Milestone 1B-B: owner-only directory creation, packaged-seed loading, and
  lock-protected missing-only initialization; complete.
- Milestone 1C: previewed, migration-backed, locked legacy durable-JSON copying,
  interruption resume, and completion receipt; complete.
- Milestone 1D: sidecar schema versioning, explicit backed-up version-0
  bootstrap, coordinated durable writes, and forward-version refusal; complete.
- Milestone 1E-A: fixed durable-operator JSON backup and previewed restore with
  pre-restore recovery evidence and interruption resume; complete.
- Milestone 1E-B: private-state movement and consistent private backup;
  implemented with its approved contract and failure-path evidence.
- Milestone 1F: versioned application-tree replacement, verified pre-upgrade
  backup, changed-seed non-overwrite, application-only uninstall, and reinstall
  preservation coverage across durable JSON and retained private Console state;
  complete without selecting installer tooling.

The source checkout continues using the current repo-local `data/` override.
Documentation must describe that as development behavior, not as the installed
public-beta layout.
