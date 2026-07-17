# Feature Slice Review: Remote Hermes Beta Contract

Status: Ready for publication approval
Slice: `beta-0-remote-contract`
Date: `2026-07-16`
Review log: `reviews/2026-07-16-beta-remote-contract.md`

## Slice contract

### Goal

Establish the authoritative beta product, security, licensing, and remote-capability contract before changing runtime behavior.

### In scope

- Adopt the MIT License with `Brandon Thomas` as the copyright holder.
- Define Mentat as a local, single-operator dashboard connected to one active local or remote Hermes endpoint.
- Require operator-supplied HTTPS and API credentials for remote connections.
- Make Console, sessions, runs, approvals, clarification, cancellation, stopping, skills/toolsets, Kanban delegation and result tracking, and read-only agent/profile discovery mandatory remote-beta capabilities.
- Permit graceful remote degradation for profile administration, identity editing, provider/model administration, cron inventory, and advanced artifact transfer.
- Prohibit direct remote Hermes-file access, SSH command adapters, mounted remote Hermes homes, and undocumented APIs.
- Inventory and classify every current Hermes integration and record API-key-authenticated remote Kanban as an upstream blocker until a supported interface is verified.
- Reorder the Road to Beta around this architecture and align its publication language with the reviewed-feature process.

### Out of scope

- Remote client implementation, configuration, credential storage, UI, or Hermes API calls.
- CI, data-root migration, upstream Hermes changes, or external publication.
- GitHub issue, commit, push, or pull request creation without later explicit authorization.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The standard MIT license is present with the approved copyright holder. | Focused contract test and file inspection. | Passed |
| AC-2 | The beta definition supports one local or remote Hermes endpoint. | Roadmap, README, and contract test. | Passed |
| AC-3 | Mandatory and degradable remote capabilities are unambiguous. | Capability matrix and contract test. | Passed |
| AC-4 | Every existing Hermes-backed Mentat feature is classified. | Source inventory mapped into `REMOTE_HERMES.md`. | Passed |
| AC-5 | Each capability records its adapter, remote evidence, authentication boundary, verification requirement, and status. | Manual matrix audit. | Passed |
| AC-6 | Remote credentials remain server-side, secret-free in browser/log surfaces, and outside tracked files. | Architecture contract and privacy inspection. | Passed |
| AC-7 | Non-loopback remote connections require verified HTTPS. | Architecture contract and focused test. | Passed |
| AC-8 | Capability discovery and unsupported operations fail closed. | Architecture contract and focused test. | Passed |
| AC-9 | Direct remote Hermes files and arbitrary remote execution are prohibited. | Architecture contract and focused test. | Passed |
| AC-10 | Remote Kanban's upstream dependency is documented without an unsafe workaround. | Capability matrix and source-linked manual review. | Passed |
| AC-11 | The roadmap orders implementation dependencies without implementing them in this slice. | Diff inspection and roadmap review. | Passed |
| AC-12 | Two independent adversarial reviewers report no unresolved blocking findings. | Review packets and reconciliation below. | Passed |

### Constraints and recovery

- Safety: No credentials, private paths, runtime mutations, unsupported remote adapters, or claims of implemented remote connectivity.
- Compatibility: Documentation must be platform-neutral and preserve existing local-only runtime behavior.
- Rendered behavior: Not applicable; no interface changes are allowed.
- Rollback or recovery: Revert documentation, test, review-log, and license files. No data or runtime recovery is required. Previously distributed MIT grants would remain effective for those copies.
- Documentation targets: `ROAD_TO_BETA.md`, `ARCHITECTURE.md`, `REMOTE_HERMES.md`, `README.md`, `CHANGELOG.md`, and `LICENSE`.
- Version-control strategy: Branch `codex/beta-0-remote-contract` from `main`; no commit, push, or ready PR without a later explicit publication approval.

### Scope discussion and approval

