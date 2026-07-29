# Feature Slice Review: Beta 6 release-candidate rehearsal

Status: Paused — publication approval and external rehearsal
Slice: `beta-6-release-candidate-rehearsal`
Date: `2026-07-20`
Review log: `reviews/2026-07-20-beta-6-release-candidate-rehearsal.md`

## Slice contract

### Goal

Make one exact release-candidate commit produce a reproducible, checksummed,
publicly documented artifact set through the protected signed workflow, with a
clear rehearsal and bad-release replacement checklist.

### In scope

- Deterministic release manifest, SHA-256 checksums, and concise release notes
  for the exact macOS, Windows, wheel, and sdist artifacts.
- RC/final-beta tag validation bound to the product version and exact source SHA.
- Protected workflow assembly of signed native and verified Python artifacts
  into one prerelease bundle after all required jobs pass.
- Public install, backup, upgrade, restore, rollback, uninstall-preservation,
  and bad-RC replacement checklist.
- Contract, negative-path, reproducibility, and workflow tests.
- Honest evidence record for the real signed/clean-machine rehearsal gate.

### Out of scope

- Inventing signing credentials, bypassing the protected `beta-release`
  environment, or creating an unsigned public RC.
- Claiming clean tier-one external-machine evidence before the protected run.
- Automatic updates, deletion of a bad tag/release, or hiding withdrawn history.
- The Milestone 7 tester cohort.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | An exact beta or numbered RC tag is accepted; other tags and mismatched source/version data fail closed. | Tag/manifest unit tests. | Pass |
| AC-2 | Exactly four expected public artifacts produce deterministic notes, manifest, and checksums without paths, secrets, timestamps, or extra files. | Reproducibility, hostile input, and exact inventory tests. | Pass |
| AC-3 | The protected workflow builds/verifies Python artifacts, gathers all signed outputs, creates the bundle, and publishes only after every protected job succeeds. | Workflow contract tests. | Pass — hosted execution pending |
| AC-4 | A second operator can follow one checklist for install, backup, upgrade, restore, rollback, uninstall, and bad-RC replacement without deleting history. | Documentation contract and manual review. | Pass — second-person execution pending |
| AC-5 | Repository-owned tests and existing preservation drills pass; the actual signed RC remains explicitly gated until credentials/protection/clean machines are available. | Focused/full suite and evidence log. | Pass — external gate retained |

### Constraints and recovery

- Safety: exact regular-file allowlist; streaming hashes; bounded names/counts;
  no credentials, local paths, runtime data, personal content, or ambient time.
- Compatibility: macOS/Windows signed native channels and Python 3.11–3.13
  `pipx`; Linux remains preview through `pipx`.
- Rendered behavior: public Markdown stays short, beginner-readable, and usable
  before download.
- Rollback or recovery: bad RCs are marked withdrawn and replaced by a higher
  RC number; tags and release history are never silently deleted.
- Documentation targets: release rehearsal checklist, roadmap, changelog,
  packaging guide, and persistent review log.
- Version-control strategy: `feat/m6-release-candidate-rehearsal` into `main` as
  one ready PR after local and hosted review gates.

### Scope discussion and approval

- Recommendation and rationale: complete every repository-controlled rehearsal
  mechanism now, but keep signed execution evidence separate from code claims.
- Alternatives considered: manually assembling checksums/notes was rejected as
  non-reproducible; publishing unsigned native artifacts was rejected by the
  approved beta contract.
- User decisions: standing Road to Beta authorization approves this slice and
  publication after required reviews; external signing gates must remain honest.
