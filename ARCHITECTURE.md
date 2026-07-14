# Mentat Architecture and Capability Contract

## Product role

Mentat is a local-first, capability-scoped Hermes control plane. It is not only
a read-only viewer, and it is not a general-purpose editor for Hermes files.
Mentat may observe Hermes state broadly, but it may mutate Hermes only through
explicit, supported capabilities implemented by the Hermes adapter.

## Identity model

- A Hermes **profile** is the canonical executable agent identity.
- A Mentat **heartbeat agent** is an observation about a running or recently
  completed process. Records in `data/agents.json` are not profile definitions.
- A Hermes **session** is conversation history owned by a specific profile.
- Mentat must not create a second agent registry that competes with Hermes.

## Write boundaries

| Surface | Policy |
| --- | --- |
| Hermes sessions and `state.db` | Read-only |
| Credentials and authentication files | Never read or write directly |
| Hermes profiles | Mutate only through approved, fixed Hermes CLI/API operations |
| Model/provider configuration | Mutate only through validated Hermes operations |
| Existing Hermes cron jobs | Read-only inventory; queue controls fail closed |
| Skills and general `SOUL.md` content | Read-only; only the versioned Mentat identity block is writable |
| Mentat runtime history | Writable, private, and gitignored |
| Mentat attachment database and blobs | Writable, private, gitignored, and project-owned |
| Mentat project/task data | Writable through allowlisted project-owned storage |
| Hermes Kanban tasks and runs | Mutate only through the supported, capability-gated Kanban adapter |
| Arbitrary Hermes files | Never write directly |

## Mutation contract

Every write-capable Hermes operation must declare:

1. a typed intent and fixed handler; browser input never becomes a command;
2. capability and Hermes-version requirements;
3. input validation and affected profile scope;
4. preview and human-confirmation requirements;
5. concurrency and locking rules;
6. verification, partial-failure, and rollback behavior;
7. privacy-aware local audit data that excludes secrets.

Unsupported capabilities and unknown Hermes versions fail closed. Mentat never
constructs a shell command from browser text and never collects Hermes secrets.

Mentat is an unauthenticated local application and must bind only to a loopback
host. Non-loopback access is not a deployment option under this contract.

Agent Console execution is globally single-run in v1. Every run records its
Hermes profile id, launches with a fixed `-p <profile>` selector, and may resume
only a session already associated with that same profile.

## Agent Console file boundary

Console files are Mentat-owned runtime data, never Hermes core data. SQLite at
`data/runtime/mentat.sqlite3` stores attachment, blob, and run-reference
metadata; bytes use private content-addressed blob files below the same
gitignored runtime root. The browser sees only opaque attachment ids, bounded
display metadata, and fixed same-origin content routes. It never receives blob
hashes, storage keys, trusted server paths, or arbitrary file-serving URLs.

Uploads and workspace snapshots must pass extension, MIME/magic, UTF-8, size,
secret-name/content, regular-file, containment, and symlink checks. Text is
served as `text/plain` with `nosniff`. Inline display is restricted to validated
PNG, JPEG, GIF, and WebP content. SVG, HTML execution, PDF embedding, archives,
executables, path traversal, and remote/data/file URLs are outside this
capability.

Content-addressed blob filenames are intentionally extensionless. They must not
be passed directly to Hermes image arguments because Hermes validates supported
image suffixes. Mentat creates a bounded, private, run-scoped input snapshot
with the server-validated extension, uses that path only for the fixed Hermes
adapter call, and deletes the snapshot when execution ends. Browser responses
and retained history never expose this path.

Workspace selection searches only explicit configured roots and returns
relative paths. The current root is the Mentat repository; VCS, hidden,
dependency, build, runtime, secret, archive, executable, and symlinked paths are
excluded. Selection creates a private no-follow snapshot before storage, so a
later workspace edit cannot change prompt context already attached to a run.

Context Packs store reusable references in project-owned `data/context_packs.json`:
bounded instructions, vault-relative Markdown paths, and workspace root ids plus
relative paths. They never store note/file contents or absolute paths. Every use
revalidates the references. Console use creates normal private staged snapshots;
delegation use resolves bounded text into the exact preview and confirmation
digest, so changed pack content must be previewed again.

Assistant-created artifacts are accepted only from a private per-run export
directory named in trusted server-generated execution context. Mentat does not
parse paths from assistant prose. After execution, it scans that directory with
bounded allowlists, snapshots acceptable files without following symlinks,
binds stored outputs to retained history, and cleans successfully registered
exports. Failed registration preserves the export for retry.

Staged files expire after two hours. Unreferenced files use a one-hour grace;
active and retained run references prevent collection. Startup reconciliation
and a bounded periodic collector repair interrupted states, release references
for history that no longer exists, and retry failed deletions with backoff.

## Profile identity boundary

The Hermes profile id remains the canonical executable name. Hermes profile
metadata remains the routing-role source used by Kanban, while a versioned
Mentat-managed block at the top of the profile's `SOUL.md` makes the same name
and role available to the running agent's system prompt. Mentat does not create
a second identity registry and never returns the remaining soul content to the
browser.

