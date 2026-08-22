# Feature Slice Review: Next.js Emerald application shell

Status: Ready for publication
Slice: `2a-b-next-emerald-shell`
Date: 2026-08-22
Review log: `reviews/2026-08-22-next-emerald-shell.md`

## Slice contract

### Goal

Replace the Node foundation page with a responsive Next.js application shell
that carries the completed Emerald interface into React and Tailwind. Provide
honest route frames for Home, Agents, Tasks, and Runs without moving data or
runtime authority out of Python.

### In scope

- Port the effective Emerald tokens, layout, spacing, panels, controls, local
  mark, and source-owned line icons from the current `public/` interface.
- Use React Server Components for shared structure and route content, with
  small client components where React improves route-aware or responsive
  interaction.
- Use CSS media or container queries for layout and React for interaction state,
  focus management, and consistent desktop/mobile controls.
- Add route frames for `/`, `/agents`, `/tasks`, and `/runs` in the existing
  `web/` application.
- Add desktop navigation, the current 76 px compact rail, and an accessible
  mobile drawer at 900 px and below.
- Preserve the fixed `/api/bridge/health` capability as the only live data in
  this slice.
- Add Standard and High Contrast behavior with a no-flash saved preference.
- Keep the six-run Lighthouse 100/100/100/100 gate.

### Out of scope

- New Agent, Task, Run, project, calendar, cron, search, settings, or Console
  data APIs.
- TanStack Query, SSE, WebSocket, messaging, stop, approval, or other runtime
  controls.
- Fake operational rows, counts, schedules, Agents, Tasks, or Runs.
- Importing the full legacy stylesheet or preserving its DOM IDs and view keys.
- Removing the Python compatibility interface or changing installers, ports,
  SQLite authority, Hermes authority, credentials, or runtime adapters.
- Building unused component-library primitives that no route frame needs.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The Next.js shell uses React and Tailwind and matches the current Emerald interface's effective palette, typography, spacing, panel, control, navigation, and responsive character without importing `public/styles.css`. | Source/token contracts and rendered comparison at agreed widths. | Met |
| AC-2 | `/`, `/agents`, `/tasks`, and `/runs` render one clear page heading, working route navigation, `aria-current="page"`, and honest foundation states with no fake data. | Build route inventory, route tests, and browser navigation. | Met |
| AC-3 | Desktop, 76 px compact, and mobile navigation remain usable with keyboard and pointer input; the drawer traps focus, closes with Escape or backdrop, and returns focus to its opener. | Focused interaction tests and browser matrix. | Met |
| AC-4 | Standard and High Contrast modes apply before first paint, persist an explicit choice, follow `prefers-contrast: more` when unset, retain visible focus, and respect reduced motion. | Source tests plus reload, media-emulation, and rendered checks. | Met |
| AC-5 | The shell reports the existing bounded bridge health projection without exposing tokens, private paths, runtime references, or a generic proxy; unavailable state remains stable and honest. | Existing boundary suites, Node tests, delayed/unavailable browser probes. | Met |
| AC-6 | No page-level horizontal overflow occurs at 1680, 1440, 1024, 768, or 390 px, including a reduced-CSS-viewport 200 percent reflow simulation; responsive changes do not duplicate or hide the primary route controls. | Browser geometry and reflow checks. | Met |
| AC-7 | Three desktop and three simulated-mobile production Lighthouse audits each score 100 for Performance, Accessibility, Best Practices, and SEO. | Pinned six-run Lighthouse gate and compact evidence. | Met |
| AC-8 | The Python app on port 8888, package boundaries, Node/Python process boundary, and unrelated user files remain unchanged; focused and full suites pass. | Diff inspection, legacy browser smoke, package checks, and clean full suite. | Met |
| AC-9 | Two independent adversarial reviewers report no unresolved blocking correctness, safety, compatibility, accessibility, or product findings. | Recorded review rounds and dispositions. | Met |

### Constraints and recovery

- Safety: browser traffic remains same-origin through Node; Python keeps all
  storage, Hermes, filesystem, credential, Agent, Task, and Run authority.
- Compatibility: the Python interface on port 8888 and its current Emerald
  implementation remain operational during the migration.
