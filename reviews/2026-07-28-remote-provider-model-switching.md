# Feature Slice Review: Remote Provider and Model Switching

Status: Approved and ready for publication
Slice: `remote-provider-model-switching-v1`
Date: `2026-07-28`
Review log: `reviews/2026-07-28-remote-provider-model-switching.md`

## Slice contract

### Goal

Let Mentat safely inventory and switch one served remote Hermes profile's
configured provider/model pair through Hermes' authenticated, revision-bound,
idempotent version-one runtime contract, while preserving the existing local
workflow and failing closed on older or malformed hosts.

### In scope

- Validate the exact advertised version-one runtime inventory and switch
  endpoints and required capability flags.
- Read one profile's bounded, secret-free provider/model choices and revision.
- Project that inventory into the existing Agent Console provider/model UI.
- Bind the existing exact preview and confirmation to the selected connection,
  profile, current state, target state, and upstream revision.
- Block preview and mutation while Mentat owns an active run for the profile.
- Send one server-generated idempotency key with the exact preview revision.
- Verify the post-switch runtime with a fresh authenticated read.
- Attempt one revision-bound rollback to the prior provider/model only when a
  fresh mismatch still has the revision acknowledged by Mentat's successful
  upstream mutation.
- Preserve fixed bounded public error codes and never return upstream payloads,
  endpoint details, credentials, paths, or identifiers outside the allowlist.
- Update the Hermes capability matrix, roadmap, changelog, tests, and this log.

### Out of scope

- Provider credential setup, endpoint editing, arbitrary model identifiers, or
  general Hermes configuration mutation.
- Remote profile creation, identity synchronization, deletion, skill
  selection, cron mutation, file transfer, or artifact retrieval.
- Switching an unserved profile or a profile with any active run.
- Supporting hosts that omit any required version, revision, idempotency, or
  active-run-lock capability.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Only the exact advertised authenticated v1 inventory/switch surface enables the remote selectors. | Capability and endpoint validation tests. | Ready for review |
| AC-2 | Inventory exposes only bounded provider/model identifiers, current state, choices, and revision. | Remote client schema/private-reflection tests. | Ready for review |
| AC-3 | Preview binds connection, profile, current and target runtime, and exact upstream revision while active runs block it. | Provider preview and server tests. | Ready for review |
| AC-4 | Apply sends one idempotent revision-bound request, verifies by fresh read, and reports stale/active/unsupported states without retrying an uncertain mutation. | Remote client and server mutation tests. | Ready for review |
| AC-5 | A verified mutation followed by failed read-back attempts one safe rollback; unverifiable rollback is an explicit partial failure. | Fault-injection tests. | Ready for review |
| AC-6 | Existing local provider switching and unsupported remote read-only behavior remain compatible. | Existing and new regression tests. | Ready for review |
| AC-7 | UI enables Review Change only for validated mutable inventory and retains stale-response/profile scoping protections. | Frontend contract and browser behavior tests. | Ready for review |
| AC-8 | Documentation accurately distinguishes implemented switching from still-deferred administration features. | Documentation contract review. | Ready for review |

### Constraints and recovery

- Safety: bearer-authenticated fixed paths only; strict shape and identifier
  validation; server-generated idempotency; no generic request primitive;
  active-run exclusion; exact revision confirmation; bounded public errors.
- Compatibility: capability-gated and read-only on older Hermes hosts; local
  behavior and existing browser endpoints remain unchanged.
- Rendered behavior: reuse the existing provider/model selectors and
  confirmation dialog; no new product surface.
- Rollback or recovery: one verified rollback attempt after post-mutation
  verification failure only while the observed state retains the acknowledged
  switch-response revision. An advanced revision is a concurrent change:
  issue no rollback and require operator inspection before a new run.
- Documentation targets: `REMOTE_HERMES.md`, `ROAD_TO_BETA.md`, `CHANGELOG.md`,
  and this review log.
- Version-control strategy: isolated branch
  `codex/remote-provider-switching-v1` from current `origin/main`; ready PR only
  after two adversarial reviews and full verification.

### Scope discussion and approval

- Recommendation and rationale: consume the exact Hermes contract that landed
  before this slice; do not broaden into other remote administration features
  whose contracts remain unavailable.
- Alternatives considered: session-only cosmetic model selection was rejected
  because it would not update the profile default; generic remote config writes
  were rejected because they would bypass the approved capability.
- User decisions: the user selected provider/model switching first, explicitly
  approved the exact revision-bound contract, requested the reviewed-feature
  workflow, granted standing slice approval, and authorized commit, push, and
  merge for this goal.
