# Feature Slice Review: Agent Console layout refinement

Status: Approved for publication
Slice: `agent-console-layout-refinement`
Date: `2026-07-29`
Review log: `reviews/2026-07-29-agent-console-layout-refinement.md`

## Slice contract

### Goal

Make the Agent Console transcript the central surface between runtime selection
and prompt entry, while removing redundant provider/model messaging.

### In scope

- Keep Agent, Provider, and Model together in the existing first selector row.
- Keep the transcript visible directly below the selector row.
- Place the prompt composer directly below the transcript.
- Remove the redundant runtime banner.
- Retain fail-closed runtime recovery as a compact, conditionally visible
  `Retry check` action in the transcript header.
- Keep successful runtime changes as transcript notices and preserve tool
  visibility controls.
- Replace provider/model repetition in the compact status line with operational
  state only.

### Out of scope

- Runtime switching protocol or safety changes.
- Hermes API or server changes.
- Model effort, speed, or slash-command controls.
- Agent Console transcript persistence changes.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Agent, Provider, and Model remain in one row. | Static UI contract and browser layout check. | Verified |
| AC-2 | The visible transcript is after selectors and before the prompt. | Static ordering assertions and browser geometry. | Verified |
| AC-3 | The standalone runtime banner is absent and provider/model are not repeated in compact status. | Static contract and browser runtime-switch checks. | Verified |
| AC-4 | A verified switch still adds one provider/model transcript notice. | Focused unit contract and browser switch smoke. | Verified |
| AC-5 | Fail-closed recovery remains available as a compact, unresolved-only retry action. | Focused retry contract and browser failure/recovery smoke. | Verified |
| AC-6 | Tool hiding, tool activity, new-session, attachments, and prompt submission remain usable. | Existing focused contracts, browser smoke, and full suite. | Verified |

### Constraints and recovery

- Safety: Do not weaken runtime mutation gating, confirmation, verification, or
  unresolved-state blocking.
- Compatibility: Preserve existing element IDs for functional controls except
  the retired banner/disclosure container.
- Rendered behavior: Desktop ordering is selectors, transcript, prompt; the
  three selectors may stack at the existing mobile breakpoint without
  reserving retired disclosure rows.
- Rollback or recovery: Revert the isolated slice; no data migration exists.
- Documentation targets: `ARCHITECTURE.md`, `CHANGELOG.md`, and this review
  log.
- Version-control strategy: isolated
  `codex/agent-console-layout-refinement` branch from `origin/main`; ready PR
  against `main` only after final publication approval.

### Scope discussion and approval

- Recommendation and rationale: keep runtime retry because it is the only
  explicit recovery from a fail-closed unresolved runtime, but make it compact
  and visible only in that state; remove the purely duplicative banner.
- Alternatives considered: removing retry entirely would strand a blocked
  console until a broader page refresh; retaining the banner would continue
  duplicating the transcript notice and selector state.
- User decisions: transcript above prompt; remove or relocate the oversized
  retry; remove redundant provider/model presentation, specifically the runtime
  banner.
- Approved at: `2026-07-29`; the user previously authorized intermediate
  approvals through final review/commit, so contract and test-strategy
  discussion proceeded under that explicit process exception.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Existing selector row was already correct. | Preserve focused static and responsive browser assertions. | No regression in selector grouping. | Browser smoke uses representative viewports. |