- Rendered behavior: current Emerald styling is the visual source. React may
  improve responsive interaction but must not create a second mobile UI or use
  JavaScript viewport sniffing for layout.
- Rollback or recovery: revert the isolated `web/`, tests, docs, and review-log
  changes. There is no data, schema, runtime, or installer migration.
- Documentation targets: roadmap, design migration notes, changelog, and this
  review log only where the completed behavior changes their claims.
- Version-control strategy: branch `feature/2a-b-emerald-shell` from merged
  `main` at `db08d394e05667ff36684bf2a20fe1bba44aadbd`; target `main` in a
  ready-for-review PR. Preserve and exclude all unrelated worktree files.

### Scope discussion and approval

- Recommendation and rationale: migrate the completed shell before connecting
  route data so visual, accessibility, performance, and process boundaries can
  be reviewed without mixing orchestration APIs into the same change.
- Alternatives considered: redesign from the mockup and Figma handoff was
  rejected because the current Emerald interface is already the approved
  design; importing the full legacy stylesheet was rejected because its large
  historical cascade would carry old DOM coupling and performance debt.
- User decisions: use the current `public/styles.css` and current UI as the
  canonical visual reference; use React and Tailwind for the new build; apply
  React where it materially improves responsive behavior while keeping CSS
  responsible for layout.
- Approved at: 2026-08-22, user message `i approve`, refined by the user's
  responsive React direction in the following message.
- Process exception: after the third review round, the user provided standing
  approval to complete any remaining in-scope corrections and then explicitly
  approved publication and merge. The final corrected candidate still required
  both reviewers' no-findings verdicts before that authorization could be used.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | `web/` renders a small foundation page with different tokens and layout. | Token/source contracts plus side-by-side browser inspection against the current Emerald UI. | The new shell ports the approved design rather than inventing another one. | Visual review is not a brittle pixel diff. |
| AC-2 | Only `/` exists as a product page. | Build inventory, route HTTP probes, semantic DOM assertions, and navigation checks. | Every approved route exists and remains honest. | Route data arrives in later slices. |
| AC-3 | The foundation has no application navigation or drawer. | Unit tests for state helpers where useful and browser keyboard, focus, Escape, backdrop, return-focus, compact-tooltip, and pointer checks. | Responsive navigation is operable and accessible. | Complete screen-reader testing remains manual. |
| AC-4 | No shell contrast preference exists. | Preloader/source tests plus empty/saved/system/high/reduced-motion browser matrix. | Appearance is stable before paint and persists correctly. | Browser emulation covers Chromium media behavior only. |
| AC-5 | Bridge health works only in the foundation card. | Existing request/bridge tests plus delayed, ready, and unavailable rendered states. | The shell reuses the fixed safe capability without widening it. | No state-changing route is exercised because none is in scope. |
| AC-6 | Current smoke checks only 1440 and 390 px on one page. | Six-width route matrix, including the exact 900 px breakpoint, plus a half-width, half-height CSS viewport reflow simulation, bounding boxes, scroll width, target sizes, and screenshots. | The shell remains usable across desktop, compact, boundary, tablet, and phone layouts, including the layout pressure expected at 200 percent zoom. | This is not a native browser-zoom or text-only-zoom test; Safari and Firefox remain untested locally. |
| AC-7 | The foundation gate covers only the old page. | Run the pinned gate after the full shell build and record all six audits. | The migrated shell preserves the exact replacement performance contract. | Synthetic Lighthouse is not field telemetry. |
| AC-8 | No shell diff or compatibility evidence exists. | npm frozen install/check/build, focused Python contracts, legacy browser smoke, package checks, clean full suite, and diff audit. | The slice does not regress the compatibility product or authority boundaries. | Hosted CI follows publication. |
| AC-9 | No independent review exists. | Two read-only reviewers receive the same raw packet, followed by fixes, retests, and full re-review as needed. | Independent adversarial scrutiny covers both safety and product behavior. | Review cannot prove every browser or future integration. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Inspect merged base, roadmap, current `web/`, current Emerald CSS, design handoff, and worktree | macOS x64 | Pass / gap confirmed | 2A-A is merged at `db08d394`; `/agents`, `/tasks`, and `/runs` are absent; unrelated JSON, mockup, runtime, lock, video, and npm files are identified for exclusion. |
| PR #114 hosted checks | GitHub Actions | Pass | 52 required checks passed on the final head and PR #114 merged. |
| Documentation clean candidate | macOS x64, Python 3.13.14 | Pass | 1,304 tests passed with 4 expected skips before the 2A-B branch began. |
| `node --version`; `npm --version`; `npm --prefix web ci --ignore-scripts` | Node 24.19.0, npm 11.17.0 | Pass | Exact approved runtime; 463 packages installed from the frozen lock with lifecycle scripts disabled. |
| `npm --prefix web run check` | Node 24.19.0 | Pass | ESLint and TypeScript passed; 9 Node tests passed. |
| `npm --prefix web run build` | managed local environment | Environment-limited | The unchanged Turbopack build could not create its PostCSS worker socket (`Operation not permitted`) in either sandbox or host-approved execution. The same command passed required GitHub CI on the merged base. |
| Supported local Webpack compile of the unchanged app | Node 24.19.0 | Pass | Next compiled, typechecked, and prerendered `/`; route inventory confirms `/agents`, `/tasks`, and `/runs` are absent. The Turbopack-specific no-hydration postprocessor rejected Webpack's different CSS asset path, confirming another baseline contract that 2A-B must replace for the multi-route shell. |

