# Feature Slice Review: Apple G2 Trust Continuity

Status: Successful
Slice: `apple-g2-trust-continuity`
Date: `2026-07-31`
Review log: `reviews/2026-07-31-apple-g2-trust-continuity.md`

## Process exception

- The user instructed Codex to assume approval for all slices and related
  implementation, verification, publication, and continuation decisions.
- Standing approval covers this contract, test strategy, implementation,
  verification, outcome, staging, commit, push, ready pull request, merge, and
  continuation to the next reviewed slice.

## Slice contract

### Goal

Make the protected hosted macOS signing job establish the official Apple
Developer ID G2 certificate chain required by the current signing identities,
without weakening release gates or leaving altered keychain state behind.

### In scope

- Download Apple's official Developer ID G2 intermediate over HTTPS during the
  protected macOS job and fail closed unless its SHA-256 matches the pinned
  public digest.
- Import only that public intermediate into the runner login keychain when the
  exact certificate is not already present.
- Preserve the original user keychain search list, add the private temporary
  signing keychain without hiding the originals, and restore the original list
  during always-run cleanup.
- Delete the G2 certificate during cleanup only when this job imported it.
- Add structural workflow tests and operator documentation for the trust-chain
  and cleanup contract.

### Out of scope

- Creating Apple notarization credentials or dispatching the protected job.
- Changing notarization, artifact publication, release creation, tag creation,
  Windows/Azure signing, or the all-platform release gate.
- Changing the signing identity bundle or any user-owned project data/designs.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The macOS job obtains the official Developer ID G2 certificate and verifies the exact pinned SHA-256 before import. | Workflow contract test and source inspection | Pass |
| AC-2 | The job captures the original user keychain search list and activates private + login + original keychains without duplicating the login entry. | Workflow contract test and source inspection | Pass |
| AC-3 | Always-run cleanup restores the original search list and removes only the G2 certificate imported by this job, plus the existing private temporary material. | Workflow contract test and source inspection | Pass |
| AC-4 | Existing protected-source, signing, notarization, Windows, release, and immutable-tag gates remain intact. | Focused and full tests | Pass |
| AC-5 | Operator documentation explains the pinned public intermediate and cleanup behavior without exposing credentials. | Documentation inspection | Pass |
| AC-6 | Two independent adversarial reviewers find no unresolved blocking correctness, safety, compatibility, or operability gap. | Review record | Pass |

### Constraints and recovery

- Safety: the intermediate is public, but private identities and passwords must
  remain secret-backed and must not be printed.
- Supply chain: accept the public intermediate only from Apple's HTTPS
  certificate authority endpoint and only when its pinned SHA-256 matches.
- Idempotence: pre-existing exact G2 certificates must not be removed.
- Cleanup: restoration must run even after a failed import/signing/notary step.
- Compatibility: macOS runner Bash must not depend on Bash 4-only features.
- Recovery: the always-run step restores the captured search list, conditionally
  removes the imported public certificate, deletes the private keychain, and
  removes temporary files.
- Version-control strategy: ready PR from
  `codex/apple-g2-trust-continuity` to `main`.

### Scope discussion and approval

- Recommendation and rationale: repair the exact trust-chain behavior proven
  locally before creating notarization credentials or dispatching hosted work.
- Alternatives considered: rely on runner image contents (not deterministic);
  disable trust verification (unsafe); weaken the release job into a macOS-only
  release (outside scope and would undermine the dual-platform gate).
- User decision: standing approval applies.
- Approved at: `2026-07-31` under the process exception.

## Test strategy

| Acceptance criterion | Planned evidence | Limitation |
| --- | --- | --- |
| AC-1 | Assert official URL, pinned digest, fail-closed digest comparison, and certificate import are present. | Structural test does not contact Apple. |
| AC-2 | Assert original list capture, Bash-3-compatible parsing, and combined search list. | Hosted runner behavior remains an external gate. |
| AC-3 | Assert always-run cleanup, original-list restoration, conditional exact-certificate deletion, keychain deletion, and temp-file deletion. | Cannot simulate macOS Keychain on Linux/Windows. |
| AC-4 | Run the focused packaging contract test and the full unit suite; inspect release job dependencies/conditions. | Azure and notary services remain undispatched. |
| AC-5 | Inspect updated release signing guide and secret-free diff. | Documentation cannot prove external service behavior. |
| AC-6 | Two independent read-only adversarial reviews after implementation and verification. | Reviewers do not access secrets. |

