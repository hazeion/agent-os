# Feature Slice Review: Remote Delegation Artifacts v1

Status: Ready for publication
Slice: `remote-delegation-artifacts-v1`
Date: `2026-07-29`
Review log: `reviews/2026-07-29-remote-delegation-artifacts-v1.md`

## Slice contract

### Goal

Let a person using Mentat with a remote Hermes safely download files produced
by a delegated Kanban task, with immediate access from the Home page when the
finished task needs attention.

### In scope

- Add a versioned, capability-advertised remote Hermes contract for artifacts
  created by delegated Kanban runs.
- Preserve only files explicitly declared by the latest successful completion
  of an API-created Kanban task, while that task is still inside its
  Hermes-managed scratch workspace.
- Support Markdown, plain text, common source-code formats, PNG, JPEG, GIF,
  and WebP in version one.
- Use opaque artifact identifiers and bounded metadata. Never expose remote
  filesystem paths, workspace paths, bearer credentials, or arbitrary URLs.
- Transfer artifact bytes only from Hermes to Mentat over the existing
  authenticated, verified HTTPS server connection.
- Revalidate filenames, types, sizes, content, and digests in Mentat before
  saving an independent snapshot in Mentat-owned private content-addressed
  storage.
- Give a finished, needs-attention task a compact Generated files row in the
  Home page Operational Focus panel.
- Show the same artifact downloads in the full task Agent work card.
- Render delegated artifacts as file cards with same-origin download actions.
  Raster images are deliberately not embedded in Home or task cards because
  the artifact limit is much larger than an inline preview should decode.
- Keep result-summary behavior unchanged when remote Hermes does not advertise
  the complete artifact contract.
- Surface rejected or unavailable artifacts clearly without treating the task
  itself as successfully transferred.

### Out of scope

- Browsing a remote workspace or remote filesystem.
- Opening a path or URL mentioned in agent prose.
- Browser-to-Hermes requests or exposing Hermes credentials to the browser.
- HTML, SVG, PDF, archives, executables, or arbitrary binary formats.
- Automatically creating ZIP archives.
- General Agent Console remote artifacts outside the delegated Kanban flow.
- Moving the Open today schedule action.
- Repairing Console token and context-window telemetry.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A completed API-created Kanban task can publish only files explicitly declared by its latest successful completion from its Hermes-managed task workspace. | Hermes unit and API contract tests | Pass |
| AC-2 | Hermes advertises the exact versioned artifact contract and returns only opaque IDs plus bounded safe metadata. | Capability and response-schema tests | Pass |
| AC-3 | Mentat fetches bytes server-to-server over the selected authenticated HTTPS binding, verifies metadata/content/digest, and snapshots accepted files into private Mentat storage. | Mentat remote adapter and integration tests | Pass |
| AC-4 | Paths, symlinks, redirects, unsupported types, malformed metadata, digest mismatches, oversized content, excessive counts, stale bindings, and partial transfers fail closed without publishing a browser download. | Negative-path and race tests in both repositories | Pass |
| AC-5 | A completed needs-attention task exposes its accepted files directly in Operational Focus on Home as file cards with one-click downloads. | UI contract tests and rendered browser check | Pass |
| AC-6 | The same files appear in the selected task's Agent work card, and all browser links are fixed same-origin Mentat routes using opaque IDs. | UI and HTTP route tests | Pass |
| AC-7 | Older remote Hermes versions retain the current summary-only task workflow without broken or misleading artifact controls. | Compatibility tests | Pass |
| AC-8 | Accepting a task does not erase its retained artifact references; rejected artifact transfers remain visibly unavailable and are not described as downloaded. | Task action and persistence tests | Pass |
| AC-9 | Each individual artifact is limited to 100 MiB, with at most 10 artifacts and 250 MiB combined per completed task. | Boundary tests | Pass |
| AC-10 | Existing local Console artifacts, local delegation, remote Kanban actions, task planning, and attachment retention continue to pass. | Focused regression and complete repository suites | Pass; 878 tests passed, 4 skipped, and the sole full-suite failure is the pre-existing user-owned `Daily Check` fixture change |

### Constraints and recovery

- Safety: trusted export directory only; symlink-safe bounded scanning; opaque
  IDs; verified HTTPS; existing bearer authentication; no arbitrary paths or
  URLs; browser receives only same-origin Mentat routes.
- Compatibility: feature is enabled only when the selected remote Hermes
  advertises the complete version-one contract. Older endpoints degrade to the
  existing text-summary behavior.
