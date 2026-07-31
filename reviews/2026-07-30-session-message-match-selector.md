# Feature Slice Review: Session Message Matches in Selector

Status: Successful
Slice: `session-message-match-selector`
Date: `2026-07-30`

## Process exception

- The user instructed Codex to assume approval for all slices and related
  decisions.
- Standing approval covers this contract, test strategy, outcome, exact
  publication packet, staging, commit, push, and ready pull request.
- Work remains one reviewed slice at a time, with unrelated user files excluded.

## Slice contract

### Goal

Keep a session available in the Session History selector when the current
search matches its message content even if its title does not match.

### In scope

- Merge accepted message-result session IDs with title-filtered selector rows.
- Limit those IDs to sessions already present in Mentat's bounded session list.
- Clear message-derived matches on new input, short queries, accepted errors,
  and session-list errors.
- Preserve request-generation protection so stale responses cannot alter the
  selector.

### Out of scope

- Remote API, privacy, transcript, pagination, mutation, and persistence changes.
- Adding older result-only sessions that are absent from the current bounded list.
- Changing search result presentation or automatic session selection.
- User-owned `data/projects.json` and `design/`.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A message-content match keeps its current-list session selectable when the title alone does not match. | Executable contract and rendered remote query | Pass |
| AC-2 | New/short queries and accepted errors remove message-derived selector matches. | Executable contract and rendered clearing check | Pass |
| AC-3 | Unknown result IDs are ignored and stale responses retain no authority. | Executable contract and app ordering regression | Pass |
| AC-4 | Existing bounded, read-only remote search and privacy behavior remain unchanged. | Remote-session suite and live payload check | Pass |
| AC-5 | Static/full checks and two independent adversarial reviews find no in-scope regression. | Verification record | Pass; unrelated local-state failures disclosed |

### Constraints and recovery

- Only normalized result aliases already present in `state.sessions` may affect
  the selector.
- The search response remains browser-ephemeral navigation data with no mutation
  authority.
- Rollback is the slice commit; there is no migration or persistent state change.
- Branch: `codex/session-message-match-selector`, stacked on the remote-search
  resilience slice until its ready PR lands.

## Test strategy

| Criterion | Baseline gap | Planned evidence | Limitation |
| --- | --- | --- | --- |
| AC-1 | Live `cronjobs` shows a result while the selector says “No matching sessions.” | Assert the merge contract, then repeat the live query and inspect the selector. | Only current bounded sessions can be added. |
| AC-2 | Selector state is title-only today. | Assert clearing precedes short-query handling; clear the live input and verify normal options return. | Browser timing is supplemental to deterministic checks. |
| AC-3 | Request generations already protect result rendering. | Keep the generation gate before selector mutation and filter against current IDs. | Static source assertions complement existing async regressions. |
| AC-4 | Parent slice is verified. | Rerun remote-session tests and confirm safe live coverage/result behavior. | Live content can change. |
| AC-5 | Slice is unimplemented at baseline. | Syntax, focused/full tests, patch hygiene, rendered breakpoints, and two reviewers. | Known unrelated local-state failures remain disclosed. |

## Baseline evidence

- At 390px and desktop widths, the live remote query `cronjobs` returns one safe
  message result.
- The same query filters the selector to zero title matches, disables it, and
  displays “No matching sessions.”
- All audited dashboard views avoid page-wide overflow at 900px and 390px;
  calendar-week and project-strip horizontal scrolling is intentionally contained.

## Approval

- Contract, test strategy, outcome handling, and publication are covered by the
  user's standing approval.

## Implementation record

- Added an ephemeral Set of message-matched aliases to Session History state.
- New search input clears the Set and advances the existing request generation.
  An accepted response may repopulate it only with aliases already present in
  the current bounded session list; stale responses return no state transition.
- Selector rendering uses one shared title-plus-message union predicate. The
  same predicate supplies the screen-reader match count so the announcement
  cannot disagree with the options shown.
- Added one atomic polite status element for searching, results, errors, and
  clearing. A global robust `sr-only` utility keeps it and existing hidden
  accessibility labels outside visual layout.
- No remote request, response, privacy, transcript, mutation, or persistent-data
  behavior changed.

## Verification

### Deterministic and static

- Executable Node selector contract: passed. It covers new-search clearing and
  generation advance, current-ID inclusion and deduplication, unknown-ID
  rejection, stale-generation rejection, accepted-error clearing, title-only,
  message-only, and distinct mixed title/message matches.
- Remote-session, frontend-workflow, and visual-contract set: 63 passed.
- `node --check` for both frontend scripts: passed.
- `git diff --check`: passed.

### Complete suite

- Final isolated run: 899 tests, 893 passed, 2 failed, 4 skipped.
- Both failures are the pre-existing local-state fixtures outside this slice:
  - user-owned `Daily Check` makes the tracked seed expect only `Mentat`;
  - the selected remote Hermes connection returns zero jobs to a local cron
    fixture that expects one.
- The slice does not edit either source of those failures.

### Live and rendered

- At 390px, `cronjobs` returned one safe message result and changed the selector
  from disabled/no title match to an enabled option for the corresponding
  current remote session, without page overflow.
- Clearing restored all 12 recent sessions.
- The status announced searching, one matching session, and the 12-session
  cleared state.
- A mixed `remote` query exposed 12 selector sessions and announced exactly 12.
- The status element measured 1 by 1 pixel with absolute positioning and did
  not create visible grid content.

## Adversarial review

### Round 1

- Both reviewers found the first regression test inspected source text instead
  of executing the stateful behavior. The logic was extracted into executable
  helpers and a Node contract covering accepted, unknown, stale, error, and
  clearing transitions.
- The product reviewer found no polite announcement for async selector changes.
  Added a dedicated atomic status instead of making the result grid live.

### Round 2

- The safety reviewer found the first announcement counted only message-derived
  matches while the selector showed the title-plus-message union. Both now use
  the same shared predicate, with a distinct mixed-match executable case.
- The product reviewer found `sr-only` had no global CSS definition and could
  render visible text. Added a robust global visually-hidden utility and visual
  contract.

### Round 3

- Both independent reviewers confirmed every substantive finding was resolved.
- No remaining privacy, alias, stale-generation, clearing, compatibility,
  accessibility, mobile, or scope finding.
- Nonblocking limitation: a later periodic session-list refresh is not
  independently announced until the next user-driven search transition.

## Outcome review

- Classification: successful.
- AC-1 through AC-5 pass, with two unrelated local-state failures disclosed.
- Current bounded sessions only; older result-only sessions are intentionally
  excluded, and stale fetches are ignored rather than aborted.
- Migration: none. Rollback: revert the slice commit.

## Publication packet

- Proposed files:
  - `CHANGELOG.md`
  - `public/app.js`
  - `public/core.js`
  - `public/index.html`
  - `public/styles.css`
  - `tests/session_selector_contract.mjs`
  - `tests/test_frontend_workflow_feedback.py`
  - `tests/test_remote_sessions.py`
  - `tests/test_visual_contract.py`
  - this review log
- Explicit exclusions: user-owned `data/projects.json` and `design/`.
- Branch/base: `codex/session-message-match-selector` stacked onto
  `codex/remote-session-search-resilience`.
- Proposed commit and ready PR title:
  `Keep message-matched sessions selectable`.

## Publication result

- Implementation commit: `24dc98a`.
- Ready stacked PR: https://github.com/hazeion/agent-os/pull/76
- Base: `codex/remote-session-search-resilience` (PR #75).
- Exact staged scope matched the publication packet.
- User-owned `data/projects.json` and `design/` remained unstaged.
