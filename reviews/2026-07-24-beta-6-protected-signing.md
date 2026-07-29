# Feature Slice Review: Beta 6 protected signing handoff

Status: Cleared — repository slice ready for publication
Slice: `beta-6-protected-signing`
Date: `2026-07-24`
Review log: `reviews/2026-07-24-beta-6-protected-signing.md`

## Slice contract

### Goal

Make the protected release workflow compatible with current public Windows
code-signing practice and give the maintainer one exact, secret-safe setup path
for the first signed Mentat release candidate.

### In scope

- Replace exportable Windows PFX handling with Azure Artifact Signing through
  GitHub OIDC.
- Sign and verify both packaged Windows executables and the final installer.
- Generate the temporary macOS CI keychain password inside each workflow run.
- Document the exact Apple secrets, Azure variables, identity binding, GitHub
  protections, and first RC dispatch.
- Keep all third-party GitHub Actions pinned to reviewed commit SHAs.

### Out of scope

- Creating Apple or Azure accounts, completing identity validation, buying
  memberships, or inventing credentials.
- Adding signing values to GitHub before the operator supplies them.
- Dispatching an unsigned or partially configured release workflow.
- Claiming the signed RC, second-person rehearsal, limited cohort, or final
  beta promotion complete.
- Changing ordinary PR/native CI or any user-facing Mentat behavior.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Windows signing uses a hardware-backed service and short-lived GitHub OIDC; no exportable PFX or client secret enters GitHub. | Workflow inspection and contract tests. | Pass |
| AC-2 | The two Windows application executables and final installer are signed and Authenticode-verified before upload. | Ordered workflow steps and contract tests. | Pass — hosted signing pending |
| AC-3 | macOS signing no longer requires a persistent temporary-keychain password. | Workflow inspection and negative assertion. | Pass |
| AC-4 | One maintainer guide names every required Apple secret and Azure variable, exact OIDC environment subject, protections, and RC dispatch. | Documentation contract and manual review. | Pass |
| AC-5 | Existing release assembly, recovery, tag immutability, and product behavior remain green. | Focused checks and full suite. | Pass — protected execution pending |

### Constraints and recovery

- Safety: signing keys never enter tracked files, ordinary CI, logs, browser
  state, or release artifacts. Azure receives only a short-lived OIDC token.
- Compatibility: `windows-2025`, Azure Artifact Signing public trust, Apple
  Developer ID Application/Installer, and the existing GitHub protected
  environment.
- Rendered behavior: no application UI changes; maintainer Markdown stays
  concise and task-oriented.
- Rollback or recovery: revert this slice before the first RC if Azure setup is
  unavailable. A failed protected run must not publish or move a tag.
- Documentation targets: `RELEASE_SIGNING.md`, `RELEASE_REHEARSAL.md`,
  `packaging/README.md`, roadmap/changelog after review, and this log.
- Version-control strategy: `codex/beta-6-protected-signing` into `main` as one
  ready pull request containing only slice files.

### Scope discussion and approval

- Recommendation and rationale: use Azure Artifact Signing because Microsoft
  now recommends it for non-Store distribution and current public code-signing
  requirements keep subscriber private keys in hardware-backed modules.
- Alternatives considered: the existing base64 PFX route would be simpler but
  assumes an exportable public-trust private key; a hardware token on a
  self-hosted runner would add runner custody and availability risk; Microsoft
  Store distribution is outside the approved direct-installer channel.
- User decisions: the standing Road-to-Beta authorization approves slices and
  PRs. The user also explicitly waived repeated slice/PR approval prompts.
- Approved at: standing authorization carried into the active goal on
  2026-07-24.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Workflow imports a base64 PFX and password. | Require OIDC permission, pinned Azure actions, and absence of PFX inputs. | No long-lived Windows signing key or client secret is configured in the workflow. | Azure tenant policy is verified only by hosted execution. |
| AC-2 | Local SignTool signs by imported thumbprint. | Require two Artifact Signing actions and subsequent SignTool verification. | Application and installer signing are separate and verified. | Cannot create a public signature without the external profile. |
| AC-3 | GitHub stores an unnecessary keychain password. | Require per-run random generation and forbid the secret reference. | Temporary keychain protection is ephemeral. | Does not exercise macOS signing without certificates. |
| AC-4 | No signing setup authority exists. | Check guide link, exact variable inventory, and OIDC subject. | The handoff is complete and repository-bound. | Identity validation remains an external account process. |
| AC-5 | Release tests predate the new authentication path. | Focused release tests, YAML parse, diff check, and full suite. | Existing release/product contracts remain intact. | Protected platform signing remains the milestone exit evidence. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| GitHub environment/ruleset audit | Signed-in repository settings | Partial | `main`, beta tags, and `beta-release` are protected; the environment has no secrets or variables. |
| `security find-identity -v -p codesigning` | Maintainer Mac | External gap | Zero valid Apple signing identities found. |
| Workflow inspection | Local checkout | Gap | Windows imported `WINDOWS_CERTIFICATE_BASE64`; macOS required `MAC_KEYCHAIN_PASSWORD`. |

### Test discussion and approval

- User questions and decisions: standing authorization permits proportionate
  workflow contract, YAML, documentation, and full-suite verification.
