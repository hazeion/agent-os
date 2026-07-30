# Remote Hermes Capability Contract

Status: Approved beta architecture; mandatory maintained-runtime contract live-verified over HTTPS
Approved: 2026-07-16
Maintainer verification: 2026-07-28 against the Hermes fork runtime contract

## Product boundary

Mentat remains a locally installed, loopback-bound, single-operator dashboard.
The operator may select one active Hermes connection at a time: the existing
local runtime or one operator-managed remote Hermes endpoint. A remote Hermes
host may be anywhere the operator can reach securely, but Mentat itself does
not become a hosted or remotely served application.

Remote beta support requires an operator-supplied HTTPS endpoint and API key.
The connection is server-to-server: Mentat's Python server calls Hermes, while
the browser continues to call only its local Mentat origin. Hermes credentials
must never be returned to the browser.

This document defines the complete target contract. Mentat now has owner-only
connection selection plus bounded authenticated health/capability discovery.
Agent Console now selects a binding-aware local or remote transport, preserves
the established local launch contract, and supports active-profile remote runs
through fixed submission, event, status, stop, and response operations.
Interactive runs keep one SSE subscription through approval and clarification
waits. A bounded monotonic event journal supports cursor-based reconnect, while
run status exposes the exact sanitized current pending action for recovery.
Bounded read-only remote session list, replay, and recent-window search now use
the advertised session resource endpoints and process-private connection-bound aliases. One staged
Context Pack may supply bounded, path-free text to remote Runs. Settings can
also show a bounded, read-only skills and toolsets inventory through the exact
advertised endpoints. On runtimes advertising the complete verified contract,
Mentat also enables complete profile discovery, fresh revision-bound session
continuation, request-bound approval and clarification responses, bounded
image data URLs, revisioned/idempotent Kanban, and profile-scoped runtime
inventory and switching. The Console loads each selected served profile's
current provider/model identity and enables the existing selectors only when
Hermes advertises the complete version-one revision, idempotency, and
active-run-lock contract. General Agent Console files remain unavailable.
Completed remote Kanban tasks can expose a separate, capability-gated set of
generated files through fixed authenticated artifact endpoints.
Content safety applies to remote session titles and previews, replay, and
search. Path- or credential-shaped content fails closed. Compact division such
as `a/b` is path-shaped here; use spaced code such as `a / b` in transcripts.
Upstream run IDs remain process-private: graceful shutdown is reconciled, while
an abrupt Mentat process death restores the local summary as interrupted and
partial rather than claiming the remote run stopped.

## Beta capability classes

- **Required**: the public beta cannot claim remote Hermes support without it.
- **Graceful degradation**: the feature may be unavailable in remote mode when
  Hermes does not advertise a supported remote capability. Mentat must explain
  that state and must not offer a control that cannot be verified.
- **Mentat-local**: the feature remains available because Mentat owns it and it
  does not require direct access to the Hermes host.
- **Prohibited**: the remote implementation must never use this route.

## Current capability matrix

