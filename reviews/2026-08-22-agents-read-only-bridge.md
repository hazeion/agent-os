# Feature Slice Review: Read-only Agents bridge

Status: Successful

Slice: `2b-a-agents-read-only-bridge`

Date: `2026-08-22`
Review log: `reviews/2026-08-22-agents-read-only-bridge.md`

## Slice contract

### Goal

Show the canonical Mentat Agent list in the new `/agents` workspace without exposing private runtime references or adding a general Python proxy.

### In scope

- One fixed private Python bridge capability for the canonical read-only Agent projection.
- One same-origin Node API route that validates and returns that projection.
- A static-first `/agents` screen with loading, empty, unavailable, unsupported, and error states.
- A manual refresh action that invokes only the fixed same-origin route.

### Out of scope

- Creating, editing, deleting, switching, or running Agents.
- Provider credentials, sign-in, provider switching, or runtime configuration editing.
- Tasks, Runs, generic bridge forwarding, or changes to the Python compatibility UI.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Python exposes only a fixed, authenticated, loopback Agent-list capability. | 10 focused Python bridge tests | Pass |
| AC-2 | Node calls one fixed path, bounds and validates the response, and does not disclose bridge authority or private fields. | 17 web checks, including Agent bridge contracts | Pass |
| AC-3 | `/agents` renders canonical Mentat IDs, names, runtime types/config IDs, and declared capabilities only. | Production browser smoke and contract tests | Pass |
| AC-4 | The page gives honest loading, empty, unavailable, unsupported, and malformed-response error feedback; refresh is fixed-route only. | Production browser smoke and DOM tests | Pass |
| AC-5 | The legacy Python UI remains unchanged and the production static route remains script-light. | Static-shell inspection, browser smoke, and focused regressions | Pass |
| AC-6 | The six-run Lighthouse gate remains 100/100/100/100. | `npm --prefix web run lighthouse:gate` | Pass |

### Constraints and recovery

- Safety: Browser input cannot select a bridge target, path, token, or headers. Python owns the canonical registry and filters its projection before Node sees it. Adapter runtime references, credentials, filesystem paths, raw Hermes data, and legacy `data/agents.json` stay out of the route.
- Compatibility: Keep the Python app on port 8888 and its existing routes unchanged. The Node preview remains optional on port 8890.
- Rendered behavior: Keep the Agents route prerendered with stable placeholders. Load current Agent data after first paint without React hydration in the production shell.
- Rollback or recovery: Reverting this slice removes only the new fixed capability, Node route, and static enhancement; no data migration or mutation occurs.
- Documentation targets: Pivot implementation plan and this review log.
- Version-control strategy: Focused branch `feature/2b-a-agents-read-only`, base `main`, ready PR after the required gates.

### Scope discussion and approval

- Recommendation and rationale: Use the existing canonical `agent-registry.sqlite3` projection through a named bridge capability. It keeps Node a narrow gateway and preserves the static performance contract.
- Alternatives considered: A generic proxy would speed later routes but breaks the capability boundary. A React-query client route would add unnecessary hydration for one small read-only list. Neither is used.
- User decisions: The standing goal approval authorizes approved pivot slices and future publication/merge actions. The user also requested future Agent switching and provider sign-in/configuration in UI and CLI; that is explicitly deferred to later approved slices.
- Future architecture note: The pivot keeps ProviderConnection separate from Agent and RuntimeConfig. It lists Vercel AI Gateway, AI SDK adapters, Sandbox, and Connect as optional infrastructure only; Mentat remains provider-neutral and Vercel types cannot become the domain model.
- Approved at: Standing authorization in the active pivot goal, reconfirmed before continuing 2B-A on 2026-08-22. This is an explicit exception to the skill's per-slice and pre-publication approval prompts.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Bridge supports health only. | Python handler tests for the fixed path, token checks, projection, and failures. | The private endpoint is fixed and redacted. | Does not test Node. |
| AC-2 | Node has no Agent capability. | TypeScript tests using mocked bridge responses, including oversized and private-field payloads. | Fixed request and fail-closed public schema. | Does not run a real Python process. |
| AC-3/4 | `/agents` is a placeholder. | Static shell contracts plus production browser smoke against seeded canonical data and unavailable bridge. | The rendered route exposes the correct visible states. | Browser smoke is representative, not exhaustive assistive-tech testing. |
| AC-5 | No Agent route enhancement exists. | Existing Python suite, web checks, build, and static-shell inspection. | Compatibility and no-hydration contract remain intact. | Does not prove every legacy interaction. |
| AC-6 | No post-change measurement. | Required six-run Lighthouse gate. | Desktop and mobile category scores stay perfect. | Local machine conditions can vary; CI repeats the gate. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `git status --short` | macOS source checkout | Pass | Started from `main` equal to `origin/main`; unrelated user changes preserved. |
| Existing 2A-B verification record | macOS source checkout | Pass | Prior main recorded 14 web checks, full Python suite, browser smoke, and six Lighthouse audits at 100/100/100/100. |

