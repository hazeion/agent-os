# Feature Slice Review: Remote Capability Inventory

Status: In progress
Slice: `beta-2g-remote-capability-inventory`
Date: `2026-07-19`
Review log: `reviews/2026-07-19-beta-2g-remote-capability-inventory.md`

## Slice contract

### Goal

Let an operator inspect the selected remote Hermes host's available skills and
toolsets from Mentat Settings through the authenticated, read-only API that
Hermes advertises, without exposing credentials, paths, raw upstream data, or
skill contents.

### In scope

- Add fixed, capability-gated reads for exactly `GET /v1/skills` and
  `GET /v1/toolsets` after validating their advertised endpoint contracts.
- Normalize bounded skill/toolset identifiers, toolset enabled state, and tool
  counts.
- Bind discovery to the selected connection before and after upstream reads.
- Show concise counts, clear unsupported/unavailable states, and expandable
  read-only inventories in Settings.
- Preserve local-mode behavior without making remote requests.

### Out of scope

- Skill descriptions, categories, contents, paths, installation, deletion,
  selection, or any mutation.
- Toolset labels/descriptions, tool names, configuration details, or mutation.
- Remote profile discovery, Kanban, approval response, clarification,
  continuation, session search, Console behavior, or diagnostics redesign.
- A local skills/toolsets UI redesign.
- README changes; installation and first-run setup are unchanged.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Mentat calls only the exact advertised authenticated skills/toolsets GET paths when `skills_api` is true. | Client contract tests | Complete |
| AC-2 | Browser data is bounded, allowlisted, path-free, credential-free, and omits descriptions, skill contents, tool names, and raw upstream fields. | Schema/privacy tests | Complete |
| AC-3 | Connection changes, capability loss, wrong endpoint contracts, malformed data, private reflection, oversized data, auth failure, and partial inventory failure fail closed. | Negative and binding tests | Complete |
| AC-4 | Local mode performs no remote capability inventory call and keeps existing local Console/profile behavior. | Server/compatibility tests | Complete |
| AC-5 | Settings presents readable counts and clear local, unsupported, loading, available, and unavailable states without stretched action controls. | UI contract and rendered browser checks | Complete |
| AC-6 | Focused, full, static, two-reviewer, ready-PR, and hosted supported-platform gates pass. | Verification record | Pending |

### Constraints and recovery

- Safety: fixed shell-free GET operations only; API key, endpoint, host, paths,
  descriptions, skill contents, tool names, raw errors, and unrestricted upstream fields stay
  server-private.
- Compatibility: preserve the local adapter and all existing remote run,
  session, and Context Pack behavior; unsupported older Hermes hosts degrade
  clearly and remain non-actionable.
- Rendered behavior: use the shared Settings panel/list styles, compact controls,
  readable wrapping, and accessible status text.
- Rollback or recovery: reverting this slice removes only the read-only adapter
  and Settings inventory; it changes no stored data or Hermes state.
- Documentation targets: `ARCHITECTURE.md`, `REMOTE_HERMES.md`,
  `ROAD_TO_BETA.md`, `CHANGELOG.md`, and this review log. README remains
  unchanged because setup is unaffected.
- Version-control strategy: branch
  `agent/beta-2g-remote-capability-inventory` from `main`; publish one ready PR
  to `main` after two zero-finding exact-diff reviews and standing publication
  authorization.

### Scope discussion and approval

- Recommendation and rationale: implement remote skills/toolsets visibility
  now because Hermes advertises stable authenticated read-only endpoints, while
  complete profile discovery and Kanban remain upstream capability blockers.
- Alternatives considered: wait on profile discovery (stalls on upstream);
  expose raw payloads (rejected as unbounded/private); add mutations (outside
  the approved remote boundary); redesign local skill management (unnecessary).
- User decisions: the active Road to Beta goal authorizes continuing all slices
  and assumes approval for scope, tests, publication, merge, and the next slice.
  This standing instruction is the recorded exception to repeated workflow
  pauses. The README must remain concise and first-user-friendly whenever it is
  changed; this slice does not change it.
