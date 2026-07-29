# Feature Slice Review: Beta 5 trust and support readiness

Status: Paused — publication
Slice: `beta-5-trust-support-readiness`
Date: `2026-07-20`
Review log: `reviews/2026-07-20-beta-5-trust-support-readiness.md`

## Slice contract

### Goal

Give first-time beta users a clear, friendly explanation of support, privacy,
security reporting, contribution expectations, and one safe path for collecting
useful bug diagnostics.

### In scope

- Public security, privacy, support, contribution, and conduct documents.
- Focused GitHub bug/feature templates with private security routing.
- User-initiated in-memory redacted diagnostics ZIP.
- Settings links for version, docs, bug reporting, and diagnostics.
- Beginner-first README links and pre-install support limitations.

### Out of scope

- Telemetry, crash upload, automatic issue submission, or unrestricted logs.
- Publishing signed installers, changing GitHub release protection, or claiming
  unverified Hermes runtimes are supported.
- A guaranteed beta support SLA or multi-user/remote browser access.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A tester can find supported platforms, prerequisites, limitations, privacy, mutation boundaries, and beta support expectations before install. | Documentation contract tests and README inspection. | Pass |
| AC-2 | Security reports have an explicit private path and public issue forms redirect security reports. | Document and issue-template tests. | Pass |
| AC-3 | Diagnostics are generated only after a local-origin POST and contain a fixed allowlist without secrets, personal content, paths, identifiers, or logs. | Unit, request-boundary, and adversarial-fixture tests. | Pass |
| AC-4 | Settings shows the current version and direct docs, issue, and diagnostics actions with clear redaction copy. | UI contract test and rendered browser smoke. | Pass |
| AC-5 | The MIT license remains declared and included in Python release artifacts. | Existing beta-contract and artifact-verifier tests. | Pass |

### Constraints and recovery

- Safety: diagnostics are built in memory from generated metadata; no file,
  directory, environment, log, credential, endpoint, or personal-data reads.
- Compatibility: Python 3.11–3.13; macOS and Windows tier one; Linux preview.
- Rendered behavior: compact Settings actions wrap naturally and keep existing
  health/config sections intact.
- Rollback or recovery: remove the new route/UI action and documents; no data
  migration or persisted diagnostic state exists.
- Documentation targets: README, SECURITY, PRIVACY, SUPPORT, CONTRIBUTING,
  CODE_OF_CONDUCT, roadmap, changelog, issue/PR templates.
- Version-control strategy: `feat/m5-trust-support-readiness` into `main` in one
  ready PR after complete verification and adversarial review.

### Scope discussion and approval

- Recommendation and rationale: one coherent public-trust slice matches the
  exact Milestone 5 exit criteria and avoids mixing in release publication.
- Alternatives considered: collecting sanitized application logs was rejected
  because an allowlisted generated report is simpler and safer for beta.
- User decisions: the project owner approved all Road to Beta slices and asked
  execution to continue without repeated approval prompts. The process exception
  covers scope/test/publication gates; evidence and review requirements remain.
- Approved at: standing authorization reiterated 2026-07-20.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Trust/support docs absent. | `tests/test_trust_support_readiness.py` | Required topics and pre-install links exist. | Does not measure reader comprehension. |
| AC-2 | No private reporting route in project docs/templates. | Document/template contract tests. | Public forms consistently route security reports privately. | Cannot verify GitHub account permissions. |
| AC-3 | No diagnostics download. | Bundle unit tests plus request-boundary tests. | Fixed ZIP names, bounded output, hostile input omission, local POST, safe headers. | Does not attach a real GitHub issue. |
| AC-4 | No Settings help path. | UI source contract plus browser smoke. | Controls render and the download completes in a browser. | Browser smoke covers one local browser environment. |
| AC-5 | License already declared. | Existing packaging and license tests. | Wheel/sdist license metadata remains intact. | Native signed artifact evidence remains Milestone 4/6 gated. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Repository/document inspection | macOS workspace, Python source checkout | Fail (expected gap) | Required trust docs, issue forms, diagnostics route, and Settings actions were absent. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts the milestone's
  roadmap-defined behavior and proportionate unit/contract/browser strategy.
