# Feature Slice Review: Beta Tester First-Launch Path

Status: Successful  
Slice: `beta-tester-first-launch`  
Date: `2026-07-31`  
Review log: `reviews/2026-07-31-beta-tester-first-launch.md`

## Process exception

- The project owner instructed Codex to assume approval for all Road-to-Beta
  slices, decisions, verification, and publication actions.
- That standing authorization covers this contract, test strategy, outcome,
  staging, commit, push, and ready pull request. Work remains one reviewed
  slice at a time and unrelated user files remain excluded.
- The previous bounded-notarization slice completed successfully and merged as
  pull request 90. Standing authorization permits this next slice without a
  separate outcome pause.

## Slice contract

### Goal

Give an invited beta tester one short, public path from the exact release
candidate to a first Mentat launch without sending them through the full
maintainer recovery rehearsal.

### In scope

- Add concise macOS native, Windows native, and supported `pipx` first-install
  and launch steps to the existing tester guide.
- Keep checksum verification and the exact invitation/release candidate as
  prerequisites.
- Make generated release-candidate notes point first-time testers to that
  guide while retaining the rehearsal as the recovery authority.
- Preserve the existing privacy, no-maintainer-help, first-workflow, feedback,
  and two-week checklist.
- Add focused documentation and generated-release-note contracts.

### Out of scope

- Browser-guided setup, a Settings connection picker, or any credential flow.
- Installer, launcher, runtime, Hermes, or release-artifact behavior changes.
- Changing recovery, migration, rollback, cohort, or beta exit criteria.
- Claiming that a public installer, completed signed RC, or tester cohort
  already exists.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The tester guide identifies the invitation's exact RC and checksum as the starting point, then gives distinct macOS, Windows, and `pipx` install/launch paths. | Focused guide contract and manual copy inspection | Pass |
| AC-2 | The short path leads into the existing version check and first-use checklist without duplicating the full recovery rehearsal. | Ordering and word-count contract | Pass |
| AC-3 | Generated RC notes link first-time installation to `BETA_TESTING.md` and keep `RELEASE_REHEARSAL.md` as the recovery authority. | Deterministic release-bundle test | Pass |
| AC-4 | No installer, launcher, credential, release gate, roadmap status, or external-evidence claim changes. | Diff inspection plus focused and full suites | Pass |
| AC-5 | Two independent adversarial reviewers report no unresolved in-scope issue. | Review record | Pass |

### Constraints and recovery

- Safety: no credentials, endpoints, machine paths, personal tester data, or
  private diagnostics enter the guide or generated notes.
- Compatibility: use commands already supported by the native launcher and
  packaged `pipx` CLI; do not promise a new install channel.
- Rendered behavior: documentation only; verify readable section order and
  bounded length rather than browser rendering.
- Rollback or recovery: revert the slice commits; no user data or runtime state
  changes.
- Documentation targets: `BETA_TESTING.md`, generated RC notes,
  `CHANGELOG.md`, and this review log.
- Version-control strategy: branch `codex/beta-tester-first-launch` from merged
  `main`, with a ready pull request back to `main`.

### Scope discussion and approval

- Recommendation and rationale: the existing tester checklist is the right
  public onboarding authority, but RC notes currently route a first-time
  install into a long maintainer rehearsal. A short entry section removes that
  detour without creating a second setup system.
- Alternatives considered: create a new install guide (more documentation and
  a competing authority); expand the README before public installers exist
  (would contradict its current release state); add browser setup (explicitly
  deferred and materially broader).
- User decisions: streamline onboarding while continuing Road to Beta; keep
  browser setup and Azure work out until their prerequisites exist.
- Approved at: 2026-07-31 under the recorded standing authorization.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | The guide starts with a generic checklist and contains no channel-specific launch handoff. | Require a `First launch` section with exact RC/checksum language and all three channel commands. | A tester can choose one supported path and reach Mentat. | Does not replace external clean-machine evidence. |
| AC-2 | Release installation and first-use steps are separated across technical documents. | Require first-launch content before the checklist and retain the existing sub-900-word bound. | The primary path stays short and precedes measurement. | Readability still needs manual inspection. |
| AC-3 | Generated notes link only the maintainer rehearsal for installation and recovery. | Build a deterministic fake RC bundle and inspect the generated notes links and wording. | Every RC carries the same first-time handoff while recovery stays canonical. | Does not publish a real release. |
| AC-4 | Documentation edits could accidentally claim unavailable artifacts or alter release code beyond copy. | Run beta-contract, limited-beta, release-rehearsal, packaging, and full-suite tests; inspect the raw diff. | Existing release and safety contracts remain intact. | Apple and Azure protected credentials are external. |
| AC-5 | Onboarding copy can still be ambiguous or platform-inaccurate. | Two identical read-only review packets and re-review after accepted fixes. | Independent safety, compatibility, and product scrutiny. | Reviewers do not perform external clean installs. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Source inspection | Merged `main` | Gap confirmed | `BETA_TESTING.md` has no channel-specific install/launch section; generated RC notes route installation and recovery together to `RELEASE_REHEARSAL.md`. |
| New first-launch guide contract | Pre-implementation branch | Expected fail | Missing `## First launch` section. |
| New generated-note handoff contract | Pre-implementation branch | Expected fail | Generated notes contain no `BETA_TESTING.md` link. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts focused
  documentation contracts plus the complete suite; no browser render is needed
  because this slice changes Markdown and deterministic generated Markdown.
