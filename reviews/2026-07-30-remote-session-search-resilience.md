# Feature Slice Review: Remote Session Search Resilience

Status: In progress
Slice: `remote-session-search-resilience`
Date: `2026-07-30`
Review log: `reviews/2026-07-30-remote-session-search-resilience.md`

## Process exception

- The user instructed Codex to assume approval for all slices and related
  decisions.
- This standing approval covers this contract, test strategy, outcome, exact
  publication packet, and ready PR after all verification and two-reviewer
  gates complete.
- Work remains one slice at a time; unrelated user files stay excluded.

## Slice contract

### Goal

Keep remote Hermes session search useful when a recent transcript contains
path- or credential-shaped text, without returning that unsafe text or
weakening the stricter read-only transcript boundary.

### In scope

- Add a search-specific remote message read that validates the complete
  response envelope and connection binding exactly as today.
- Omit individual user/assistant messages that fail Mentat's existing
  browser-visible content-safety classifier.
- Search all remaining safe messages in the existing bounded 12-session recent
  window.
- Report the number of filtered messages and affected sessions in coverage
  metadata and UI copy.
- Preserve fixed authenticated GET endpoints, opaque aliases, all existing
  bounds, and local search behavior.

### Out of scope

- Expanding beyond the existing 12 recent sessions or adding upstream
  pagination/search.
- Showing, redacting, summarizing, or returning any blocked message content.
- Relaxing path, credential, endpoint, upstream-ID, or secret detection.
- Changing strict remote transcript/replay reads, session continuation, or any
  Hermes mutation.
- User-owned `data/projects.json` and `design/`.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | One unsafe nonmatching message no longer makes the whole remote search unavailable; safe matching messages are returned. | Client/server regression and live remote query | Pass |
| AC-2 | Blocked message text and all private transport/session identifiers remain absent from the browser payload. | Negative serialization tests | Pass |
| AC-3 | Schema, pagination, binding, capability, transport, and connection changes still fail the whole search closed. | Existing and focused failure tests | Pass |
| AC-4 | Coverage reports filtered-message and affected-session counts without revealing content. | Payload and UI contract tests | Pass |
| AC-5 | Strict transcript reads and local search behavior remain unchanged. | Compatibility tests | Pass |
| AC-6 | Focused/full/static checks and two independent adversarial reviews disclose no in-scope regression. | Verification record | Pass; unrelated suite failures disclosed |

### Constraints and recovery

- The upstream read surface remains fixed, authenticated, bounded, shell-free,
  and read-only.
- Filtering is message-granular only after the full envelope and exact binding
  validate; structural or transport uncertainty still discards all results.
- No blocked text, reason, path, token, identifier, endpoint, or raw error may
  cross the browser boundary.
- Rollback is the slice commit; there is no migration or persistent state
  change.
- Branch: `codex/remote-session-search-resilience` from `origin/main`.
- Publication target: one ready PR to `main`.

### Alternatives considered

- Keep failing the entire search. Rejected because one unrelated unsafe message
  makes every query unusable on the live remote host.
- Relax the content classifier. Rejected because it weakens the established
  browser privacy boundary.
- Redact blocked messages and search the remainder of their text. Rejected
  because derived redaction could leak context and adds unnecessary complexity.
- Omit unsafe messages only for search and disclose bounded counts. Selected
  because it preserves privacy while restoring useful safe matches.

## Test strategy

| Criterion | Baseline gap | Planned evidence | Limitation |
| --- | --- | --- | --- |
| AC-1 | Live `cronjobs` and `session` queries both return `remote_private_reflection` with zero results. | Add unsafe-plus-safe mixed-message tests, then rerun both live queries. | Live results depend on current recent sessions. |
| AC-2 | Current client aborts before returning anything. | Assert blocked marker text, API key, endpoint, upstream IDs, and unsafe content never serialize. | Absence checks complement existing classifier tests. |
| AC-3 | Existing all-or-nothing failure coverage is strong. | Rerun complete remote-session suite and add a malformed-envelope search-specific case if needed. | Deterministic fake HTTP supplies exact failures. |
| AC-4 | Coverage has no filtered-message fields. | Assert exact counts and static UI copy/escaping. | Counts intentionally reveal no reason or source text. |
| AC-5 | Search and transcript share one strict message reader. | Keep `get_session_messages` strict; add a distinct search reader and explicit strict-read regression. | This slice does not make filtered transcripts openable. |
| AC-6 | Slice is unimplemented. | Focused remote suites, syntax, patch hygiene, complete suite, rendered/live check, and two reviewers. | Chromium and the configured live host are local evidence. |

## Baseline evidence

- Live selected remote Hermes, `GET /api/hermes/search?q=cronjobs`:
  `remote_private_reflection`, zero results.
