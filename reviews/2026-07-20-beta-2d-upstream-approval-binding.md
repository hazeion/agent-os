# Feature Slice Review: Upstream HTTP Approval Request Binding

Status: Upstream draft PR open  
Slice: `beta-2d-upstream-approval-binding`  
Date: `2026-07-20`  
Review log: `reviews/2026-07-20-beta-2d-upstream-approval-binding.md`

## Slice contract

### Goal

Give authenticated Hermes Runs API clients an exact, privacy-safe way to answer
the approval request they actually displayed.

### In scope

- Build on upstream Hermes PR #6105 so its request-ID work and authorship are
  preserved.
- Carry a stable approval request ID through Runs approval events and accept it
  on the existing approval-response endpoint.
- Resolve only the matching queued request when an ID is supplied.
- Add a versioned structured preview made only from fixed, server-owned
  categories and labels.
- Advertise exact binding and structured-preview support through authenticated
  capabilities.
- Preserve the legacy no-ID FIFO path for existing clients.
- Document the HTTP contract.

### Out of scope

- Mentat approval buttons or browser routes.
- Clarification responses, denial reasons, persistent approval scopes, or
  `resolve_all` in Mentat.
- Removing the legacy Hermes approval surface.
- Remote continuation, profiles, Kanban, or image-input blockers.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Concurrent approvals have distinct IDs and an exact response resolves only its matching request. | Core queue and HTTP integration tests | Passed |
| AC-2 | A missing, stale, or unknown ID cannot resolve another queued request. | Negative HTTP and queue tests | Passed |
| AC-3 | Exact request binding cannot be combined with resolve-all behavior. | HTTP validation test | Passed |
| AC-4 | The structured preview contains only versioned fixed categories/labels and cannot echo command text, credentials, descriptions, or paths. | Privacy and fallback tests | Passed |
| AC-5 | Authenticated capabilities explicitly advertise exact binding and the structured preview version. | Capability contract test | Passed |
| AC-6 | Existing authenticated clients that omit the ID retain FIFO behavior. | Compatibility regression test | Passed |
| AC-7 | The HTTP contract and safe-client behavior are documented. | Documentation inspection and checks | Passed |

### Constraints and recovery

- Safety: unknown, replaced, overlapping, or uncertain requests fail closed.
- Compatibility: the existing endpoint and no-ID behavior remain available;
  safe clients gate on the new capabilities and always send the event ID.
- Rendered behavior: not applicable; this is an HTTP contract.
- Rollback or recovery: remove the additive capability flags, preview, and
  exact-ID HTTP wiring; the prerequisite PR's legacy FIFO flow remains.
- Documentation targets: Hermes API-server and programmatic-integration docs;
  Mentat remote-contract records only after upstream availability.
- Version-control strategy: isolated Hermes branch based on PR #6105, with a
  later rebase or dependent contribution that preserves its original commit.

### Scope discussion and approval

- Recommendation and rationale: extend the existing exact-request primitive
  instead of duplicating it, then expose the smallest backward-compatible HTTP
  contract Mentat can capability-gate.
- Alternatives considered: a new endpoint adds avoidable surface; making the
  ID mandatory immediately breaks older clients; a local Mentat-only ID cannot
  close the upstream replacement race.
- User decisions: approved the contract and test strategy; granted standing
  authorization for later slice contracts and asked not to pause for repeated
  approval questions.
- Approved at: 2026-07-20.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Current Runs HTTP resolves FIFO and accepts no ID. | Two-entry core test plus HTTP exact-response test | The selected request, not the oldest, is resolved. | Does not simulate a network proxy. |
| AC-2 | A displayed request can be replaced before the response. | Stale/unknown-ID tests with another request pending | Stale consent cannot spill into a new request. | Process-local queue only. |
| AC-3 | Existing resolve-all can fan out. | Reject exact ID plus `all` or `resolve_all` | Exact consent remains singular. | Legacy explicit fan-out remains for old clients. |
| AC-4 | Events expose free-form command and description fields. | Generate previews from sensitive and unknown inputs | The new preview is bounded and server-owned. | Legacy fields remain for compatibility and must be ignored by safe clients. |
| AC-5 | Capabilities advertise only generic approval response/events. | Authenticated capability response assertion | Clients can fail closed on unsupported runtimes. | Does not prove client gating. |
| AC-6 | Existing clients depend on FIFO responses. | Existing and added no-ID regression tests | The additive contract does not break them. | It intentionally preserves the unsafe legacy mode. |
| AC-7 | Current docs do not define exact mode. | Documentation inspection/checks | Integrators receive the safe usage contract. | Documentation cannot enforce clients. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Current-main source and API audit | Clean isolated upstream checkout | Gap confirmed | Runs approval accepts a choice and resolves FIFO; no structured safe preview is advertised. |
| Search open upstream issues and PRs | GitHub | Overlap found | PR #6105 supplies the core request-ID primitive but does not wire the Runs HTTP API or safe preview. |
| Focused test wrapper | Isolated checkout using installed runtime venv | Environment failure | No tests ran because that runtime venv does not contain `pytest`; a separate temporary development venv will be used. |

