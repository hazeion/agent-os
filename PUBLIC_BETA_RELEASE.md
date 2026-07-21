# Publish the Public Beta

This is the maintainer checklist for promoting one fully tested release
candidate to `v0.1.0-beta.1`. It reuses the exact candidate files. It never
rebuilds, resigns, renames, or silently replaces an artifact.

## Before promotion

Do not dispatch the workflow until all of these are true:

- Milestone 6 is complete for the exact candidate.
- Milestone 7 is complete, with its private evidence and public redacted exit
  summary reviewed.
- The candidate prerelease is still immutable and every public asset matches
  its manifest and checksums.
- GitHub release immutability is enabled. The candidate release shows
  **Immutable** and its release attestation verifies.
- CI, native installer smoke, Quality Gates, clean install, upgrade, backup,
  restore, rollback, and uninstall-preservation evidence are green.
- No P0 or P1 issue is open.
- The `beta-release` environment and final-tag update/deletion protection are
  enabled.
- `v0.1.0-beta.1` does not already exist.

Create the public exit summary with the **Milestone 7 exit summary** issue form.
Keep it aggregate and redacted, close it only after every cohort gate passes,
and copy its issue URL.

## Run the protected promotion

From **Actions → Promote tested RC to public beta → Run workflow**, use `main`
and enter:

- the exact numbered candidate tag;
- its exact 40-character source commit;
- the closed public Milestone 7 summary issue URL; and
- `PROMOTE_V0.1.0_BETA_1` only after rechecking the list above.

The protected workflow verifies the candidate tag, source checks, checked exit
attestations in the closed issue, immutable prerelease identity, GitHub's asset
digests and attestation, exact six-file public inventory, manifest, checksums,
and artifact bytes. It uploads a 90-day recovery bundle before creating the
final tag at the candidate commit. The final GitHub release uses those same
candidate bytes and generated public notes without the prerelease flag, then
verifies the final immutable identity, digests, and attestation.

## If publication is interrupted

Use only `mentat-public-beta-promotion-recovery` from that workflow run. Verify
`SHA256SUMS` before doing anything else.

- If the final tag was not pushed, fix the gate and rerun the protected
  workflow. Do not create the tag by hand.
- If the final tag exists but the release is missing or incomplete, finish that
  tag with only the exact files and notes in the recovery bundle.
- If any existing asset differs, do not replace it or move/delete the tag.
  Record the failed publication visibly and prepare a new version through the
  complete release gate.

## Open the support window

After the release is complete:

- confirm the final page says **Immutable**, has six assets, and the checksums
  and release attestation pass;
- install once from the final release URLs as a last link check;
- keep the public issue forms and private security advisory path open;
- update [known beta issues](KNOWN_ISSUES.md) at least twice a week and before
  every follow-up candidate;
- triage P0/P1 immediately and review all other reports at least weekly.

Updates remain manual. Follow-up versions use the same RC, rehearsal, cohort,
and exact-byte promotion gates.