### Test discussion and approval

- User decisions: Standing pivot authorization covers this test strategy and the usual publication actions.
- Accepted coverage gaps: Provider sign-in/switching and Agent mutations are intentionally not in this read-only slice.
- Approved at: 2026-08-22 standing authorization.

## Implementation record

### Changes

- Added the exact private `GET /bridge/v1/agents` Python capability. It reads
  only the canonical Agent projection and validates every public field before
  returning it.
- Added the fixed same-origin Node `GET /api/agents` route and a bounded,
  strict Node bridge client. It maps only known fixed bridge states and keeps
  bridge authority out of browser responses.
- Replaced the `/agents` foundation message with a static-first list that has
  loading, empty, unavailable, unsupported, and safe-error states. Its manual
  refresh calls only `/api/agents` after first paint.
- Added Agent bridge, static-shell, and production browser-smoke coverage.
- Documented the fixed public Agent projection in `ARCHITECTURE.md` and marked
  this slice complete in the implementation plan.
- Updated the Node foundation CI job to install the pinned Python runtime
  dependencies before its Python bridge tests import `server.py`.

### Deviations and decisions

- The Node route recognizes an older bridge only when it returns the exact
  authenticated `404 {"error":"bridge_route_not_found"}` payload. That maps
  to the honest unsupported state; every other 404 remains a safe error.
- The normal Turbopack build cannot create its required OS socket in this local
  environment, even with host execution. The equivalent webpack build passed.
  Hosted CI remains the required normal-build confirmation.
- Hosted CI initially exposed the missing Python dependency setup in the Node
  foundation job. The workflow now installs `requirements.txt`; its workflow
  contract tests pass locally and CI will rerun on the update.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `npm --prefix web run check` | macOS source checkout | 0 | 17 pass | Lint, typecheck, and Node contracts, rerun after the review fix. |
| `python3 -m unittest tests.test_mentat_local_bridge tests.test_agent_runtime_architecture -v` | macOS source checkout | 0 | 14 pass | Fixed bridge, redaction/failure mapping, and roadmap contract. |
| `python3 -m unittest tests.test_ci_quality_gate tests.test_ci_workflow -v` | macOS source checkout | 0 | 16 pass | Verifies the focused Node-foundation dependency setup. |
| `node web/scripts/run-next.mjs build --webpack && node web/scripts/prepare-standalone.mjs` | macOS source checkout | 0 | 4 static routes + `/api/agents` | Fallback build because this environment blocks Turbopack's required socket. |
| `node scripts/web_foundation_smoke.mjs` | Production preview on `127.0.0.1:8890` | 0 | Pass | Verified full browser → Node → bridge → Python flow; live canonical registry was honestly empty. Injected ready, unsupported, unavailable, and error states passed. |
| `npm --prefix web run lighthouse:gate` | Production preview on `127.0.0.1:8890` | 0 | 6/6 pass | Three desktop and three mobile audits each scored Performance, Accessibility, Best Practices, and SEO at 100. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | Dirty macOS source checkout | 1 | 1 unrelated failure | 1,308 tests and 4 skips completed. The only failure reads the user's modified `data/projects.json`, which adds local projects beyond the fixture expectation; no slice test failed. |
| `python3 -m unittest tests.test_apple_notarization -v` | macOS source checkout | 0 | 8 pass | Isolated follow-up for a clean-archive subprocess anomaly; unrelated to this slice. |

