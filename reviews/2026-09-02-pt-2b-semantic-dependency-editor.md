# PT-2B review log — semantic dependency editor

Issue: [#173](https://github.com/hazeion/agent-os/issues/173)
Wayfinder map: [#165](https://github.com/hazeion/agent-os/issues/165)
Branch: `codex/pt-2b-semantic-dependency-editor`

## Approved scope

- Add the accessible, mobile-default dependency editor to the selected-Task
  inspector.
- Expose only two named, bounded read capabilities: selected Task dependency
  relationships and a paged dependency picker.
- Use the existing exact-revision Task edit capability as the sole dependency
  mutation; preserve full canonical collection validation in the same write
  transaction.
- Show direct prerequisites and dependents, including cross-Project labels,
  with explicit counts and truncation state.

## Explicit exclusions

- No React Flow, Map tab, graph layout metadata, or visual dependency graph.
- No new relationship write endpoint, Task execution, delegation, review-cycle
  action, or runtime authority.
- No ambient all-Task browser projection, generic bridge route, or private
  Task detail leakage.

## Verification strategy

- Cover dependency projection and picker bounds, cursor/query validation,
  missing/self/duplicate/cycle rejection, exact revision conflicts, and
  cross-Project relationships in Python, bridge, Node, and React tests.
- Verify keyboard operation, explicit state announcements, focus restoration,
  narrow layouts without horizontal overflow, and List/Board coherence.
- Before merge, complete local browser acceptance, two independent
  defect-first reviews, and the full GitHub CI matrix.

## Execution evidence

- Python compilation passed for `conversation_planning.py`, `server.py`, and
  `mentat/local_bridge.py`.
- Focused Python/bridge coverage passed: 59 tests in 24.45 seconds.
- The final complete web suite passed: 237 tests in 23.59 seconds, including
  lint and TypeScript checks. The focused planning contract/UI suite also
  passed: 32 tests in 4.44 seconds.
- The final UI race coverage proves that stale successful and failed paginated
  picker requests cannot overwrite a newer query, and that the 100-item and
  160-character UI limits are enforced before a save attempt.

## Independent review

- Backend/bridge review: no P0--P3 findings.
- UI review identified stale paginated-success and stale paginated-failure
  handling, the prerequisite-count interaction limit, and the search-input
  length bound. All were corrected and independently re-reviewed with no
  remaining P0--P3 findings.

## Browser acceptance

- Built the production Next.js dashboard, then exercised it through the local
  browser against an isolated initialized copy of the seed data.
- Opened a selected Task, added a prerequisite, saved, reopened to confirm the
  persisted relationship, then removed and saved it again.
- Verified keyboard activation can stage a prerequisite, and switching between
  List and Board keeps the selected Task and its stage coherent.
- At a 390px viewport the dependency editor remained present with document
  `scrollWidth === clientWidth`; the temporary viewport override was reset.

## Broad local suite note

`python -m unittest discover -s tests -v` completed 1,804 tests in 707.41
seconds with seven pre-existing Windows/environment failures outside PT-2B:
legacy Agent Console subprocess assumptions, one local socket abort, one
concurrent temporary-file permission error, one Windows preflight expectation,
and one link-preview worker availability result. None cover or involve the
PT-2B dependency files. The focused 59-test Python/bridge suite and final
237-test web suite are green; the complete GitHub matrix remains the merge
gate.