- Live selected remote Hermes, `GET /api/hermes/search?q=session`:
  `remote_private_reflection`, zero results.
- Session listing itself succeeds, so the failure occurs while validating
  message content inside the recent search window.
- Existing implementation intentionally scans at most 12 recent sessions and
  returns at most 20 matches; those bounds remain unchanged.

## Approval

- Contract, test strategy, outcome handling, and later publication are covered
  by the user's standing approval.

## Implementation record

- Added a search-specific message reader alongside the unchanged strict
  transcript reader.
- The shared reader still validates the exact response envelope, session
  binding, roles, timestamps, content shape, and message bound before applying
  a policy.
- Search mode omits messages rejected by the existing private-public-text
  classifier and returns only a count; strict transcript mode still raises
  `remote_private_reflection`.
- The transport and selected-search handler carry only safe normalized messages
  plus bounded filtered counts.
- Coverage now exposes `filtered_messages` and
  `sessions_with_filtered_messages`; the UI renders the plain-language escaped
  notice “messages omitted for privacy.”
- Updated architecture, remote contract, and changelog documentation.

## Verification

### Focused and static

- `python3 -m unittest tests.test_remote_sessions -v`: 28 passed.
- Remote session, remote connection, transport, workflow-feedback,
  next-phase, and beta-contract set: 116 passed.
- `python3 -m py_compile server.py remote_hermes.py hermes_transport.py`:
  passed.
- `node --check public/app.js` and `node --check public/core.js`: passed.
- `git diff --check`: passed.

### Complete suite

- 897 tests run: 891 passed, 2 failed, 4 skipped.
- The same two unrelated local-state failures remain:
  - user-owned `Daily Check` conflicts with the tracked seed-fixture assertion;
  - selected remote Hermes state yields zero jobs for a local-cron fixture.
- The slice does not edit either source of those failures.

### Live and rendered

- Before implementation, live `cronjobs` and `session` searches both returned
  `remote_private_reflection`.
- After implementation, live `cronjobs` returned one safe match after scanning
  12 recent sessions and 121 safe messages; 6 messages across 5 sessions were
  reported as privacy-filtered.
- Live `session` returned a normal zero-match result with the same honest
  coverage instead of an availability error.
- The browser rendered the result and coverage notice, highlighted the match,
  and opened the existing read-only transcript.
- At 390x844, the result container and document had no horizontal overflow.
- No blocked content, filter reason, endpoint, credential, path, or upstream
  session identifier appeared in either live response.

## Publication packet

- Proposed files:
  - `ARCHITECTURE.md`
  - `CHANGELOG.md`
  - `REMOTE_HERMES.md`
  - `hermes_transport.py`
  - `public/app.js`
  - `remote_hermes.py`
  - `server.py`
  - `tests/test_remote_sessions.py`
  - this review log
- Explicit exclusions: user-owned `data/projects.json` and `design/`.
- Branch/base: `codex/remote-session-search-resilience` to `main`.
- Proposed commit: `Keep remote session search usable with filtered messages`.
- Proposed ready PR title: `Keep remote session search usable with filtered messages`.

## Adversarial review

### Round 1

- Security/privacy reviewer: no substantive findings. Confirmed exact envelope,
  binding, schema, timestamp/content, count, fixed-path, and final-revalidation
  boundaries remain intact and aggregate counts expose no private material.
- Product/compatibility reviewer: no blocking finding. Recommended replacing
  the technical phrase “privacy-filtered” with plainer UI copy; changed to
  “messages omitted for privacy.”
- Both reviewers noted the approved search-only limitation: a safe match from a
  session containing another filtered message can be listed while the strict
  transcript remains unavailable. The live click-through check proves an
  unaffected result, not every filtered-session result.
- The product reviewer also noted ordinal message IDs could become stale if
  upstream content changes after search. This pre-existing remote-search
  staleness applies even without filtering; the result is browser-ephemeral,
  detail is fetched fresh, and no mutation or authority is attached to the ID.
  It is recorded as a non-blocking navigation limitation.

### Round 2

- Both reviewers confirmed the plain-language copy correction.
- Both agreed the strict-transcript limitation is required by the approved
  boundary and the ordinal-staleness risk is non-blocking, pre-existing, and
  limited to navigation/highlighting after an upstream transcript change.
- No remaining substantive finding or publication blocker.

## Outcome review

- Classification: successful.
- Acceptance criteria: AC-1 through AC-6 pass, with the two unrelated
  local-state full-suite failures disclosed.
- Remaining limitations: search remains bounded to 12 recent sessions; strict
  transcripts can remain unavailable for a session with any filtered message;
  browser-ephemeral ordinal targets can become stale if upstream history
  changes between search and click.
- Migration/rollback: none; revert the slice commit.
- Publication: authorized by the user's standing approval after this completed
  verification and review gate.
