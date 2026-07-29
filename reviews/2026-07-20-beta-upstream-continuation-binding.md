# Milestone 2 upstream blocker — exact stoppable continuation

Status: implemented and published upstream as a draft; Mentat integration remains blocked pending upstream merge and release

## Goal

Add the smallest supported Hermes HTTP contract that lets an authenticated
client continue the exact currently visible session tip through the existing
Runs lifecycle. The accepted continuation must retain pollable status, events,
approval and clarification handling where advertised, cancellation, and stop.

Mentat will continue to fail closed until the capability is merged, released,
advertised, and independently verified against an installed Hermes version.

## Standing approval and review timing

The maintainer approved every remaining Road to Beta slice without another
scope, test, commit, push, or publication pause. The two independent
adversarial reviews remain deferred until every Milestone 2 slice is complete,
as explicitly directed by the maintainer.

## Upstream baseline

- Hermes Runs accepts a caller-supplied `session_id`, but currently treats it
  as correlation/task identity and does not load or bind persisted history.
- Session chat can load history, but does not expose the Runs status, event,
  cancellation, and stop contract required by Mentat's Agent Console.
- Session list projection can advance a compression root to its current tip.
  A safe continuation must bind that exact resolved tip and the exact model-fed
  message snapshot; an old, cross-session, malformed, or changed binding must
  fail before a run is allocated.

## Scope

### Included

- A bearer-authenticated, read-only endpoint that issues a versioned
  continuation descriptor for one existing session after resolving its current
  resumable tip.
- A bounded, transport-safe revision derived from the exact normalized message
  history that Hermes would feed to the continued run.
- A versioned `continuation` object accepted only by `POST /v1/runs`.
- Exact session, resolved-tip, and revision verification before run allocation.
- Loading the verified persisted history into the new Runs turn.
- Existing Runs status/events/approval/clarification/stop behavior for the new
  turn, including a returned effective session identity in private upstream
  status.
- Capability and endpoint advertisement plus operator/developer documentation.
- Compatibility behavior proving ordinary new Runs and the existing
  correlation-only `session_id` field remain unchanged.

### Excluded

- Mentat UI or adapter enablement before the upstream capability is available.
- Treating arbitrary `session_id`, client-supplied history, or session chat as
  proof of continuation.
- Session create, fork, rename, end, delete, branch, or database mutation APIs.
- Durable bearer grants, cross-endpoint continuation, remote database access,
  or direct Hermes file/database writes.
- Profile inventory, Kanban, richer content inputs, or other Milestone 2
  blockers.
- README changes; first-run installation guidance is unchanged by this
  upstream contract slice.

## Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Capabilities advertise a distinct versioned stoppable-continuation feature and exact fixed endpoint. | Capability tests | Complete |
| AC-2 | The descriptor resolves compression roots to the current tip and binds the exact normalized model-history revision. | Endpoint/unit tests | Complete |
| AC-3 | `POST /v1/runs` accepts only a well-formed descriptor whose session, tip, version, and revision still match; stale, unknown, cross-session, and changed descriptors fail before run allocation. | Negative and race-oriented handler tests | Complete |
| AC-4 | An accepted continuation supplies the verified persisted history to the agent and remains controllable through status, events, cancellation, and stop. | Runs integration tests | Complete |
| AC-5 | Explicit client history cannot be combined with continuation, and the legacy `session_id` input remains correlation-only. | Compatibility tests | Complete |
| AC-6 | Responses and errors disclose no message content, local path, credential, raw database state, or signing secret. | Schema/redaction tests | Complete |
| AC-7 | Focused tests, lint/compile checks, canonical-suite attempt, docs, branch publication, and draft upstream PR complete. | Verification record | Complete with full-suite environment limitation recorded below |

## Proposed wire contract

Descriptor request:

```text
GET /v1/sessions/{session_id}/continuation
```

Descriptor response:

