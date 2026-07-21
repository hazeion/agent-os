# Feature Slice Review: Beta 7 limited-beta kit

Status: Successful
Slice: `beta-7-limited-beta-kit`
Date: `2026-07-21`
Review log: `reviews/2026-07-21-beta-7-limited-beta-kit.md`

## Slice contract

### Goal

Give invited testers and the maintainer one short, privacy-safe process for
running and measuring the limited external beta once Milestone 6 is complete.

### In scope

- A beginner-friendly tester checklist for install, first useful workflow,
  local/remote Hermes, ordinary use, feedback, and optional recovery.
- A maintainer runbook for cohort coverage, private evidence, severity triage,
  aggregate checkpoints, RC cadence, and the exit decision.
- A structured GitHub feedback form aligned with Milestone 7 evidence.
- Documentation contract tests and honest roadmap/support links.

### Out of scope

- Recruiting testers or claiming that the cohort has started.
- Creating signed artifacts or substituting for the Milestone 6 external gate.
- Storing participant identities, raw evidence, or private reports in Git.
- Changing the app, telemetry, diagnostics, or release criteria.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | An invited tester can follow a short checklist from exact RC through first useful workflow, assigned integration/recovery work, and feedback. | Documentation contract and inspection. | Pass |
| AC-2 | The feedback form captures platform, channel, experience, install/help, time, Hermes mode, integration, and recovery outcomes with a required privacy check. | Issue-form contract and semantic YAML check. | Pass |
| AC-3 | The maintainer can measure the roadmap exit criteria without committing participant-level or private data. | Runbook contract and inspection. | Pass |
| AC-4 | Docs state the Milestone 6 entry gate and do not claim cohort evidence that does not exist. | Roadmap/support contract and review. | Pass |

### Constraints and recovery

- Safety: no telemetry or tracked participant data; public reports explicitly
  exclude credentials, private content, endpoints, and unrestricted logs.
- Compatibility: cover both tier-one platforms, `pipx`, local/remote Hermes,
  and the existing Intel/Rosetta boundary without widening support promises.
- Rendered behavior: concise Markdown and native GitHub issue-form controls.
- Rollback or recovery: remove the preparation docs/form if the cohort design
  changes; no operator data migration or application behavior is involved.
- Documentation targets: beta tester guide, cohort runbook, Support, Road to
  Beta, changelog, and this review log.
- Version-control strategy: `feat/m7-limited-beta-kit` into `main` as one ready
  PR, excluding user-owned local changes.

### Scope discussion and approval

- Recommendation and rationale: prepare the smallest useful external-beta kit
  now while retaining the signed-rehearsal dependency.
- Alternatives considered: app telemetry was rejected by the beta contract;
  tracked participant spreadsheets were rejected as a privacy and maintenance
  risk; an unstructured issue was insufficient for exit evidence.
- User decisions: the user's standing instruction approves Road to Beta slices
  without repeated questions. This is recorded as a process exception to the
  skill's ordinary per-phase approval prompts; scope, evidence, external gates,
  and publication still remain explicit in this log.
- Approved at: standing authorization, applied 2026-07-21.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | No tester onboarding/checklist exists. | Required content, length bound, and manual inspection. | Core tester path is short and complete. | Does not replace an external tester following it. |
| AC-2 | The bug form does not capture cohort outcomes. | Exact field/privacy assertions plus YAML parse. | Structured feedback maps to exit evidence. | GitHub rendering remains hosted behavior. |
| AC-3 | No cohort evidence or triage process exists. | Runbook content/privacy assertions. | Maintainer process covers metrics without tracked private data. | Actual evidence stays external by design. |
| AC-4 | Milestone 7 is simply not started. | Roadmap/support assertions and diff review. | Preparation is visible but no completion is claimed. | External entry/exit gates remain pending. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Repository/roadmap inspection | merged `main` at `cb046ee` | Expected gap | No tester guide, cohort runbook, structured beta form, or M7 preparation status exists. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts the roadmap-
  aligned documentation/contract strategy without another prompt.
- Accepted coverage gaps: real GitHub rendering, recruitment, two-week usage,
  platform installs, recovery, and remote-Hermes cohort evidence remain manual
  and external.
- Approved at: standing authorization, applied 2026-07-21.

## Implementation record

### Changes

- Added a concise tester guide, cohort runbook, structured feedback form,
  public known-issues surface, and focused contract tests.
- Bound invitations to the exact verified Mentat/Hermes builds and completed
  Milestone 6 matrix; defined timing, migration/recovery assignments, and every
  mandatory remote capability outcome.
- Kept participant evidence private and aggregate while excluding endpoints,
  hostnames, IP addresses, credentials, and private content from public reports.

### Deviations and decisions