- Accepted coverage gaps: GitHub private-advisory availability and signed native
  release artifacts remain external release-configuration evidence.
- Approved at: standing authorization reiterated 2026-07-20.

## Implementation record

### Changes

- Added concise public security, privacy, beta support, contribution, and conduct
  policies plus focused GitHub issue and pull-request forms.
- Added `diagnostics_bundle.py`, a bounded in-memory ZIP builder that normalizes
  every value to a fixed category and ignores all unrestricted source fields.
- Added a loopback-origin-protected POST download with non-sniffable private
  response headers and no persistence.
- Added compact Settings help/version/actions and browser smoke coverage for the
  live ZIP response.
- Preserved the beginner-first README flow while putting support limitations and
  trust links before deeper technical documentation.

### Deviations and decisions

- The diagnostics bundle intentionally contains generated allowlisted JSON only;
  it never attempts to sanitize arbitrary logs after collection.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m py_compile diagnostics_bundle.py server.py` plus JS syntax checks | macOS, Python 3.13, Node | Exit 0 | 4 syntax targets | Server, bundle, and frontend parse cleanly. |
| `python3 -m unittest tests.test_trust_support_readiness tests.test_request_boundary tests.test_beta_contract tests.test_packaging_cli -v` | macOS, Python 3.13 | Exit 0 | 52 pass | First run found two wording expectations; corrected without weakening behavior. |
| `python3 -m unittest tests.test_ci_quality_gate tests.test_packaging_cli tests.test_trust_support_readiness -v` | macOS, Python 3.13 | Exit 0 | 34 pass | Exact artifact allowlist includes the new public module. |
| `git diff --check` | repository | Exit 0 | 0 errors | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS, Python 3.13 | Exit 0 | 739 pass, 4 platform skips | Complete repository suite green. |

An optional local artifact build could not start because this workspace lacks
the `build` module and an importable `setuptools.build_meta`. Exact artifact
inventory/license contract tests pass; the pinned hosted packaging workflow is
the authoritative artifact build after publication.

### Rendered or manual behavior

- Existing Chromium smoke plus the new Settings checks passed against
  `http://127.0.0.1:8891`: 18 named checks, including visible support actions,
  displayed `v0.1.0` version, HTTP 200 ZIP signature, content type, and fixed
  attachment disposition.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: complete uncommitted branch diff and all new files.
- Verification evidence: 739-pass full suite, 52/34 focused checks, and 18-check
  browser smoke.