| Mentat capability | Current local adapter or source | Supported remote evidence | Remote authentication boundary | Required verification | Beta class and current status |
| --- | --- | --- | --- | --- | --- |
| Public connection liveness | `remote_hermes.py` calls only fixed `/health` and treats the result as untrusted | Hermes documents unauthenticated `GET /health` as a cheap public liveness probe in its [API Server](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/api-server.md) | No authentication; response is untrusted liveness only | Bounded timeout/size/schema checks; never derive identity, readiness, or enabled features from this response | **Required** diagnostic; 2A foundation implemented |
| Authenticated readiness and capability discovery | `remote_hermes.py` validates fixed `/health/detailed` and `/v1/capabilities` responses and returns an allowlisted summary | Hermes documents bearer-authenticated `GET /health/detailed` and machine-readable `GET /v1/capabilities` in its [API Server](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/api-server.md) | API-server bearer key over verified HTTPS | Validate schema/version, endpoint identity, advertised auth, bounded readiness, model, and capability set | **Required**; complete inventory stays capability-gated |
| Hermes configuration and overview summary | `server.py` reads local `CONFIG_PATH` metadata and combines it with normalized profile/provider discovery | Remote health, capabilities, and model endpoints can supply bounded connection/profile/model status; remote configuration-file metadata is unnecessary | API-server bearer key; never request or expose raw remote configuration | Normalize an allowlisted summary and suppress upstream errors, paths, headers, and secret-shaped values | Safe connection/profile/model status is **Required**; file/configuration details remain local-only |
| Agent Console conversation and streaming | `hermes_transport.py` selects a binding-aware transport, preserves the profile-scoped local CLI launch, and implements the active remote profile Runs adapter | Hermes documents Chat Completions, Responses, run submission, SSE events, approvals, and session chat in the [API Server](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/api-server.md) and [programmatic integration guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/programmatic-integration.md) | API-server bearer key over verified HTTPS; key remains in Mentat's server process | Bind each run to the active endpoint; keep one stream through interactive waits; verify monotonic cursors and bounded replay; never retry submission | **Required**; bounded Context Pack text and capability-gated images are supported; general Console file output is not |
| Run status, progress, approval, cancellation, and stopping | `server.py` and `agent_run_history.py` normalize remote events/status and keep upstream run identity private | Fixed Runs, status, replayable SSE, stop, and request-bound approval endpoints are capability-advertised by the verified runtime | Same API-server bearer boundary | Capability match before action, exact live-run/request binding, authoritative pending-action recovery, one claimed stop attempt, and post-action status read-back | **Required**; approval choices are enabled only with the exact bound-preview contract |
| Clarification requests and responses | `server.py` retains bounded run interaction state and posts a typed response through `hermes_transport.py` | The verified runtime advertises a typed request/response endpoint with exact request binding | API-server bearer key | Require a machine-readable request event, typed bounded response, exact run/request binding, and post-response status verification | **Required** for the verified runtime; unavailable without the contract |
| Session list, replay, continuation, and search | `server.py` preserves local `state.db` reads and routes selected remote history through `remote_hermes.py` | The verified runtime advertises an exact revision-bound, stoppable continuation descriptor as well as session reads | API-server bearer key; no remote database access; upstream IDs remain process-private | Normalize bounded user/assistant history, bind opaque aliases to the selected projected identity, label compressed history partial, require a fresh exact continuation descriptor | **Required**; continuation is enabled only with that exact capability |
| Read-only agent/profile discovery | `hermes_profiles.py` runs inside the local Hermes runtime; the remote adapter uses only the advertised profile inventory | The verified runtime advertises a complete API-key-authenticated profile inventory | API-server bearer key; no direct profile-file access. The separate dashboard session-token boundary is not the approved stable API-server bearer boundary | Require a capability-advertised bounded complete inventory and reconcile it with the endpoint's active profile | **Required**; live-verified for the maintained `0.19.0` contract |
| Profile creation | `hermes_profile_creation.py` and fixed Hermes profile operations | No API-key-authenticated profile-creation capability is advertised by the API server | No approved remote boundary | Exact preview, capability match, profile-bound confirmation, and verified refresh would be required | **Graceful degradation**; remote unavailable unless upstream adds support |
| Profile identity inspection and synchronization | `hermes_profile_identity.py` resolves local profile metadata and the managed `SOUL.md` block through Hermes APIs | No supported API-server identity capability is advertised | Direct remote `SOUL.md` access is prohibited | Existing revision-bound preview, confirmation, atomicity, verification, and rollback contract would still apply | **Graceful degradation**; remote unavailable unless upstream adds support |
| Profile deletion | `hermes_profile_deletion.py` calls the supported local Hermes profile API | No supported API-server deletion capability is advertised | No approved remote boundary | Existing exact preview, active-run exclusion, confirmation, and post-delete discovery would still apply | **Graceful degradation**; remote unavailable unless upstream adds support |
| Provider/model inventory and switching | `hermes_provider_switching.py` preserves the local picker/fixed-operation path; `remote_hermes.py`, `hermes_transport.py`, and `server.py` consume the remote profile runtime contract | The fork advertises exact authenticated `GET /v1/profiles/{profile_id}/runtime` and `POST /v1/profiles/{profile_id}/runtime/switch` version-one endpoints with revision binding, idempotency, and active-run exclusion | Hermes remains credential owner; Mentat receives only validated provider/model choices and a runtime revision, never credentials or provider endpoints | Require every exact capability flag and endpoint; bind preview to profile/current/target/revision; hold connection and profile mutation locks; send one server-generated idempotency key; fresh-read verify; attempt one revision-bound rollback only after a verified mutation mismatch | **Graceful degradation**; fully supported hosts enable switching, while partial/older hosts retain the read-only current-runtime projection |
| Skill and toolset visibility | `hermes_skills.py` discovers the local built-in catalog inside the Hermes runtime; Settings uses the remote inventory adapter only in remote mode | The API capability document advertises exact `GET /v1/skills` and `GET /v1/toolsets` paths when supported | API-server bearer key | Revalidate the selected connection before and after both reads; bound and allowlist skill/toolset identifiers, enabled state, and counts; reject private reflection and malformed/partial results; omit descriptions, categories, labels, paths, skill contents, and tool names | **Required**; read-only visibility implemented in 2G |
| Skill selection | `hermes_skills.py` applies local profile-scoped selection through Hermes | No API-server skill-selection mutation is part of the approved stable surface | No approved remote boundary | Exact profile and selection preview, confirmation, capability match, and refreshed catalog | **Graceful degradation**; remote unavailable unless upstream adds support |
| Durable Kanban delegation and follow-up | `hermes_kanban.py` uses fixed shell-free local operations or the fixed remote Kanban adapter with task/run read-back | The verified runtime advertises bearer-authenticated revisioned and idempotent Kanban endpoints | API-server bearer key; the dashboard browser/session token remains prohibited | Preserve exact preview/confirmation, mutation locks, in-flight reservation, live task/run binding, idempotency, and operation-specific read-back | **Required** for the verified runtime; unavailable elsewhere |
| Cron inventory | `server.py` reads the local store in local mode and uses the selected transport in remote mode | The maintained runtime advertises the complete version-one `GET /v1/jobs` read-only contract | API-server bearer key; direct remote cron-file access remains prohibited | Check the connection before and after one bounded read; accept only ID, an ID-based label, schedule, enabled state, last and next run times, status, and an opaque revision; reject malformed, duplicate, oversized, older, or partial responses | **Graceful degradation**; compatible hosts can show remote jobs, but Mentat still cannot change or run them |
| Console input attachments and Context Packs | `agent_console_attachments.py`, `agent_console_artifacts.py`, and Mentat-owned Context Pack resolution stage local snapshots | The verified Runs contract accepts up to four bounded image data URLs; general uploaded files and paths remain unsupported | API-server bearer key; Mentat-owned files stay local unless explicitly transmitted through a supported bounded content type | Bind one-use Context Pack grants to the connection, pack revision, and exact snapshots; enforce text/image bounds and never transmit a path | **Required**; images are capability-gated and general files **gracefully degrade** |
| Delegated Kanban artifacts | `delegation_artifacts.py` imports only explicit completion files returned by the fixed remote manifest | Hermes advertises `kanban_artifacts` version 1, digest verification, exact list/download routes, 10 files, 100 MiB per file, and 250 MiB total | API-server bearer key stays server-side; browser downloads only from opaque same-origin Mentat routes | Bind task, board, connection, manifest ID, size, type, digest, and private snapshot; reject recognizable secrets and active content | **Graceful degradation**; supported only when the complete contract is advertised |
| General assistant-created artifacts | Mentat discovers local Console files only in a trusted local run export directory | No general remote Console artifact-download contract is established | No arbitrary remote file URL or path may be opened | A separate advertised resource contract and Mentat-owned snapshot would be required | **Graceful degradation** pending a supported Console resource contract |
| Calendar, notes, planning, projects, tasks, search, themes, and reminders | Mentat-owned storage and integrations; Google Calendar is read-only | No Hermes access is required for the core feature behavior | Local Mentat boundary | Preserve existing local validation and mutation contracts | **Mentat-local** and available in both connection modes |
| Google Calendar credential location | `server.py` currently resolves `google_token.json` below local `HERMES_HOME` | Not a remote Hermes API concern | Credentials must move to the future Mentat operator-data root rather than a remote Hermes host | Migration and read-only calendar verification in Milestone 1 | **Mentat-local**; storage coupling must be removed before remote beta |
| Agent Pulse heartbeat observations | Project-owned `data/agents.json` and the local Mentat heartbeat endpoint | No Hermes API is required | Local Mentat boundary | Preserve observation-only semantics; never treat heartbeats as profile authority | **Mentat-local** |
| Connection setup and local/remote runtime selection | `remote_hermes.py` owns selection and binding rotation; `hermes_transport.py` selects the exact Console transport and revalidates before queue and launch | Remote selection is Mentat-owned configuration; authenticated readiness/capabilities describe the selected remote | Owner-only Mentat operator configuration outside the install | Preserve local discovery, validate one explicit remote origin, and invalidate all endpoint-bound state on selection changes | **Required**; 2A/2B selection and Console routing implemented |
| Hermes diagnostics | `health_checks.py` selects local checks or a remote summary from `remote_hermes.py` | Public `/health` supplies liveness only; authenticated `/health/detailed` and `/v1/capabilities` supply bounded remote readiness | Bearer auth required for trusted readiness/capability conclusions | Redact upstream details; distinguish unreachable, unauthenticated, degraded, unsupported, and healthy states without exposing paths or secrets | **Required**; Milestone 2I implemented |

