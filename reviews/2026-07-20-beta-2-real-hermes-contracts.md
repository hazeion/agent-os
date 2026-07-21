# Feature Slice Review: Real Hermes Milestone 2 contract integration

Status: Ready to publish; GitHub CLI authentication required  
Slice: `beta-2-real-hermes-contracts`  
Date: `2026-07-20`  
Review log: `reviews/2026-07-20-beta-2-real-hermes-contracts.md`

## Slice contract

### Goal

Finish secure remote-Hermes parity by letting Mentat recognize and safely use
the six authenticated contracts provided by the connected `mentat-beta-contracts`
Hermes runtime.

### In scope

- Capability-gated, fixed-path support for exact approval responses and typed
  clarification responses.
- Capability-gated exact stoppable session continuation, read-only complete
  profile inventory, revisioned/idempotent Kanban operations, and bounded
  data-URL Runs image input.
- Existing Mentat preview, confirmation, lock, reservation, and post-operation
  verification boundaries adapted to the remote transport where applicable.
- Focused automated tests, a local live-runtime end-to-end check, and Milestone
  2 documentation/evidence updates.

### Out of scope

- Hermes profile, provider, credential, MCP, skill-content, or general file
  administration.
- Arbitrary remote endpoints, arbitrary shell commands, browser-to-Hermes
  calls, dashboard/session-token use, or direct remote data-store access.
- General file or artifact transfer, public deployment, installer work, and
  Milestone 3 implementation.
- Any change to Hermes itself beyond using the already-connected fork runtime.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Mentat accepts all six contracts only when their exact capability versions, limits, and fixed endpoints are authenticated and valid. | Contract and negative-path tests | Pass |
| AC-2 | A remote Console can present a bounded approval preview and submit only a current exact `once` or `deny` answer; typed clarification answers are bound to the current request. | Lifecycle and fixed-request tests | Pass; provider-driven live request remains nondeterministic |
| AC-3 | A remote session can be continued only from a fresh exact descriptor and remains controllable through the Runs lifecycle. | Descriptor, stale-alias, and fixed-request tests | Pass; no synthetic live session was created |
| AC-4 | Mentat exposes only safe complete remote profile metadata and routes supported remote work through selected served profiles. | Schema/route tests and authenticated live inventory | Pass |
| AC-5 | Remote delegation and follow-up preserve exact confirmation, revision, idempotency, locking, and authoritative read-back. | Kanban contract/negative tests and live safe fixture | Pass |
| AC-6 | Remote Console image input sends only validated, bounded data URLs from Mentat's private attachment boundary; paths, URLs, and unsupported runtimes fail closed. | Input and fixed-request tests | Pass; provider vision behavior is not claimed |
| AC-7 | Local behavior remains compatible; evidence, roadmap, operator docs, and concise first-user README guidance reflect the verified runtime contract. | Full suite, manual route checks, docs checks | Pass |

### Constraints and recovery

- Safety: exact authenticated capability/endpoint validation; browser receives
  no key, remote ID, path, or raw upstream payload; failed verification is
  reported as partial failure and cannot claim completion.
- Compatibility: local Hermes behavior remains unchanged; unsupported remote
  runtimes remain clearly non-actionable.
- Rendered behavior: unavailable actions remain clear; newly available actions
  use the existing compact UI and confirmation flow.
- Rollback or recovery: selecting another connection invalidates remote-bound
  state; reverting this Mentat branch restores the prior fail-closed behavior.
- Documentation targets: `ROAD_TO_BETA.md`, `REMOTE_HERMES.md`, `README.md`,
  and this log.
- Version-control strategy: branch `feat/m2-real-hermes-contracts` from `main`,
  ready PR back to `main` after final review.

### Scope discussion and approval

- Recommendation and rationale: integrate the six already implemented,
  capability-advertised contracts as one final M2 slice because they jointly
  supply the mandatory remote-parity exit criteria and share one live runtime.
