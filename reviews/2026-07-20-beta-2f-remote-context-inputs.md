# Feature Slice Review: Remote Context Pack Inputs

Status: Ready PR implementation matrix complete; final evidence publication pending
Slice: `beta-2f-remote-context-inputs`
Date: `2026-07-20`

## Goal

Let the selected remote Hermes host receive bounded text from one staged
Context Pack without sending local paths, filenames, storage details, or
unsupported files. Keep unsupported remote images and artifacts clear and
fail-closed.

## Standing approval and process note

The operator has explicitly approved continuing every Road to Beta slice,
including implementation, verification, commit, ready-PR publication, and
merge. That standing approval replaces the skill's repeated pause-for-approval
prompts. The required two-reviewer, exact-diff, hosted-CI, and merge-readiness
gates remain in force.

## In scope

- Stage one Context Pack as current private text snapshots.
- Issue a random, process-private, expiring grant bound to the selected remote
  connection, Context Pack id and revision, and exact attachment ids.
- Build a bounded remote-only prompt from generic context-item labels,
  user-authored instructions, and validated UTF-8 snapshot text.
- Never include local paths, filenames, blob ids, hashes, storage keys, or
  connection details in the Hermes request.
- Bind accepted snapshots to the Mentat run and expose only the existing safe
  attachment cards in Mentat.
- Reject changed/expired grants, changed connections or pack revisions,
  missing snapshots, extra attachments, direct uploads, images, and prompt
  overflow before remote submission.
- Preserve local Context Pack and attachment behavior.
- Document the delivered boundary and the upstream image blocker.

## Out of scope

- Arbitrary remote text-file transfer, uploaded files, or local paths.
- Remote artifacts or downloads.
- Inline images until Hermes advertises an exact Runs image-input capability
  with the existing status, event, and stop lifecycle.
- Remote session continuation, profile selection, approval response,
  clarification, Kanban, providers, skills, or cron.
- README changes; installation and first-run setup are unchanged.

## Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A remote Context Pack grant works only for the exact connection, pack revision, and attachment-id sequence that staged it. | Server binding tests | Complete |
| AC-2 | The upstream Runs body contains bounded text with generic context labels and no local filenames, paths, hashes, storage keys, endpoint details, or credentials. | Client/server privacy tests | Complete |
| AC-3 | Expired, replayed, changed, missing, extra, direct-upload, image, and artifact inputs fail before any network call. | Negative tests | Complete |
| AC-4 | Context text is valid UTF-8, NUL-free, deterministically bounded, and the complete submitted prompt stays within 20,000 characters. | Bounds tests | Complete |
| AC-5 | Accepted snapshots are bound to the Mentat run; source-file changes after staging do not alter the submitted snapshot. | Snapshot/lifecycle tests | Complete |
| AC-6 | Local Context Pack staging, local text/image attachments, and remote run/cancel/safe-stop behavior remain unchanged. | Compatibility/full suite | Complete |
| AC-7 | The UI binds only the opaque grant and attachment ids, replaces stale remote pack state, and gives a clear unsupported-input error. | UI contract tests | Complete |
| AC-8 | Focused/full/static checks, two independent zero-finding reviews, ready PR, and hosted matrix pass. | Verification record | Pending |

## Upstream evidence

- Current Hermes `/v1/capabilities` advertises the stoppable Runs lifecycle:
  submission, status, SSE events, and stop.
- Its Runs endpoint documents a simple string input. Chat Completions and
  Responses document inline images, but they do not expose the exact status and
  stop lifecycle Mentat requires for Agent Console work.
- Current capabilities do not advertise an image-input feature for Runs.
  Mentat therefore must not infer support from another endpoint or from
  incidental request parsing.

## Test strategy

| Area | Planned evidence |
| --- | --- |
| Grant boundary | Same connection/exact ids/revision succeeds once; changed connection, changed revision, mismatch, expiry, and replay fail |
| Content boundary | Exact private snapshots, deterministic per-item/total bounds, UTF-8/NUL checks, no private metadata in upstream JSON |
| Unsupported inputs | Direct text uploads, images, files, and artifacts rejected before client submission |
| Lifecycle | Run attachment binding, cleanup on bind failure, source changes after stage do not change the snapshot |
| UI | Opaque token only, one remote pack at a time, clear reset/error behavior, no local path fields |
| Regression | Local packs/attachments plus remote Runs, status, cancellation, connection switching, and history |

## Baseline

