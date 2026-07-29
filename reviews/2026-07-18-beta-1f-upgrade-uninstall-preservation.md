# Feature Slice Review: Upgrade and Uninstall Data Preservation

Status: Implementation, local verification, documentation, and two zero-finding adversarial reviews complete; final exact-head hosted verification and merge pending
Slice: `beta-1f-upgrade-uninstall-preservation`
Date: `2026-07-18`
Review log: `reviews/2026-07-18-beta-1f-upgrade-uninstall-preservation.md`

## Slice contract

### Goal

Close Milestone 1 by proving that a manual versioned application replacement
and an application-only uninstall preserve the external Mentat data root,
including tasks, settings, Context Packs, retained Console history, SQLite
metadata, and referenced blobs.

### In scope

- Cross-platform integration coverage using isolated, versioned application
  trees whose immutable packaged seeds deliberately differ.
- A clean installed-style first start into a sibling external data root,
  realistic operator mutations, and a verified version-2 pre-upgrade backup.
- Application replacement followed by startup against the same external data
  root, proving newer packaged defaults never refresh or overwrite existing
  operator documents.
- Application-only uninstall followed by reinstall, proving deletion of the
  application tree does not delete, relocate, or rewrite durable operator or
  private Console state.
- Exact durable-JSON byte checks, private Console consistency-unit checks,
  backup validation, application-tree immutability checks, and platform-owner
  permission checks where supported.
- Roadmap, data-layout, README, changelog, tests, two independent adversarial
  reviews, hosted CI, publication, merge, and outcome review.

### Out of scope

- Choosing or implementing native installer formats, package metadata, a
  unified installed CLI, signing/notarization, automatic updates, or an
  uninstaller executable; those remain Milestone 3 and later.
- Deleting the operator data root, adding an opt-in data-removal command, or
  treating cache/runtime/log/browser/external state as durable preservation
  authority.
- Schema downgrade, rollback rehearsal, remote-Hermes credentials, secret
  export, release artifacts, or installer-specific registry/LaunchAgent/
  shortcut cleanup.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Installed-style first start creates a current external data root without modifying the versioned application tree. | Application/data sibling integration test and tree snapshot | Complete |
| AC-2 | A valid version-2 backup of all supported durable JSON and retained private Console state exists before application replacement. | Backup result, preview, and archive-presence assertions | Complete |
| AC-3 | Starting a replacement application tree with changed packaged seeds preserves exact task, dashboard-setting, Context Pack, and other fixed durable-document bytes. | Before/after fixed-inventory byte comparison | Complete |
| AC-4 | Upgrade preserves the retained Console consistency unit: history, SQLite relationships, attachment metadata, and referenced blob bytes remain valid and equivalent. | Private-unit capture/digest and attachment-resolution assertions | Complete |
| AC-5 | Removing only the application tree leaves the external data root byte-for-byte unchanged, including backups and durable configuration, while excluded runtime/cache/log state grants no preservation authority. | Pre/post uninstall filesystem snapshot with class exclusions stated | Complete |
| AC-6 | Reinstalling from another changed application tree reconnects to the same data root without recopying defaults, duplicating private records, or modifying the application tree. | Reinstall startup, exact JSON/private checks, and application snapshot | Complete |
| AC-7 | Local/full/static checks, the supported hosted matrix, documentation, and two independent adversarial reviews clear on the final diff. | Verification record and CI link | Code-head hosted/review complete; final evidence-log head pending |

### Constraints and recovery

- The application tree and data root are distinct siblings; no test may infer
  preservation from overlapping paths.
- Only temporary test-owned application trees are removed. The integration
  test never deletes a real checkout, configured operator root, home
  directory, or platform default.
- Upgrade uses the existing startup/initializer/schema gates and ordinary
  backup API. It does not add a hidden migration or overwrite rule.
- Uninstall preservation means application-only removal. Operator data removal
  would require a separate explicit product decision and exact safety design.
- The pre-upgrade backup remains below the external data root and therefore
  survives application removal; recursive backup, runtime, cache, log, browser,
  external, and credential classes remain excluded according to their current
  policies.

### Scope discussion and approval

- Recommendation: close Milestone 1 with integration tests over the existing
  installed-data boundary, not a placeholder installer. This directly proves
  data ownership and preservation while leaving installer format/tooling to
  its roadmap dependency in Milestone 3.
- Alternatives rejected: a documentation-only claim would not exercise the
  boundary; introducing an installer or uninstaller now would choose tooling
  prematurely; copying the data root during upgrade would create a competing
  authority; treating source-checkout `data/` as installed operator state would
  test the wrong layout.
- User decision: standing authorization requires completion of every roadmap
  criterion in bounded slices, repeated review to zero findings, publication,
  merge, and immediate continuation. This records approval for the recommended
  test-focused scope without expanding into installer implementation.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Initialization tests do not model a replaceable application tree. | Create versioned seed/app tree and external sibling root; snapshot app before/after startup. | Installed startup reads immutable seeds and writes only external state. | Does not build a native artifact. |