- Accepted coverage gaps: a real Apple signature, notarization, Azure public
  signature, and protected GitHub run require operator-owned accounts and are
  mandatory before Milestone 6 completion.
- Approved at: standing authorization carried into the active goal on
  2026-07-24.

## Implementation record

### Changes

- Added job-scoped `id-token: write` and pinned Azure Login v3.0.0.
- Added two pinned Azure Artifact Signing v2.0.0 operations: application
  executables before packaging and the final Inno Setup installer afterward.
- Retained explicit SignTool `/pa /all /v` verification after each signing
  boundary.
- Removed Windows PFX decode/import/cleanup and certificate password inputs.
- Replaced the stored macOS temporary-keychain password with `openssl rand`.
- Added `RELEASE_SIGNING.md` and linked it from the rehearsal and packaging
  guides.
- Updated the packaging contract test for OIDC, pinned actions, signing order,
  secret absence, and documentation inventory.

### Deviations and decisions

- The initial recommendation was only to remove the unnecessary macOS
  keychain secret and document the existing PFX handoff. Current Microsoft and
  CA/Browser Forum guidance showed that the exportable Windows key assumption
  was stale, so the slice adopted the supported hardware-backed OIDC route
  without expanding the release channel.
- Process exception: the user explicitly directed Codex to assume approval for
  future slices and pull requests, so the normal repeated publication prompt is
  replaced by a recorded exact publication packet before staging.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_packaging_cli tests.test_ci_quality_gate tests.test_release_rehearsal tests.test_public_beta_promotion -v` | macOS, Python 3.13 | 0 | 42 pass | Workflow, release, recovery, promotion, and guide contracts. |
| `ruby -e 'require "yaml"; YAML.parse_file(".github/workflows/signed-release-artifacts.yml")'` | macOS Ruby | 0 | Pass | Workflow YAML parses. |
| `git diff --check -- <slice files>` | local worktree | 0 | Pass | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | macOS, Python 3.13 | 0 | 768 pass, 4 skip | Expected native Windows skips only. |

### Rendered or manual behavior

- No application UI changed. The signing guide was inspected as Markdown for
  short steps, explicit secret handling, and direct authoritative links.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: raw current diff for the five slice files plus new
  `RELEASE_SIGNING.md`; unrelated user changes excluded.
- Verification evidence: 42 focused tests, 768 full-suite tests with four
  expected skips, YAML parse, and diff check.
- Rendered artifacts: not applicable; maintainer Markdown reviewed directly.

### Reviewer A — correctness and safety

- Blocking: both native SignTool verification calls lacked immediate
  `$LASTEXITCODE` checks, so a later successful command could hide an invalid
  application signature.
- Non-blocking: the OIDC guide named the subject but not the issuer, audience,
  or exact Azure portal environment selection.

### Reviewer B — compatibility and product

- Blocking: both native SignTool verification calls could continue after a
  failed verification and package invalid executables.
- Blocking for AC-4: the OIDC setup was not operable enough without the exact
  issuer, audience, entity type, environment, and app-registration service
  principal note.

### Reconciliation and disposition

- Both reviewers independently corroborated the same two issues; there was no
  unique finding or conflicting recommendation requiring cross-critique.
- Added an immediate throwing `$LASTEXITCODE` guard after every application and
  installer SignTool verification.
- Added exact OIDC issuer, subject, audience, Azure portal scenario, entity
  type, environment, and service-principal guidance.
- Extended contract coverage for both corrections.

### Reverification

- Focused release tests: 42 pass after the corrections; the final
  release-and-roadmap set passes 54 tests.
- Full suite: 768 pass, 4 expected platform skips after the corrections.
- YAML parse and exact-slice diff check: pass after the corrections.
- Round 2: both independent reviewers re-read the complete corrected slice and
  reported no findings.

## Documentation updates

- Roadmap: records the completed live WSL/Hermes HTTPS evidence and links the
  remaining protected signing setup.
- Changelog: records the Azure OIDC signing route and maintainer guide.
- Architecture/operator docs: signing and rehearsal guides updated.
- Project/session notes: this persistent review log.
- Documentation verification: guide inventory included in the focused tests.

## Publication gate

- Proposed files: workflow, signing/rehearsal/packaging guides, packaging
  contract test, roadmap/changelog follow-up, and this log.
- Branch and base: `codex/beta-6-protected-signing` into `main`.
- Commit message: `ci: modernize protected release signing`.
- PR title: `Modernize protected beta release signing`.
- PR summary: use Azure Artifact Signing OIDC for Windows, remove unnecessary
  long-lived signing inputs, and add the exact maintainer setup guide.
- Unresolved risks: real Apple/Azure credentials and hosted signatures remain
  external.
- User authorization and scope: standing authorization; stage only the exact
  slice files and publish a ready PR.
- Commit hash: recorded in the ready PR.
- Ready PR URL: recorded after publication.

## Outcome review

- Classification: Repository slice complete — protected external setup remains.
- Acceptance criteria summary: repository-owned criteria pass; hosted signing
  remains mandatory.
- Potential bugs or untested paths: Azure role/federated-subject mistakes and
  Apple identity/export mistakes can be proven only by the protected run.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: no product data migration; revert
  before the first RC if the external service is unavailable.
- User decision: standing authorization continues.
- Next slice authorized: Yes, after this slice's ready PR and CI are green.