- Recommendation and rationale: Lock the local-Mentat/remote-Hermes boundary before CI, storage, or connection implementation so later slices share one security and capability target.
- Alternatives considered: Browser-to-remote-Mentat access; direct public Mentat hosting; full native Mentat authentication; remote Hermes file mounts; SSH command adapters; and reducing the beta to Console-only remote access. These were rejected or deferred because they either solve the wrong access direction, expand the trust boundary, or fail the requested parity goal.
- User decisions: Mentat remains local; one active Hermes endpoint; operator supplies a secure HTTPS endpoint and API key; most features should work remotely; direct Hermes files may remain inaccessible; Kanban and read-only profile discovery are mandatory; MIT selected with `Brandon Thomas` as copyright holder.
- Approved at: 2026-07-16 in the active Codex conversation.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | No public license exists. | `tests/test_beta_contract.py` plus license inspection. | The approved standard license is tracked. | Not legal advice. |
| AC-2, AC-3 | Roadmap assumes local Hermes and does not define remote parity. | Focused text-contract tests and cross-document audit. | Stable product commitments exist consistently. | Does not prove connectivity. |
| AC-4, AC-5 | No comprehensive Hermes adapter-to-remote-capability inventory exists. | Source search plus manual row-by-row matrix audit. | Current integrations and evidence are accounted for. | Upstream APIs may change later. |
| AC-6 through AC-10 | No approved remote trust boundary exists. | Focused contract tests, official-source links, and adversarial security review. | Unsafe implementation routes are explicitly prohibited and blockers are honest. | Does not exercise TLS, auth, or a live endpoint. |
| AC-11 | Roadmap sequencing predates the remote-Hermes decision. | Roadmap inspection and full diff audit. | Follow-up work is dependency-ordered without scope creep. | Does not deliver follow-up slices. |
| AC-12 | No independent review has occurred. | Two independent reviewer agents with separate packets. | Correctness/safety and compatibility/product concerns receive independent scrutiny. | Review cannot guarantee absence of defects. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `git status --short --branch` and `git rev-parse HEAD` | macOS workspace | Pass | Clean branch at `e58c54b9702a532d1dea1d9027f5fbebad1e4b8c`. |
| `python3 -m py_compile server.py` | Local Python | Pass | No output. |
| `node --check public/core.js` | Local Node.js | Pass | No output. |
| `node --check public/app.js` | Local Node.js | Pass | No output. |
| `python3 -m unittest discover -s tests -v` | macOS workspace | Pass | 349 tests passed in 14.883 seconds; existing history-permission warning observed. |

### Test discussion and approval

- User questions and decisions: User approved the focused contract test, manual source inventory, complete regression suite, syntax checks, two-reviewer process, and documented accepted gaps.
- Accepted coverage gaps: No live remote Hermes, HTTPS/auth interoperability, Windows/Linux execution, remote Kanban implementation, Hermes-version guarantee, rendered UI check, or legal opinion.
- Approved at: 2026-07-16 in the active Codex conversation.

## Implementation record

### Changes

- Added the standard MIT license with the approved copyright holder.
- Added `REMOTE_HERMES.md` with the product boundary, full current adapter inventory, capability classifications, credential rules, upstream blockers, implementation order, and beta exit evidence.
- Updated `ARCHITECTURE.md` to distinguish loopback Mentat serving from an outbound remote Hermes connection and apply existing mutation safeguards to remote adapters.
- Recorded the approved remote and licensing decisions in `ROAD_TO_BETA.md` while leaving the remaining Milestone 0 owner decisions open, added the remote-parity milestone before packaging, shifted dependent milestones, and aligned the slice workflow with the reviewed-feature process.
- Updated `README.md` and `CHANGELOG.md` without claiming remote support is already implemented.
- Added `tests/test_beta_contract.py` to preserve the approved license, scope, parity, documentation-link, roadmap, and security commitments.

### Deviations and decisions

