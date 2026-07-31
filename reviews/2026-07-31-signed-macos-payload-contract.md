# Signed macOS Payload Contract Review

## Status

Successful.

## Slice contract

- Goal: keep the protected signed macOS workflow's payload validation aligned with the authoritative native packaging manifest.
- In scope: correct the stale public-asset count and add a regression test tying the workflow counts to `PUBLIC_ASSETS` and `PUBLIC_SEEDS` in `packaging/mentat.spec`.
- Out of scope: Apple credentials, signing or notarization commands, release/tag behavior, Windows/Python packaging, and product UI.
- Acceptance criteria:
  1. The signed workflow accepts exactly the six allowlisted public assets and nine allowlisted seed files.
  2. A focused test fails whenever either workflow count diverges from the authoritative packaging manifest.
  3. Existing signing, notarization, protected-environment, and fail-closed behavior is unchanged.
  4. Two independent adversarial reviews report no unresolved P0-P3 findings.

## Approval record

The user granted standing approval for all slices, testing, publication, and continuation on 2026-07-30. This slice proceeds under that approval.

## Baseline and evidence

- Hosted macOS-only run `30653592475` built the unsigned application and failed in the payload-count assertion before importing signing identities.
- `packaging/mentat.spec` allowlists six public assets and nine public seed files.
- The signed workflow expected five public assets and nine seed files.

## Verification

- Red baseline: the focused regression test failed with `PUBLIC_ASSETS` 6 versus workflow `public` 5.
- Implementation: corrected the protected workflow's exact public-asset assertion from five to six. The nine-file seed assertion is unchanged.
- Focused regression: 1/1 passed.
- Packaging/CLI module: 25/25 passed.
- Workflow YAML parse: passed.
- `git diff --check`: passed.
- Full suite: 911 tests ran; 905 passed, 4 skipped, and 2 failed for known machine/user state outside this slice:
  - `test_only_mentat_project_remains_active_for_v1` sees the user's uncommitted `Daily Check` project in `data/projects.json`.
  - `test_inventory_is_read_only_without_an_atomic_hermes_queue_capability` sees zero live cron jobs instead of its fixture's one job.

## Independent reviews

- Round 1 correctness review: one P1 evidence gap and two P2 parser-robustness findings.
- Round 1 operability review: two matching P2 parser-robustness findings and one P2 publication-hygiene reminder.
- Resolution implemented: workflow parsing is scoped to the exact named macOS step with unique exact-line matches; manifest parsing requires one literal assignment with no additional stores and proves both constants feed `datas`.
- Post-resolution focused regression: 1/1 passed.
- Post-resolution packaging/CLI module: 25/25 passed.
- Post-resolution YAML parse and `git diff --check`: passed.
- Round 2 correctness review: no P0-P3 findings.
- Round 2 operability review: one remaining P2 AST-shape finding; require immutable tuple manifests and prove each exact comprehension iterable/destination pair.
- Resolution implemented: both manifests must remain tuple literals; the public list comprehension must iterate `PUBLIC_ASSETS` into `public`, and the seed generator must iterate `PUBLIC_SEEDS` into `data`.
- Post-resolution focused regression: 1/1 passed; packaging/CLI module: 25/25 passed; YAML parse and `git diff --check`: passed.
- Round 3 operability review: no P0-P3 findings.
- Round 3 correctness review: one P3 stale-log-status finding; removed the obsolete pending entry.
- Final correctness re-review: no P0-P3 findings remain.
- Final operability re-review: no P0-P3 findings remain.
- Publication will stage only the workflow, packaging test, and this review record. User-owned `data/projects.json` and `design/` remain explicitly excluded.

## Publication

Approved for publication under the user's standing approval. Only the workflow, packaging regression test, and this review record are in scope.