### Baseline results

- Local signing proof at tested revision
  `8917ddc0ed6311dba3989e15bac9c440dfbbbe9a` passed real Application and
  Installer signing only after the official G2 public intermediate and original
  login-keychain access were available.
- The baseline protected workflow imported the private bundle into a temporary
  keychain, replaces the search list with only that keychain, does not acquire
  G2, and deletes the keychain without restoring the original list.
- Pull request 81 recorded and independently reviewed the proof; all required
  GitHub checks passed before merge.

## Implementation record

### Changes

- The protected macOS job now downloads `DeveloperIDG2CA.cer` only from
  Apple's HTTPS certificate authority endpoint and compares its normalized
  SHA-256 against the pinned public digest before any import.
- It derives the downloaded certificate's SHA-1 locally for exact keychain
  inventory/deletion operations, without treating SHA-1 as the authenticity
  check.
- It captures the original user keychain search list and default login
  keychain before mutation. Both outputs are normalized for macOS indentation
  and quotes. The Bash parsing uses ordinary arrays/loops and is compatible
  with the macOS runner's Bash 3.x.
- It captures certificate inventory to a private file before searching, which
  avoids a `grep -q`/`pipefail` SIGPIPE misclassification. It imports the public
  G2 intermediate only when the exact certificate is absent, records intent
  before the mutation, and verifies the exact certificate afterward.
- Certificate inventory accepts only success or macOS Security's precise
  `errSecItemNotFound` process status (44) as an empty inventory; every other
  access result fails closed. Cleanup applies the same distinction.
- It activates a search list containing the private temporary keychain, the
  normalized login keychain, and every original keychain, avoiding a duplicate
  login entry when the original list already contains it.
- It applies `umask 077`, explicitly sets the materialized encrypted PKCS#12 to
  mode `0600`, and verifies that mode before importing private identities.
- Ownership/attempt markers are written before G2 import, private-keychain
  creation, and search-list mutation so cleanup can recover partial attempts.
- Always-run cleanup independently attempts search-list restoration,
  conditional public-certificate removal, private-keychain deletion, and
  temporary-file removal. It records failures while continuing the remaining
  cleanup actions, then returns a nonzero result if any required cleanup failed.
- Structural tests pin the URL/digest, fail-closed comparison, original-list
  preservation/restoration, conditional cleanup markers, cleanup status, and
  the absence of Bash 4-only `mapfile`.
- `RELEASE_SIGNING.md` now explains the public G2 pin, temporary import,
  original-list preservation, and conditional cleanup behavior.

### Deviations and decisions

- The public certificate is imported into the runner login keychain because
  the real local proof showed that isolating the leaf identities and G2 only in
  the private temporary keychain did not establish trust. Private identities
  remain confined to the disposable signing keychain.
- The workflow does not use `security add-trusted-cert` or disable validation;
  it relies on the normal Apple Root CA trust anchor and a pinned official
  intermediate.
- The full dual-platform release/tag graph is unchanged. This slice makes the
  macOS path viable but does not dispatch it while notary credentials and Azure
  configuration remain incomplete.

## Verification

### Focused checks

- `python3 -m unittest tests.test_packaging_cli -v`: 24 passed.
- YAML parse of `.github/workflows/signed-release-artifacts.yml`: passed.
- The exact search-list parsing loop ran under macOS system Bash
  `3.2.57(1)-release` and parsed the current quoted keychain-list format into
  one non-empty array entry: passed.
- The exact default-keychain normalization produced an existing login-keychain
  path from macOS's indented/quoted output: passed.
- `security error -25300` confirmed `errSecItemNotFound` means the specified
  keychain item was not found; the CLI's shell exit mapping is 44. Only that
  empty-inventory case is tolerated.
- `git diff --check`: passed.
- Source inspection confirmed all four protected-main job guards, the three
  trusted-source checks, notarization/stapling/Gatekeeper checks, both Windows
  signing phases, release dependency graph, prerelease creation, and immutable
  tag push remain present and unchanged outside the macOS identity/cleanup
  steps.
