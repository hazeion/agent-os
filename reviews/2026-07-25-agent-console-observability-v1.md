# Feature Slice Review: Agent Console observability v1

Status: Awaiting Publication Approval
Slice: `agent-console-observability-v1`
Date: `2026-07-25`
Review log: `reviews/2026-07-25-agent-console-observability-v1.md`

## Slice contract

### Goal

Make Agent Console session boundaries, context-window use, and live agent
activity visible and trustworthy for both local and remote Hermes runs.

### In scope

- Show exact context tokens used, the exact total context window, and the
  resulting percentage beneath a completed Console turn when Hermes supplies
  trustworthy values.
- Show an explicit pending-new-session state immediately after the operator
  chooses **New session**, followed by a durable visual session divider when
  Hermes accepts the first run in that new session.
- Render bounded structured activity events with exact tool identifiers and
  safe, concise progress summaries.
- Add a private run-scoped structured progress and usage channel to the Hermes
  fork for local Console runs; Mentat must not parse terminal decoration,
  free-form logs, or prose into synthetic tool events.
- Accept equivalent optional structured telemetry from remote Hermes when its
  advertised run contract supplies it.
- Preserve path, credential, argument, and hidden-reasoning privacy boundaries.
- Persist new public-safe events and metrics through the existing private
  Agent Console history boundary.
- Update the architecture contract and focused operator-facing documentation.

### Out of scope

- Exposing private chain-of-thought, hidden reasoning tokens, raw tool
  arguments, raw tool results, local paths, credentials, or arbitrary logs.
- Guessing a model context window or treating cumulative billing tokens as the
  active context size.
- Scraping or parsing Hermes terminal output for progress.
- Retrofitting telemetry into historical runs that did not record it.
- Redesigning the Console composer, provider picker, session browser, or other
  Hermes user interfaces.
- Making unsupported remote Hermes hosts claim telemetry they do not expose.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A completed run with trustworthy telemetry shows context used, total context window, and percentage; missing telemetry is labeled unavailable without estimation. | Backend normalization tests and rendered Console tests. | Pass |
| AC-2 | Choosing **New session** immediately shows the pending state, and the accepted first run contains one durable, accessible “New Hermes session started” divider. | Frontend interaction and run-contract tests. | Pass |
| AC-3 | Local and remote structured events render exact tool identifiers and bounded progress summaries in sequence. | Hermes producer tests, Mentat adapter tests, and browser rendering. | Pass |
| AC-4 | Telemetry rejects or redacts credentials, private paths, raw arguments/results, malformed values, and hidden chain-of-thought. | Negative contract, persistence, and request-boundary tests. | Pass |
| AC-5 | Existing run history, cursor polling, cancellation, continuation, attachments, and unsupported-runtime fallbacks remain compatible. | Regression tests and full suites in both repositories. | Pass with documented Hermes baseline limitation |
| AC-6 | Emerald Console presentation remains compact, readable, keyboard accessible, and does not turn polling updates into noisy whole-log announcements. | Browser smoke, accessibility-focused contract tests, and screenshot review. | Pass |
| AC-7 | Safe reasoning summaries longer than 100 characters show the first 100 characters plus `...` and expand through a keyboard-accessible disclosure without exposing hidden chain-of-thought. | UI contract tests and independent source/accessibility review. | Pass |

### Constraints and recovery

- Safety: all telemetry files are private, run-scoped, bounded, validated,
  symlink-safe, and deleted with existing run scratch data. Browser payloads
  remain path-free and secret-free.
- Compatibility: new fields and events are optional. Old local Hermes builds,
  remote hosts, and retained run summaries must continue to load with an
  explicit unavailable state.
- Rendered behavior: use the existing Emerald Console log hierarchy, a compact
  divider, and concise activity rows; do not introduce hero cards.
- Rollback or recovery: Mentat must safely ignore absent telemetry; reverting
  either side restores the existing generic progress behavior without a data
  migration.
- Documentation targets: `ARCHITECTURE.md`, affected feature/contract tests,
  and this review log. Add other canonical operator documentation only if the
  implementation changes an operator-facing setup requirement.
- Version-control strategy: coordinated branches named
  `codex/console-observability-v1`. Mentat is based on `main`; the Hermes fork
  is based on its maintained `mentat-beta-contracts` integration branch
  because that branch contains the remote capabilities Mentat consumes.
  Ready PRs are allowed only after the publication gate.

### Scope discussion and approval