- The first focused-test run passed 6 of 7 tests. The remaining assertion compared a phrase across a Markdown line wrap. The test was corrected to normalize whitespace before checking the security commitments; no product contract changed. The next run passed 7 of 7.
- Round 1 review found that the roadmap had accidentally promoted several recommended Milestone 0 choices to approved commitments. The roadmap now records only the user's remote-architecture and MIT decisions as approved and leaves the remaining owner choices pending.
- Round 1 review found inconsistent milestone ordering. The canonical dependency order is now early CI, durable operator data, remote Hermes parity, packaging, full release CI, trust/support, release candidate, limited beta, and public beta.
- Official Hermes documentation corrected three assumptions: public `/health` is untrusted liveness while authenticated `/health/detailed` supplies readiness; Kanban's localhost plugin HTTP routes are unauthenticated and its WebSocket token is not a reusable server-to-server credential; and the bearer-authenticated Jobs API exists even though Mentat still needs capability/schema validation before remote cron inventory.
- Clarification handling, setup/runtime selection, and diagnostics were added explicitly to the mandatory inventory. The focused contract assertions were updated to preserve these corrected facts rather than stale wording.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_beta_contract -v` | Local Python on macOS | Exit 0 | 7 passed, 0 failed, 0 skipped | Focused contract checks passed after the line-wrap assertion correction. |
| `python3 -m py_compile server.py` | Local Python on macOS | Exit 0 | Pass | No runtime Python changes or syntax regressions. |
| `node --check public/core.js` | Local Node.js on macOS | Exit 0 | Pass | No JavaScript changes or syntax regressions. |
| `node --check public/app.js` | Local Node.js on macOS | Exit 0 | Pass | No JavaScript changes or syntax regressions. |
| `git diff --check` | Git worktree | Exit 0 | Pass | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | macOS workspace | Exit 0 | 356 passed, 0 failed, 0 skipped | Completed in 21.722 seconds; existing Agent Console history-permission warning observed. |

### Rendered or manual behavior

- Rendered behavior: Not applicable; this slice has no interface changes.
- Manually mapped local file/process dependencies for Console, session search/replay, profile lifecycle/identity, provider/model controls, skills, Kanban, cron, configuration summary, attachments/artifacts, Google Calendar token storage, and Agent Pulse.
- Confirmed the changed-file set contains only the approved license, documentation, review log, and focused contract test.
- Targeted searches found no stale `no remote access` or draft-PR language in the current roadmap/remote contract and no local-path, API-key assignment, or bearer-value examples; `git diff --check` passed.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Uncommitted worktree diff from baseline `e58c54b9702a532d1dea1d9027f5fbebad1e4b8c`.
- Verification evidence: Focused 7/7, full suite 356/356, Python and JavaScript syntax checks, and `git diff --check` before review.
- Rendered artifacts: Not applicable.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | High | Yes | The contract treated Kanban HTTP/dashboard authentication as a usable remote boundary, but official Kanban documentation says plugin HTTP routes are unauthenticated by design and only the events WebSocket uses an ephemeral query token. | Yes | Require a new authenticated, capability-advertised server-to-server surface; prohibit the current HTTP and WebSocket-token routes remotely. |
| A-2 | Medium | Yes | Clarification was mandatory in the approved scope but was not consistently documented, and the HTTP API does not advertise an equivalent clarification-response operation. | Yes | Classify clarification as an explicit upstream compatibility blocker with typed request/response and binding requirements. |
| A-3 | Medium | Yes | The contract overlooked the documented bearer-authenticated Jobs API and described cron too narrowly. | Yes | Acknowledge `/api/jobs`, while retaining graceful degradation until capability, schema, and read-only semantics are validated. |
| A-4 | Medium | Yes | Setup/runtime selection and diagnostics were absent from the integration inventory. | Yes | Add `scripts/mentat_setup.py`, `runtime_config.py`, and `health_checks.py` rows and inventory coverage. |
| A-5 | Medium | Yes | The contract did not distinguish unauthenticated public `/health` from authenticated `/health/detailed`. | Yes | Treat public health as untrusted liveness only and require authenticated readiness/capability discovery. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | High | Yes | Milestone 0 was marked complete and several unapproved release choices were presented as commitments. | Yes | Keep Milestone 0 in progress; mark only remote architecture and MIT as approved. |
| B-2 | Medium | Yes | Roadmap, remote contract, and README implied different implementation orderings. | Yes | Use one dependency order across all documents. |
| B-3 | Medium | No | README's broad statement that credentials stay in Hermes conflicted with Mentat owning the future remote API key. | Yes | Distinguish Hermes provider/model credentials from Mentat's server-only remote connection key. |
| B-4 | Low | No | The focused adapter-inventory test could silently drift as integration modules are added. | Yes | Discover `hermes_*.py` dynamically and explicitly cover non-prefixed integration files. |

### Round 2 packet

- Diff reviewed: Full corrected uncommitted worktree diff from the same baseline.
- Verification evidence: Focused 7/7, full suite 356/356, syntax checks, and diff check after Round 1 fixes.
- Rendered artifacts: Not applicable.

### Reviewer B — Round 2 compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-5 | Medium | Yes | Cancellation and stopping were distinct in the detailed matrix, but several mandatory-capability summaries omitted stopping. | Yes | Add stopping to every authoritative summary and the focused parity assertion. |
| B-6 | Low | No | The SSH test asserted only `invoke SSH`, so an authorization could satisfy it. | Yes | Bind the assertion to explicit prohibition language. |

### Reviewer A — Round 2 correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 follow-up | High | Yes | The profile-discovery row still described an unauthenticated Kanban plugin HTTP route as dashboard-session-authenticated. | Yes | State that the route is unauthenticated and loopback-only and require a new authenticated inventory surface. |
| A-2 follow-up | Medium | Yes | Clarification was corrected in the core contract but remained absent from the README blocker summary and changelog capability summary. | Yes | Add clarification to both operator-facing summaries. |
| A-6 | Medium | Yes | Architecture said Mentat never collects Hermes secrets despite the approved operator-supplied remote Hermes API key. | Yes | Narrow the prohibition to Hermes-owned provider/model credentials and authentication-file contents while governing the remote key explicitly. |

### Round 3 final disposition

- Reviewer A re-reviewed the full diff and all cross-cutting fixes. A-1 through
  A-6 are resolved; no blocking or nonblocking findings remain.
- Reviewer B re-reviewed the full diff and all cross-cutting fixes. B-1 through
  B-6 are resolved; no blocking or nonblocking findings remain.
- Neither reviewer edited the worktree.

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| A-1, A-5 | Corroborated security-boundary defects | Resolved in Round 3 | Official Hermes docs support the findings. Public health cannot authorize features, and existing Kanban plugin routes cannot cross the remote trust boundary. | Corrected matrix, architecture invariants, blocker language, and focused tests. |
| A-2 | Unique scope/compatibility defect | Resolved in Round 3 | Clarification remains mandatory and is now an explicit upstream blocker; no workaround is authorized. | Added matrix row, blocker section, roadmap step, exit evidence, and tests. |
| A-3 | Unique upstream-surface correction | Resolved in Round 3 | The Jobs API is documented, but remote cron stays degradable pending capability/schema/read-only validation. | Corrected cron matrix and architecture wording. |
| A-4, B-4 | Corroborated inventory-completeness risk | Resolved in Round 3 | Setup, runtime selection, diagnostics, and future `hermes_*.py` files must remain covered. | Added rows and dynamic inventory assertions. |
| B-1 | Unique approval-state defect | Resolved in Round 3 | Only the decisions explicitly approved in conversation may be commitments. | Reopened Milestone 0 and labeled every remaining recommendation pending. |
| B-2 | Unique product-sequencing defect | Resolved in Round 3 | Canonical order follows data safety before credential storage and remote work, then packaging and full CI. | Reordered milestones and aligned README/remote contract. |
| B-3 | Unique credential-ownership ambiguity | Resolved in Round 3 | Hermes owns provider/model secrets; Mentat owns only its future remote connection key. | Corrected README and architecture terminology. |
| A-1 follow-up | Corroborated residual authentication contradiction | Resolved in Round 3 | The profile inventory cannot use an unauthenticated loopback plugin route remotely. | Corrected the row and added a regression assertion against the stale authentication claim. |
| A-2 follow-up, B-5 | Corroborated mandatory-set consistency defects | Resolved in Round 3 | Clarification and stopping must appear consistently wherever the approved mandatory set is summarized. | Corrected README, changelog, roadmap, architecture, review scope, and focused parity tests. |
| A-6 | Unique credential-boundary contradiction | Resolved in Round 3 | Mentat may collect only the explicit remote connection key, not Hermes-owned provider/model secrets or authentication-file contents. | Narrowed architecture language and added focused regression assertions. |
| B-6 | Unique test-strength issue | Resolved in Round 3 | AC-9 requires the SSH assertion to encode prohibition, not mere mention. | Added the exact contract phrase `Mentat must not invoke SSH` and asserted it. |

### Reverification

- Focused tests: `python3 -m unittest tests.test_beta_contract -v` passed 7/7 after Round 2 corrections.
- Full suite: `python3 -m unittest discover -s tests -v` passed 356/356 in 12.136 seconds after Round 2 corrections; the existing history-permission warning was observed.
- Syntax and diff checks: `python3 -m py_compile server.py`, both JavaScript `node --check` commands, and `git diff --check` passed.
- Next review round or gate result: Both Round 3 reviewers approved with no unresolved findings.

## Documentation updates

- Roadmap: Approved remote/license decisions recorded without closing Milestone 0; remote parity inserted before packaging and later release milestones; next actions reordered.
- Changelog: Added the 2026-07-16 contract, license, remote-boundary, and process outcomes.
- Architecture/operator docs: Added `REMOTE_HERMES.md`; updated `ARCHITECTURE.md` and `README.md` with explicit implementation status and cross-links.
- Project/session notes: This persistent review log contains the approved scope, evidence, deviations, and pending independent reviews.
- Documentation verification: Focused contract tests, source inventory, contradiction/privacy searches, full diff inspection, and `git diff --check` passed.

## Publication gate

- Proposed files: `LICENSE`, `REMOTE_HERMES.md`, `ROAD_TO_BETA.md`, `ARCHITECTURE.md`, `README.md`, `CHANGELOG.md`, `tests/test_beta_contract.py`, and this review log.
- Branch and base: `codex/beta-0-remote-contract` from `main`.
- Commit message: `Define remote Hermes beta contract`.
- PR title: `Define the remote Hermes beta contract`.
- PR summary: Adopt MIT, record the approved local-Mentat/remote-Hermes product and security boundary, inventory current integrations and upstream blockers, reorder the beta milestones, and add contract regression tests.
- Unresolved risks: This slice defines rather than implements remote support; live HTTPS/auth interoperability and cross-platform behavior remain untested; mandatory clarification, complete profile discovery, and Kanban still need upstream authenticated capabilities; the remaining Milestone 0 owner decisions are intentionally open; an MIT grant cannot be withdrawn from copies already distributed under it.
- User authorization and scope: Approved in the active Codex conversation on
  2026-07-16 for the eight listed files, approved commit message, branch push,
  and ready pull request.
- Commit hash: Not created.
- Ready PR URL: Not created.

## Outcome review

- Classification: Pending.
- Acceptance criteria summary: Pending.
- Potential bugs or untested paths: Pending.
- Remaining reviewer dissent: Pending.
- Compatibility/migration/rollback concerns: Pending.
- User decision: Pending.
- Next slice authorized: No
