# Feature Slice Review: Remote Public-Text Performance Stability

Status: Successful
Slice: `remote-public-text-performance`
Date: `2026-07-31`
Review log: `reviews/2026-07-31-remote-public-text-performance.md`

## Process exception

- The user instructed Codex to assume approval for all slices and related
  implementation, verification, publication, and continuation decisions.
- Standing approval covers this contract, test strategy, implementation,
  verification, outcome, staging, commit, push, ready pull request, merge, and
  continuation to the next reviewed slice.

## Slice contract

### Goal

Remove the reproduced macOS Python 3.12 performance bottleneck in remote
session public-text validation without weakening its fail-closed path,
credential, host, URL, normalization, or browser-output safety boundary.

### In scope

- Avoid the delimiter grammar entirely for the exact public-safe shape made
  only from `:` and `=` characters.
- Preserve all existing security decisions and maximum-input bounds.
- Verify the maximum slash-free text performance contract, the complete remote
  session module, and the full suite.
- Record and publish the fix separately from the macOS signing workflow slice
  whose otherwise-green CI exposed it.

### Out of scope

- Raising or removing the two-second hosted macOS validation budget.
- Changing session result limits, redaction policy, URL policy, secret grammar,
  remote API behavior, or browser payload shape.
- Changing signing/release workflow behavior or user-owned project data/designs.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Non-empty delimiter-only text skips the expensive delimiter grammar, while every other value retains the original path. | Source inspection, targeted tests, and differential comparison | Pass |
| AC-2 | Identifier, property, bracket, host/port, human credential phrase, URL, secret-token, and normalization decisions remain unchanged. | Complete remote-session test module, bracket regressions, and differential comparison | Pass |
| AC-3 | Maximum delimiter-dense input remains under the unchanged platform-aware budget. | Existing performance contract locally and hosted macOS CI | Pass |
| AC-4 | The optimization remains linear and bounded for the maximum 100,000-character public input. | Algorithm inspection and benchmark evidence | Pass |
| AC-5 | No unrelated application, release, or user-owned files enter the slice. | Scoped diff and staged-file inspection | Pass |
| AC-6 | Two independent adversarial reviewers find no unresolved blocking correctness, safety, compatibility, or operability gap. | Review record | Pass |

### Constraints and recovery

- Fail closed: ambiguous credential, path, host, URL, bracket, or normalized
  content must still be rejected.
- Performance: do not solve the reproduced failure by widening the budget.
- Compatibility: use only existing Python 3.11-3.13 language/runtime behavior.
- Recovery: one isolated code change can be reverted without data migration or
  external-state cleanup.
- Version-control strategy: ready PR from
  `codex/remote-public-text-performance` to `main`.

### Scope discussion and approval

- Recommendation and rationale: fix the repeated inert-delimiter work exposed
  twice on the same hosted shard; this is the smallest implementation change
  that improves the actual validator instead of masking the failure.
- Alternatives considered: rerun indefinitely (already failed twice); raise the
  budget (masks regression); disable the performance assertion (unsafe); fold
  it silently into the signing slice (violates scope continuity).
- User decision: standing approval applies.
- Approved at: `2026-07-31` under the process exception.

## Test strategy

| Acceptance criterion | Planned evidence | Limitation |
| --- | --- | --- |
| AC-1 | Inspect the exact delimiter-only fast path and run the targeted maximum-input test for colon-only, equals-only, and mixed input. | Unit tests cannot enumerate all Unicode strings. |
| AC-2 | Run all `tests.test_remote_sessions` cases, add bracket-shape regressions, and compare 25,000 deterministic random values against the unchanged implementation. | Live remote Hermes is mocked; differential fuzzing is sampled rather than exhaustive. |
| AC-3 | Keep the exact existing budget and rerun hosted macOS Python 3.12 CI. | Hosted load varies; repeated pass is the final gate. |
| AC-4 | Compare five local maximum delimiter-dense samples before/after and inspect loop bounds. | Local hardware is faster than hosted Intel macOS. |
| AC-5 | Inspect scoped diff/staging and preserve local user files. | Does not validate untracked user content. |
| AC-6 | Two independent read-only adversarial reviews after verification. | Reviewers do not control hosted runner load. |

### Baseline results

- Pull request 83's otherwise-green first CI attempt failed only macOS Python
  3.12 when the unchanged delimiter-dense performance assertion took
  2.016983895 seconds against its 2.0-second budget.
- A targeted failed-job rerun reproduced the same assertion at
  2.050326516 seconds; this ruled out a single transient event.
