# Feature Slice Review: Remote Hermes Approval Responses

Status: Blocked safely after implementation audit
Slice: `beta-2d-remote-approval-responses`
Date: `2026-07-20`

## Goal

Determine whether Mentat can safely let a user answer one current remote Hermes
approval request with `once` or `deny`.

## Required contract

- The browser must receive an informative preview without credentials, private
  paths, endpoint identity, or upstream run identity.
- Confirmation must bind the displayed request to the exact upstream mutation.
- Only `once` and `deny` may be offered; persistent scopes and `resolve_all`
  remain unavailable.
- Changed, overlapping, lost, stale, unsupported, or uncertain requests must
  fail closed.

## Upstream audit

Hermes advertises `approval_events`, `run_approval_response`, and
`POST /v1/runs/{run_id}/approval`. The response body accepts a choice, but no
approval request ID, revision, expected hash, or responder lease. The operation
resolves the oldest pending request for the run's approval session.

This creates an uncloseable race: Mentat can display request A, another
authenticated responder can resolve A, and Mentat's later `once` can resolve
unseen request B while the run still reports `waiting_for_approval`. A local
opaque ID cannot bind a mutation that does not accept that ID.

The upstream command and description are also untrusted and may contain
arbitrary credentials or private paths. Replacing them with a generic label is
private, but makes `Allow once` blind and therefore is not informed consent.

## Decision

Do not ship an approval-response route or approval buttons. Mentat retains the
2C behavior: an approval request stops the bound remote run safely. Approval
responses remain blocked until Hermes exposes both:

1. a bounded structured preview/category safe for display; and
2. an approval request identifier or expected revision/hash carried by the
   event/status and required by the response mutation (or an equivalent
   authenticated exclusive responder lease).

Clarification forms, session/permanent approval, denial reasons, `resolve_all`,
and status-only blind approval remain out of scope.

## Verification and adversarial review

- A complete implementation prototype was exercised with focused lifecycle,
  race, privacy, UI, and compatibility tests, then withdrawn before commit.
- Compatibility review rejected generic blind approval and confirmed common
  command text cannot be safely handled through an open-ended redaction list.
- Safety review demonstrated the request-replacement race and confirmed it
  cannot be closed by another local state check.
- Both independent reviewers returned `ZERO FINDINGS` on the final blocker-only
  diff.
- Final focused roadmap/remote checks: 44 passed.
- Final full repository suite: 638 passed, 4 skipped.
- Python compilation, JavaScript syntax, `git diff --check`, and the README
  unchanged check passed.
- The shipped tree remains on the reviewed 2C safe-stop implementation.
- README is intentionally unchanged because installation and first-run setup
  did not change.

## Publication

Publish only this blocker contract and the architecture/roadmap notes. Do not
publish the withdrawn response implementation.

- Implementation/audit commit: `133fb48`
- Ready pull request: `#32`
- Hosted supported-matrix run `29715527296`: all 42 jobs passed on macOS,
  Ubuntu, and Windows with Python 3.11 through 3.13.
