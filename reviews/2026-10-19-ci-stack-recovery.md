# CI stack recovery

Status: reviewed repair; hosted verification and stack carry in progress.

The owner requested finishing the existing work, beginning with a current
checkout and repair of the open PR stack. The original checkout contains
unrelated local edits and remains untouched. This focused branch starts at
PR #321 head `e1b42af`; remote main is `038f1d1`. No PR merge or production
activation is part of this repair.

## Reproduced failures and scope

- PR #321's Python matrix rejects the old Next 16.3.4 test expectation and a
  schema-36 fixture containing empty schema-44 through schema-46 tables.
- Its Windows 3.11 bridge request exceeds the unchanged 30-second deadline
  while building the expected embedded Agent schema on disk.
- Its secret scan reports 135 new public provenance hashes, a public package
  signing fingerprint and explicit synthetic negative-test/local-only values.
- PR #243's quality gate fails the braces dependency audit. A fresh audit of
  the tip also finds newer Next, sharp and source-map-js advisories.

Build the expected Agent DDL in a closed in-memory database using the same
complete migration sequence and signature comparison. Remove only explicitly
named, proven-empty newer tables when reconstructing the historical fixture;
retain exact schema, foreign-key, saved-row and backup/restore checks. Update
the reviewed secret fingerprints without changing detectors or exclusions.

Pin Next and its ESLint config to patched 16.3.8 and refresh patched transitive
locks. Replace the Next lint plugin's vulnerable fast-glob dependency with a
local directory-only adapter using tinyglobby 0.2.17. The adapter explicitly
disables recursive directory expansion and preserves absolute versus relative
paths. Unsupported upstream call shapes fail rather than silently changing
lint behavior. Verify both resolved directory targets and the actual
no-html-link-for-pages rule, including exclusion of nested fixture pages.
Preserve all existing audit thresholds and gates.

## Review and verification

The first independent read-only review found no material Python/baseline
issues and verified exact file-backed versus in-memory signatures for
schema 9, 36 and 46. The second found the initial glob test incorrectly
expected identical absolute-path formatting. The direct replacement also
expanded nested directories, producing a verified false-positive lint error
for unrelated fixture pages. Both regressions were reproduced before adding
the narrow adapter and explicit nested-directory and lint-rule tests.
Both final independent reviews are clear after correcting Windows root-path
normalization in the regression test. The adapter uses the repository's ESM
style, loaded synchronously by Next under the pinned Node 24.19.0.

Local isolated Python 3.13.14 evidence so far:

- 38 Node contract, historical migration and Agent registry tests pass.
- The previously timed-out cold bridge request and nine CI gate tests pass.
- The oldest PR's own 32 registry and Node contract tests pass.
- The unchanged tracked-secret gate and runtime dependency audit pass.
- Fresh locked npm install/audit reports zero vulnerabilities. Lint and
  typecheck pass. All 514 web tests pass with two concurrent test files, and
  the production standalone build passes with Next 16.3.8. The ordinary local
  test command had UI readiness/latency failures under concurrent host load;
  no test, timeout, assertion or repository CI command was changed to pass.
- The full Python suite remains running. No completion claim is made from its
  partial output. Hosted current-head verification remains required.

Hosted multi-platform CI, stack propagation, integrated owner workflow,
provider qualification and real host/garage acceptance remain incomplete.
