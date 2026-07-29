# Feature Slice Review: Beta 8 exact public-beta promotion

Status: Successful — approved for publication
Slice: `beta-8-public-beta-promotion`
Date: `2026-07-21`
Review log: `reviews/2026-07-21-beta-8-public-beta-promotion.md`

## Slice contract

### Goal

Make the final public-beta release promote the exact fully tested RC bytes
through one protected, recoverable workflow instead of rebuilding artifacts.

### In scope

- Restrict the signing workflow to numbered RC tags.
- Verify one published immutable RC's exact source, release identity, six
  public assets, manifest, checksums, and bytes.
- Require protected approval, a closed public redacted Milestone 7 summary,
  exact confirmation, and green stable checks for the RC source.
- Preserve a promotion recovery bundle before creating the final tag at the RC
  commit and publishing the same assets without a prerelease flag.
- Add concise publication, partial-recovery, and support-opening instructions.
- Add negative, reproducibility, workflow, and documentation tests.

### Out of scope

- Claiming Milestone 6 or 7 external evidence exists.
- Dispatching the protected workflow, creating a final tag, or publishing a
  release in this repository slice.
- Rebuilding, resigning, renaming, or replacing tested candidate assets.
- Automatic updates or changing the beta version.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The signed release workflow accepts numbered RC tags but cannot publish the final beta directly. | Tag and workflow contract tests. | Pass |
| AC-2 | Promotion accepts only one exact published prerelease bundle bound to its candidate tag/source and rejects changed, missing, extra, malformed, or mismatched evidence. | Unit/negative tests. | Pass |
| AC-3 | The protected workflow verifies stable gates and a closed cohort summary, saves recovery evidence before tagging, tags the RC commit, and republishes the exact six assets without rebuilding. | Workflow contract/YAML tests. | Pass |
| AC-4 | A maintainer has concise preflight, dispatch, interruption recovery, link-check, known-issues, and support-cadence instructions without a false release claim. | Documentation contract and review. | Pass |

### Constraints and recovery

- Safety: fixed inventory, no-follow regular files, bounded metadata/artifacts,
  exact hashes, no private cohort evidence or credentials in files/logs/notes.
- Compatibility: exact macOS, Windows, wheel, and sdist candidate assets;
  final tag stays `v0.1.0-beta.1` at the candidate source.
- Rendered behavior: short maintainer Markdown and native GitHub forms/workflow.
- Rollback or recovery: upload exact recovery bytes before tagging; never move
  or delete the tag or replace a differing asset.
- Documentation targets: beginner-first README, publication checklist, roadmap,
  changelog, issue form, workflow, tests, and this log. README describes the
  release path first while honestly stating that no final beta exists yet.
- Version-control strategy: `feat/m8-public-beta-promotion` into `main` as one
  ready PR, excluding user-owned local changes.

### Scope discussion and approval

- Recommendation and rationale: separate final promotion from signing so the
  final public files are byte-for-byte the already tested RC.
- Alternatives considered: rebuilding on the final tag was rejected because
  signatures/timestamps can change bytes; renaming candidate files was rejected
  because it breaks exact identity; manual publication alone was rejected as
  non-reproducible and weak on partial failure.
- User decisions: the persistent Road to Beta goal supplies standing slice and
  publication approval; external completion gates must remain honest.
- Approved at: standing authorization, applied 2026-07-21.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Signing workflow also accepts the final tag. | RC-only validation and workflow assertions. | Final publication cannot accidentally rebuild. | Protected dispatch is hosted evidence. |
| AC-2 | No final promotion verifier exists. | Exact fixture, mutation, metadata, URL, confirmation, and exclusive-output tests. | Candidate identity and bytes fail closed. | Does not verify real platform signatures again. |
| AC-3 | No exact-byte promotion workflow exists. | Source inspection, YAML parse, and ordering assertions. | Protected gates and no-rebuild publication are wired. | Environment/rules/tag protection require GitHub configuration. |
| AC-4 | No final publication runbook/summary form exists. | Required-step/privacy/history contract and inspection. | Maintainer can execute/recover without inventing state. | Real second-person use remains external. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Workflow/roadmap inspection | merged `main` at `fddfa80` | Expected gap | Current signed workflow can accept the final tag and rebuilds artifacts; no exact-RC promotion workflow or final checklist exists. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts the exact-byte
  promotion and proportionate unit/workflow/full-suite strategy.
- Accepted coverage gaps: actual protected approval, candidate download,
  closed cohort issue, tag protection, final link install, and support window
  remain external completion evidence.
- Approved at: standing authorization, applied 2026-07-21.

## Implementation record

### Changes

- Verifier, protected promotion workflow, exit-summary form, publication guide,
  and tests added.