- Recommendation and rationale: implement a stable structured Hermes-to-Mentat
  channel so local Console activity is truthful instead of inferred from
  terminal output. Keep the public event shape small and privacy-safe.
- Alternatives considered: a Mentat-only UI change would improve remote runs
  but leave local runs generic; terminal/log parsing would be unstable and
  violate Mentat's architecture boundary.
- User decisions: approved the coordinated end-to-end slice, its exclusions,
  two-branch strategy, and this review-log path.
- Approved at: `2026-07-25`

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Mentat stores remote billing-token totals but renders no Console usage, and neither local report nor remote normalization carries exact active-context fields. | Extend Hermes one-shot usage tests for `context_tokens` and `context_length`; add Mentat normalization, persistence, and UI tests for exact values and unavailable fallback. | The UI labels active context truthfully and never substitutes cumulative billing tokens. | Deterministic tests do not verify every provider's upstream token accounting. |
| AC-2 | **New session** only changes transient form text, and accepted runs contain no durable boundary. | Add server run-contract tests for a fresh-session marker and frontend tests for pending state, one divider, persistence, and continuation behavior. | Operators receive immediate feedback and retained history keeps exactly one boundary. | Historical runs remain unchanged by design. |
| AC-3 | Remote tool names are normalized but reasoning loses its summary; local CLI returns only final stdout. | Add Hermes JSONL progress-writer producer tests and Mentat incremental-consumer tests; extend remote event normalization; assert ordered exact tool labels and bounded summaries in the Console. | Both transports use structured events rather than inferred terminal prose. | A remote host must implement the optional fields to provide summaries. |
| AC-4 | Existing event redaction covers generic nested data but no new telemetry file/parser contract exists. | Test malformed JSONL, partial writes, oversized files/fields, symlinks, credentials, paths, raw arguments/results, invalid token values, and reasoning-summary truncation/redaction. | The new channel fails closed and keeps private data out of browser/history. | Semantic secrets that do not resemble supported credential patterns may require future redaction improvements. |
| AC-5 | Existing run/history/cursor suites pass before the change. | Rerun focused continuation, cancellation, attachment, remote-run, history, and cursor tests; run complete Mentat and Hermes suites. | Optional telemetry does not break established workflows or retained schemas. | Native platform-only behavior relies on repository CI where unavailable locally. |
| AC-6 | Current Emerald Console contracts pass but do not cover dividers or telemetry rows. | Add DOM/CSS accessibility contracts and run browser smoke with deterministic fixture data; capture a screenshot for review. | The new presentation remains compact, ordered, readable, and non-noisy. | Automated visual checks cannot judge every viewport or assistive technology. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest tests.test_agent_run_events tests.test_remote_console_runs tests.test_agent_console_attachments_ui tests.test_home_operations_ui -v` | Mentat, macOS, Python 3.13 | Pass | 59 passed; confirms current run, remote, attachment, and Emerald Console contracts before implementation. |
| `.venv/bin/python -m pytest tests/hermes_cli/test_oneshot_usage_file.py -q` | Hermes fork, macOS, Python 3.13 | Pass with environment warning | 6 passed; pytest could not write its cache because the Hermes checkout is read-only in this task environment. |
| Source inspection of `run_hermes_agent`, `_apply_remote_console_event`, `renderAgentConsole`, and Hermes `run_oneshot`/`_write_usage_file` | Both repositories | Gap confirmed | Local Mentat uses final-output CLI execution; remote reasoning is collapsed to a generic line; no Console context meter or durable session boundary exists. |

### Test discussion and approval

- User questions and decisions: user approved the complete strategy and asked
  the implementation workflow to proceed without repeated intermediate
  approvals.
- Accepted coverage gaps: deterministic producer, consumer, browser, and
  full-suite evidence is required, but an automatically billed live-provider
  run is not required unless the user explicitly requests it.
- Approved at: `2026-07-25`

## Implementation record

### Changes

- Mentat now creates owner-only run-scoped usage and progress files, passes
  their absolute paths through optional environment variables, tails bounded
  monotonic JSONL tool events, reads exact context metrics, and removes the
  scratch files through the existing cleanup boundary.
- The Hermes fork now supports versioned bounded usage, tool lifecycle events,
  and a fixed reasoning-presence phase for quiet runs. It records only the
  latest provider-reported prompt count, refuses unsafe strict destinations,
  and never derives a reasoning label from assistant response text.
- Fresh-session requests remain pending until a local Hermes session ID is
  parsed or a remote run ID is accepted. Only that acceptance creates the
  durable divider.
- Remote and retained usage keep valid billing totals while independently
  omitting malformed optional context fields.
- The Emerald Console shows exact tool names, a compact accepted-session
  divider, and used/total/percentage context values or an explicit unavailable
  state. Its polled history is a non-live region; concise form feedback remains
  the live status surface.
- Safe normalized reasoning summaries longer than 100 characters render as a
  collapsed native disclosure containing the literal first 100 characters plus
  `...`; expansion reveals the escaped public summary, never raw provider
  scratch work.

### Deviations and decisions

- Branch-base clarification: source inspection showed that the Hermes fork's
  Mentat-facing capability work is carried on `mentat-beta-contracts`, while
  `origin/main` mirrors upstream. Basing the Hermes slice on the integration
  branch keeps its eventual PR limited to the approved telemetry change and
  avoids republishing unrelated carried commits.
- Compatibility adjustment after review: Mentat does not add telemetry flags
  to the Hermes command. New Hermes reads private optional environment
  variables; old Hermes ignores them and receives the exact prior argv.
- Truthfulness adjustment after review: local structured progress is limited
  to genuine tool lifecycle callbacks. Generic lifecycle text remains visible,
  but ordinary assistant prose is never presented as model reasoning.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_agent_console_observability tests.test_hermes_transport tests.test_remote_console_runs tests.test_profile_aware_console -q` | Mentat, macOS, Python 3.13 | 0 | 60 passed | Covers acceptance timing, old-runtime argv, context normalization, remote events, persistence, sequence rejection, and cleanup. |