| AC-2 | Transcript was inside a collapsed disclosure after the prompt. | New DOM-order tests plus browser geometry. | Visible transcript is physically between selectors and composer. | Does not replace subjective visual review. |
| AC-3 | Banner and state line duplicated runtime identity. | Negative DOM/JS assertions and runtime browser smoke. | Redundant surface is removed. | Selector option suffixes remain for inventory semantics. |
| AC-4 | Transcript notice already existed. | Preserve notice contract and immediate-switch browser smoke. | Removal of banner does not remove switch feedback. | Browser uses mocked Hermes payloads. |
| AC-5 | Retry was a full-width sibling in the command grid. | Container/text contract plus rendered width and recovery smoke. | Recovery remains present, compact, and safe. | Exact appearance varies by theme/font. |
| AC-6 | Moving mounts can break handlers or hidden-tool behavior. | Existing focused tests, Node syntax, browser smoke, full suite. | Functional mounts and flows remain intact. | No manual screen-reader session. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python -m unittest tests.test_agent_console_runtime_switch_ui tests.test_home_operations_ui tests.test_visual_contract -v` | macOS, repository Python | Pass | 45 passed before test changes. |
| Same focused command after adding desired-behavior assertions | macOS, repository Python | Expected fail | 39 passed; 2 failures and 4 errors demonstrated the missing transcript ordering and retained banner/disclosure. |

### Test discussion and approval

- User questions and decisions: no additional questions were necessary; the
  requested vertical ordering and redundant element were explicit.
- Accepted coverage gaps: no pixel-perfect snapshot baseline; browser geometry,
  responsive smoke, and a rendered screenshot will be used instead.
- Approved at: `2026-07-29` under the user's standing intermediate-approval
  instruction.

## Implementation record

### Changes

- Replaced the collapsed `details` history disclosure with an always-visible,
  labelled transcript section between the runtime row and prompt form.
- Moved runtime state, New session, Show tools, and the conditional retry into a
  compact transcript header.
- Removed `agent-console-runtime-banner` and its rendering/styles.
- Reduced the runtime state label to operational state (`Ready`, `working`,
  `Switching runtime…`, or verification/unavailable state) while retaining the
  selected provider/model in the selectors and verified changes in transcript
  notices.
- Updated desktop/mobile styles, browser smoke, static UI contracts, the
  profile-aware runtime contract, architecture, and changelog.
- Removed a stale four-row mobile grid template so Classic does not reserve an
  empty 300 px track below the Console at phone widths.

### Deviations and decisions

- Retained runtime retry as a compact safety recovery instead of deleting it.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m unittest tests.test_agent_console_runtime_switch_ui tests.test_home_operations_ui tests.test_visual_contract tests.test_beta_contract tests.test_profile_aware_console.ProfileAwareConsoleTests.test_frontend_runtime_refresh_is_read_only_and_stale_response_safe -v` | macOS, repository Python | Exit 0 | 59 passed | Final post-review focused run covers ordering, mounts, compact retry, notices, tool visibility, Classic mobile grid regression, documentation, and stale-safe reads. |
| `node --check public/app.js` and `node --check scripts/browser_smoke.mjs` | macOS, Node.js | Exit 0 | 2 syntax checks passed | No JavaScript syntax regression. |
| `python -m py_compile server.py` | macOS, repository Python | Exit 0 | 1 compile check passed | Server import syntax remains valid. |
| `git diff --check` | macOS, Git | Exit 0 | Pass | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -v` | macOS, repository Python | Exit 1, then two exit-0 runs | Initial: 859 run, 1 failed, 4 skipped. Pre-review correction: 859 run, 4 skipped, all non-skipped passed. Final post-review: 860 run, 4 skipped, all non-skipped passed. | The only initial failure asserted intentionally removed status copy. The final count includes the Classic mobile grid regression. |

### Rendered or manual behavior

- Chromium smoke passed all listed checks, including Agent Console vertical
  layout across responsive viewports, tool visibility, immediate provider and
  model switching, failed-switch reconciliation, and runtime retry.
- The final Chromium run also passed a Classic-shell 390 x 844 check for
  selector/transcript/composer order, no trailing grid gap, and no horizontal
  overflow.
- Focused in-app browser inspection at 1280 px confirmed selectors, compact
  status/actions, transcript, then composer with document `scrollWidth` equal
  to `innerWidth` (no horizontal overflow).

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: uncommitted isolated worktree diff.
- Verification evidence: 46 focused passed; 12 documentation contracts passed;
  final full suite ran 859 with 4 skips and no failures; syntax, compile, browser
  smoke, and diff check passed.
- Rendered artifacts: Chromium smoke capture plus focused in-app browser
  inspection; no tracked screenshot contains local/private data.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | None | No | No findings. Runtime safety, mutation gates, session ownership, tool behavior, attachments, and fail-closed recovery remained unchanged. | Yes | Clear after final re-review. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | Medium | Yes | The narrow Classic cascade retained `grid-template-rows: auto 300px auto auto`, reserving an empty 300 px track because the Console now has one direct grid child. | Yes | Use a single auto row and add rendered Classic phone coverage. |
| B-2 | Low | Yes | `ARCHITECTURE.md` still described tool activity outside collapsed Console history. | Yes | Document the always-visible transcript and persistent live-region behavior. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| B-1: stale mobile grid tracks | Unique product/compatibility finding; safety reviewer found no runtime issue. | Both reviewers re-inspected the complete corrected diff. | Accepted. Final Chromium smoke passed Classic at 390 x 844 with correct order, trailing gap <= 2 px, and no horizontal overflow; static regression passed. | Replaced the stale four-track mobile template with `auto`; added browser and unit regressions. |
| B-2: stale architecture prose | Unique documentation finding. | Both reviewers confirmed the revised text matches the implementation and accessibility behavior. | Accepted. Documentation contract tests and final full suite passed. | Updated `ARCHITECTURE.md` to describe the visible transcript, in-transcript activity summary, and transition-only live region. |

### Reverification

- Focused tests: 59 passed.
- Full suite: 860 run, 4 skipped, all non-skipped passed.
- Rendered verification: full Chromium smoke passed, including Classic mobile
  Console geometry.
- Next review round or gate result: Reviewer A and Reviewer B both returned no
  findings after the fixes. Review gate is clear.

## Documentation updates

- Roadmap: Not required; no milestone or capability boundary changed.
- Changelog: Added a `2026-07-29` Changed entry for the vertical transcript,
  removed banner, and compact retry.
- Architecture/operator docs: Updated the tool-activity UI/accessibility
  contract from collapsed history to the always-visible transcript.
- Project/session notes: This review log.
- Documentation verification: Included in the 59-test focused run and final
  860-test suite.

## Publication gate

- Proposed files: `ARCHITECTURE.md`, `CHANGELOG.md`, `public/app.js`,
  `public/index.html`, `public/styles.css`, `scripts/browser_smoke.mjs`,
  `tests/test_agent_console_runtime_switch_ui.py`,
  `tests/test_home_operations_ui.py`, `tests/test_profile_aware_console.py`,
  `tests/test_visual_contract.py`, and this review log.
- Branch and base: `codex/agent-console-layout-refinement` -> `main`.
- Commit message: `Refine Agent Console transcript layout`
- PR title: `Refine Agent Console transcript layout`
- PR summary: Keep selectors on the top row, move the always-visible transcript
  above the prompt, remove redundant runtime presentation, retain compact
  fail-closed retry and tool controls, and add Classic mobile regression
  coverage.
- Unresolved risks: No known blockers. Rendered checks use Chromium and
  representative viewports rather than pixel snapshots for every browser.
- User authorization and scope: the user approved the exact publication packet
  on `2026-07-29`, including staging, commit, push, and a ready PR.
- Commit hash: Pending.
- Ready PR URL: Pending.

## Outcome review

- Classification: Successful through the publication approval gate.
- Acceptance criteria summary: All six acceptance criteria are verified.
- Potential bugs or untested paths: No manual screen-reader session; persistent
  live-region behavior remains covered by existing contracts and browser smoke.
- Remaining reviewer dissent: None after re-review.
- Compatibility/migration/rollback concerns: No migration; rollback is the
  isolated UI/docs/test commit.
- User decision: Approved exact files, commit, push, and ready PR on
  `2026-07-29`.
- Next slice authorized: No