## Run continuity and runtime identity

Terminal Runs may include `usage.context_tokens` and
`usage.context_length`. Hermes must produce these as one internally consistent
pair from the provider-reported prompt size and the active model window.
Mentat validates the pair again, keeps cumulative billing totals separate, and
shows **Unavailable** rather than guessing when either value is absent or
invalid.

When advertised, `run_event_replay` version 1 gives every Runs SSE event a
monotonic `id`/`sequence` retained in a fixed in-memory window. Multiple
subscribers receive independent copies. A reconnect must send
`Last-Event-ID`; malformed, ahead-of-stream, and expired cursors fail closed.
Mentat reconnects automatically after a genuine transport interruption without
resubmitting the run. The journal is count- and byte-bounded and contains only
normalized public fields; raw tool previews and reasoning bodies are omitted.
This is a transport recovery mechanism, not durable recovery across a Hermes
restart.

`run_pending_action_status` version 1 makes the exact sanitized current
approval or clarification available from run status. Mentat accepts it only
when its kind matches the waiting status and its request schema passes the same
validation as the live event. A legacy no-ID approval acknowledgement never
clears Mentat's exact local request by itself; Mentat reconciles authoritative
run status first. `run_runtime_identity` and
`profile_runtime_inventory` version 1 exposes only bounded provider/model IDs.
The separate `profile_runtime_switch` version-one contract adds bounded choices
and an opaque runtime revision. It is trusted only when revision binding,
idempotency, active-run locking, API-key inventory, and both exact profile
runtime endpoints are advertised together. These contracts never expose
endpoints, paths, credential metadata, environment names, or tokens.