- Approved at: standing authorization reiterated 2026-07-20.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Workflow only accepts the final display tag and cannot name RCs. | Pure tag/source validation tests. | Only the current beta and numbered RC tags are valid. | Does not create a real remote tag locally. |
| AC-2 | No final release bundle generator exists. | Temporary-artifact exactness/reproducibility/negative tests. | Output is complete, deterministic, path-free, and fail-closed. | Signatures are checked by protected platform jobs. |
| AC-3 | Signed workflow omits Python artifacts, checksums, notes, and release publication. | Workflow source contract tests. | Every artifact/result is wired into the final gate. | Secrets/environment rules require GitHub-hosted evidence. |
| AC-4 | No single public rehearsal runbook exists. | Required-step/order/link contract tests and inspection. | Operators see all required drills and withdrawal policy. | A second human rehearsal remains external evidence. |
| AC-5 | Preservation tests exist separately. | Focused tests, full suite, and existing upgrade/uninstall test. | Repository-owned behavior remains green. | Actual signed tier-one rehearsal cannot be simulated. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Repository and workflow inspection | merged main at `da0e9a2` | Expected gap | Signed jobs/tag exist; final Python bundle, manifest/checksums/notes, RC tag form, and rehearsal runbook are absent. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts the roadmap's
  exact Milestone 6 scope and proportionate contract/full-suite strategy.
- Accepted coverage gaps: real signing/notarization, protected environment,
  public prerelease, and clean external tier-one installs remain mandatory
  hosted/manual evidence before Milestone 6 can be marked complete.
- Approved at: standing authorization reiterated 2026-07-20.

## Implementation record

### Changes

- Added `scripts/release_rehearsal.py` with exact tag/source validation, a
  four-file allowlist, no-follow regular-file hashing, deterministic SHA-256,
  manifest, and release-note output, and exclusive metadata-file creation.
- Added `RELEASE_REHEARSAL.md` as the public checklist for exact artifact
  verification, clean install, upgrade, backup, restore, rollback,
  uninstall/reinstall, second-person acceptance, and visible RC withdrawal.
- Added a verified Python artifact job to the protected signed workflow. The
  final job now downloads all three job artifacts, rejects an inexact
  inventory, builds metadata before tagging, preserves the exact recovery
  bundle, and publishes one prerelease.
- Documented the Intel macOS artifact and separate Apple Silicon with Rosetta
  rehearsal role without claiming untested support.
- Added focused negative, reproducibility, documentation, packaging, and
  workflow contract tests.

### Deviations and decisions

- The repository cannot supply signing credentials, configure the protected
  environment, or manufacture second-person clean-machine evidence. The code
  portion therefore remains explicitly separate from Milestone 6 completion.
- Direct workflow-style invocation initially failed to import `mentat`; the
  script now adds the repository root before its version import and a
  subprocess regression runs from outside the checkout.