### Test discussion and approval

- User questions and decisions: the user confirmed React and Tailwind and asked
  for React-based responsive improvements when they provide a real benefit.
- Accepted coverage gaps: no full screen-reader pass, Safari/Firefox matrix,
  installed Node packaging, or field performance in this shell-only slice.
- Approved at: 2026-08-22, user message `i approve`, with the subsequent React
  responsive refinement treated as an in-scope addition.

## Implementation record

### Changes

- Replaced the one-page runtime foundation with shared React Server Components,
  a fixed four-route registry, source-owned SVG icons, and honest Home, Agents,
  Tasks, and Runs frames.
- Ported the effective Emerald palette and shell behavior into the focused
  Tailwind stylesheet. Desktop uses a 216 px sidebar, compact layouts use a
  76 px rail, and widths at or below 900 px use one accessible drawer.
- Added a no-flash contrast preloader and a small deferred shell runtime for
  saved contrast, drawer focus management, and the fixed bridge-health fetch.
  No initial shell content waits for that fetch.
- Extended the production postprocessor and rewrites to publish four validated
  static HTML routes with only the preference and shell scripts; no Next.js
  hydration or Flight payload reaches the browser.
- Resized the copied Emerald mark from 940 px and 248,846 bytes to a visually
  equivalent 168 px and 18,882 bytes for its 42 px display size.
- Expanded source, Python contract, production browser, responsive, failure,
  zoom, and Lighthouse coverage; updated the roadmap, Emerald plan, and
  changelog.

### Deviations and decisions

- React owns the reusable server component and route structure, while CSS owns
  responsive layout. One zero-DOM client signal tells the persistent shell
  runtime when development hydration is complete so Next Link transitions can
  remain enabled without a hydration mismatch. Production strips that client
  runtime together with every other framework script and retains only the two
  source-owned preference and progressive-enhancement scripts.
- The final normal `npm --prefix web run build` path now completes locally with
  Next.js 16.3.2 and Turbopack. The earlier worker-socket limitation did not
  reproduce on the corrected candidate.
- An initial mobile audit scored 94 Accessibility because the visually hidden
  compact Contrast text did not name its select. `aria-label="Contrast"`
  closed that audit.
- One pre-optimization mobile run scored 98 Performance with a 2.42 second LCP.
  The page was needlessly transferring and preloading the 248 KB source mark.
  Removing priority and resizing the copied web asset reduced transfer from
  about 263 KB to 33 KB and stabilized all three mobile LCPs near 1.27 seconds.
- Round-one review found that compact bridge text could clip, unavailable text
  could shift the utility bar, the contrast select lost its focus outline, and
  vertically constrained navigation could hide later links. The status now has
  fixed geometry with visible Ready/Offline text on phones, the select keeps a
  visible keyboard outline, both navigation containers scroll when needed, and
  all icon controls meet the 44 px target size.