- Five local baseline calls for 100,000 colons took approximately 0.307,
  0.314, 0.308, 0.313, and 0.314 seconds.

## Implementation record

### Changes

- `_secret_shaped_text()` still performs the secret-token check first.
- It then returns public only for a non-empty value whose entire content is
  made from `:` and `=`. Such a value cannot contain a credential label, host,
  path, URL, or bracket expression.
- Every other value continues through the unchanged credential candidate,
  bracket, port, property-chain, bounded identifier, and credential grammar.
- The performance test now covers colon-only, equals-only, and mixed
  delimiter-only maximum-size values. It also locks in malformed, quoted, and
  overlong punctuation-ending bracket cases exposed during review.
- The test budget and all existing security expectations are unchanged.

### Deviations and decisions

- The first attempted per-delimiter shortcut was removed after both reviewers
  showed that immediate-left-character reasoning could bypass an active or
  malformed bracket context.
- The replacement is a whole-value proof for one exact inert character class;
  it does not alter the per-delimiter decision path.
- Three proposed unquoted, closed punctuation-label assertions were not kept:
  direct baseline checks showed the unchanged implementation already treats
  those exact shapes as public. Making them private would be an unrelated
  grammar change rather than continuity evidence. Quoted, unmatched, and
  overlong ambiguous bracket shapes remain fail closed and are now explicit
  regressions.

## Verification

### Focused checks

- Targeted maximum-input performance test: passed under the unchanged budget.
- Complete `tests.test_remote_sessions` module: 29 passed after adding the
  bracket and delimiter-only regression cases.
- Five local post-change 100,000-colon calls took approximately 0.114, 0.105,
  0.105, 0.103, and 0.102 seconds. Equals-only and mixed values were similarly
  approximately 0.10 seconds, with one equals-only sample at 0.165 seconds.
- A deterministic 25,000-case random differential comparison against the
  unchanged function produced zero decision differences. Explicit empty,
  colon-only, equals-only, and mixed-delimiter boundary cases also matched.
- `git diff --check`: passed.

### Full suite

- `python3 -m unittest discover -s tests -q`: 910 run; 908 passed, 2 failed,
  4 skipped.
- The two failures are the unchanged machine-local state differences outside
  this slice: the preserved `Daily Check` project and the live Hermes cron
  inventory returning zero jobs where a fixture expects one.
- No remote-session validation or performance test failed.

### Publication checks

- `python3 -m py_compile remote_hermes.py`: passed.
- The scoped implementation diff is one six-line exact-shape fast path plus
  focused regression-test updates; this review record is the only other slice
  file.
- User-owned `data/projects.json` and `design/` remain excluded.
- Pull request 84 ran 50 hosted checks and all 50 passed. The previously
  failing `macos-15-intel / Python 3.12` shard passed in 4m03s without changing
  the two-second assertion budget. macOS Python 3.11 and 3.13, Linux and
  Windows matrices, native artifacts, browser smoke, packaging, quality, and
  dependency/secret scanning also passed.

## Adversarial review

### Round 1

- Both reviewers independently reported a blocking P1: the initial
  immediate-left-character shortcut bypassed malformed or punctuation-ending
  bracket handling. The operability reviewer also reported a P2 test-coverage
  gap around the new equivalence boundary.
- Disposition: accepted root cause. The shortcut was removed rather than
  amended. A narrow whole-value delimiter-only proof replaced it, and focused
  bracket and expanded delimiter-only regressions were added.
- Reviewer examples involving closed, unquoted punctuation labels were checked
  against the unchanged implementation and found not to be before/after
  regressions. They are recorded as evidence but excluded from this continuity
  slice; quoted, unmatched, and overlong ambiguous forms are covered.
- Round 2 correctness/safety reviewer: no P0-P3 findings; AC-1, AC-2, AC-4,
  and AC-5 pass, AC-3 passes locally pending hosted confirmation, and the
  Round 1 blocking finding is resolved.
- Round 2 compatibility/operability reviewer: no P0-P3 findings; independently
  reran 29/29 remote-session tests, compilation, diff checks, and maximum-input
  samples at approximately 0.10 seconds. AC-1 through AC-6 pass locally, with
  hosted macOS confirmation remaining the publication gate.
- Both reviewers agreed that changing the already-public closed unquoted
  punctuation-label grammar would be an out-of-scope security-policy change.

## Outcome

- Successful. All acceptance criteria pass, both reviewers report no P0-P3
  findings after the correction, and all 50 hosted checks pass. The change is
  isolated to validation code, focused tests, and this review record; rollback
  is a normal commit revert with no data migration or external cleanup.