- Rendered behavior: artifact downloads must be visible with the task in Home
  Operational Focus and in its full Agent work card without causing action
  controls to jump or stretch.
- Rollback or recovery: disabling or removing the advertised Hermes capability
  returns Mentat to summary-only behavior. Mentat-owned snapshots follow the
  established private attachment retention and garbage-collection boundary.
- Documentation targets: `ARCHITECTURE.md`, `REMOTE_HERMES.md`, applicable
  Hermes API documentation, `CHANGELOG.md`, and this review log.
- Version-control strategy: branches
  `codex/remote-delegation-artifacts-v1` in Mentat and Hermes, both based on
  their current `main`. The user's standing authorization includes publication
  after the verification and review gates pass.

### Scope discussion and approval

- Recommendation and rationale: implement the remote artifact security
  contract before the unrelated Today-layout and token-telemetry fixes because
  it requires a coordinated Hermes and Mentat boundary.
- Alternatives considered: scanning the full remote workspace, parsing paths
  from result prose, browser-direct downloads, and generic remote file access
  were rejected because they create confused-deputy and credential-exposure
  risks.
- User decisions: approved the slice; requested a 100 MB maximum and direct
  Home-page access, with duplicate access elsewhere allowed. The standing
  approval permits the implementation agent to settle remaining questions
  while keeping security and secret protection foremost.
- Bounds selected under that approval: 100 MiB per file, at most 10 artifacts,
  and 250 MiB combined per task.
- Process exception: on `2026-07-29` the user explicitly authorized the
  remaining slice, test-strategy, review-disposition, and follow-up-slice
  decisions without repeated pauses. This removes interactive approval pauses
  but does not weaken tests, independent reviews, security checks, scope
  records, or publication evidence.
- Approved at: `2026-07-29`.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Hermes exposes no delegated artifact contract. | Failing export-discovery and completed-run contract tests. | Only trusted run exports become candidates. | Does not prove Mentat ingestion. |
| AC-2 | Capabilities list only Kanban task operations. | Capability and API schema tests. | Clients can distinguish complete support from older servers. | Does not exercise network transfer. |
| AC-3 | Mentat imports only local Console artifacts. | Adapter tests plus an HTTPS-shaped integration fixture that downloads and stores an artifact. | Authenticated server-side transfer and private snapshot behavior. | A local fixture cannot prove every deployed proxy. |
| AC-4 | No remote artifact rejection paths exist. | Table-driven malicious metadata/content, redirect, symlink, race, truncation, count, size, and digest tests. | Fail-closed behavior across the boundary. | Resource exhaustion is bounded by tests, not load-tested at production scale. |
| AC-5 | Operational Focus has no artifact controls. | DOM contract test plus desktop and narrow rendered browser checks. | Files are easy to find and controls remain stable. | Manual rendering covers representative dimensions. |
| AC-6 | Agent work cards show only result text. | UI and same-origin content-route tests. | Duplicate access and browser isolation. | Does not validate external download-manager behavior. |
| AC-7 | Current remote servers advertise no artifact endpoint. | Old-capability compatibility fixture. | Existing deployments remain usable. | Cannot cover unknown third-party forks. |
| AC-8 | Task actions have no artifact persistence behavior. | Accept/revision/refresh persistence tests. | Files survive normal review actions and failures are honest. | Long-term retention timing remains governed by existing GC tests. |
| AC-9 | No remote bounds exist. | Exact below/at/above-boundary tests. | Agreed file and task limits are enforced on both sides. | Final cases await the cap decision. |
| AC-10 | Cross-repository regression risk exists. | Focused suites followed by complete Mentat and relevant complete Hermes suites. | Existing supported workflows remain intact. | Platform-specific CI behavior may still require repository CI. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Repository and contract inspection | Mentat and local Hermes checkouts on macOS | Gap confirmed | Remote Kanban returns bounded task, comments, runs, and result summary only. No artifact endpoint is advertised. |
| Home UI inspection | Mentat static frontend | Gap confirmed | Operational Focus contains task rows but no generated-file controls. |
| Existing local artifact inspection | Mentat local Console artifact tests | Existing capability identified | Private content-addressed storage and same-origin downloads can be extended without exposing paths. |

### Test discussion and approval

- User questions and decisions: standing approval granted with security and
  secret protection as the top priority. Exact-boundary, malicious-content,
  redirect, stale-binding, and rendered Home-page checks remain required.
- Accepted coverage gaps: a local HTTPS fixture cannot reproduce every
  deployed reverse proxy; repository CI remains responsible for platform-only
  behavior.