- Approved at: `2026-07-28`, in this thread.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Mentat knows only aggregate read-only runtime identity. | Exact feature/version/endpoint positive and negative tests. | Mutation cannot be inferred from partial capability advertisement. | Uses fake HTTPS connections. |
| AC-2 | No exact per-profile choice/revision parser exists. | Valid, malformed, oversized, duplicate, private-shaped, and reflected values. | Browser-visible inventory is bounded and secret-free. | Live-host evidence follows after merge. |
| AC-3 | Existing preview omits remote revision and blocks all remote mutations. | Preview token change, two-connection replay, and active-run tests. | Confirmation is stale-safe, connection-bound, and profile-bound. | Process-local active-run state is tested deterministically. |
| AC-4 | No remote mutation method exists. | Request body, fixed path, response, stale revision, active run, idempotency conflict, timeout, and binding-change tests. | Exactly one safe upstream intent is issued and normalized. | A dropped response remains intentionally uncertain and is not retried. |
| AC-5 | Existing rollback is local-only. | Owned-revision mismatch, rollback success/failure, and advanced-revision interleaving tests. | Mentat never claims success without read-back or overwrites a newer controller's state. | Cannot make upstream persistence transactional beyond Hermes' contract. |
| AC-6 | Remote paths are explicitly read-only today. | Existing local/remote suite plus unsupported-host tests. | Compatibility and graceful degradation. | Older hosts remain read-only by design. |
| AC-7 | UI already keys off `providers.switch`. | Frontend workflow/behavior contracts and manual browser smoke if changed. | Existing controls activate only from normalized capability state. | No new visual design is introduced. |
| AC-8 | Matrix says mutation is unavailable. | Documentation assertions and review. | Operator-facing contract matches reality. | Maintained runtime version note must be updated after live verification. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python -m unittest tests.test_remote_console_runs tests.test_profile_aware_console tests.test_remote_hermes tests.test_hermes_transport -v` | macOS local worktree | Pass: 104 tests | Current `origin/main` before implementation. |

### Test discussion and approval

- User questions and decisions: standing approval applies to this ordered slice.
- Accepted coverage gaps: fake authenticated transport for focused tests; live
  remote verification follows the established maintained-runtime matrix.
- Approved at: `2026-07-28`, in this thread.

## Implementation record

### Changes

- Extended authenticated capability validation with the exact version-one
  profile runtime read/switch endpoints and all revision, idempotency, and
  active-run-lock flags.
- Added a strict per-profile runtime normalizer that rejects extra fields,
  malformed revisions, duplicate providers/models, a current pair outside the
  advertised choices, unsafe identifiers, and endpoint/credential reflection.
- Added dedicated remote transport operations for fresh runtime reads and one
  exact switch request with bounded upstream error translation.
- Extended provider confirmation binding with optional runtime revision and
  opaque transport binding ID; the local token remains byte-for-byte
  compatible when both are absent.
- Reused the Agent Console selectors for fully supported remote inventory and
  retained the current read-only projection for partial or older hosts.
- Implemented connection/profile locking, target-profile active-run exclusion,
  fresh pre-apply state, confirmation recomputation, server-generated
  idempotency, one target mutation, fresh verification, and at most one
  revision-bound rollback plus rollback verification while the fresh state
  retains the switch response's acknowledged revision.
- Updated remote capability, roadmap, and changelog documentation without
  claiming profile creation, identity, deletion, skill selection, cron
  mutation, credentials, or session-scoped runtime overrides.

### Deviations and decisions

- A transport failure or malformed successful response after the POST is
  classified as an uncertain mutation. Mentat does not retry or attempt a
  rollback without a fresh trusted revision.
- An authenticated successful switch followed by an unavailable verification
  read cannot be rolled back safely because no new trusted revision exists; it
  is reported as an explicit partial/unverified outcome.
- A verification read with a revision newer than the successful switch
  response is treated as a concurrent controller change. Mentat issues no
  rollback mutation and returns a bounded operator-inspection result.
- Remote confirmation incorporates the existing opaque transport binding ID,
  preventing replay after selection changes to a different connection with
  identical runtime data without exposing connection secrets.
- No new visual surface was introduced; existing selector enablement already
  keys off the normalized `providers.switch` capability.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m py_compile remote_hermes.py hermes_transport.py hermes_provider_switching.py server.py` | macOS isolated worktree | Exit 0 | Compile pass | Initial implementation syntax check. |