- Approved at: standing user authorization, applied `2026-07-19`.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | The client allowlist excludes both inventory paths. | Fake-transport capability and request-order tests. | Exact method/path/capability gating. | No live remote host required. |
| AC-2 | No remote inventory normalizer or public payload exists. | Bounds, truncation, allowlist, control-character, reflection, and omission assertions. | Only intended bounded metadata reaches the browser. | Upstream display text remains untrusted and escaped by the UI. |
| AC-3 | Inventory-specific failure modes are untested. | Endpoint mismatch, false/missing feature, malformed envelope/row, duplicate, overflow, auth, one-call failure, and connection-change tests. | Fail-closed behavior with no partial claim. | TLS behavior is already covered by the shared client tests. |
| AC-4 | Local mode has no capability-inventory route. | Local transport spy plus focused compatibility suites. | No remote request or local regression. | Does not redesign local inventory. |
| AC-5 | Settings has no runtime-capability surface. | Static UI contract tests, JavaScript syntax, browser smoke, and rendered narrow/wide inspection. | States render and remain usable. | Visual inspection is local-browser evidence, not pixel-perfect cross-platform proof. |
| AC-6 | Slice is not implemented or reviewed. | Focused tests, full suite, static checks, two independent adversarial reviews, and hosted matrix. | Repository and supported-platform gate. | Hosted tests cannot contact a private Hermes host. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest tests.test_remote_hermes tests.test_hermes_transport tests.test_hermes_skills tests.test_remote_context_inputs -v` | macOS / Python 3.11 | Pass | 55 tests; no failures or skips. |
| `node --check public/core.js` and `node --check public/app.js` | Node.js | Pass | Existing frontend syntax is valid. |
| `git diff --check` | Git | Pass | Review-log-only baseline diff is clean. |

### Test discussion and approval

- User questions and decisions: the standing goal authorizes the mapped test
  strategy without another pause.
- Accepted coverage gaps: no live private remote host in tests; deterministic
  fake HTTP responses plus the installed Hermes 0.18.2 source/docs establish
  the upstream contract. Hosted CI supplies OS/Python coverage.
- Approved at: standing user authorization, applied `2026-07-19`.

## Implementation record

### Changes

- Added fixed authenticated reads for exactly `/v1/skills` and `/v1/toolsets`
  after strict `skills_api` endpoint validation.
- Added bounded, all-or-nothing normalizers for public-safe skill and toolset
  metadata. Raw fields, contents, tool names, descriptions, categories, labels,
  paths, configured state, private
  reflections, and malformed or oversized responses fail closed.
- Added a binding-aware transport method and a loopback Mentat route that
  revalidates the selected connection before and after inventory reads. Local
  mode performs no remote call.
- Added a read-only Settings surface with escaped available, unsupported,
  unavailable, loading, and local states using the existing compact panel
  styles.
- Added focused backend, privacy, binding, compatibility, and frontend contract
  tests. Updated the architecture, remote contract, roadmap, and changelog;
  README remains unchanged because installation is unaffected.

### Deviations and decisions

- The browser payload deliberately reports only validated identifiers, enabled
  state, and counts. Hermes descriptions can name concrete tools and current
  labels can contain prose slashes, so all descriptions, categories, and labels
  remain server-private.
- Inventory is intentionally all-or-nothing: if either endpoint fails or the
  connection changes, Mentat returns no partial catalog.

## Verification

### Focused checks

- `python3 -m unittest tests.test_remote_capability_inventory tests.test_remote_capability_inventory_ui tests.test_remote_hermes tests.test_hermes_transport tests.test_remote_console_runs tests.test_remote_sessions tests.test_hermes_skills tests.test_remote_context_inputs -v`
  — pass, 98 tests.
- `python3 -m unittest tests.test_beta_contract tests.test_remote_capability_inventory tests.test_remote_capability_inventory_ui`
  — pass, 18 tests.
- `python3 -m py_compile server.py remote_hermes.py hermes_transport.py` — pass.
- `node --check public/core.js` and `node --check public/app.js` — pass.
- `git diff --check` — pass.

### Full suite

- `python3 -m unittest discover -s tests` — pass, 672 tests with four expected
  platform-specific skips.

### Rendered or manual behavior

- In-app browser inspection at 1280 px and 390 px confirmed the local Settings
  capability state is compact and readable with no horizontal overflow.
- A loopback fake Hermes fixture rendered the available remote state at 390 px
  with maximum 120-character skill and toolset identifiers. Both expanded lists
  wrapped within the 390 px viewport; the DOM contained no upstream category,
  label, description, path-like text, or concrete tool name.
- `scripts/browser_smoke.mjs` passed all 15 repository browser checks against a
  temporary loopback server, including navigation, task, calendar, Agents,
  Context Packs, and Console surfaces.
- The available-remote state is covered by escaped static UI contracts and the
  loopback fake-Hermes rendered fixture; no private remote host was contacted.

## Adversarial review

### Round 1

- Safety/privacy reviewer: three findings — optional inventory endpoint
  validation could disable existing run/session discovery; path/short-host
  reflection filtering missed separator and URI forms; permissive envelopes
  and falsy defaults could present partial or malformed data as complete.
- Compatibility/correctness reviewer: three findings, one overlapping — current
  Hermes toolset descriptions can name concrete tools; bundled multiline skill
  descriptions were rejected; optional endpoint validation could disable
  existing run/session discovery.
- Resolution: scoped inventory endpoint validation to the inventory operation;
  added run/session regressions; normalized permitted multiline whitespace;
  hardened path/URI/UNC/Windows and short-host token reflection checks; required
  exact complete envelopes and typed optional fields; removed toolset
  descriptions from the browser payload and UI; added fixtures based on Hermes
  0.18.2 shapes.
- Post-fix evidence: 97 focused tests and 671 full-suite tests pass, with four
  expected platform-specific skips; static checks pass.

### Round 2

- Safety/privacy reviewer: two residual findings — relative path forms could
  remain in visible metadata, and skill descriptions could still carry tool
  names declared by the toolset response.
- Compatibility/correctness reviewer: two findings — relative/network path
  forms remained possible, and maximum unbroken visible metadata needed an
  explicit narrow-layout wrapping contract and rendered test.
- Resolution: narrowed the browser allowlist again to validated identifiers,
  enabled state, and counts. Descriptions, categories, and labels are bounded
  and type-checked server-side but never returned. Every visible free-text field
  rejects slash or backslash path forms. Capability-scoped wrapping now stacks
  detail titles and pills safely at narrow widths. Added absolute, relative,
  UNC/network, Windows, tool-name, omission, CSS, and maximum-length rendered
  regressions.
- Post-fix evidence: 97 focused tests and 671 full-suite tests pass, with four
  expected platform-specific skips; static checks and the 390 px maximum-value
  remote fixture pass.

### Round 3

- Safety/privacy reviewer: one finding — a short private hostname followed by
  `.`, `-`, or `_` could bypass the hostname token boundary in visible fields.
- Compatibility/correctness reviewer: one finding — real Hermes 0.18.2 toolset
  labels include prose slashes, so the path filter would reject the inventory.
- Resolution: reduced the browser contract to strict skill/toolset identifiers,
  enabled state, and counts only. Categories, labels, and descriptions are
  validated for type/bounds but omitted. Short-host boundaries now use
  alphanumeric adjacency, rejecting `lab.internal`, `lab-remote`, and
  `lab_remote` while allowing `collaborative`. Added current-Hermes prose-label,
  private ignored-metadata, decorated-host, false-positive, omission, and final
  maximum-identifier browser regressions.
- Post-fix evidence: 98 focused tests and 672 full-suite tests pass, with four
  expected platform-specific skips; static checks and the identifier-only
  390 px remote fixture pass.

### Round 4

- Safety/privacy reviewer: `ZERO FINDINGS`.
- Compatibility/correctness reviewer: `ZERO FINDINGS`.
- Result: all prior findings are resolved; no blocking dissent remains on the
  identifier-only implementation packet.

### Round 5 — committed head

- Exact reviewed commit: `afc0614f0a4dad3f7a0519fbce6efb9f4134b881`.
- Safety/privacy reviewer: `ZERO FINDINGS`.
- Compatibility/correctness reviewer: `ZERO FINDINGS`.
- Result: the committed implementation head exactly matches the cleared packet.

## Documentation updates

- Roadmap: records Milestone 2G as complete and keeps the remaining blockers
  explicit.
- Changelog: records the read-only capability view and privacy boundary.
- Architecture/operator docs: record the fixed endpoint, connection-binding,
  allowlist, omission, and all-or-nothing contracts.
- Project/session notes: this review log.
- Documentation verification: beta contract tests and full suite pass.

## Publication gate

- Proposed files: `remote_hermes.py`, `hermes_transport.py`, `server.py`,
  `public/core.js`, `public/index.html`, `public/app.js`, `public/styles.css`, focused tests,
  `ARCHITECTURE.md`, `REMOTE_HERMES.md`, `ROAD_TO_BETA.md`, `CHANGELOG.md`, and
  this review log. README is intentionally unchanged.
- Branch and base: `agent/beta-2g-remote-capability-inventory` → `main`.
- Commit message: `Add remote Hermes capability inventory`.
- PR title: `Add remote Hermes capability inventory`.
- PR summary: expose bounded, read-only remote skills/toolsets in Settings with
  exact capability gating, connection binding, fail-closed normalization, and
  local/remote compatibility tests.
- Unresolved risks: a live private remote host is not available to CI; the
  installed Hermes 0.18.2 source/docs and deterministic HTTP fakes establish
  the schema contract. Hosted cross-platform verification remains pending.
- User authorization and scope: standing authorization recorded above.
- Implementation commit: `afc0614f0a4dad3f7a0519fbce6efb9f4134b881`.
- Evidence commit: pending.
- Ready PR URL: pending.

## Outcome review

- Classification: pending.
- Acceptance criteria summary: pending.
- Potential bugs or untested paths: pending.
- Remaining reviewer dissent: pending.
- Compatibility/migration/rollback concerns: pending.
- User decision: standing authorization to continue after successful merge.
- Next slice authorized: Yes, under the active Road to Beta goal.