Identity inspection and writes run inside the Hermes runtime and resolve the
profile only through Hermes' profile API. A write is allowed only when the
runtime exposes the required profile-resolution and metadata operations. The
adapter rejects symlinked soul files, multiple or malformed managed blocks,
reserved marker text, unknown profiles, stale revisions, and active Console
runs. Every change requires an exact preview and profile-bound confirmation,
uses an atomic same-directory soul replacement, synchronizes the Hermes routing
description, refreshes both surfaces for verification, and attempts rollback on
failure. Content outside the managed block is preserved and remains read-only.

## Personal task and planning model

Mentat's project-owned task record is the source of truth for personal planning.
Optional planning metadata covers deliberate Today selection and rank, estimates
and scheduled blocks, browser reminders, subtasks, dependencies, recurrence,
calendar links, Obsidian note links, planning state, and the safe references
needed to associate a task with delegated Hermes work.

The planning validator preserves legacy task records while strictly validating
nested planning objects. It rejects unsafe note paths, malformed timestamps,
unknown nested execution metadata, missing or self-referential dependencies,
and dependency cycles. Recurrence is implemented in Mentat's locked task update:
completing a recurring task creates at most one next occurrence and preserves
the completed instance as history. Scheduled blocks and reminders retain a
validated IANA time zone so recurring wall-clock times remain stable across
daylight-saving transitions.

Browser reminders are advisory UI behavior over Mentat-owned timestamps. The
browser asks for notification permission only after an explicit operator action
and locally deduplicates delivered notifications. No reminder mutates Hermes or
Google Calendar.

## Hermes Kanban delegation boundary

The supported Hermes Kanban adapter is the only durable delegation mutation
path. Agent Messages remains a project-owned communication queue, and Agent
Console remains an interactive, globally single-run conversation surface;
neither is a durable dispatcher.

The adapter uses shell-free argument arrays and a fixed set of supported Kanban
operations. It omits workspace paths, process identifiers, arbitrary metadata,
and secrets from browser payloads. Mentat advertises a Kanban operation only
when runtime discovery reports the corresponding capability.

Creating a delegation requires:

1. a Mentat task, Hermes profile, Kanban board, supported workspace mode, and
   bounded instructions;
2. an exact preview whose confirmation token is bound to the current task and
   complete delegation intent, including bounded attached-note context;
3. revalidation of the same intent at confirmation time;
4. an atomic project-owned reservation that prevents task edits or duplicate
   delegation while the external operation is in flight;
5. a shared Kanban/task mutation lock and one fixed adapter operation;
6. a read-back that verifies the created task's title, context, assignee, and
   workspace before Mentat stores its safe link.

A changed task or intent invalidates confirmation. Missing capabilities and
unknown boards/profiles fail closed. If Hermes accepts a mutation but its state
cannot be read back, Mentat returns a partial failure and does not claim that
the operation was verified. Follow-up remote actions—reply, retry, reclaim/stop,
request revision, and mark blocked—also require an exact preview and confirmation
and are refreshed from Hermes after mutation. Result acceptance is a local review
decision that completes the Mentat task without an additional Hermes mutation.
Action previews refresh and bind the live Hermes task status and latest run
identity; confirmation is rejected if either Hermes or the Mentat task changes.
Adapter mutations verify operation-specific postconditions rather than treating
a merely readable task as proof that the requested effect occurred.

The task's delegation object stores normalized profile, board, task, run and
session identifiers; state, synchronization and review status; bounded summary
or blocking-question text; attempt count; timestamps; and a bounded secret-free
audit. Agent Activity is derived from these task-linked records and groups work
into needs input, ready for review, running, failed, and recently completed.

## Calendar, notes, and search boundaries

Google Calendar access remains read-only. Creating a Mentat task from a verified
event, linking a selected task, or assigning a scheduled block writes only to
`data/tasks.json`. Mentat never edits, deletes, or reschedules the Google event.

Task note attachments are validated Markdown paths relative to the configured
Obsidian vault. Symlinks and paths that escape the vault are rejected. Delegation
context may contain a bounded excerpt from attached notes; Mentat does not edit
those files. Opening a note is an explicit user-facing Obsidian application link,
not a generic server-side file opener.

Grouped global search returns bounded, public-safe navigation records for tasks,
projects, session metadata, notes, and cached/local calendar events. Searching
does not itself change views; navigation occurs only after the operator selects
a result. Deep Hermes message search remains a separate read-only endpoint.

## Provider switching boundary

Provider discovery and selection are scoped to the selected Hermes profile.
Mentat obtains picker context from Hermes through `load_picker_context()` and
builds the selectable inventory with
`build_models_payload(..., explicit_only=True, picker_hints=True)`. The browser
may therefore see only providers Hermes reports as explicitly configured and
authenticated for that profile, plus whether each provider is current. It must
not receive credential values, credential paths, environment-variable names,
tokens, or an unfiltered catalog of every provider Hermes supports.

Hermes remains the sole owner of provider credentials and authentication.
Mentat does not add, edit, validate, migrate, or delete credentials. Provider
switching is an approved, fixed Hermes adapter capability with these rules:

- Mentat advertises the switch capability only after probing that the installed
  Hermes runtime exposes the supported profile-model operation;
- the requested provider must be present in the profile-scoped authenticated
  inventory returned by Hermes;
- the current provider is reported separately from the authenticated set;
- Mentat previews the affected profile, current provider, requested provider,
  and model implications before requiring profile-bound confirmation;
- switching is blocked while an Agent Console run is active;
- Mentat refreshes Hermes picker context after the operation to verify the
  selected provider and models;
- a failed verification triggers rollback to the previous provider when Hermes
  supports it, otherwise Mentat reports the partial failure and fails closed.

This boundary covers selection among already authenticated providers only.
Credential setup and reauthentication continue to happen through Hermes.
There is no direct or unconfirmed Agent Console model-mutation route; all
provider/model changes enter through this capability contract.

## Project task deletion boundary

Task deletion affects only Mentat's allowlisted project-owned task store. It
requires an exact preview and matching confirmation bound to the task's complete
current state. The task is re-read under the project-data lock before
the atomic update, so a changed or missing task fails closed. This operation
does not mutate Hermes data and is not reversible from Mentat.

## Hermes cron boundary

Mentat currently exposes Hermes cron inventory as read-only. The installed
Hermes runtime does not provide an atomic, expected-revision, enabled-only
operation for moving an existing job to the next scheduler tick. A separate
read followed by the available trigger operation cannot close that race: a job
could be changed or disabled between validation and mutation, and the trigger
may implicitly enable it. Mentat therefore advertises no working queue
capability and its queue controls fail closed.

Safe next-tick queueing requires an upstream Hermes compare-and-swap operation
that atomically verifies the complete expected job revision and enabled state
while scheduling the next tick. If Hermes adds that capability, Mentat may
integrate it through the normal preview, confirmation, lock, and post-operation
verification contract. Mentat must not approximate it by writing
`~/.hermes/cron/jobs.json` or by composing multiple non-atomic operations.

An immediate **Run now** action is a separate product choice with different
execution, confirmation, progress, and delivery semantics. It remains deferred
and must not be presented as a substitute for next-tick queueing. Creating,
editing, enabling, disabling, and deleting cron jobs also remain Hermes-owned
operations.

Agent Console progress is exposed as versioned, structured Mentat events. Event
sequence numbers are monotonic within a run and double as polling cursors. The
browser requests only events newer than its cursor and merges them into its local
run view; the full-run response remains available for compatibility and recovery.
Events describe Mentat-owned lifecycle transitions only. Mentat does not parse
unstable native Hermes output into synthetic tool-call events, and it does not
require a streaming transport for this local-first contract.

Agent Console slash commands come from Mentat's versioned, project-owned safe
command manifest. Each entry declares its dashboard handler, arguments,
description, and safety classification. The frontend accepts only the current
schema and a fixed handler registry. The initial allowlist is `/model`, `/new`,
and `/help`; this is intentionally distinct from the full Hermes CLI.

Future command sources must be introduced as an explicit capability and emit
the stable Mentat schema. Mentat does not parse CLI help/output to discover
commands, and it never provides arbitrary Hermes CLI passthrough.

## Initial agent-creator scope

The first version may create a fresh profile or clone approved configuration
through supported Hermes operations. It may collect a profile name,
description, creation mode/source, and skill-seeding choice.

Approved for the initial creator:

- default Hermes bundled skills;
- no bundled skills for a fresh profile;
- an explicit enabled subset selected from Hermes' built-in skill catalog.

Skill selection uses a capability-gated Hermes runtime operation. Mentat stores
skill identifiers only; it does not edit skill contents or copy skill files.

Approved for Managed Agents:

- deletion of a non-default, non-active Hermes profile when Hermes advertises
  `profiles.delete`;
- an exact preview and profile-bound confirmation token before deletion;
- blocking deletion while any Mentat Agent Console run is active;
- post-operation profile discovery to verify the profile was removed.
- profile-scoped provider/model configuration using the same authenticated-only
  inventory, preview, confirmation, active-run lock, verification, and rollback
  contract as the Agent Console. This is the configuration path for a fresh
  profile that does not yet have a provider assigned.
- profile identity inspection and confirmed synchronization of the immutable
  profile name and routing role into the versioned managed `SOUL.md` block.

Deletion is performed only through Hermes' supported profile API in its own
runtime. Mentat never deletes profile directories or their contents directly.

The Agent Creator uses a compact step-progress indicator instead of status-pill
controls; skill choices and review details remain explicit form controls.

After creation, the operator may explicitly test the selected profile in a new
Agent Console identity-check session or begin creating and assigning its first
task. The same actions appear in Managed Agents. Provider/model mutation remains
inside the existing authenticated-only, previewed Advanced configuration flow;
these onboarding actions do not weaken that boundary.

Deferred until separately approved:

- general `SOUL.md` editing outside the managed identity block;
- clone-all;
- profile rename;
- skill content editing, hub installation, or arbitrary MCP configuration;
- non-loopback access.

Mentat retains one active dashboard run globally for the first version. This
can be revisited after profile-scoped execution and cancellation are proven.