- Approved at: `2026-07-29`.

## Implementation record

### Changes

- Hermes now advertises `kanban_artifacts` version 1 and exposes fixed,
  bearer-authenticated manifest and byte-download endpoints.
- Completion files are copied before managed task-workspace cleanup, then
  rediscovered only from preserved trusted state. Local legacy completion
  behavior remains unchanged.
- Both repositories validate the same type, per-file, count, and combined-size
  limits. Hermes rejects links, hard links, races, active content, malformed
  images/text, and recognizable credential material before advertising a file.
- Hermes and Mentat independently decode and rewrite accepted raster images so
  EXIF, comments, XMP, appended data, and other hidden metadata do not survive
  either side of the trust boundary. EXIF orientation is applied before the
  metadata is removed.
- Mentat downloads only through its selected server-side adapter, verifies the
  manifest and streamed bytes, and saves an independent content-addressed
  snapshot under gitignored private runtime storage.
- Artifact records are bound to the exact Mentat task, connection, board, and
  remote task. Startup, task deletion, revision requests, and changed remote
  references reconcile stale private mappings.
- Home renders local data first, then performs a bounded background refresh for
  current-connection delegated tasks and redraws the affected cards as soon as
  that check completes.
- Ready-for-review and archived/completed results import files when not already
  synchronized. Unsupported servers are terminal for automatic checks;
  failures use bounded exponential backoff. An explicit refresh compares the
  remote completion revision and restores missing local snapshots.
- Old unbound remote task references require an exact reconnect preview and
  confirmation before Mentat reads remote task state.
- Generated files appear in both Operational Focus and the full task card as
  compact download cards. Missing private blobs omit the content URL and render
  as unavailable.
- Remote artifact transfers use a dedicated 120-second timeout and stream into
  a private temporary file instead of buffering the remote response in memory.

### Deviations and decisions

- The initial contract described a generic run-owned export directory. Hermes'
  actual supported boundary is narrower: only explicit files attached to the
  latest successful completion of an API-created Kanban task are preserved
  from that task's managed scratch workspace. This is easier to bind and audit.
- Inline image thumbnails were removed from delegated task surfaces. Validated
  images remain downloadable, but a 100 MiB accepted image is not decoded in
  the browser merely because Home rendered the task.
- Cleartext remote endpoints accept only literal loopback IP addresses.
  `localhost` and other hostnames require verified HTTPS so DNS resolution
  cannot silently move a cleartext binding off-loopback.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_remote_context_inputs tests.test_agent_console_attachments tests.test_remote_kanban_artifacts tests.test_task_delegation tests.test_task_delegation_ui tests.test_home_operations_ui tests.test_request_boundary tests.test_hermes_api tests.test_task_planning` | Mentat, macOS Python 3.13 | 0 | 193 passed | Final artifact lifecycle, image canonicalization and orientation, background Home refresh, retry, unavailable-file, UI, request-boundary, attachment, remote-input, API, and planning checks. |
| `.venv/bin/python -m pytest tests/gateway/test_kanban_api.py tests/gateway/test_kanban_artifact_api.py tests/hermes_cli/test_kanban_db.py -q` | Hermes worktree, macOS | 0 | 271 passed | Manifest/download API, canonical raster output and orientation, completion preservation, named-board cleanup, security boundaries, and local Kanban compatibility. |
| `python3 -m py_compile ...`, `node --check ...`, `git diff --check` | Mentat | 0 | Pass | Python, browser JavaScript, and patch hygiene are clean. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests` | Mentat | 1 | 878 passed, 1 failed, 4 skipped | Only `test_only_mentat_project_remains_active_for_v1` fails because the user's intentionally uncommitted `data/projects.json` adds `Daily Check`; that file is excluded from this slice. |
| `.venv/bin/python -m pytest tests/gateway/test_kanban_api.py tests/gateway/test_kanban_artifact_api.py tests/hermes_cli/test_kanban_db.py -q` | Hermes worktree | 0 | 271 passed | Complete affected Kanban/API set. |

### Rendered or manual behavior

- The local browser fixture rendered two accepted artifacts, including a PNG,
  in Operational Focus and the task view at 1280×720 and 390×844.
- Both files showed fixed same-origin Download actions. The delegated PNG used
  an `IMG` file card and created no `<img>` element.
- Neither desktop nor narrow layout introduced horizontal overflow.

## Adversarial review