The inventory covers the current integration modules `remote_hermes.py`, `hermes_transport.py`, `hermes_profiles.py`,
`hermes_profile_creation.py`, `hermes_profile_identity.py`,
`hermes_profile_deletion.py`, `hermes_provider_switching.py`,
`hermes_skills.py`, `hermes_kanban.py`, the Hermes-backed paths in `server.py`,
the Console metadata boundary in `agent_run_history.py`, local/remote selection
in `runtime_config.py` and `scripts/mentat_setup.py`, and diagnostics in
`health_checks.py`.

## Connection and credential contract

The first remote implementation must satisfy all of these rules:

1. Mentat supports one active Hermes connection at a time. Switching the
   endpoint invalidates endpoint-bound capability, session, run, preview, and
   confirmation state.
2. A non-loopback remote endpoint must use `https`. Cleartext `http` is
   accepted only with a literal loopback IP (`127.0.0.0/8` or `::1`), not a
   hostname. URLs containing user info,
   fragments, or embedded credentials are invalid. Certificate verification is
   mandatory, redirects are not followed across origins, and calls use bounded
   connection/read timeouts and response sizes.
3. The operator supplies the endpoint and API key explicitly. After Milestone
   1, the secret belongs in owner-only operator configuration outside the
   application/install directory. It never belongs in tracked files, URLs,
   browser storage, browser payloads, exception text, diagnostics, or logs.