| `python -m unittest tests.test_hermes_provider_switching tests.test_profile_aware_console tests.test_remote_console_runs -v` | macOS isolated worktree | Exit 0 | 64 passed | Exact contract, server mutation, rollback, UI projection, and local compatibility. |
| `python -m unittest tests.test_hermes_provider_switching tests.test_profile_aware_console tests.test_remote_console_runs tests.test_hermes_transport tests.test_remote_hermes -v` | macOS isolated worktree | Exit 0 | 124 passed | Broader connection, transport, and provider-switch regression suite. |
| `python -m unittest tests.test_beta_contract tests.test_hermes_provider_switching tests.test_profile_aware_console tests.test_remote_console_runs tests.test_hermes_transport tests.test_remote_hermes -v` | macOS isolated worktree | Exit 0 | 136 passed | Final focused rerun after strict version/endpoint checks and documentation-contract correction. |
| `python -m unittest tests.test_hermes_provider_switching tests.test_profile_aware_console -v` | macOS isolated worktree | Exit 0 | 25 passed | Reviewer-fix regression check for connection binding, concurrent revision handling, safe owned rollback, and local compatibility. |
| `python -m unittest tests.test_beta_contract tests.test_hermes_provider_switching tests.test_profile_aware_console tests.test_remote_console_runs tests.test_hermes_transport tests.test_remote_hermes -v` | macOS isolated worktree | Exit 0 | 139 passed | Post-review final focused suite, including the two new adversarial safety cases. |
| `git diff --check && python -m unittest tests.test_beta_contract -v` | macOS isolated worktree | Exit 0 | Diff check passed; 12 tests passed | Publication-record and beta documentation contract check after recording final reviewer clearance. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m py_compile server.py remote_hermes.py hermes_transport.py hermes_provider_switching.py && python -m unittest discover -s tests -v` | macOS isolated worktree | Exit 1 | 844 passed, 1 failed, 4 skipped | Documentation-only beta contract failure: adding a separate completed checklist item changed the fixed definition-of-done count. The provider-switch evidence was folded into the existing remote-capability checklist item; rerun pending. |
| `python -m py_compile server.py remote_hermes.py hermes_transport.py hermes_provider_switching.py && python -m unittest discover -s tests -v` | macOS isolated worktree | Exit 0 | 845 passed, 0 failed, 4 skipped | Final full-suite rerun after the documentation-contract correction. |
| `python -m py_compile server.py remote_hermes.py hermes_transport.py hermes_provider_switching.py && python -m unittest discover -s tests -v` | macOS isolated worktree | Exit 0 | 848 passed, 0 failed, 4 skipped | Post-review full verification after both P1 fixes. |

### Rendered or manual behavior

- No layout or component changes. Existing provider/model selectors receive the
  same normalized payload shape; supported remote inventory sets
  `providers.switch` true and `read_only` false, while unsupported hosts retain
  disabled read-only controls.

## Adversarial review

### Round 1 — independent reviews

- **Compatibility and product reviewer:** cleared the initial slice with no
  blocking findings. Existing local switching, unsupported-host read-only
  behavior, Agent Console contracts, and documentation boundaries remained
  compatible.
- **Correctness and safety reviewer:** identified two blocking P1 findings:

- **P1: rollback could overwrite a newer third-party runtime change.**
  Accepted and fixed. Mentat now retains the switch response runtime and permits
  recovery only when fresh verification retains its acknowledged revision. An
  interleaving test covers acknowledged revision B followed by observed
  revision C and asserts that no rollback request is sent.
- **P1: remote confirmation was not bound to the selected connection.**
  Accepted and fixed. The token now includes the opaque transport binding ID,
  and a two-transport replay test asserts rejection before either transport
  receives a switch request. The exact legacy local token remains unchanged.
- **Fix verification:** the required focused suite passed 139 tests; Python
  compilation and the full suite passed 848 tests with 4 platform skips; and
  `git diff --check` passed.

### Round 2 — independent re-reviews

- **Correctness and safety reviewer:** cleared the complete revised slice with
  no remaining blocking findings.
- **Compatibility and product reviewer:** independently cleared the complete
  revised slice with no blocking compatibility, workflow, or regression
  findings.
- **Final disposition:** both required reviewers cleared publication. No
  blocking finding or unresolved reviewer dissent remains.

## Documentation updates

- Roadmap: records exact remote switching as implemented and read-only
  degradation as the compatibility behavior.
- Changelog: records capability gating, confirmation, idempotency,
  verification, rollback, and uncertainty boundaries.
- Architecture/operator docs: replaces stale categorical remote-mutation
  prohibition with the exact supported contract and preserves deferred
  administration boundaries.
- Project/session notes: this persistent log.
- Documentation verification: `git diff --check` passed after the post-review
  focused and full verification runs.

## Publication gate

- Proposed branch and base:
  `codex/remote-provider-switching-v1` → `main`.
- User authorization: explicit approval to commit, push, and open a ready
  pull request for this exact slice.
- Unresolved risks: none blocking publication. Merge remains gated on pull
  request checks and coordinator approval.

## Outcome review

- Classification: Successful through implementation, verification, and
  adversarial review; approved for ready pull request publication.
- Next slice authorized: profile creation only after its separate upstream
  contract is defined and implemented; otherwise proceed to the next safe
  read-only capability.