### Rendered or manual behavior

- The production `/agents` page starts with a stable loading placeholder and
  no React hydration runtime. The live canonical registry returned an empty
  list, which rendered `No canonical Agents yet.` and enabled the fixed refresh
  control.
- The browser smoke injected a safe ready response and verified each visible
  Agent field and capability; no private runtime value was rendered. It also
  verified the unsupported, unavailable, and error messages and found no
  browser console errors or narrow-layout overflow.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: uncommitted Slice 2B-A diff, including the review fix.
- Verification evidence: focused checks, production smoke, and six Lighthouse
  audits listed above.
- Rendered artifacts: production preview DOM assertions from
  `scripts/web_foundation_smoke.mjs`.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | Medium | No | An older bridge's exact 404 route-not-found response was rendered as a generic error rather than unsupported. | Yes | Map only the exact fixed 404 body to unsupported; reject all other 404 payloads. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | None | No | No concrete compatibility or product defect. Peer review confirmed the A-1 fix preserves fail-closed behavior. | Yes | Add an explicit extra-field 404 rejection test. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| A-1 old bridge route 404 | Unique A finding; B corroborated the fix | Both reviewers rechecked the mapping. | Accepted. Exact `{ "error": "bridge_route_not_found" }` maps to unsupported; wrong or extra fields are invalid. | Added strict validator and three 404 tests: exact, wrong value, and extra field. |

### Reverification

- Focused tests: 17 web checks and 14 focused Python tests pass after the fix.
- Full suite: The dirty source suite has one unrelated user-fixture failure;
  isolated notarization test passes after the clean-archive subprocess anomaly.
- Next review round or gate result: Both reviewers found the final fix clean;
  no blocking dissent remains. Both also re-reviewed the narrow CI dependency
  fix after PR #116 and found no new issue.

## Documentation updates

- Roadmap: Slice 2B-A marked Complete in this branch.
- Changelog: Not applicable; the implementation plan is the canonical slice record.
- Architecture/operator docs: `ARCHITECTURE.md` now names `/api/agents` and
  its safe public projection.
- Project/session notes: This review log.
- Documentation verification: `tests.test_agent_runtime_architecture` passes.

## Publication gate

- Proposed files: fixed bridge, Node API/client, static Agents screen/style and
  smoke/contracts, architecture/roadmap, and this review log only. Unrelated
  user data, design files, videos, lockfile, temporary files, and npm config
  remain unstaged.
- Branch and base: `feature/2b-a-agents-read-only` -> `main`.
- Commit message: `Add the read-only Agents bridge to the Next workspace`.
- PR title: `Add the read-only Agents bridge to the Next workspace`.
- PR summary: one fixed canonical Agent projection through the private bridge
  and Node gateway, with a static-first Agents screen and unchanged 100-score
  Lighthouse gate.
- Unresolved risks: Normal Turbopack build must be confirmed by hosted CI;
  the local environment blocks its socket creation. JavaScript remains required
  to replace the intentionally safe static placeholder.
- User authorization and scope: Standing authorization recorded above.
- Commit hash: Pending.
- Ready PR URL: Pending.

## Outcome review

- Classification: Successful implementation pending hosted CI and merge.
- Acceptance criteria summary: AC-1 through AC-6 pass locally, including six
  exact Lighthouse audits.
- Potential bugs or untested paths: Hosted CI must run the normal Turbopack
  build and rerun the Node foundation job after its dependency fix. The
  user-modified fixture prevents a clean full-suite result in this checkout but
  is unrelated to this slice.
- Remaining reviewer dissent: None.
- Compatibility/migration/rollback concerns: No data migration or mutation.
  Revert removes the new fixed route and static enhancement; the Python
  compatibility UI stays unchanged.
- User decision: Standing approval authorizes publication and merge.
- Next slice authorized: Standing authorization, after outcome evidence is recorded.