4. Mentat's server adds the authorization header. The browser never calls
   Hermes directly, so remote Hermes does not need to allow the Mentat browser
   origin through CORS.
5. A connection test may use public `/health` only as an untrusted liveness
   hint. It derives endpoint identity, readiness, active profile, version, and
   enabled features exclusively from authenticated, validated responses. Mentat
   displays only a bounded label, safe health/readiness state, active profile
   identifier, safe version metadata, and supported capability names—not raw
   response bodies, headers, paths, environment names, or secrets.
6. Unknown schemas, missing authentication, unsupported capabilities,
   certificate failures, timeouts, endpoint changes, and unverifiable results
   fail closed. A local feature remains usable only when it does not depend on
   the failed remote operation.
7. Every remote mutation keeps Mentat's existing typed-intent, preview,
   confirmation, concurrency, verification, partial-failure, audit, and
   rollback requirements. A generic HTTP client does not broaden authority.

The remote URL is an explicit operator-granted network destination, not an
arbitrary per-request fetch target. Later implementation must threat-model
server-side request forgery, DNS changes, redirects, proxy behavior, certificate
validation, and endpoint identity before accepting configuration from the UI.

## Operator experience: local and remote selection

Status: setup and CLI connection selection implemented. A Settings-page selector
remains deferred.

The operator should not need to edit Mentat's private connection record or
repeat a manual request payload to move between local and remote Hermes. The
implemented experience keeps local Hermes permanently available and remembers one
operator-approved remote endpoint so routine switching becomes an explicit
setup or CLI action.

The first-run setup helper should ask which Hermes connection Mentat will use:

- **Local Hermes** uses the detected local profile and remains the recommended
  default when detection succeeds.
- **Remote Hermes** asks for a display label and one HTTPS origin containing
  only scheme, host or IP address, and optional port. It then obtains the API
  key from a server-only secret source, tests authenticated readiness and
  capabilities, shows a secret-free preview, and saves only after confirmation.
- Selecting local later must not erase the remembered remote definition.
  Selecting remote later must retest it before activation.

A non-loopback IP address is acceptable only when the URL uses HTTPS and the
certificate validates for that IP address. Setup must not add an insecure TLS
override to make a raw IP convenient. Operators without a valid IP certificate
should use a hostname or a securely managed network name whose certificate can
be verified.

The non-secret connection definition lives in Mentat's owner-private connection
record and contains only the active mode, local label, one remote label and
endpoint, opaque binding, and a credential-source reference. The API key itself
must be supplied through a named environment variable or an owner-only
environment file outside tracked source. The environment file uses an exact
assignment such as:

```text
MENTAT_REMOTE_HERMES_API_KEY="replace-with-the-real-server-key"
```

On POSIX, set its mode to `0600`. The setup and CLI paths never place the value
in `mentat.toml`, `mentat.local.toml`, command-line
arguments, shell history, URLs, browser storage, browser payloads, logs, or
diagnostics. Windows requires an owner-only ACL. Rerunning setup preserves the
credential-source reference unless the operator explicitly replaces the remote
definition.

