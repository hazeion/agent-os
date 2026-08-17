# Feature Slice Review: Hermes fallback retirement and fork audit

Status: Ready for publication
Slice: `hermes-fallback-retirement-audit`
Date: `2026-08-17`

## Slice contract

### Goal

Decide, with pinned stock-Hermes evidence, which polling, telemetry, and custom
remote contracts can be retired after native-event migration without weakening
Mentat's correctness, privacy, compatibility, or mutation boundaries.

### In scope

- Audit every event wakeup, browser/server fallback, local telemetry path, and
  custom remote authority named by the 9I plan.
- Record stock equivalent, partial, custom-required, and Mentat-local classes.
- Retire a path only if compatibility, dropped-event convergence, rollback, and
  production soak evidence all exist.
- Add executable contract tests, update architecture/release/roadmap docs, run
  full automated and rendered verification, and obtain two independent
  adversarial reviews.

### Out of scope

- Weakening a capability validator because stock exposes a similarly named but
  less strongly bound endpoint.
- Trusting event payload fields for state, telemetry, or mutation success.
- Upstream Hermes changes, new API contracts, or a new user-facing control.
- Beginning the post-Milestone-9 multi-agent product pivot.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Every remaining custom/fallback contract has one explicit stock classification and safe behavior. | Machine-checked inventory. | Pass |
| AC-2 | No polling or telemetry path is retired without all required evidence. | Source assertions and retirement gates. | Pass |
| AC-3 | Webhooks remain payload-discarding freshness hints, never data or mutation authority. | Documentation and contract tests. | Pass |
| AC-4 | Stock-compatible behavior and custom-host degradation are explicit for live usage/tool/model progress. | Audit row and source tests. | Pass |
| AC-5 | Full tests, packaging, privacy scan, computer-use, and Lighthouse 100/100/100/100 pass. | Verification table. | Pass |
| AC-6 | Two independent adversarial reviewers report no unresolved findings. | Review rounds. | Pass |

### Constraints and recovery

- Compatibility: pinned to stock Hermes `v2026.8.13`; older, absent, disabled,
  and partial hosts retain existing behavior.
- Recovery: this slice removes no runtime path and changes no private schema;
  rollback is a documentation/test revert.
- Version control: branch `codex/hermes-fallback-retirement-audit`, stacked on
  accepted 9H branch `codex/hermes-native-event-migration`.
- User approval: standing approval applies to this in-scope slice and its
  publication; destructive actions remain excluded.

## Test strategy

| Criterion | Pre-change gap | Test/evidence | Limitation |
| --- | --- | --- | --- |
| AC-1 | 9I is only a prose gate. | Parse exact inventory IDs and classes. | Source inspection proves the pinned release, not future releases. |
| AC-2 | The plan says “until 9I,” which could imply automatic removal. | Assert exact 30-second and 60-second production fallbacks plus 24-hour gate. | No production soak has occurred. |
| AC-3 | Event migration could be mistaken for telemetry replacement. | Assert wakeup/data/authority distinctions. | Private request memory still briefly receives signed bodies. |
| AC-4 | Stock has related Runs features but not every hardened Mentat contract. | Pin local telemetry env contract and each custom degradation row. | Upstream equivalence requires a future re-audit. |
| AC-5 | No 9I release evidence exists. | Full repository, package, secret, browser, and Lighthouse gates. | Platform CI follows publication. |
| AC-6 | No independent review exists. | Two reviewer agents per round, maximum three rounds. | Review supplements tests; it does not replace them. |

## Baseline evidence

| Check | Result |
| --- | --- |
| Pinned stock checkout | Tag `v2026.8.13`, commit `f80f453ae0679347e38abc917c7f94f717bf96c5`, clean. |
| Stock outbound events | Exact 17-event topology already validated by 9H. |
| Stock local telemetry search | No live Mentat progress/context file contract exists. Stock has a fixed-field, best-effort one-shot `-z --usage-file` report, but Mentat uses `chat -q`; safe adoption needs a Mentat-owned path, bounded reads/minimization, and preserved chat continuity. |
| Stock Runs surface | Runs/status/events/stop/approval/steer exist, but replay, exact pending-action/request binding, typed clarification, and other hardened contracts are incomplete or absent. |
| Retirement evidence | Required production 24-hour soak is absent; no fallback qualifies for removal. |

## Implementation record

- Added `HERMES_STOCK_COMPATIBILITY.md` as the explicit stock-first inventory.
- Added executable inventory, fallback, telemetry, authority, and milestone
  contract tests.
- No production fallback or fork-dependent path was removed.

## Verification record

- Focused contract/source suite: 23 tests passed.
- Exact stock validator: 3 pinned files and required/forbidden capability
  markers passed at `v2026.8.13`.
- Expanded native-event validator: 11 pinned emitter/registration files passed.
- Full suite initially exposed seven sandbox-denied loopback binds; the elevated
  run reached all HTTP tests and exposed one stale module-inventory assertion.
  `REMOTE_HERMES.md` now inventories the canonical 9I module.
- Final full suite: 1,068 tests passed with 4 native-platform skips.
- Package: wheel and source distribution built and passed exact artifact
  inventory/RECORD verification.
- Pinned `detect-secrets==1.5.0` staged-file gate passed with only reviewed
  stock source/report hashes in the narrow baseline.
- Browser/computer-use: the complete responsive and interaction smoke matrix
  passed against an owner-private isolated fixture; all dashboard APIs returned
  200 during the final run and no browser diagnostics remained.
- Lighthouse 13.4.1 desktop/provided: 100 performance, 100 accessibility, 100
  best practices, and 100 SEO; FCP 319.818 ms, LCP 563.664 ms, TBT 0 ms, CLS
  0.02783004229234159. Compact evidence is in
  `reviews/2026-08-17-hermes-fallback-retirement-audit-lighthouse.json`.

## Adversarial review record

### Round 1

Both independent reviewers found that stock `-z --usage-file` was a partial
equivalent, broad rows hid independently gated capabilities, completeness tests
were self-referential, status was premature, and lifecycle source validation
omitted subagent/session-end emitters.

Resolution: split live progress from final usage; added a canonical capability
manifest covering every production boolean feature exactly once; split Runs
recovery, session resources, inline images, profile inventory/runtime, skills,
and prohibited admin; added exact stock usage/capability source validation; and
expanded native-event emitter hashes/markers.

### Round 2

Reviewers found that classes/decisions were still prose-only, completion text
remained premature in two files, and stock usage was incorrectly called bounded
while its arbitrary output path and failure field require Mentat hardening.

Resolution: canonicalized every class and disposition and asserted every table
row; synchronized in-progress status; described stock usage as fixed-field,
best-effort, and requiring a Mentat-owned path, bounded read/minimization, and
chat-continuity solution.

### Round 3

Both independent reviewers reported no remaining actionable findings. All
review agents were closed after completion.

## Documentation and publication

Architecture, remote capability contract, release notes, milestone plan, and
the standalone stock audit are updated. All local release gates pass;
publication and platform CI are the remaining steps.