- The first compatibility review identified automatic Home refresh, image
  embedding, legacy binding, archived import, missing-blob presentation,
  revision cleanup, transfer buffering/timeouts, and documentation gaps. All
  were corrected and covered by focused tests.
- The first security review reported no P0/P1 issues. It identified broader
  secret-pattern coverage and cleartext `localhost` handling; both were
  tightened and regression-tested.
- A later security pass identified image-container polyglots and hidden raster
  metadata as a publication blocker. Hermes now creates a descriptor-owned
  canonical raster snapshot, and Mentat independently canonicalizes it again
  before storage. The final security audit found no remaining P0-P3 issues and
  cleared publication.
- The final compatibility audit found no P0/P1 issues. Its EXIF-orientation
  finding was corrected and regression-tested. It also noted that Hermes
  canonicalizes all accepted images once for a manifest and again for an
  individual download. That bounded v1 cost is accepted as a residual
  performance risk rather than weakening the descriptor-owned security
  snapshot.

## Documentation updates

- Roadmap: not applicable unless an existing milestone entry is affected.
- Changelog: `CHANGELOG.md` records the capability and safety boundary.
- Architecture/operator docs: `ARCHITECTURE.md` and `REMOTE_HERMES.md` describe
  the fixed contract, graceful degradation, reconnect flow, bounds, and remote
  transport requirements.
- Hermes docs: `website/docs/user-guide/features/api-server.md` and
  `website/docs/user-guide/features/deliverable-mode.md` describe explicit
  completion artifacts and the API surface.
- Project/session notes: this review log is the current persistent record.
- Documentation verification: focused terminology search completed; duplicate
  API rows and repeated prose were removed.

## Publication gate

- Proposed files: the remote adapter, artifact snapshot boundary, task/action
  integration, Home/task UI, tests, architecture/operator docs, changelog, and
  this review log in Mentat; the Kanban artifact boundary, API routes, tests,
  and user docs in Hermes.
- Branch and base:
  `codex/remote-delegation-artifacts-v1` from `main` in both repositories.
- Commit message: `feat: add secure remote delegation artifacts`.
- PR title: `Add secure remote delegation artifact downloads`.
- PR summary: Add a capability-gated, bounded, server-to-server artifact
  contract and present private Mentat snapshots as same-origin task downloads.
- Unresolved risks: heuristic secret detection is defense in depth, not a
  credential DLP guarantee; the local transport fixture does not reproduce
  every TLS reverse proxy; production-scale 250 MiB load behavior and Windows
  filesystem semantics remain CI/deployment verification items. A task with
  many large images can spend material CPU time canonicalizing the manifest
  and then the selected download; the fixed 10-file, 250 MiB, pixel, frame, and
  120-second transfer bounds limit but do not eliminate that cost.
- User authorization and scope: standing authorization covers implementation,
  review dispositions, publication, and the next requested slices.
- Mentat commits: `52550aa`, `bb13e4f`, and `f066fcb`.
- Hermes commits: `d846f6e95` and `e96de80c6`.
- Mentat PR: https://github.com/hazeion/agent-os/pull/69
- Hermes PR: https://github.com/hazeion/hermes-agent/pull/4

## Outcome review

- Delivered outcome: completed remote delegated work can return supported files
  through a capability-gated Hermes manifest and authenticated byte route.
  Mentat rechecks every file and keeps its own private snapshot.
- User experience: generated files are visible beside work that needs attention
  on Home and in the full task card. A missing snapshot is clearly unavailable,
  never linked, and can be restored with Refresh.
- Safety outcome: no browser request reaches Hermes; no remote path, digest,
  upstream ID, storage key, or bearer credential reaches browser data.
- Residual limits: heuristic credential scanning is defense in depth; v1 does
  not browse workspaces, make ZIP files, or inline large image previews.
- Decision: accepted under the user's standing authorization. Proceed to
  publication, then begin the separately scoped Today-schedule layout slice.

- Classification: Ready for publication.
- Acceptance criteria summary: AC-1 through AC-10 pass.
- Potential bugs or untested paths: deployed TLS proxy behavior, maximum-size
  production load, heuristic credential-detection gaps, and Windows-only
  filesystem behavior remain explicit residual risks.
- Remaining reviewer dissent: none. The compatibility review's bounded
  repeated-canonicalization concern is recorded as an accepted residual risk.
- Compatibility/migration/rollback concerns: recorded in the slice contract.
- User decision: standing authorization granted for implementation, review
  dispositions, publication, and the next requested slices.
- Next slice authorized: Yes, after this slice's required verification and
  review gates complete.