| AC-2 | Backup tests do not place backup explicitly in an upgrade sequence. | Create and preview a version-2 backup before replacing the app tree. | Manual upgrade has verified recovery evidence first. | Does not automate update orchestration. |
| AC-3 | Missing-only seed tests do not span versioned app replacement. | Give every replacement seed different bytes and compare all live documents exactly. | Packaged-default changes cannot overwrite operator state. | Future schema steps need their own migration tests. |
| AC-4 | Private backup tests do not span app replacement/uninstall. | Persist one retained run with a bound attachment and compare private-unit digest/metadata/blob bytes. | Retained Console data remains one valid durable unit. | Active process checkpointing stays excluded. |
| AC-5 | No application-only uninstall drill exists. | Remove only a validated temporary app-tree path and compare complete authoritative data snapshot. | Data ownership is external to application removal. | Native uninstaller side effects remain Milestone 3/6. |
| AC-6 | Reinstall has not been tested after app removal. | Start a third changed app tree against the same root and recheck exact state/app immutability. | Reinstall reconnects instead of resetting or duplicating state. | Does not test shortcuts/services/registry entries. |
| AC-7 | No slice evidence exists. | Focused/full/static/hosted checks plus two adversarial agents. | Cross-platform regression and independent review gates. | Signed installer smoke remains later work. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS, Python 3.13 | Pass | 575 tests and four skips from merged 1E-B final gate. |
| Final 1E-B hosted run `29669483299` | GitHub Actions | Pass | All 42 Linux/macOS/Windows jobs passed. |
| Roadmap/data-layout search | Repository | Gap confirmed | Upgrade and uninstall preservation are the remaining Milestone 1 evidence. |

### Test discussion and approval

- Standing authorization accepts the mapped integration coverage and explicit
  installer exclusions above. No authority to delete operator data or choose
  packaging tooling is inferred.

## Implementation record

- Added one installed-layout integration drill with three distinct immutable
  application trees (`0.1.0b1`, `0.1.0b2`, and `0.1.0b3`) and one sibling
  external operator data root.
- Every application version supplies different bytes for all nine packaged
  seeds. The first startup creates the current schema/layout; the test then
  writes an operator task, dashboard settings, Context Pack, retained Console
  run, bound attachment row, and referenced blob.
- Before replacement, the test creates and re-parses a canonical version-2
  backup and verifies its private summary contains exactly one retained run and
  one referenced blob.
- Upgrade deletes only the temporary first application tree and starts from the
  second immutable/snapshotted tree. POSIX also applies filesystem read-only
  modes; Windows relies on the exact entry/byte/mode/mtime comparison. Every
  live durable document differs from the new defaults while exact operator
  bytes and the private-unit digest stay unchanged.
- Uninstall snapshots the complete temporary external data root—including
  schema evidence, backups, private files, runtime/cache/log directory entries,
  and metadata—then deletes only the second application tree and proves the
  data snapshot is identical. Reinstall from the third changed tree reuses the
  same state and existing deterministic backup without duplication.
- Application snapshots include entries, bytes, modes, and modification times,
  so each startup proves the selected application tree remains immutable.

## Verification

- Focused preservation test passes on macOS Python 3.13.
- Beta-contract and CI-contract suites pass with Milestone 1 complete and
  Milestone 2 as the next bounded roadmap action.
- Full local discovery passes: 576 tests, four platform-specific skips, zero
  failures/errors on macOS Python 3.13 in 125.526 seconds after the hosted-CI
  contract correction.
- `python3 -m compileall -q .`, JavaScript syntax checks for the public/runtime
  scripts, and `git diff --check` pass.
- The first hosted run, `29670059938`, passed 33 of 42 jobs. The preservation
  test passed on Ubuntu and its Windows Python 3.11 shard; all nine failures
  came from two stale `test_data_layout_contract.py` expectations that still
  described Milestone 1 as incomplete.
- Code-head hosted run `29706197693` passes all 42 Linux, macOS, and Windows
  jobs on commit `5b0fd09ab7da51bfc8e8544fef5fa4fe7247b4fb`.

## Adversarial review

The independent safety reviewer found that the first draft hand-wrote a
noncanonical Context Pack, so byte preservation did not prove the feature
remained usable. The test now creates the pack through the real product API and
after both upgrade and reinstall verifies its canonical ID/schema/timestamps/
revision through list, delegation-normalization, and staging paths. The
compatibility reviewer found a stale outcome sentence that understated the
completed local gates and an overbroad read-only claim that did not distinguish
POSIX modes from Windows snapshot evidence. All findings were fixed, the
focused and full suites were rerun, and both reviewers returned zero findings
on the implementation diff.

After the first hosted run exposed obsolete documentation-contract assertions,
both reviewers independently found that the initial correction encoded
incidental Markdown wrapping. The correction now normalizes prose whitespace
and slash-boundary wrapping while retaining exact status/table assertions and
requiring the canonical combined 1E-B/1F completion statement. Focused tests
passed 9/9, full discovery passed 576 tests with four native-platform skips,
and both reviewers returned zero findings on the corrected exact diff.

## Documentation updates

ROAD_TO_BETA, DATA_LAYOUT, ARCHITECTURE, README, and CHANGELOG now record
Milestone 1F and distinguish proven external-data preservation from deferred
installer/uninstaller mechanics. Contract tests require Milestone 2's private
credential and bounded HTTPS boundary to remain the next roadmap work.

## Publication gate

- Branch and base: `codex/beta-1f-upgrade-uninstall-preservation` to merged
  `main`.
- Implementation commit: `fa35bc884e271cde19de5ea53a5000f15cd660d5`.
- Hosted-contract correction commit:
  `5b0fd09ab7da51bfc8e8544fef5fa4fe7247b4fb`.
- Ready PR: `https://github.com/hazeion/agent-os/pull/27`.
- User authorization: standing approval recorded.

## Outcome review

Implementation, local verification, documentation, adversarial review, and
ready-PR publication are complete. The code head passed the full hosted matrix;
pending final evidence-log review, exact-head CI, and merge.