- Previous slice merged as PR `#33` at main commit `11495ed`.
- Previous exact hosted matrix: 42 of 42 jobs passed.
- Previous local full suite: 650 passed, 4 skipped.
- README remains intentionally unchanged and retains its beginner-first voice.

## Implementation

- Remote Context Pack staging now creates the same private text snapshots as
  local mode, then issues a random 15-minute process-private grant when the
  selected transport is remote.
- The grant records only its monotonic lifetime, connection binding, pack id
  and revision, exact ordered attachment ids, and bounded instructions. It is
  consumed once and never enters retained run history.
- Submission compares the complete grant binding, rechecks the current pack
  revision before and after capability discovery, resolves only digest-verified
  text blobs, requires strict UTF-8 without NULs, and applies fixed
  4,000-character item and 12,000-character complete-context limits before
  enforcing the existing 20,000-character Runs limit.
- Upstream text uses only generic `Context item N` labels. Filenames, vault and
  workspace paths, blob/storage metadata, attachment ids, grant values, and
  connection details are omitted.
- Accepted snapshots become ordinary retained input attachments after their
  contents are fixed. Direct text/image uploads and artifact-shaped input fail
  before capability discovery or run submission.
- The browser keeps one remote pack grant at a time, replaces prior remote
  pack snapshots, clears stale grants on connection/input changes or before a
  replacement attempt, and does not duplicate pack instructions into the
  visible prompt. Instructions-only and attachment-only packs receive a fixed
  generic user prompt when the composer is blank.
- Roadmap, remote contract, architecture, and changelog now record the text
  path and the exact upstream Runs-image blocker. README is unchanged because
  installation and first-run setup did not change.

## Local verification

- Focused remote input, Context Pack, remote run, attachment-store, and UI
  tests after review fixes: 61 passed.
- Expanded remote/local/UI/contract regression command: 150 passed.
- Full suite after all review fixes: 660 passed, 4 skipped.
- `python3 -m py_compile server.py remote_hermes.py hermes_transport.py` and
  `python3 -m compileall -q .`: pass.
- `node --check` for `public/core.js`, `public/app.js`, and
  `scripts/browser_smoke.mjs`: pass.
- `git diff --check`: pass.

## Hosted verification

- Ready PR `#34` published at implementation commit `8cf07dd`.
- GitHub Actions run `29719150251`: all 42 supported-platform jobs passed
  (macOS and Ubuntu on Python 3.11-3.13, plus all 36 Windows shards).
- Final evidence-only head matrix pending.

## Independent review and publication

Round 1 produced five actionable findings.

- Safety reviewer: P1 pack-revision TOCTOU during remote capability discovery;
  P2 the 12,000-character context claim excluded up to 6,000 characters of
  pack instructions.
- Compatibility reviewer: P1 instructions-only and attachment-only packs
  could not submit with a blank composer; P1 a failed pack replacement left
  the previous grant armed; P2 equal-length blob tampering bypassed the size
  check.

Fixes implemented before re-review:

- A documented connection → Context Pack → run-state lock order now excludes
  concurrent pack mutations from grant validation through queue publication.
  A second revision check after capability discovery also catches re-entrant
  edit/delete changes before a run is queued.
- Pack instructions, policy framing, item labels, separators, and snapshot
  excerpts all share the exact 12,000-character context budget.
- A valid remote grant is submit-ready with a fixed generic prompt even when
  the visible composer and attachment list are empty.
- Starting a replacement disarms and removes the prior remote grant before the
  new staging request, so a failed replacement cannot send old context.
- Attachment text is now opened without following symlinks where supported and
  verified against its recorded type, state, size, and SHA-256 digest before
  any remote discovery call.
- New regressions cover edit and delete during discovery, maximum instructions
  plus file content, blank-composer pack variants, failed replacement ordering,
  and equal-length blob tampering.

Round 2 confirmed that all five original findings were fixed. The compatibility
reviewer returned `ZERO FINDINGS`. The safety reviewer found one new P3 edge
case: consuming a valid grant when the process-private registry held exactly
128 entries also evicted an unrelated live grant because capacity eviction ran
on consumption as well as registration.

Expiry pruning and capacity eviction are now separate. Consumption removes
only expired entries and its requested one; registration alone evicts the
oldest grant when space is needed. An exact-capacity regression consumes the
oldest grant and verifies that all other 127 grants remain live.

Round 3 final exact-diff re-review completed after the capacity fix. Both the
correctness/safety reviewer and compatibility/product reviewer returned
`ZERO FINDINGS`. The local adversarial gate and implementation-head hosted
matrix are complete; only the final evidence-only head matrix remains pending.