- Round-one review also found a breakpoint focus edge case, a development-only
  preference flash, an imprecise Agents description, and overclaims in the
  initial verification wording. Focus ownership now survives the 900 px mode
  change, the preference script runs synchronously in source and production,
  Agents are described as canonical workers, and the evidence below names its
  actual Chromium and reflow limits.
- Round-two review found that the route-level enhancement script would not be
  re-executed after an actual hydrated Next Link transition. The user chose to
  retain Link. The runtime now lives in the persistent root layout, delegates
  interaction at the document boundary, and resynchronizes route DOM through a
  bounded observer. A tiny React effect signals completed development
  hydration before enhancement begins. Development alone permits the
  `unsafe-eval` required by Webpack React Refresh; the static production CSP
  remains `script-src 'self'`.
- The other round-two review found that the Home panels stayed side by side
  from 721 through 900 px and that the utility bar used 58 px instead of the
  completed Emerald contract's 64 px. The shell now switches to one content
  column with 16 px padding at 900 px, reduces outer padding to 12 px below
  640 px, and uses a 64 px utility bar. The browser matrix now includes the
  exact 900 px boundary.
- Round-three review found that the Mentat Home Link did not share the drawer
  dismissal hook, compact pseudo-tooltips were clipped by scroll containers,
  and a slow or failed runtime left the translated mobile drawer focusable.
  The brand now participates in delegated navigation and has a real hydrated
  Link regression. A fixed, viewport-clamped label outside the scrolling rail
  replaces the clipped pseudo-tooltip, while both navigation containers retain
  bounded vertical scrolling at every width. A 1024 x 320 keyboard regression
  reaches and reveals the final Runs link. The closed mobile drawer is hidden
  through CSS before enhancement, and a held-runtime browser probe verifies
  that keyboard focus skips it.
- The final reviewers independently identified one remaining hydration race:
  compact focus and pointer handlers could mutate the server-rendered tooltip
  before the React hydration signal. Every tooltip event now fails inert until
  the hydration-aware runtime starts. A development regression pauses all Next
  framework JavaScript, sends compact keyboard and pointer input, and verifies
  that tooltip text, visibility, and inline position remain untouched until
  hydration completes.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `npm --prefix web run check` | Node 24.19.0 | 0 | 14 passed | ESLint, TypeScript, bridge/request tests, process-timeout test, shell routes, preferences, responsive contracts, and static-publication contracts pass. |
