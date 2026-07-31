# Feature Slice Review: Onboarding CLI Continuity

Status: Successful
Slice: `onboarding-cli-continuity`
Date: `2026-07-31`

## Process exception

- The user instructed Codex to assume approval for all slices and related
  decisions.
- Standing approval covers this contract, test strategy, outcome, staging,
  commit, push, and ready pull request.
- Work remains one reviewed slice at a time, with unrelated user files excluded.

## Slice contract

### Goal

Make the installed setup result truthful and immediately actionable for both
planner-only users and users who intend to connect Hermes.

### In scope

- Report the exact installed CLI command that starts Mentat and opens its
  browser dashboard.
- Keep that base command available as a stable machine-readable result field,
  and indicate when private setup options must be repeated without echoing
  their values.
- State that planning remains usable without Hermes.
- Add a focused regression test and changelog entry.

### Out of scope

- A browser-guided first-run or Settings connection picker, which the beta
  roadmap explicitly defers.
- Changing native-launcher behavior; native bundles already open the browser by
  default.
- Changing source-checkout setup instructions, remote credential handling, or
  any Hermes capability.
- User-owned `data/projects.json` and `design/`.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Default `mentat setup` reports `mentat start --open-browser` as the exact next command. | Focused CLI test | Pass |
| AC-2 | Setup no longer claims plain `mentat start` opens the browser. | Focused CLI test | Pass |
| AC-3 | Setup clearly says planning works without Hermes. | Focused CLI test | Pass |
| AC-4 | Customized setup tells callers to repeat the same options without echoing private option values; native launching and CLI lifecycle remain unchanged. | Focused and full-suite verification | Pass |
| AC-5 | Two independent adversarial reviewers find no unresolved in-scope regression. | Review record | Pass |

### Constraints and recovery

- Output remains JSON and does not include paths, credentials, endpoints, or
  machine-specific state.
- No data migration or runtime behavior changes.
- Rollback is the slice commit.
- Branch: `codex/onboarding-cli-continuity`, based on merged `main`.

## Test strategy

| Criterion | Baseline gap | Planned evidence | Limitation |
| --- | --- | --- | --- |
| AC-1 | Setup recommends a command without the browser-opening flag. | Parse successful default setup JSON and assert the exact `next_command`. | Does not launch a real browser. |
| AC-2 | Human-readable text claims plain start opens the dashboard. | Reject the stale phrase in the focused test. | Copy correctness only. |
| AC-3 | The successful result does not explain the planner-only path. | Assert the no-Hermes planning statement. | Hermes discovery remains the doctor's job. |
| AC-4 | A fixed command alone would lose supported custom runtime choices; echoing values could expose private paths. | Assert custom setup returns `repeat_setup_options: true`, truthful copy, and no option values; run packaging CLI tests and the complete suite. | Callers must retain their own options. |
| AC-5 | Small copy/API changes can still create compatibility ambiguity. | Two read-only adversarial reviews after verification. | Reviewers do not modify the worktree. |

## Baseline evidence

- `mentat setup` currently reports: “Run `mentat start` to open your
  dashboard.”
- `mentat start` runs the server in the foreground and opens no browser unless
  `--open-browser` is supplied.
- Native launcher shortcuts already default to `start --open-browser`.
- The README already explains that Mentat works as a planner without Hermes.
- The roadmap defers a browser-guided connection/setup picker until after beta.

## Implementation record

- Updated successful setup JSON with truthful launch guidance and a stable
  `next_command` field.
- Added `repeat_setup_options` and tailored copy so customized setup safely
  preserves its continuation contract without returning private values.
- Kept output secret-free and path-free.
- Added a focused setup-result regression test and changelog entry.

## Verification

- Python compilation and patch whitespace checks passed.
- All 24 packaging/CLI tests passed, including default and custom setup paths,
  installed lifecycle, native browser launch, and diagnostic privacy.
- A real setup against a temporary data root returned the expected fixed base
  command, option-repeat signal, planner-only guidance, and no private path.
- Complete suite: 908 run, 903 passed, 1 failed, 4 skipped.
- The sole failure is the pre-existing user-owned `Daily Check` fixture conflict
  in `test_only_mentat_project_remains_active_for_v1`; this slice does not edit
  `data/projects.json`.

## Adversarial review

### Round 1

- The safety/privacy reviewer reported no finding: the command is fixed,
  path-free, secret-free, and does not alter runtime or credential behavior.
- The product/compatibility reviewer found one P2: supported custom runtime
  setup options would be lost if a caller followed only the fixed command.
- Resolution: report whether setup options must be repeated, tailor the message,
  keep their values out of output, and add a custom-options regression test.

### Round 2

- The product/compatibility reviewer confirmed the P2 is fully resolved: both
  default and customized continuations are truthful, covered, and additive.
- The safety/privacy reviewer confirmed only a boolean and fixed base command
  cross the output boundary; no option value, path, host, port, endpoint,
  environment name, or credential is returned.
- Both reviewers reported no remaining in-scope finding.

## Outcome review

- Classification: successful.
- AC-1 through AC-5 pass. The single full-suite failure belongs to the disclosed
  user-owned local seed fixture and is unrelated.
- Migration: none. Rollback: revert the slice commit.

## Publication packet

- Proposed files:
  - `CHANGELOG.md`
  - `mentat/cli.py`
  - `tests/test_packaging_cli.py`
  - this review log
- Explicit exclusions: user-owned `data/projects.json` and `design/`.
- Branch/base: `codex/onboarding-cli-continuity` on `main`.
- Proposed commit and ready PR title: `Clarify installed setup next steps`.

## Approval

- Contract, test strategy, outcome handling, and publication are covered by the
  user's standing approval.

## Publication result

- Implementation commit: `5ecf2c7`.
- Ready pull request: https://github.com/hazeion/agent-os/pull/78
- Base: `main`.
- Exact staged scope matched the publication packet.
- User-owned `data/projects.json` and `design/` remained unstaged.