- Rendered artifacts: live headless Chromium Settings flow and ZIP response.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | P2 | Yes | Duplicate allowlisted subsystem entries were not deduplicated or bounded before compression; 200,000 entries created a 12.8 MB uncompressed member in a 38 KB ZIP. | Yes | Keep one worst status per fixed key and cap uncompressed entry/total sizes. |
| A-2 | P2 | Yes | The POST called live `health()`, which can read local private state and contact Google Calendar or remote Hermes, contradicting the no-new-I/O contract. | Yes | Download only the previously sanitized dashboard health snapshot. |
| A-3 | P2 | Yes | The real local `cron` health key was omitted while unused keys were allowed. | Yes | Align the exact key set with local/remote health outputs and test cron. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | P1 initially; peer revised impact to P3 | Yes by strict trust invariant | Default `writestr` added ambient local timestamp/platform metadata outside the fixed allowlist; `generated_at` was also missing from privacy disclosure. | Yes | Use constant explicit `ZipInfo` metadata, test it, and disclose generation time. |
| B-2 | P1 initially; peer revised to P2 | Yes | The README's “Before installing” support link appeared after clone/pip/setup/run commands. | Yes | Move it above commands and assert ordering. |
| B-3 | P2 | No independently | Same missing-`cron` root cause as A-3 reduced diagnostic usefulness. | Yes | Add cron and representative coverage. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Missing cron | Corroborated | Both maintained it; safety treated it as acceptance-blocking. | Accept. Actual local health always includes cron. | Exact real key set now includes cron and removes unused categories. |
| ZIP metadata | Unique B | Safety maintained the evidence but revised impact to P3; strict allowlist still makes it process-blocking. | Accept. Ambient archive metadata contradicted the stated fixed shape. | Constant 1980 timestamp, Unix system, owner-only mode, and compression metadata plus assertions; privacy now names generation time. |
| README ordering | Unique B | Safety maintained as P2 blocking. | Accept. Presence-only evidence did not meet “before installation.” | Support note moved above commands; test asserts it precedes `git clone`. |
| Duplicate/uncompressed bound | Unique A | Product maintained as P2 hardening, non-blocking alone because production health cardinality is fixed. | Accept. The builder should preserve its own bounded invariant against regressions. | One worst status per six fixed keys plus 16 KiB entry and 64 KiB total uncompressed caps; 200,000-entry regression test. |
| Live health I/O on click | Unique A | Product maintained as P1 blocking due privacy/latency mismatch. | Accept. Redaction of output did not justify unexpected connected-service probes. | Ordinary `/api/health` stores only a sanitized snapshot; download deep-copies it without calling live health. Tests prove no live call and no raw fields in cache. |

### Reverification

- Focused tests: 43 pass after fixes; Python/JS syntax and diff check pass.
- Full suite: 741 pass, 4 platform-only skips after fixes.
- Browser smoke: all 18 checks pass after fixes, including the live ZIP path.
- Next review round or gate result: both reviewers will receive the fresh full
  diff and evidence after full/browser reverification.

### Round 2 — complete-slice re-review

- Reviewer A: **No findings; no blocking findings.** Independently reran 34
  relevant tests and diff check. Confirmed fixed bounds, exact keys, no-I/O
  snapshot, safe threaded publication, constant ZIP metadata, privacy wording,
  and README order.
- Reviewer B: **No findings; no blocking findings.** Independently reran 26
  focused tests. Confirmed product/support contract, UI workflow, issue routing,
  responsive controls, and every original finding's resolution.
- Gate result: passed. No reviewer dissent remains.

## Documentation updates

- Roadmap: Milestone 5 marked complete with signed release evidence kept in its
  owning milestones.
- Changelog: public trust, diagnostics, and safety outcome recorded.
- Architecture/operator docs: public trust/support set and README links added.
- Project/session notes: this persistent log.
- Documentation verification: focused contracts and full suite pass.

## Publication gate

- Proposed files: README, roadmap, changelog, public trust/support/contribution
  docs, GitHub issue/PR templates, diagnostics module/server/UI, package/artifact
  inventories, browser smoke, tests, and this review log.
- Branch and base: `feat/m5-trust-support-readiness` into `main`.
- Commit message: `feat: add beta trust and diagnostics support`.
- PR title: `Complete Milestone 5 trust and support readiness`.
- User authorization and scope: standing authorization covers commit, push,
  ready PR, and merge after required gates pass.
- Commit hash: pending.
- Ready PR URL: pending.

## Outcome review

- Classification: Successful through local implementation, full verification,
  browser verification, and adversarial review; publication is the remaining
  procedural step.
- Acceptance criteria summary: AC-1 through AC-5 pass.
- Potential bugs or untested paths: GitHub private-advisory availability and the
  pinned hosted artifact build require post-publication hosted verification;
  the local Python environment lacks the package-build backend.
- Remaining reviewer dissent: None.
- Compatibility/migration/rollback concerns: no data migration or persisted
  diagnostic state; remove the route/UI/docs to roll back.
- Next slice authorized: Yes, under the project owner's standing Road to Beta authorization after this milestone is complete.