| `uv run --extra dev pytest -q tests/hermes_cli/test_structured_telemetry.py tests/hermes_cli/test_oneshot_usage_file.py tests/cli/test_single_query_session_finalize.py tests/agent/test_context_compressor.py` | Hermes fork, locked uv environment | 0 | 222 passed | Covers per-turn exact provider context, secure strict and explicit writes, genuine reasoning signals, tool events, quiet failure reports, and existing compressor behavior. |
| `python3 -m py_compile ...` and `node --check public/app.js` | Mentat | 0 | Pass | Python modules and frontend parse successfully. |
| `git diff --check` | Both repositories | 0 | Pass | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests` | Mentat, macOS, Python 3.13 | 0 | 796 discovered; suite passed with existing platform permission notices and 4 platform skips | Full Mentat regression rerun after the final expandable-summary UI change. |
| `pytest -x` against the complete Hermes suite | Hermes fork and untouched source checkout | Baseline failure | First failure reproduced in both checkouts | `tests/acp/test_edit_approval.py::test_write_file_approval_mutates_and_request_includes_diff` fails because this macOS pytest temp directory is classified as sensitive. The full Hermes suite contains 45,782 tests and was stopped after the identical baseline/environment failure was proven in the untouched checkout. |

### Rendered or manual behavior

- Reloaded the running branch at `http://127.0.0.1:8893`.
- Opened Console history and verified it exposes one named region rather than
  a live log, exact `Tool` rows, and explicit unavailable context values on
  retained runs without telemetry.
- Rechecked the 390 × 844 responsive viewport; controls and cards remained
  readable without overlap, then reset the temporary viewport override.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: complete uncommitted working-tree diffs in Mentat and
  the Hermes integration worktree.
- Verification evidence: focused suites, complete Mentat suite, baseline
  Hermes failure reproduction, static checks, and browser inspection above.
- Rendered artifacts: live Emerald Console desktop/accessibility inspection and
  responsive viewport review.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A1 | High | Yes | Active context mixed a rough preflight estimate with provider usage and capped inconsistent values. | Yes | Track a separate latest provider-reported prompt count and make inconsistent pairs unavailable. |