Existing schema-v1 records that embedded the API key migrate automatically to
schema v2. The key moves to
`<data-root>/private/remote-hermes-credential.env`, the connection record keeps
only a `private_env_file` reference, and both files are owner-only and excluded
from ordinary backups and diagnostics. A failed or unverifiable migration
restores the prior record or reports an explicit partial failure.

A candidate non-interactive setup interface is:

```text
python scripts/mentat_setup.py --hermes-mode local
python scripts/mentat_setup.py --hermes-mode remote \
  --hermes-endpoint https://hermes.example.test:8642 \
  --hermes-label "Remote Hermes" \
  --hermes-api-key-env MENTAT_REMOTE_HERMES_API_KEY
```

Endpoint metadata may be passed as arguments; the API key value may not. The
installed CLI provides:

```text
mentat connection status
mentat connection test remote
mentat connection use local
mentat connection use remote
mentat connection configure-remote \
  --endpoint https://hermes.example.test:8642 \
  --label "Remote Hermes" \
  --api-key-env MENTAT_REMOTE_HERMES_API_KEY
```

Use `--api-key-file /absolute/path/to/owner-only.env` instead of
`--api-key-env` to read the fixed `MENTAT_REMOTE_HERMES_API_KEY` assignment from
a file. CLI connection mutations refuse to run while the Mentat server is
active. Server startup and offline connection commits share a durable
cross-process reservation, so a server beginning to start cannot slip between
the liveness check and the saved selection. Schema-v1 migration uses the same
boundary and remains blocked while another Mentat process is active. In an
interactive terminal, mutation commands show the secret-free plan and ask for
confirmation. A non-interactive call first returns exit code `3` with a
secret-free confirmation token; rerun the exact command with
`--confirm <token>` to apply it. Remote configuration and selection probe the
authenticated readiness/capability contract before committing. `test remote`
performs the same probe without changing the active mode; `test local` verifies
that the supported Hermes CLI can execute without returning its version text or
local path.

Version one needs only local plus one remembered remote. Multiple named remote
connections are deferred until there is demonstrated operator need.

Every mode change must retain the existing connection-operation lock and:

1. refuse the change while an incompatible Agent Console run or mutation is
   active;
2. preview the exact current and proposed labels without exposing endpoint or
   credential data to the browser;
3. authenticate and validate a remote target before committing it;
4. atomically change the active selection and rotate its opaque binding ID;
5. invalidate endpoint-bound runs, sessions, cached capabilities, previews,
   confirmations, and runtime inventory;
6. read back and verify the saved selection; and
7. preserve or restore the prior selection when commit verification fails.

Mentat must never silently fall back from remote to local, or from one remote
endpoint to another, because that could send a prompt or mutation to the wrong
Hermes identity. Unavailable remote state should be visible and recoverable
through the explicit local/remote selector.

Acceptance evidence for this operator experience requires:

- a clean install can select and validate local or remote Hermes without
  hand-editing a private JSON record;
- non-interactive setup can select either mode without placing a secret value
  in process arguments;
- switching to local and back to the remembered remote requires no endpoint or
  key re-entry;
- setup reruns are idempotent and do not overwrite secrets unexpectedly;
- failed authentication, TLS validation, capability discovery, and selection
  verification leave the prior connection selected; and
- browser responses, logs, diagnostics, tracked files, and backups that are not
  secret-aware remain free of endpoint and credential data.

## Provider runtime selection

Status: profile-default runtime switching implemented; session-scoped
overrides remain deferred.

Hermes messaging adapters already provide session-scoped `/model` behavior
because Telegram, Discord, and Slack events enter the in-process gateway
command dispatcher. The Runs API used by Mentat instead creates an agent
directly and does not dispatch slash commands. Mentat must not send `/model` as
model prose or impersonate a messaging platform.

