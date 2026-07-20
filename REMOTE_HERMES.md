# Remote Hermes Capability Contract

Status: Approved beta architecture; Milestones 2A through 2C implemented; approval response audited and blocked
Approved: 2026-07-16

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
the established local launch contract, and supports one plain default-profile
remote run through fixed submission, event, status, and stop operations.
Bounded read-only remote session list and replay now use the advertised session
resource endpoints and process-private connection-bound aliases. Session
continuation, content transfer, complete profile discovery, and Kanban remain
later capability-gated work. Approval response was audited after 2C and remains
blocked on an exact upstream request-binding capability and a structured safe
preview.
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
| Authenticated readiness and capability discovery | `remote_hermes.py` validates fixed `/health/detailed` and `/v1/capabilities` responses and returns an allowlisted summary | Hermes documents bearer-authenticated `GET /health/detailed` and machine-readable `GET /v1/capabilities` in its [API Server](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/api-server.md) | API-server bearer key over verified HTTPS | Validate schema/version, endpoint identity, advertised auth, bounded readiness, model, and capability set | **Required** foundation implemented; active-profile inventory remains blocked |
| Hermes configuration and overview summary | `server.py` reads local `CONFIG_PATH` metadata and combines it with normalized profile/provider discovery | Remote health, capabilities, and model endpoints can supply bounded connection/profile/model status; remote configuration-file metadata is unnecessary | API-server bearer key; never request or expose raw remote configuration | Normalize an allowlisted summary and suppress upstream errors, paths, headers, and secret-shaped values | Safe connection/profile/model status is **Required**; file/configuration details remain local-only |
| Agent Console conversation and streaming | `hermes_transport.py` selects a binding-aware transport, preserves the profile-scoped local CLI launch, and implements a default-profile remote Runs adapter | Hermes documents Chat Completions, Responses, run submission, SSE events, approvals, and session chat in the [API Server](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/api-server.md) and [programmatic integration guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/programmatic-integration.md) | API-server bearer key over verified HTTPS; key remains in Mentat's server process | Bind each run to the active endpoint; validate event schemas and terminal state; never retry submission | **Required**; plain default-profile remote runs implemented, sessions and richer inputs pending |
| Run status, progress, approval, cancellation, and stopping | `server.py` and `agent_run_history.py` normalize remote events/status and keep upstream run identity private | `/v1/runs`, run status, SSE events, approval, and stop are documented and advertised by `/v1/capabilities`; the current approval mutation accepts no request ID/revision/hash | Same API-server bearer boundary | Capability match before action, exact live-run/request binding, one claimed stop attempt, and post-action status read-back | **Required**; status, progress, cancellation, and stopping implemented; approval response audited and blocked, so requests stop safely |
| Clarification requests and responses | Local Console can retain and display bounded run interaction state | Hermes' [programmatic integration guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/programmatic-integration.md) describes `clarify.request` for its TUI gateway, but the documented HTTP API does not advertise an equivalent clarification-response operation | No approved API-server bearer capability yet | Require a machine-readable request event, typed bounded response, exact run/request binding, and post-response status verification | **Required**; upstream/compatibility blocker |
| Session list, replay, continuation, and search | `server.py` preserves local `state.db` reads and routes selected remote history through `remote_hermes.py` | Hermes advertises exact session list/detail/messages endpoints; its list projects compression roots to current tips, while messages for those tips omit ancestor turns. Runs accepts a session ID without a distinct continuation capability, and session-chat streaming has no matching public status/stop operation | API-server bearer key; no remote database access; upstream IDs remain process-private | Normalize bounded user/assistant history, bind opaque aliases to the selected projected identity, label compressed history partial, and reject stale/cross-endpoint aliases or changed message identity | **Required**; bounded read-only list/replay implemented in 2E, continuation blocked pending an exact stoppable capability, remote search pending |
| Read-only agent/profile discovery | `hermes_profiles.py` runs inside the local Hermes runtime; Kanban also supplies assignee/profile context | `/v1/models` identifies the endpoint's active profile/model, but does not document complete profile inventory; Kanban's `/api/plugins/kanban/profiles` is an unauthenticated loopback plugin HTTP route | The loopback plugin route has no approved remote authentication boundary; remote beta requires a new API-key-authenticated, capability-advertised inventory | Require a capability-advertised bounded profile inventory and reconcile it with the endpoint's active profile | **Required**; upstream blocker for complete inventory |
| Profile creation | `hermes_profile_creation.py` and fixed Hermes profile operations | No API-key-authenticated profile-creation capability is advertised by the API server | No approved remote boundary | Exact preview, capability match, profile-bound confirmation, and verified refresh would be required | **Graceful degradation**; remote unavailable unless upstream adds support |
| Profile identity inspection and synchronization | `hermes_profile_identity.py` resolves local profile metadata and the managed `SOUL.md` block through Hermes APIs | No supported API-server identity capability is advertised | Direct remote `SOUL.md` access is prohibited | Existing revision-bound preview, confirmation, atomicity, verification, and rollback contract would still apply | **Graceful degradation**; remote unavailable unless upstream adds support |
| Profile deletion | `hermes_profile_deletion.py` calls the supported local Hermes profile API | No supported API-server deletion capability is advertised | No approved remote boundary | Existing exact preview, active-run exclusion, confirmation, and post-delete discovery would still apply | **Graceful degradation**; remote unavailable unless upstream adds support |
| Provider/model inventory and switching | `hermes_provider_switching.py` loads local picker context and performs a fixed profile-model operation | The API surface advertises the endpoint model, but the documented model field is not a complete provider-administration contract | Hermes remains credential owner; Mentat must never receive provider secrets | Require explicit authenticated inventory, exact preview, active-run lock, switch verification, and rollback capability | **Graceful degradation**; remote administration blocked pending a supported capability |
| Skill and toolset visibility | `hermes_skills.py` discovers the local built-in catalog inside the Hermes runtime | The API capability document advertises skills/toolset visibility when supported | API-server bearer key | Validate bounded catalog metadata and enable visibility only when advertised | **Required**; supported upstream, Mentat adapter needed |
| Skill selection | `hermes_skills.py` applies local profile-scoped selection through Hermes | No API-server skill-selection mutation is part of the approved stable surface | No approved remote boundary | Exact profile and selection preview, confirmation, capability match, and refreshed catalog | **Graceful degradation**; remote unavailable unless upstream adds support |
| Durable Kanban delegation and follow-up | `hermes_kanban.py` uses fixed shell-free `hermes kanban` operations with task/run read-back | Hermes documents localhost dashboard-plugin HTTP routes that are unauthenticated by design; only its events WebSocket uses an ephemeral query token in the [Kanban security model](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/kanban.md) | Neither unauthenticated HTTP nor the dashboard WebSocket token is an approved remote server-to-server boundary | Preserve exact preview/confirmation, mutation locks, in-flight reservation, live task/run binding, idempotency, and operation-specific read-back | **Required**; upstream authenticated capability blocker |
| Cron inventory | `server.py` reads the local Hermes cron store; queue controls already fail closed | Hermes documents bearer-authenticated Jobs API list/CRUD/pause/resume/run endpoints, including `GET /api/jobs` | API-server bearer key; direct remote cron-file access remains prohibited | Before integration, verify capability advertisement, bounded schema, read-only inventory semantics, and correspondence with Mentat's existing job revisions; mutations remain separately deferred | **Graceful degradation**; documented upstream surface needs compatibility validation |
| Console input attachments and Context Packs | `agent_console_attachments.py`, `agent_console_artifacts.py`, and Mentat-owned Context Pack resolution stage local snapshots | Hermes API supports inline images; its documented API does not accept general uploaded files or arbitrary local paths | API-server bearer key; Mentat-owned files stay local unless explicitly transmitted through a supported bounded content type | Revalidate content, enforce size/type bounds, bind bytes/text to the exact run preview, and never transmit a path | Text instructions and supported inline images are **Required**; general files may **gracefully degrade** |
| Assistant-created artifacts | Mentat discovers files only in a trusted local run export directory | No general remote artifact-download contract is established by the approved API surface | No arbitrary remote file URL or path may be opened | Require an advertised resource endpoint, bounded metadata/content, type validation, and Mentat-owned snapshot before display | **Graceful degradation** pending a supported resource contract |
| Calendar, notes, planning, projects, tasks, search, themes, and reminders | Mentat-owned storage and integrations; Google Calendar is read-only | No Hermes access is required for the core feature behavior | Local Mentat boundary | Preserve existing local validation and mutation contracts | **Mentat-local** and available in both connection modes |
| Google Calendar credential location | `server.py` currently resolves `google_token.json` below local `HERMES_HOME` | Not a remote Hermes API concern | Credentials must move to the future Mentat operator-data root rather than a remote Hermes host | Migration and read-only calendar verification in Milestone 1 | **Mentat-local**; storage coupling must be removed before remote beta |
| Agent Pulse heartbeat observations | Project-owned `data/agents.json` and the local Mentat heartbeat endpoint | No Hermes API is required | Local Mentat boundary | Preserve observation-only semantics; never treat heartbeats as profile authority | **Mentat-local** |
| Connection setup and local/remote runtime selection | `remote_hermes.py` owns selection and binding rotation; `hermes_transport.py` selects the exact Console transport and revalidates before queue and launch | Remote selection is Mentat-owned configuration; authenticated readiness/capabilities describe the selected remote | Owner-only Mentat operator configuration outside the install | Preserve local discovery, validate one explicit remote origin, and invalidate all endpoint-bound state on selection changes | **Required** 2A/2B foundations implemented; Settings UI and remote feature routing remain |
| Hermes diagnostics | `health_checks.py` probes the local runtime, profiles, paths, and integration health | Public `/health` supplies liveness only; authenticated `/health/detailed` and `/v1/capabilities` supply bounded remote readiness | Bearer auth required for trusted readiness/capability conclusions | Redact upstream details; distinguish unreachable, unauthenticated, degraded, unsupported, and healthy states without exposing paths or secrets | **Required**; remote diagnostics adapter needed |

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
2. A non-loopback remote endpoint must use `https`. URLs containing user info,
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