- Local `data/tasks.json` changes and an unrelated deferred-work addition in
  `ROAD_TO_BETA.md` are user-owned and excluded from this slice's publication
  scope.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m py_compile scripts/release_rehearsal.py` | local shell | 127 | Not run | No `python` executable exists on local PATH; repeated with `python3`. |
| `python3 -m py_compile scripts/release_rehearsal.py` | macOS, Python 3.13.14 | 0 | Pass | Script compiles. |
| `python3 -m unittest tests.test_release_rehearsal tests.test_ci_quality_gate tests.test_packaging_cli tests.test_trust_support_readiness -v` | macOS, Python 3.13.14 | 0 | 42 pass | Final tag, source, direct CLI, inventory, reproducibility, symlink, output, docs, workflow, packaging, and support contracts. |
| `ruby -e 'require "yaml"; YAML.parse_file(".github/workflows/signed-release-artifacts.yml")'` | local macOS Ruby | 0 | Pass | Workflow YAML parses. |
| `git diff --check` | local worktree | 0 | Pass | No whitespace errors. |
| `python3 scripts/check_tracked_secrets.py` | macOS, Python 3.13.14 | 1 | Tool unavailable | Local interpreter lacks `detect_secrets`; no scan result was produced. Pinned hosted quality gate remains required. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | macOS, Python 3.13.14 | 0 | 748 pass, 4 skip | Final exact diff; expected native-Windows skips only; existing upgrade/uninstall/reinstall preservation test passed. |

### Rendered or manual behavior

- No application UI changed. Public Markdown was inspected for short,
  beginner-readable steps and has a focused content contract test.

## Adversarial review

### Round 1 packet

- Diff reviewed: complete raw slice diff after direct CLI import correction;
  user-owned task data and unrelated roadmap hunk explicitly excluded.
- Evidence: focused tests, full suite, YAML parse, and diff check.
- Rendered artifacts: not applicable; public Markdown inspected directly.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | High | Yes | Native commands were not on PATH; backup location/confirmation and ordering were incomplete. | Yes | Add exact platform commands, locations, copy step, and backup-before-upgrade flow. |
| A-2 | Medium | Yes | Tag immutability promise lacked an update/deletion protection preflight. | Yes | Make verified release-tag protection an external gate. |
| A-3 | Medium | Yes | A failure after tag push could strand a tag without a recoverable release. | Yes | Preserve exact pre-tag recovery bytes and document same-tag completion. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | High | Yes | Public checklist lacked executable native/pipx install, backup, restore, rollback, and uninstall steps. | Yes | Add exact channel procedures and stronger content tests. |
| B-2 | Medium | Yes | Tag-first publication had no partial-publication recovery procedure. | Yes | Reuse only the original protected-run artifact bytes. |
| B-3 | Medium | Yes for rehearsal | Intel-only macOS artifact was broader than public macOS wording. | Yes | Disclose Intel packaging and require Apple Silicon+Rosetta evidence. |

### Reconciliation and disposition

| Finding/root cause | Classification | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Native recovery procedure | Corroborated | Both maintained | Accepted | Exact native commands, backup locations/copy, real prior-version upgrade, isolated restore, and tests. |
| Tag protection | Unique A | Reviewer B maintained | Accepted as external completion gate | Added tag update/deletion protection preflight. |
| Partial publication | Corroborated | Both maintained | Accepted | Checksum-verified seven-file recovery artifact uploaded before tag; no rebuild/replacement recovery rule. |
| Intel macOS scope | Unique B | Reviewer A maintained | Accepted | Intel limitation and separate Apple Silicon+Rosetta rehearsal are explicit. |

### Rounds 2 and 3

- Round 2 found that reinstalling the application did not create a clean
  restore target, the candidate was installed before the supposed upgrade,
  and same-candidate uninstall/reinstall preservation lacked an executable
  sequence. Both reviewers maintained the evidence. The guide now uses distinct
  `CLEAN_INSTALL_DIR`, `UPGRADE_DIR`, and `RESTORE_DIR` states; requires a real
  previous artifact, `restored` result, app-level comparison, and same-candidate
  preservation before rollback.
- Round 3 found two final ordering issues: the upgraded instance needed to stop
  before the restore instance started, and preservation needed to precede
  rollback. Both were corrected and contract-tested.
- Low documentation cleanups were accepted: the rehearsal is the artifact
  install authority, README remains source setup, the sdist is named, and
  SUPPORT distinguishes RC prereleases from the final beta.

### Final re-review

- Reviewer A: **No findings**. Independently reran 748 tests with 4 expected
  skips, plus focused checks, YAML parse, and diff check.
- Reviewer B: **No findings**. Independently reran 33 focused tests, YAML
  parse, and diff check.
- Gate result: no blocking or non-blocking reviewer finding remains.

## Documentation updates

- Roadmap: marks repository tooling in progress and retains the signed/manual
  completion gate.
- Changelog: records deterministic metadata, rehearsal guide, and protected
  Python/prerelease assembly.
- Architecture/operator docs: adds `RELEASE_REHEARSAL.md` and links it from the
  native packaging guide; clarifies the Intel/Rosetta support boundary.
- Documentation verification: focused documentation contract passed.

## Publication gate

- Branch and base: `feat/m6-release-candidate-rehearsal` into `main`.
- Proposed commit: `feat: add release candidate rehearsal tooling`.
- Proposed PR: `Add Milestone 6 release candidate rehearsal tooling`.
- Proposed files: signed workflow, release generator, release guide, support
  and packaging guides, focused tests, changelog, Milestone 6 roadmap hunks,
  and this log.
- Exclusions: `data/tasks.json` and the unrelated Road to Beta deferred-work
  hunk remain unstaged.
- User authorization: standing Road to Beta authorization covers slices, but
  the selected skill requires the final exact publication packet immediately
  before staging, commit, push, and ready PR creation.

## Outcome review

- Classification: Partially successful pending publication and the protected
  signed/manual rehearsal; all repository-owned acceptance evidence passes.
- External completion gate: protected signed RC run plus clean tier-one/manual
  recovery evidence.
- Next slice authorized: No; Milestone 7 requires the real Milestone 6 rehearsal.