```json
{
  "object": "hermes.session.continuation",
  "version": 1,
  "session_id": "resolved-session-tip",
  "revision": "sessionrev_<64 lowercase hex characters>"
}
```

Run submission:

```json
{
  "input": "Continue with the next step",
  "continuation": {
    "version": 1,
    "session_id": "resolved-session-tip",
    "revision": "sessionrev_<64 lowercase hex characters>"
  }
}
```

The descriptor is not authorization. The API key remains the authentication
boundary, and Hermes recalculates the exact binding immediately before
allocating the run. The descriptor contains no transcript content.

## Test strategy

| Area | Planned evidence |
| --- | --- |
| Contract | Capability flags/version, exact endpoint, auth, response allowlist |
| Binding | Existing session, compression-tip resolution, deterministic revision, changed content/identity, wrong session, stale revision |
| Runs | Persisted history delivery, status identity, events and stop behavior, no allocation on rejection |
| Compatibility | Plain new run, legacy `session_id`, explicit history, previous response, existing session reads |
| Privacy | No transcript reflection in descriptor/errors; fixed revision syntax |
| Regression | Focused API/session tests, Python compile/lint, canonical suite against pristine-main baseline |

## Implementation record

- Added a bearer-authenticated continuation descriptor route to the existing
  API server and advertised its versioned exact/stoppable capability.
- Added an atomic `SessionDB.get_continuation_snapshot()` read that resolves a
  compression tip and captures its active message identities and normalized
  model-fed history.
- Bound revisions to the descriptor version, resolved session ID, message row
  identities, and normalized history. A delete-and-recreate with identical text
  therefore still invalidates the descriptor.
- Added strict descriptor parsing, constant-time revision comparison, and a
  profile-scoped pre-verification reservation. Only one exact continuation for
  a profile/session may be active at once.
- Loaded only the verified snapshot into the continued run and retained the
  existing Runs status, events, approval, clarification, cancellation, and stop
  lifecycle. The continuation claim is held until executor-backed work exits.
- Preserved ordinary new Runs and the existing correlation-only `session_id`
  behavior.
- Documented the public contract in Hermes' user and developer API guides.

## Verification record

- Post-rebase changed-surface gate: **56 passed** across
  `test_session_api.py` and `test_api_server_runs.py`.
- Complete API-server surface: **416 passed**.
- Expanded API/session/storage surface: **669 passed**.
- Python compilation, Ruff, and `git diff --check`: passed.
- Docs diagram lint: **365 files checked, 0 errors**.
- Docusaurus production build: passed for English and zh-Hans. It emitted
  existing unrelated link warnings and used supported fallback indexes because
  the local system Python lacked PyYAML and the sandbox could not fetch the live
  skills index.
- Canonical `pytest -q` attempt: stopped at 43% after an unrelated Chromium
  launch fixture left a browser subprocess alive for more than 30 minutes. The
  browser-dependent remainder was contaminated when that orphan was terminated,
  so it is not reported as a pass or a regression comparison. The changed
  continuation surface was rerun cleanly afterward and passed 56/56.
- The post-rebase verification ran against upstream `main` commit
  `18ca0e862cc970c20123226c550def9668d2fb89`.

## Publication packet

- Fork: `hazeion/hermes-agent`
- Branch: `feat/http-exact-stoppable-continuation`
- Current commit after the Milestone 2-wide review fix:
  `d0273162ffb590e40683dde61b6359263756e62c`.
- The review found that exact-continuation endpoints inherited optional API
  authentication. Both descriptor issuance and descriptor-based Runs now
  require a configured bearer key, and capability discovery reports the
  feature unavailable without one. Regressions prove a no-key client cannot
  obtain a descriptor or submit it, while descriptor binding/lifecycle tests
  still pass (58 focused tests after the fix).
- Upstream draft PR:
  [NousResearch/hermes-agent#68177](https://github.com/NousResearch/hermes-agent/pull/68177)
- Mentat must not advertise or enable this integration until the upstream
  capability is merged, released, and independently verified against the
  installed Hermes runtime.