- Accepted coverage gaps: only an invited external tester can prove no-help
  clean installation and time to first useful workflow.
- Approved at: 2026-07-31 under the recorded standing authorization.

## Implementation record

### Changes

- Added a short, checksum-first choice among macOS native, Windows native, and
  `pipx` to the tester guide before its existing timed checklist.
- Changed deterministic RC notes to link that guide for first installation and
  keep the rehearsal link for assigned recovery and upgrade drills.
- Added focused contracts and an operator-visible changelog entry.

### Deviations and decisions

- None.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m unittest tests.test_limited_beta_readiness tests.test_release_rehearsal tests.test_beta_contract tests.test_packaging_cli -q` | macOS, Python 3.13 | 0 | 51 pass | Tester guide, deterministic notes, beta truthfulness, installer, and CLI contracts. |
| Python compilation and `git diff --check` | macOS | 0 | All pass | Generated-note source compiles and patch is whitespace-clean. |
| Tester-guide word count | Source inspection | 753 words | Pass | Below the existing 900-word onboarding bound. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -q` | macOS, Python 3.13 | 0 | 915 run, 911 pass, 4 expected platform skips | No regression; negative-path CLI diagnostics are expected test output. |

### Rendered or manual behavior

- Manual Markdown inspection: the prerequisite, three channel headings, timed
  handoff, existing checklist, privacy warning, and recovery link read in one
  linear order. No browser rendering is involved.

## Adversarial review

### Round 1

- Correctness reviewer: one blocking issue. The pipx path installed a remote
  wheel without a channel-local checksum step, while the broad guide contract
  let the unsafe ordering pass.
- Operability reviewer: two blocking issues. It independently found the pipx
  checksum-order defect, and also found that native commands used unexplained
  filenames and assumed the shell already opened in Downloads.
- Reconciliation: accepted all findings. The guide now names each exact
  artifact, uses quoted Downloads-qualified paths, verifies the pipx wheel
  before installing its local file, and the generated notes no longer expose a
  direct remote-install shortcut. Tests now inspect each channel's local
  contract and enforce checksum-before-install ordering.
- Re-review: Round 2 found two shared blocking issues, one additional
  operability issue, and one Markdown semantics issue. Both reviewers found
  that Linux needs `sha256sum` rather than macOS's `shasum`, and that the
  recorded guide word count was stale. The operability reviewer also found
  that the pipx path did not state its Python and pipx prerequisites, and that
  the final command fence was detached from its numbered step.
- Round 2 reconciliation: accepted all findings. The guide now separates the
  three platform checksum commands, states the supported Python range and
  links the official pipx installation guide, keeps the setup block inside its
  list item, and records the current word count. The focused contract now
  requires the Linux command and pipx prerequisites.
- Round 3: the operability reviewer reported no unresolved issue. The
  correctness reviewer found one blocking test-quality gap: ordering checks
  compared the download's `SHA256SUMS` text rather than the actual hashing
  command, so a command could move below installation without a failure.
- Round 3 reconciliation: accepted. Each native assertion now compares its
  platform hashing command with the install action, and all three pipx hashing
  commands must precede the first local install command.
- Round 4: both independent reviewers reported no unresolved in-scope issue.
  The operability reviewer reran the focused 51-test set and `git diff --check`;
  both passed. No reviewer edited files.

## Documentation updates

- Roadmap: no status change planned; external gates remain open.
- Changelog: records the shorter first-launch handoff.
- Architecture/operator docs: tester guide and generated RC notes updated;
  recovery remains canonical in `RELEASE_REHEARSAL.md`.
- Project/session notes: this review log.
- Documentation verification: focused 51-test contract passes; guide is 753
  words and generated notes remain deterministic.

## Publication gate

- Proposed files: `BETA_TESTING.md`, `CHANGELOG.md`,
  `scripts/release_rehearsal.py`, `tests/test_limited_beta_readiness.py`,
  `tests/test_release_rehearsal.py`, and this review log.
- Branch and base: `codex/beta-tester-first-launch` to `main`.
- Commit message: `Streamline beta tester first launch`.
- PR title: `Streamline beta tester first launch`.
- PR summary: add a short supported-channel handoff for invited testers and
  route generated RC notes to it while retaining the full recovery rehearsal.
- Unresolved risks: external clean-machine/no-help evidence remains required;
  this documentation slice does not claim that evidence.
- User authorization and scope: standing Road-to-Beta approval recorded above.
- Commit hash: recorded in the branch history after the publication gate.
- Ready PR URL: recorded in the publication handoff after creation.

## Outcome review

- Classification: Successful.
- Acceptance criteria summary: AC-1 through AC-5 pass.
- Potential bugs or untested paths: an external tester must still prove the
  clean-machine, no-maintainer-help experience for each assigned channel.
- Remaining reviewer dissent: none after four rounds.
- Compatibility/migration/rollback concerns: documentation-only; revert the
  slice commits.
- User decision: standing authorization permits publication; all local gates
  and independent review gates passed.
- Next slice authorized: Yes, under the standing Road-to-Beta authorization.