The Hermes fork now exposes **Profile Default Runtime Management** through an
exact authenticated runtime read and revision-bound switch. Mentat projects the
validated choices into the Agent Console's Agent, Provider, and Model row. An
Agent change re-reads the exact served-profile runtime without mutation. A
Provider change selects Hermes's first listed model, while a Model change keeps
the selected provider; either selector change automatically performs the safe
preview/apply flow without a second review-dialog click. Preview re-reads the
selected served profile and binds its current provider/model, requested pair,
connection, and revision. Apply excludes an active Mentat run for that profile,
revalidates the connection under the shared mutation locks, recomputes the
confirmation, and makes one idempotent switch call. A fresh read must verify
the target. A mismatch permits one rollback only when the fresh state still has
the exact revision acknowledged by Mentat's switch response, followed by
another fresh read. If that revision has advanced, Mentat treats the state as a
concurrent change, does not roll it back, and requires operator inspection. An
uncertain mutation is never retried. A verified change is shown as a browser-
session transcript notice bound to the current connection and profile, and is
never injected into model context.

The displayed current pair always comes from Hermes's exact runtime fields,
not from the first selectable provider/model. During a selector mutation,
Mentat shows the last confirmed pair plus the pending target. If the mutation
fails and the reconciliation read also fails, the Console clears stale picker
data and pauses prompts, attachments, new sessions, and runtime changes until
the operator's explicit runtime retry obtains a fresh, non-error confirmed
pair. Delayed results from a prior connection are discarded. Context Pack and
attachment staging serialize with runtime changes and are discarded if their
connection/profile context changes in flight.

Hosts missing any required flag or exact endpoint remain read-only. Provider
credentials, endpoint configuration, remote profile creation, skill selection,
cron mutation, and arbitrary configuration writes remain outside this
contract.

One-turn or session-scoped runtime overrides remain a separate future Runs API
capability. Mentat must not emulate them by sending `/model` as prose or by
changing a saved profile default and immediately changing it back.

## Deferred command discovery and typed execution

Hermes' central command registry makes a secret-free command catalog feasible,
but command discovery and command execution are separate capabilities. A later
**Gateway Command Discovery API** may return bounded names, aliases,
descriptions, argument declarations, availability, safety class, interaction
requirements, and the exact typed API capability—if any—that implements each
command.

Mentat may display that catalog, but it must continue to execute only its own
versioned allowlist of fixed handlers. Hermes commands differ in safety,
platform dependencies, confirmation behavior, and CLI or gateway availability.
There must be no generic endpoint that accepts an arbitrary slash-command
string. Commands become remotely actionable only through separately
advertised, structured interfaces such as Runs stop, Runs approval, session
creation, runtime selection, or another reviewed typed capability.

## Capability prerequisites and remaining blockers

### Kanban

Remote beta parity uses the maintained authenticated Kanban surface. Mentat
requires a remote host that:

- is advertised through machine-readable capabilities;
- accepts the same API-server bearer authentication as the selected endpoint,
  or another documented non-ephemeral server-to-server credential;
- exposes bounded board, profile, task, run, comment, and event records;
- supports the fixed mutations Mentat already previews and confirms;
- supplies revisions or equivalent state needed to reject stale actions; and
- permits operation-specific read-back verification and idempotency.

On hosts that do not advertise and verify that contract, Mentat labels remote
Kanban unavailable. Generated-file retrieval is a separate optional capability:
version one permits at most 10 explicit latest-completion files, 100 MiB each,
and 250 MiB combined. It never enables remote workspace browsing or path-based
downloads. Mentat renders local Home data before this background check, backs
off failed transfers, and stops automatically retrying hosts that do not
advertise the artifact contract. A manual task refresh checks the remote
completion revision again and can restore a missing private snapshot.
Raster files are structurally decoded with fixed frame and pixel ceilings at
both boundaries, then re-encoded as metadata-free canonical snapshots.
Malformed files are rejected; unknown chunks, embedded metadata, appended
payloads, and the original untrusted container are never published. The
browser presents delegated images as download-only file cards; it does not
decode the original artifact as a Home-page thumbnail.
It must not acquire, expose, or replay the dashboard's process/session token as
a remote server credential or call dashboard-plugin routes as though they were
the advertised API-server surface. Mentat must not invoke SSH, interpolate
slash commands, mount the Hermes home, read `kanban.db`, or acquire/replay a
dashboard WebSocket credential.