- The first focused run had one brittle whitespace-sensitive assertion for
  `P0 or P1`; the test now normalizes Markdown whitespace without weakening the
  required policy text.
- Review found that a parse-only YAML check accepted unquoted `No`/`Yes` as
  booleans. The form now quotes them and a semantic check requires every
  dropdown option to be a non-empty string.
- The roadmap's qualitative “large majority” threshold was not reproducible.
  Under the owner's standing approval to make Road to Beta decisions without
  another prompt, it is now defined as at least 80% with a fixed conservative
  denominator. This operationalizes the existing criterion and is recorded as
  a further approval-process exception; it does not claim cohort evidence.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_limited_beta_readiness tests.test_trust_support_readiness tests.test_beta_contract -v` | macOS, Python 3.13.14 | 0 | 27 pass | Final tester, executable remote procedure, cohort, issue, known-issues, support, trust, and beta-contract checks. |
| Ruby YAML semantic dropdown check | local macOS Ruby | 0 | Pass | Form parses and every dropdown option is a non-empty string. |
| `git diff --check` | local worktree | 0 | Pass | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | macOS, Python 3.13.14 | 0 | 755 pass, 4 skip | Final matrix fixes; expected native-Windows skips only. |

### Rendered or manual behavior

- Markdown was inspected directly for a concise first-user path and explicit
  privacy/entry-gate language. The issue form parses; hosted GitHub rendering
  remains an external check after publication.

## Adversarial review

### Round 1 packet

- Diff reviewed: complete slice paths; user-owned task data, `design/`, and the
  unrelated guided Hermes-selector roadmap hunk excluded.
- Verification evidence: 24 focused tests, YAML parse, diff check, and 752-test
  full suite with 4 expected skips.
- Rendered artifacts: Markdown and issue-form source; hosted rendering external.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | P1 | Yes | Singular clean-platform language was weaker than the complete Milestone 6 matrix. | Yes | Require M6 completion and every platform/channel drill. |
| A-2 | P1 | Yes | One Hermes feature/free text could not prove the mandatory remote set. | Yes | Assign, record, and aggregate every required category. |
| A-3 | P1 | Yes | Public warnings omitted endpoints/hostnames despite remote reporting. | Yes | Add endpoint, hostname, IP, and network privacy language and tests. |
| A-4 | P2 | Yes | No owned, maintained visible emerging-known-issues surface existed. | Yes | Add a redacted public list with fields, cadence, and lifecycle. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | High | Yes | Unquoted `No`/`Yes` parsed as booleans invalid for GitHub dropdown options. | Yes | Quote them and semantically validate option types. |
| B-2 | Medium | Yes | Migration was recorded in the runbook but absent from tester/form steps. | Yes | Add an assigned disposable-data drill and structured result. |
| B-3 | Medium | Yes | Bucketed time data could not produce the requested numeric median/range. | Yes | Align checkpoint statistics with buckets. |
| B-4 | Medium | Yes | New Hermes operators lacked exact verified runtime/setup and timing boundaries. | Yes | Bind the invitation packet and define timing start/stop. |

### Reconciliation and disposition

Both reviewers independently maintained the peer's four unique findings after
cross-review. Reviewer A revised B-3 to non-blocking P3 because bucket medians
are possible, while supporting the wording correction. All eight findings were
accepted as in-scope and fixed. There was no conflicting recommendation.

### Reverification

- Focused tests: 25 pass plus semantic YAML dropdown check and diff check.
- Full suite: 753 pass, 4 expected native-Windows skips.
- Next review round: both reviewers received the complete fresh diff/evidence.

### Round 2 findings and disposition

| ID | Severity | Blocking | Finding and cross-review result | Decision and change |
| --- | --- | --- | --- | --- |
| A-5 | P2 | Yes | Ordinary P1 blockers could wait behind the two-week feedback step; peer maintained. | Added immediate public beta-form reporting before ordinary use, while security/data-safety reports remain private. |
| A-6 | P3 | No | July 21 work appeared under July 20; peer agreed chronology was confusing but noted broader drift. | Added a July 21 changelog section for this slice. |
| B-5 | High/P1 | Yes | Six shorthand remote groups omitted multiple authoritative Required rows; peer maintained. | Added versioned one-to-one matrix and a test that derives the exact set from `REMOTE_HERMES.md`; the form includes every row. |
| B-6 | Medium/P1 | Yes | “Large majority” had no threshold or denominator; peer maintained the defect and requested owner approval for the number. | Standing owner authorization applied: at least 80% of all supported-platform install starters, with helped/blocked/not-reached/post-start-dropout outcomes retained as failures. Roadmap and runbook now agree. |

### Round 2 reverification

- Focused tests: 26 pass plus semantic YAML dropdown check and diff check.
- Full suite: 754 pass, 4 expected native-Windows skips.
- Round 3: pending final complete-slice re-review.

### Round 3 findings

Both reviewers independently found that the exact remote-row inventory still
lacked safe executable actions and observable pass criteria. This is a
corroborated P1/high blocking finding: a beginner could mark the same row
`pass` after a materially different or incomplete check. The proposed in-scope
fix is a versioned companion procedure with prerequisites, actions, expected
user-visible results, subchecks, and outcome rules for every Required row,
contract-tested against the authoritative matrix.

The reviewers also found two related install-measurement blockers:

- `not reached` belongs to the first-workflow timing result and must not turn an
  otherwise successful no-help install into an install failure;
- the 80% aggregate can hide a tier-one platform or native channel with no
  no-help success. It needs separate strata plus at least one independent
  no-help success for Intel macOS native, Apple Silicon with Rosetta native,
  Windows native, and the supported `pipx` role.

All previous fixes remained intact. No reviewer edited the repository. The
skill's default maximum of three review rounds is now reached with blocking
findings, so implementation/re-review is paused for explicit owner direction.

The persistent goal then explicitly reiterated standing approval to continue
until the Road to Beta is complete. This authorizes fixing the corroborated
findings and one fourth review round as a recorded process exception.

### Round 3 disposition and reverification

- Added `REMOTE_BETA_MATRIX.md` version 1. Every authoritative Required row has
  a named performer, safe action, and observable all-subchecks pass rule. The
  tester guide, runbook, and feedback form link or bind to that version.
- Corrected the install metric so first-workflow `not reached` remains a
  separate onboarding outcome rather than rewriting a completed install.
- Retained the owner-approved 80% overall rate and added at least one no-help
  success for Intel Mac native, Apple Silicon with Rosetta native, Windows
  native, and supported `pipx`, with separate numerators and denominators.
- Focused tests: 27 pass plus semantic YAML dropdown check and diff check.
- Full suite: 755 pass, 4 expected native-Windows skips.
- Round 4: authorized final complete-slice re-review pending.

### Round 4 finding and disposition

Both reviewers corroborated one remaining P1/high blocker: several negative or
race-oriented pass clauses had no corresponding external action. The standing
goal authorizes continued completion, so a fifth review is recorded as another
explicit exception rather than pausing again.

Every external procedure now uses numbered action/pass pairs, contract-tested
for exact correspondence. Unsafe or non-reproducible hostile checks—malformed
capabilities, stream interruption resubmission, stale clarification, compacted
history, partial skill results, and Kanban replay/idempotency—are removed from
external pass claims and bound to named automated test modules instead.

### Round 5 final review

- Reviewer A — correctness and safety: **No findings**.
- Reviewer B — compatibility and product: no product, privacy, compatibility,
  or implementation finding; one P3 publication-record issue noted stale
  canonical test counts and outcome wording.
- Disposition: corrected the canonical Verification rows and outcome record.
  No substantive re-review is required for this bookkeeping-only fix.
- Final gate: no blocking or non-blocking implementation finding remains.

## Documentation updates

- Roadmap: records repository preparation while retaining the unstarted cohort
  and Milestone 6 entry gate.
- Changelog: records the preparation kit without external-result claims.
- Architecture/operator docs: tester, cohort, and known-issues guides added and
  linked from Support.
- Project/session notes: this persistent review log.
- Documentation verification: 27 focused tests and semantic YAML validation passed.

## Publication gate

- Proposed files: beta feedback form; tester, cohort, remote-matrix, known-issues,
  Support, changelog, and Road to Beta documentation; focused tests; this log.
- Branch and base: `feat/m7-limited-beta-kit` into `main`.
- Commit message: `docs: add limited beta testing kit`.
- PR title: `Add Milestone 7 limited beta testing kit`.
- PR summary: add a privacy-safe external-beta kit, executable authoritative
  remote evidence matrix, reproducible install thresholds, and visible
  known-issues process without claiming real cohort results.
- Unresolved risks: external Milestone 6 and cohort evidence gates.
- User authorization and scope: standing Road to Beta publication approval;
  exact final packet will be recorded before publication.
- Commit hash: pending.
- Ready PR URL: pending.

## Outcome review

- Classification: Successful for repository preparation; Milestone 7 remains
  externally gated and has not started.
- Acceptance criteria summary: AC-1 through AC-4 pass.
- Potential bugs or untested paths: GitHub rendering and real tester use.
- Remaining reviewer dissent: None.
- Compatibility/migration/rollback concerns: documentation-only slice.
- User decision: standing authorization permits continuation after required gates.
- Next slice authorized: Yes, after this slice's review and publication gates.