### Test discussion and approval

- User questions and decisions: approved as proposed.
- Accepted coverage gaps: no rendered UI; hosted platform coverage comes from
  upstream CI after publication.
- Approved at: 2026-07-20.

## Implementation record

### Changes

- Updated the installed Hermes checkout from its carried local revision to
  upstream `183712ab8` with `hermes update`, then confirmed the installed Runs
  API still lacked request-bound approvals and structured previews.
- Rebased and preserved PR #6105's exact queue-request work as its own credited
  prerequisite commit on current Hermes `main`.
- Added transport-safe request-ID validation and replacement for malformed
  internally supplied IDs.
- Added exact `request_id` handling to the Runs approval endpoint, including
  stale-ID failure, singular-scope validation, request-bound response events,
  and correct waiting state while another approval remains pending.
- Added a versioned preview containing only fixed Hermes-owned copy and
  recognized built-in risk labels.
- Added explicit capability flags and upstream API documentation.

### Deviations and decisions

- Per user direction, adversarial reviewers run once after all Milestone 2
  slices are complete, not after this individual upstream slice.
- Standing slice authorization replaces repeated scope/test approval pauses.
  Publication packets will still be recorded before external publication, but
  do not require another reply unless authority or scope materially changes.
- The Hermes updater needed a second run to converge after removing the carried
  local commit. It created recovery snapshot `20260720-134858-pre-update` and
  restarted the gateway successfully. The optional Matrix backend retained its
  prior version because its dependency build failed; this did not affect the
  approval capability audit or implementation checkout.

## Verification

### Focused checks

| Check | Result |
| --- | --- |
| Runs API, capability, and approval-core tests with retries disabled | 280 passed |
| Interactive platform approval regression set with retries disabled | 412 passed |
| Combined focused regression set after rebasing to current upstream | 658 passed |
| Ruff on affected Python files | Passed |
| Python bytecode compilation on affected Python files | Passed |
| `git diff --check` | Passed |
| Windows footgun check on all affected source files | Passed |

### Full suite

The canonical upstream suite completed with 43,518 passing tests and 26 failures
across 12 files, plus three unrelated timeout flakes. Every slice-specific API,
approval, and platform test passed. Running the exact 12-file failure set with
retries disabled on pristine current upstream `main` reproduced the same 26
failures (1,048 passed), confirming they are baseline macOS/Python 3.13 issues
rather than changes from this slice. The failures cover `/tmp` alias handling,
Linux/systemd assumptions, host command behavior, process timing, and an
Anthropic keychain mock.

### Rendered or manual behavior

Not applicable.

## Adversarial review

Deferred by explicit user direction until the complete Milestone 2 review.

## Documentation updates

- Roadmap: pending upstream availability.
- Changelog: not applicable yet.
- Architecture/operator docs: updated the upstream API-server and programmatic
  integration guides with capability gating, safe preview use, exact response,
  stale-ID behavior, and legacy compatibility.
- Project/session notes: this review log.
- Documentation verification: content inspection and diff checks passed; full
  upstream suite remains in progress.

## Publication gate

Standing user authorization applies. Publication packet:

- Repository/target: `NousResearch/hermes-agent` → `main`.
- Publication route: create `hazeion/hermes-agent`, push the isolated feature
  branch, and open a draft cross-repository PR.
- Included commits: PR #6105's original author-preserving prerequisite commit,
  followed by `feat(api): bind run approvals to exact requests`.
- Included new-work files: Runs API server, approval core validation, focused
  tests, and two upstream API documentation pages.
- Excluded: Mentat UI/routes, unrelated Hermes baseline failures, the Mentat
  README, and all other beta blockers.
- Validation: focused no-retry suites and static checks passed; canonical full
  suite failures reproduced identically on pristine upstream.
- Known limitation: legacy no-ID FIFO and legacy free-form event fields remain
  for compatibility; capability-aware clients must display only `preview` and
  return its event's exact `request_id`.
- Recovery: close the draft PR and delete the fork branch; the installed Hermes
  updater snapshot remains available independently.

Published result:

- Fork: `hazeion/hermes-agent`.
- Branch: `feat/http-approval-request-binding-main`.
- Preserved prerequisite: `06c572bc9` by mr.Shu.
- API extension: `d63ba956a` by Hazeion.
- Draft PR: [NousResearch/hermes-agent#68080](https://github.com/NousResearch/hermes-agent/pull/68080).
- Initial GitHub state: open, draft, and mergeable; upstream checks pending.

## Outcome review

- Classification: implementation complete and published as a draft; upstream
  acceptance and release remain external dependencies.
- Acceptance criteria summary: AC-1 through AC-7 passed.
- Potential bugs or untested paths: hosted CI is still needed for native Linux
  coverage; the legacy compatibility path intentionally remains less safe than
  the new capability-gated contract.
- Remaining reviewer dissent: milestone-level review deferred.
- Compatibility/migration/rollback concerns: additive capability with legacy
  FIFO retained.
- User decision: standing authorization permits publication and continuation.
- Next slice authorized: Yes, under standing authorization.