### Complete profile discovery

The maintained runtime advertises an authenticated, capability-gated complete
profile inventory with stable bounded identifiers. The separate runtime
inventory adds only current provider/model IDs. Hosts missing either contract
degrade clearly; local filesystem or CLI discovery is never a remote
substitute.

### Clarification handling

The maintained runtime advertises an API-key-authenticated clarification
request/response surface with stable request identifiers, bounded typed
answers, exact run binding, persistent event streaming, and post-response
status verification. Hosts missing any part fail closed. Mentat never
substitutes free-form chat, dashboard-token replay, or an undocumented
endpoint.

## Implementation order

Remote work begins only after the early CI guardrail and the operator-data root
can store configuration safely outside the install. Reviewed slices then proceed
in this order:

1. connection configuration, secret storage, HTTPS validation, and bounded
   health/capability discovery; **Milestone 2A foundation implemented**;
2. a transport-neutral Hermes adapter interface that preserves local behavior;
   **Milestone 2B foundation implemented**;
3. remote Console runs, bounded events/status, and cancellation;
   **Milestone 2C implemented for the default profile**;
4. remote session list and replay through supported endpoints; **Milestone 2E
   read-only visibility implemented**. Continuation, approval, and clarification
   responses are enabled only when the exact verified contracts are advertised;
5. bounded Context Pack text and supported image inputs; **Milestone 2F
   implements exact one-use, path-free Context Pack text and capability-gated
   bounded Runs image data URLs**;
6. remote skill and toolset visibility through exact advertised authenticated
   read-only endpoints; **Milestone 2G implemented with bounded Settings
   metadata and fail-closed connection binding**;
7. bounded recent-session message search through the existing authenticated
   session reads; **Milestone 2H implemented with all-or-nothing 12-session
   coverage and explicit list, compaction, and result limits**;
8. read-only profile discovery through a supported authenticated capability;
9. Kanban delegation and follow-up through a supported authenticated capability;
10. capability-gated degradation, compatibility, recovery, and cross-platform
   remote-parity tests.

No later step may invent a workaround for a missing earlier capability.

After that baseline contract is stable, the next operator-facing slices are:

11. the setup and CLI connection experience described in
    **Operator experience: local and remote selection**, initially for local
    plus one remembered remote endpoint; **implemented**. The Settings selector
    remains deferred; and
12. the Hermes-fork capability and Mentat profile-default **Remote Runtime
    Selector** described in **Provider runtime selection**; **implemented with
    exact capability gating, revision-bound confirmation, verification, and
    rollback**.

Command discovery and session-scoped runtime overrides remain later,
separately reviewed capabilities.

## Beta exit evidence

Remote Hermes support is ready for external beta only when:

- local mode retains its existing behavior;
- a clean Mentat install can configure exactly one remote endpoint without
  placing its secret in the application directory;
- the mandatory capabilities pass against a supported Hermes version over
  verified HTTPS;
- unavailable degradable features are clear and non-actionable;
- endpoint switching invalidates bound state and cannot cross profiles/hosts;
- clarification requests and responses preserve exact endpoint, run, and
  request binding;
- Kanban mutations preserve preview, confirmation, locking, and read-back;
- logs, diagnostics, browser responses, and backups remain secret-free; and
- interruption, timeout, authentication failure, capability change, and
  upgrade/rollback cases have automated coverage.

The maintainer matrix met these technical criteria on 2026-07-24 against one
operator-managed Hermes `0.19.0` endpoint over authenticated,
certificate-verified HTTPS. This does not replace the separate signed-RC,
clean-platform, or external-cohort gates in `ROAD_TO_BETA.md`. Other Hermes
builds remain capability-driven: Mentat enables only the exact advertised
contract and fails closed when a required piece is missing.

This contract relies only on documented Hermes surfaces. Hermes' own
[security policy](https://github.com/NousResearch/hermes-agent/security)
requires authorization across network trust boundaries; Mentat does not weaken
that requirement.