- README now leads with short native and `pipx` release instructions and keeps
  source setup as the development fallback.
- Promotion binds stable checks to the candidate source through the dedicated
  `RELEASE_SOURCE_SHA` input instead of attempting to replace GitHub's workflow
  commit variable.
- The closed cohort issue is captured and verified for exact URL, candidate
  tag/source, every required section, and all three checked exit attestations.

### Deviations and decisions

- The initial implementation checked only whether the supplied cohort issue
  was closed. Focused verification exposed a separate release-notes omission,
  and implementation inspection exposed the candidate-SHA environment binding.
  Both were corrected inside the approved fail-closed promotion scope before
  adversarial review.

## Verification

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m py_compile scripts/release_rehearsal.py scripts/public_beta_promotion.py scripts/verify_release_checks.py` | macOS development checkout | Pass, exit 0 | All changed Python entry points compile. |
| `python3 -m unittest tests.test_public_beta_promotion tests.test_release_rehearsal tests.test_ci_quality_gate tests.test_limited_beta_readiness tests.test_trust_support_readiness -v` | macOS, Python 3 | 41 passed, exit 0 | Covers exact bytes, wholesale replacement, trusted digests, mutations, release/cohort binding, docs, workflow, and adjacent release contracts. |
| `yaml.safe_load(...)` for the promotion workflow, signed workflow, and exit form | macOS, installed PyYAML | 3 parsed, exit 0 | Confirms syntax only; hosted Actions behavior remains CI evidence. |
| `python3 -m unittest discover -s tests -v` | macOS, Python 3 | 764 passed, 4 expected platform skips, exit 0 | Full repository regression suite after round-1 fixes. |

The first focused run had one new assertion failure because generated notes
linked private advisories but not the repository security policy. The notes now
link both `PRIVACY.md` and `SECURITY.md`; the rerun above is clean. No required
check remains failing.

## Adversarial review

### Round 1

- Safety/correctness reviewer: High/blocking — the downloaded manifest and
  checksums were self-authenticating, so a wholesale consistent asset
  replacement could pass. Medium/blocking — unrestricted substring matching
  let checked attestation text pasted into another field spoof the real exit
  section.
- Product/compatibility reviewer: independently reported the same
  High/blocking asset-provenance gap. Also reported Low/non-blocking README
  friction because checksum verification had no beginner command.
- Disposition: all accepted as in scope. The signed RC and final workflows now
  require immutable release state, compare every downloaded file with GitHub's
  asset digest, verify the GitHub release attestation, and post-verify the final
  release. The cohort parser requires one exact ordered set of sections, binds
  tag/SHA inside the candidate section, and accepts only the three exact checked
  lines inside the exit section. README gives one concise macOS and Windows
  checksum command.
- Added regressions: immutable false, wrong GitHub digest, fully regenerated
  self-consistent replacement bundle, copied checked text, duplicate headings,
  wrong-section source text, mixed checked/unchecked state, and final-release
  digest verification.

### Round 2

- Product/compatibility reviewer: No findings; all round-1 findings resolved.
- Safety/correctness reviewer: Medium/blocking — candidate evidence was in the
  right section but used independent substring checks, allowing multiple or
  ambiguous tag/SHA identities in that section.
- Disposition: accepted as in scope. Candidate evidence must now equal exactly
  `<candidate-tag> at <40-character-source-sha>` after surrounding whitespace
  normalization. Tests reject old-then-expected, expected-then-other, and
  duplicate identities. Workflow jobs also request explicit read permission
  for the release-attestation verification they perform.
- Post-fix evidence: focused 41 passed; all three YAML files parsed; full suite
  764 passed with 4 expected platform skips; diff check clean.

### Round 3

- Safety/correctness reviewer: No findings.
- Product/compatibility reviewer: No findings.
- Review gate: complete. No blocking or non-blocking finding remains.

## Documentation updates

- Roadmap/changelog/publication guide updated without claiming release.
- README remains honest about release availability while putting the supported
  release install path before source-development setup.

## Publication gate

- Branch/base: `feat/m8-public-beta-promotion` into `main`.
- Proposed commit: `feat: add exact public beta promotion gate`.
- Proposed PR: `Add exact tested-RC public beta promotion gate`.
- User authorization: standing Road to Beta authorization; exact final packet
  applied after 41 focused tests, 764 full-suite tests, clean YAML/diff checks,
  and three adversarial review rounds ending with two no-finding verdicts.

## Outcome review

- Classification: Successful for repository preparation; external release
  execution remains deliberately unclaimed.
- External gates: Milestone 6 signed rehearsal, Milestone 7 cohort, protected
  promotion execution, final link install, and support-window opening.
- Next slice authorized: Yes, after review/publication gates.