| A2 | High | Yes | Session boundaries were persisted at queue time before local launch or remote acceptance. | Yes | Preserve pending state and promote only after accepted execution. |
| A3 | Medium | Yes | Assistant response prose could be labeled as reasoning. | Yes | Emit local progress only from genuine tool callbacks; do not classify prose. |
| A4 | Medium | Yes | Producer sequence was discarded, allowing duplicate/regressing records. | Yes | Retain and strictly enforce monotonic sequence. |
| A5 | Medium | Yes | Producer writes and cleanup were not fully bounded or symlink-safe. | Yes | Pre-create owner-only files, use no-follow descriptor writes, cap events/bytes, and unlink unsafe child symlinks without following them. |
| A6 | Medium | No | Quiet-run usage was not guaranteed on unexpected failure. | Yes | Write a bounded failure report before re-raising. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B1 | High | Yes | New CLI flags would break old Hermes runtimes. | Yes | Preserve the legacy command and use optional environment variables. |
| B2 | High | Yes | Queue-time session marker could falsely claim acceptance. | Yes | Same pending/accepted state correction as A2. |
| B3 | High | Yes | Inconsistent context was silently capped. | Yes | Omit both context fields instead. |
| B4 | Medium | Yes | JSONL sequence was not enforced. | Yes | Same monotonic enforcement as A4. |
| B5 | Medium | Yes | Polling replaced an implicitly live `role=log`, causing noisy announcements. | Yes | Make history `role=region` with `aria-live=off`; keep concise dedicated status feedback. |
| B6 | Medium | Yes | Remote/history optional-context policies and tests differed. | Yes | Preserve valid billing values and independently omit invalid optional context across both boundaries. |
| B7 | Low | No | Publication log listed the wrong Hermes base. | Yes | Correct Hermes base to `mentat-beta-contracts`. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Exact context truthfulness | Corroborated by both reviewers | Round 2 requested | Provider-only measurement and null-on-inconsistency implemented and tested. | Yes |
| Accepted session boundary | Corroborated by both reviewers | Cleared in final review | Pending state promotes exactly once after a parsed local Hermes session ID or accepted remote run ID. Rejections never render the divider. | Yes |
| Ordered structured progress | Corroborated by both reviewers | Round 2 requested | Strict increasing producer sequence; channel disables on replay/regression. | Yes |
| Compatibility and accessibility | Unique product review | Round 2 requested | Legacy argv preserved; history is a non-live named region. | Yes |
| Producer and cleanup safety | Unique safety review | Round 2 requested | Server-owned 0600 files, descriptor/no-follow writes, hard bounds, recoverable cleanup. | Yes |
| Reasoning semantics | Unique safety review | Round 2 requested | No local prose-derived reasoning; remote summaries remain optional and allowlisted. | Yes |

### Reverification

- Focused tests: final Mentat slice 61 passed; final Hermes slice 222 passed.
- Full suite: Mentat pass; Hermes full-suite baseline limitation documented
  with unchanged-checkout reproduction.
- Review rounds: both independent reviewers challenged the first implementation,
  re-reviewed the fixes, and completed a final narrow review after the
  expandable-summary addition. No blockers remain.
- Next gate: fresh user approval is required before either repository is
  committed, pushed, or published as a ready PR.

## Documentation updates

- Roadmap: no change; this is an implementation slice within the existing
  Console capability rather than a milestone or beta-scope change.
- Changelog: no canonical changelog exists in either repository.
- Architecture/operator docs: Mentat `ARCHITECTURE.md` and Hermes
  `docs/observability/structured-cli-telemetry.md` updated.
- Project/session notes: this review log.
- Documentation verification: terminology and compatibility behavior checked
  against the implemented contracts.

## Publication gate

- Proposed files: all tracked changes listed by each branch's final
  `git status`; Mentat's pre-existing untracked `design/` directory is excluded.
- Branch and base: Mentat `codex/console-observability-v1` to `main`; Hermes
  `codex/console-observability-v1` to `mentat-beta-contracts`.
- Commit messages: `Add Agent Console observability`; `Add structured quiet-run telemetry`.
- PR titles: `Add Agent Console observability`; `Add structured quiet-run telemetry for Mentat`.
- PR summary: coordinated optional telemetry adds exact context measurement,
  accepted session boundaries, and safe tool progress without exposing private
  reasoning or breaking older Hermes runtimes.
- Unresolved risks: full Hermes regression remains dependent on upstream CI
  because the local suite's first ACP approval test has an unchanged-checkout
  platform failure.
- User authorization and scope: awaiting the required fresh publication
  approval after final files, tests, review findings, and risks were summarized.
- Commit hash: pending.
- Ready PR URL: pending.

## Outcome review

- Classification: Ready pending publication approval.
- Acceptance criteria summary: all seven criteria pass with the documented
  complete-Hermes-suite environment limitation.
- Potential bugs or untested paths: strict local telemetry intentionally
  degrades to generic status on platforms lacking secure directory-descriptor
  primitives; upstream CI remains responsible for the full Hermes matrix.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: no migration planned; optional
  fields must degrade safely.
- User decision: awaiting fresh commit/push/ready-PR approval.
- Next slice authorized: No