- Secret-free diff inspection: only the public certificate URL/fingerprints,
  keychain control flow, structural assertions, operator guidance, and this
  review record are in scope. No private certificate data, passwords, Apple
  Account identifier, or user-local signing paths are present.

### Full suite

- `python3 -m unittest discover -s tests -q`: 910 run; 908 passed, 2 failed,
  4 skipped.
- The two failures are pre-existing local-state differences outside this slice:
  user-owned `data/projects.json` contains the intentionally preserved
  `Daily Check` project, while the live local Hermes cron inventory returned
  zero jobs where the fixture test expects one.
- The changed packaging module is independently green, and the user-owned data
  file and `design/` remain unmodified by this slice.

### Publication checks

- The first pull-request dependency/secret scan rejected the public pinned G2
  SHA-256 assertion as a high-entropy candidate. This was a fail-closed false
  positive, not secret exposure.
- Added the repository's narrow `# pragma: allowlist secret` annotation only to
  the two exact test assertions of that public fingerprint. The workflow,
  guide, and evidence continue to show the public pin intentionally; no secret
  baseline was broadly weakened.
- Both independent reviewers rechecked the publication fix and found no P0/P1
  or publication concern. The local environment lacks the `detect_secrets`
  package, so the hosted rerun remains the authoritative scanner result.
- The first hosted rerun cleared the workflow assertion but then reported the
  second exact public-fingerprint occurrence in the operator-guide assertion.
  Applied the same line-specific annotation to that assertion only; scanner
  configuration and baseline remain unchanged.
- Both independent reviewers rechecked the second annotation and found no
  P0/P1, scan-scope, or publication concern.
- Pull request 82's third hosted quality-gate run passed the dependency/secret
  scan, browser smoke, Python package/installed lifecycle, and required quality
  aggregate. The authoritative hosted scanner therefore confirms both narrow
  public-pin annotations without any baseline or configuration relaxation.

## Adversarial review

- Correctness/safety review initially found blocking risks in piped
  pre-existing-certificate detection and private PKCS#12 permissions, plus
  marker ordering and structural-test precision gaps. These were resolved with
  private inventory files, exact status handling, `umask 077`, explicit/verified
  mode `0600`, pre-mutation markers, post-import verification, and ordering
  assertions.
- Its second pass found that an empty login keychain can return
  `errSecItemNotFound`, which fail-fast Bash had to treat as an empty inventory,
  and requested narrower deduplication wording. The workflow now accepts only
  status 0 or the exact 44 mapping, fails closed otherwise, applies the same
  logic during cleanup, and describes only login-entry deduplication. Final
  review found no P0/P1 findings and supported AC-1 through AC-5.
- Operability/compatibility review initially found that macOS indentation made
  the default-keychain path invalid and that the login keychain was not
  deterministically included in the signing search list. Normalizing the path
  and building private + login + original keychains fixed both. Final review
  found no P0/P1 findings or publication blockers and supported AC-1 through
  AC-5.
- Both reviewers confirmed Bash 3.2 compatibility, idempotent exact-certificate
  cleanup, continued cleanup after partial failures, private-material
  containment, and preservation of every release/Windows/tag gate.

## Publication gate

- Contract, test strategy, implementation, AC-1 through AC-6, focused checks,
  full-suite interpretation, documentation, and two independent reviews pass.
- Publication is authorized under the standing approval. Stage only the
  workflow, signing guide, focused test, and this review record; exclude
  user-owned `data/projects.json` and `design/`.

## Outcome review

- Classification: Successful.
- Acceptance criteria: AC-1 through AC-6 pass.
- Remaining reviewer dissent: none.
- External proof still required: hosted signing/notarization after credentials
  exist; Azure and the full dual-platform release candidate remain deferred.
- Compatibility/rollback: protected gate topology is unchanged; reverting this
  slice restores the prior workflow but also restores its known G2 failure.
- User decision: standing approval recorded; Successful outcome accepted under
  the process exception.
- Next slice authorized: Yes, under the standing process exception, after this
  slice is complete and published.