- Alternatives considered: keep M2 paused for upstream releases (safer for a
  public distribution, but does not meet the maintainer's fork-runtime goal),
  or enable unverified APIs (rejected; violates the capability boundary).
- User decisions: the maintainer explicitly directed completion against the
  connected fork, live end-to-end checks, soft approvals, full evidence, and
  two adversarial read-only reviews before merge/push.
- Process exception: the maintainer's standing approval covers scope, test
  strategy, commit, push, and publication actions. This intentionally replaces
  the skill's usual separate approval pauses; the final publication packet and
  outcome review will still be recorded and reported.
- Approved at: 2026-07-20 in the maintainer's current request.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | The client recognizes only the earlier remote flags. | Unit tests for strict six-contract capability schema and endpoint validation. | A runtime cannot enable a feature with a loose or forged advertisement. | Does not prove provider-backed execution. |
| AC-2 | Approval requests currently stop the run; clarification is unavailable. | Lifecycle tests for previews, stale request rejection, choices, and safe response post-checks. | Mentat preserves exact request binding and fails closed. | A provider may not naturally request every prompt shape. |
| AC-3 | Remote continuation is disabled. | Descriptor freshness, stale/rejected descriptor, and stop lifecycle tests. | A continuation binds the selected current session tip. | Live execution depends on the configured provider. |
| AC-4 | Remote profile inventory is unused. | Strict inventory/schema tests plus authenticated live list. | Only complete safe roster data reaches Mentat. | Does not add profile mutations. |
| AC-5 | Delegation uses only the local CLI adapter. | Revision/idempotency/confirmation/read-back tests plus a harmless live board read/create/reclaim sequence. | Remote mutations use exact protected API semantics. | Live test must not disturb real queued work. |
| AC-6 | Runs images are rejected remotely. | Data-URL/count/size/type and path/URL rejection tests plus a harmless image run if provider accepts it. | Input remains private and bounded. | Model vision support may vary independently of transport acceptance. |
| AC-7 | M2 remains marked in progress. | Focused tests, full suite, browser/manual route checks, documentation assertions. | No regression and accurate operator/first-user information. | A local loopback runtime is not a public HTTPS deployment. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `GET /v1/capabilities` through the configured Mentat connection | Local fork runtime at loopback | Pass | All six target flags are advertised, while Mentat's current summary does not recognize them. |
| `POST /api/hermes/connection/test` | Local Mentat and connected fork | Pass | Liveness/readiness is verified; existing remote Console basic run capability is available. |
| `git status --short --branch` | Mentat repository | Pass | Clean `main` before creating this slice branch. |

### Test discussion and approval

- User questions and decisions: live end-to-end validation, soft approval
  handling, evidence completion, and two final adversarial reviews are
  explicitly required.
- Accepted coverage gaps: public HTTPS/cross-platform deployment is a later
  milestone; live provider behavior may prevent forcing every interactive event
  type, so the authenticated contract tests remain required evidence.
- Approved at: 2026-07-20 under the recorded standing approval.

## Implementation record

### Changes

- Extended the remote client with strict capability/version/limit/endpoint
  validation for the six fork contracts. The client still has no generic HTTP
  surface.
- Added exact continuation descriptors, safe approval and clarification
  responses, bounded Runs data-URL images, complete safe profile discovery, and
  a revisioned/idempotent remote Kanban adapter.
- Routed Agent Console profile selection, continuation, and images through the
  advertised remote contract. Approval and clarification events retain only the
  validated safe request representation and require an explicit local operator
  response.
- Routed remote profile and Kanban capability payloads through the authenticated
  API rather than the local Hermes CLI.

### Deviations and decisions

- The Hermes Kanban create/action response omits the optional `board` field
  even though a task read includes it. Mentat treats a missing board only as the
  caller's already-validated board; a different board still fails closed.
- The live Kanban fixture was created unassigned and then revision-bound
  blocked. It is retained as an audit record because the supported API does not
  expose deletion.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m py_compile remote_hermes.py` and `python3 -m unittest tests.test_remote_hermes -v` | macOS, Python 3.13 | Pass | 30 passed | Existing remote-client baseline remains green. |
| Python compilation and `node --check public/{app,core}.js` | macOS, Python 3.13 / Node | Pass | Syntax checks passed | No generated files. |
| `python3 -m unittest tests.test_remote_hermes tests.test_hermes_kanban -v` | macOS, Python 3.13 | Pass | 44 passed | Includes new remote Kanban revision/idempotency tests. |
| Authenticated live discovery/profile/Kanban reads against `127.0.0.1:8642` | Connected `hazeion/hermes-agent` `mentat-beta-contracts` fork | Pass | six target capabilities available | API key read server-side only; never logged. |
| Live remote Console prompt through `POST /api/agent-console/runs` | Local Mentat -> connected fork | Pass | 1 completed run | Exact reply completed with submission, reasoning, completion, and status evidence. |
| Live revisioned Kanban fixture | Connected fork | Partial then verified | 1 unassigned fixture retained, blocked | First parser exposed the fork response's omitted optional `board`; corrected parser, then a fresh exact revision/idempotency-bound comment returned HTTP 200. |
| Final loopback Console, profile, and Kanban payload reads | Local Mentat -> connected fork | Pass | 1 served profile; all allowed Kanban operations available | Browser payload contained only normalized Mentat data; no API key, path, or upstream task identifier was recorded here. |

### Full suite

`python3 -m unittest discover -s tests -v` ran on macOS/Python 3.13 and
completed with **700 tests passed and 4 skips**. The four skips are native
Windows-only filesystem checks. Stale remote-limit assertions were replaced by
contract-gated tests, and local-mode tests now explicitly select the local
adapter instead of inheriting the operator's active remote connection.

### Rendered or manual behavior

The existing compact Console request controls render bounded approval choices,
structured choice prompts, and a 2,000-character text-answer input. JavaScript
syntax checks and focused UI contract tests pass.

## Adversarial review

### Round 1

- Safety review found three P1 issues: interactive runs stopped before a
  response, interactive event text bypassed browser-private-text checks, and
  image reads bypassed the no-follow digest-checked attachment reader. It also
  identified prompt-response binding and malformed-evidence hardening work.
- Compatibility review found the interactive-text issue (P0), unsupported
  non-active profile selection (P1), paused-run lifecycle failure (P1), and
  stale roadmap/changelog wording.
- Fixes: remote interaction fields now use the same known-identity and generic
  browser-private-text checks; images use the attachment reader's no-follow
  regular-file, size, and SHA-256 verification; only the active remote profile
  is runnable; paused interactions retain their bound run and resume only after
  a verified `running` read-back; clarification answers are prompt-bound;
  continuation plus image input rejects before queueing; docs are aligned.

### Round 2

- Compatibility re-review found an unchanged `waiting_*` status after a posted
  response could clear the pending request too early. Mentat now requires an
  exact verified `running` state, otherwise retains the pending action and
  reports a partial result.
- Safety re-review found generic path/credential-shaped interactive text and
  concurrent conflicting responses. Mentat now rejects generic browser-private
  text and atomically claims the exact request before the outbound mutation.
- Final safety re-review: no P0 or P1 findings. The partial/unverified response
  path deliberately retains its claim and fails closed rather than allowing a
  conflicting retry.

## Documentation updates

- Roadmap: Milestone 2 is recorded complete for the maintained fork, with an
  explicit upstream-runtime compatibility caveat.
- Changelog: Records the capability-gated contract set and retained file limits.
- Operator docs: `REMOTE_HERMES.md` distinguishes verified-fork support from
  upstream release support and retains all fail-closed boundaries.
- README: Keeps remote setup optional and beginner-friendly.
- Project/session notes: this log.
- Documentation verification: `tests.test_beta_contract` and
  `tests.test_ci_workflow` pass.

## Publication gate

- Proposed files: 24 implementation, test, documentation, and review-log files
  listed by `git diff --name-only`; all belong to this M2 slice.
- Branch and base: `feat/m2-real-hermes-contracts` -> `main`.
- Commit message: `Complete verified remote Hermes contracts`.
- PR title: `Complete verified remote Hermes contracts`.
- PR summary: capability-gated six-contract integration, hardened interactive
  Console lifecycle, strict attachment and schema boundaries, green full suite,
  and verified maintained-fork evidence.
- Unresolved risks: the live runtime is a user-maintained fork; external beta
  distribution still needs the documented supported-runtime decision.
- User authorization and scope: standing authorization recorded above.
- Commit hash: Pending GitHub CLI authentication.
- Ready PR URL: Pending GitHub CLI authentication.

## Outcome review

- Classification: Pending.
- Acceptance criteria summary: Pending.
- Potential bugs or untested paths: Pending.
- Remaining reviewer dissent: Pending.
- Compatibility/migration/rollback concerns: Pending.
- User decision: Pending.
- Next slice authorized: No.