## Mandatory upstream blockers

### Kanban

Remote beta parity requires the durable Kanban path. Mentat needs an upstream
surface that:

- is advertised through machine-readable capabilities;
- accepts the same API-server bearer authentication as the selected endpoint,
  or another documented non-ephemeral server-to-server credential;
- exposes bounded board, profile, task, run, comment, and event records;
- supports the fixed mutations Mentat already previews and confirms;
- supplies revisions or equivalent state needed to reject stale actions; and
- permits operation-specific read-back verification and idempotency.

Until that exists and is verified, Mentat must label remote Kanban unavailable.
It must not expose or call the unauthenticated dashboard-plugin HTTP routes over
the network. Mentat must not invoke SSH, interpolate slash commands, mount the
Hermes home, read `kanban.db`, or acquire/replay the dashboard WebSocket's
ephemeral token.

### Complete profile discovery

The API server identifies the active endpoint profile, but the beta also
requires read-only discovery of the profiles/agents available for routing and
delegation. Mentat needs an authenticated, capability-advertised inventory with
stable identifiers and bounded public descriptions. Local filesystem or CLI
discovery is not an acceptable remote substitute.

### Clarification handling

Remote Console parity requires operators to answer a running agent's bounded
clarification request. Hermes documents a typed `clarify.request` event for its
TUI gateway, but the current HTTP API does not advertise a corresponding
server-to-server response operation. Mentat needs a capability-advertised,
API-key-authenticated request/response surface with stable request identifiers,
bounded typed answers, exact run binding, and post-response status
verification. Until that exists and is verified, Mentat must not claim complete
remote Console parity or substitute free-form chat, dashboard-token replay, or
an undocumented endpoint.

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
   read-only visibility implemented**. Continuation remains blocked until
   upstream advertises an exact stoppable capability; approval responses remain
   blocked until upstream provides an exact request
   binding and structured safe preview; clarification responses remain blocked
   until a typed capability exists;
5. bounded Context Pack text and supported image inputs;
6. read-only profile discovery through a supported upstream capability;
7. Kanban delegation and follow-up through a supported upstream capability;
8. capability-gated degradation, compatibility, recovery, and cross-platform
   remote-parity tests.

No later step may invent a workaround for a missing earlier capability.

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

This contract relies only on documented Hermes surfaces. Hermes' own
[security policy](https://github.com/NousResearch/hermes-agent/security)
requires authorization across network trust boundaries; Mentat does not weaken
that requirement.