| `npm --prefix web run build` | Node 24.19.0, Next.js 16.3.2, Turbopack | 0 | 4 static product routes | `/`, `/agents`, `/tasks`, and `/runs` prerender; each published route contains only `/preference-preload.js` and `/shell-runtime.js` and no Flight payload. |
| `python3 -m unittest` focused Node/preview/CI/architecture set | Python 3.13.14 | 0 | 36 passed | Includes the updated merged-2A-A and completed-2A-B roadmap contract. |
| `node scripts/web_foundation_smoke.mjs` | Chromium 152.0.7923.0 | 0 | All checks passed | Four routes; 1680, 1440, 1024, 900, 768, and 390 px; one content column at and below 900 px; a held-runtime phone probe that skips the hidden drawer; delayed/ready/unavailable bridge at desktop and phone widths; real keyboard and CDP pointer input; fixed compact-tooltip geometry; 1024 x 320 compact keyboard reachability with a scrolling rail; focus trap, Escape, backdrop, breakpoint handoff, return focus, persisted/system contrast, visible focus, reduced motion, 44 px targets, and a 720 x 360 reduced-CSS-viewport reflow simulation. No horizontal overflow or status layout shift. |
| `MENTAT_WEB_CLIENT_NAVIGATION=1 node scripts/web_foundation_smoke.mjs` against Webpack development | Chromium 152.0.7923.0 | 0 | All checks passed | With Next framework JavaScript deliberately paused, early compact keyboard and pointer input left the unhydrated tooltip untouched; hydration then completed. Real pointer-activated Home-to-Tasks and brand-to-Home Link transitions preserved the document, active route, bridge state, contrast choice, one persistent runtime, drawer dismissal, Escape focus return, and a clean console. |
| `npm --prefix web run lighthouse:gate` after the hydration-race fix | Lighthouse 13.4.1, Chromium 152.0.7923.0 | 0 | 6/6 audits at 100/100/100/100 | Desktop LCP 209-225 ms; mobile LCP 1,047-1,277 ms; TBT 0 ms; mobile CLS 0; transfer 34,468 bytes. |
| Visual screenshot review | Chromium 152.0.7923.0 | Pass | 5 viewport captures | Wide, desktop, compact, tablet, and phone preserve the completed dark Emerald character and readable hierarchy. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests` in the final hydration-corrected clean candidate | macOS x64 host, Python 3.13.14 | 0 | 1,304 passed, 4 skipped in 213.824 s | Disposable `git archive` candidate overlaid only with slice files. User-owned JSON, mockups, runtime, lock, video, and npm-config files were absent; tracked JSON fixtures matched the base byte-for-byte. |
| `python3 -m unittest tests.test_agent_runtime_architecture tests.test_node_runtime_foundation` after post-merge roadmap status update | macOS x64, Python 3.13.14 | 0 | 7 passed | Confirms 2A-B Complete, 2B-A Proposed, and the final Node shell publication contracts. |

### Rendered or manual behavior

- The desktop shell keeps the full Mentat brand, compact grouped controls, and
  two-column planning frame. The compact rail retains the same route controls
  without text overflow. Tablet and phone use one drawer and reflow panels
  without creating a separate mobile interface.
- Home contains only migration status and current-slice facts. Agents, Tasks,
  and Runs explicitly say which later data slice they are waiting for.
- Bridge health changes from checking to ready or unavailable without moving
  the surrounding controls or panels. It does not delay the initial heading or
  content paint.

## Adversarial review

### Round one

- Reviewer A reported two blocking findings: compact bridge text was visually
  clipped and depended on color, and the wider unavailable label could shift
  controls above the phone breakpoint. The reviewer also identified focus
  ownership during breakpoint changes, preference preload behavior in local
  development, and evidence wording as non-blocking issues.
- Reviewer B reported two blocking findings: the contrast select suppressed its
  focus outline, and the original scale probe did not prove constrained-height
  navigation remained reachable. The reviewer also identified 42 px mobile
  icon targets and wording that conflated Mentat Agents with runtime identities.
- All findings were accepted. The fixes and expanded browser checks are
  recorded in the implementation and verification sections above.
- Both reviewers named the same residual limits: Chromium-only rendered checks,
  no full screen-reader pass, no Safari/Firefox matrix, and no native
  browser-zoom check.

### Round two

- Reviewer A found one blocking development-only issue: route-scoped script
  listeners would not survive a hydrated Next Link transition. The reviewer
  also found that the contrast select remained below the intended 44 px mobile
  target and that the browser probe measured only icon buttons.
- Both findings were accepted. Link remains in place by user decision. The
  persistent hydration-aware runtime, development-only CSP allowance, exact
  Link-transition browser probe, 44 px select, and expanded target measurement
  are recorded above.
- Reviewer B found one blocking responsive mismatch: the canonical Emerald
  contract requires a single content column at and below 900 px, while the
  candidate used 720 px. The reviewer also reported the utility bar's 58 px
  height instead of the completed design's 64 px height as non-blocking.
- Both findings were accepted and corrected with exact source and browser
  boundary checks.

### Final re-review

- Reviewer B returned **No findings** after the responsive correction.
- Reviewer A then identified two blocking navigation issues: the Mentat Home
  Link did not dismiss a hydrated drawer, and compact labels were clipped by
  their scroll ancestors. The reviewer also reported the pre-enhancement
  off-canvas drawer remaining focusable as non-blocking.
- All three findings were accepted and corrected with direct browser
  regressions. Reviewer A's next pass found that the interim overflow change
  removed short-height compact scrolling. The final fixed tooltip now lives
  outside the scrolling containers, and the rail again scrolls at every width;
  a dedicated 1024 x 320 keyboard regression covers the failure mode.
- Both independent reviewers are re-reviewing the complete corrected candidate
  and current evidence packet. AC-9 remains pending until both return with no
  unresolved blocking findings.

### Hydration-race review

- Reviewer A and Reviewer B independently reported the same blocking issue:
  compact `focusin` and `pointerover` handlers could mutate React-owned tooltip
  markup while framework mode was still waiting for its hydration signal.
- The finding was accepted. Tooltip focus, pointer, scroll, and compact-media
  handlers now return without mutation until `runtimeStarted` is true.
- The development browser probe now pauses `/_next/static/*.js`, focuses and
  hovers Agents at compact width, verifies the tooltip remains blank and hidden,
  releases the framework scripts, and observes the hydration signal before
  continuing through the existing Link-transition checks.
- Reviewer A also noted stale clean-suite and roadmap wording in this log. The
  acceptance table and documentation summary now match the completed roadmap;
  the post-fix clean-suite refresh passes.
- Both reviewers will receive the complete retested candidate for a final
  independent no-findings verdict.
- Reviewer A returned **No findings** on the complete hydration-corrected
  candidate.
- Reviewer B independently returned **No findings** on the same candidate.
- Both retained only the accepted residual test limits recorded below; no
  correctness, safety, compatibility, accessibility, or product dissent
  remains.

## Documentation updates

- Roadmap: records merged 2A-A, completed 2A-B, and proposed 2B-A.
- Changelog: records the responsive shell, static publication, performance,
  and retained Python authority.
- Architecture/operator docs: no authority, port, setup, or operator command
  changed; no update required.
- Project/session notes: this review log.
- Documentation verification: focused architecture and roadmap contracts pass;
  the final clean full suite passes.

## Publication gate

- Proposed files:
  - `CHANGELOG.md`
  - `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`
  - `design/emerald-operations/IMPLEMENTATION_PLAN.md`
  - `reviews/2026-08-22-next-emerald-shell.md`
  - `scripts/web_foundation_smoke.mjs`
  - `tests/test_agent_runtime_architecture.py`
  - `tests/test_node_runtime_foundation.py`
  - `web/next.config.ts`
  - `web/public/foundation-status.js` (delete)
  - `web/public/mentat-mark-emerald.png`
  - `web/public/preference-preload.js`
  - `web/public/shell-runtime.js`
  - `web/scripts/prepare-standalone.mjs`
  - `web/src/app/agents/page.tsx`
  - `web/src/app/app-shell.tsx`
  - `web/src/app/bridge-status.tsx`
  - `web/src/app/globals.css`
  - `web/src/app/layout.tsx`
  - `web/src/app/page.tsx`
  - `web/src/app/route-frame.tsx`
  - `web/src/app/runs/page.tsx`
  - `web/src/app/shell-icon.tsx`
  - `web/src/app/shell-runtime-signal.tsx`
  - `web/src/app/tasks/page.tsx`
  - `web/src/lib/shell-routes.ts`
  - `web/tests/shell-contract.test.ts`
- Explicit exclusions: user-owned `data/projects.json`, `data/tasks.json`,
  `design/mockups/`, `tmp/`, `uv.lock`, `videos/`, and `web/.npmrc`.
- Branch and base: `feature/2a-b-emerald-shell` into `main`.
- Commit message: `Add the Next.js Emerald application shell`.
- PR title: `Add the Next.js Emerald application shell`.
- PR summary: port the completed Emerald interface into responsive shared React
  route shells; preserve Python authority and the fixed health bridge; retain
  the exact six-run Lighthouse gate at 100/100/100/100.
- Unresolved risks: no blocking risk known. Rendered coverage remains Chromium-
  only; no full screen-reader, Safari/Firefox, native browser/text zoom,
  installed-package, or field-telemetry pass is included in this slice. Hosted
  CI remains a publication gate and must pass before merge.
- PR mode: ready for review, never draft.
- User authorization and scope: implementation, publication, and merge were
  explicitly approved on 2026-08-22; only the reviewed-integration verification
  and no-findings gates remain before exercising that authorization.
- Commit hash: Pending.
- Ready PR URL: Pending.

## Outcome review

- Classification: pending hosted publication and CI.
- Acceptance criteria summary: AC-1 through AC-9 are met locally.
- Potential bugs or untested paths: the accepted residual test limits listed in
  the publication gate.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: no data or schema migration.
- User decision: pending.
- Next slice authorized: No.
