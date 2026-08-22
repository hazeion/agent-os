# Feature Slice Review: Node Runtime Foundation

Status: Ready for publication approval

Slice: `2a-a-node-runtime-foundation`

Date: 2026-08-21
Review log: `reviews/2026-08-21-node-runtime-foundation.md`

## Slice contract

### Goal

Provide one source-checkout preview command that launches a production-built,
loopback-only Next.js shell on Node 24 and reports live readiness from a
private Python Local Bridge, while leaving the installed Python product and
legacy `public/` frontend operational and unchanged.

### In scope

- Add a `web/` Next.js App Router project using React, TypeScript, Tailwind CSS,
  semantic Mentat tokens, and the standard Node server with standalone output.
- Require Node 24 only: accept Node `>=24.19.0 <25`, pin source/CI verification
  to Node `24.19.0`, and commit an exact npm dependency lock.
- Add a fixed, read-only Python bridge-health endpoint protected by a
  process-ephemeral token, strict loopback/Host checks, and a server-to-server
  request boundary that rejects browser-originated requests.
- Add a fixed Next.js backend-for-frontend health route and a local request
  boundary that rejects non-loopback Host values, cross-site requests, and
  mismatched origins without forwarding arbitrary paths or headers.
- Add a source-only preview supervisor that launches the private Python bridge
  and production Node gateway with fixed shell-free argument arrays, monitors
  both processes, and shuts down the surviving process when either exits.
- Render a small accessible Mentat runtime-foundation page with fixed status
  geometry so asynchronous health does not create layout shift.
- Add focused Python/TypeScript tests, production integration evidence, CI
  checks, documentation, browser inspection, and repeatable Lighthouse
  evidence.

### Out of scope

- Replacing the installed product or moving the canonical browser URL on port
  8888 from Python to Node.
- Bundling Node or the standalone Next output into pipx, macOS, or Windows
  release artifacts.
- Migrating the real Home, Agents, Tasks, Runs, Console, Settings, or other
  legacy views; Slice 2A-B owns the Emerald Operations shell migration.
- Adding TanStack Query, shadcn/ui components, Radix primitives, Lucide, SSE,
  WebSocket, mutations, or a generic proxy before a concrete consumer exists.
- Moving SQLite, orchestration, Hermes, filesystem, credential, or runtime
  authority out of Python.
- Modifying or including the user's `data/projects.json`, `data/tasks.json`,
  untracked design/mockup/video/runtime files, or unrelated `uv.lock`.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The source checkout requires Node `>=24.19.0 <25`, pins the repository and every Node CI setup to `24.19.0`, and rejects Node 22, 23, 25, or 26 for the preview. | Version contract tests, workflow inspection, and preview negative tests. | Met |
| AC-2 | One documented preview command launches the production standalone Next shell on an explicit loopback port and displays both Node gateway readiness and live Python bridge readiness. | Production build, process integration test, and rendered Chromium inspection. | Met |
| AC-3 | The Python bridge exposes only fixed, read-only versioned health behavior; valid token-bound server requests succeed while missing/wrong tokens, browser headers, foreign Host values, non-loopback binds, unsupported methods, and unknown routes fail closed. | Python unit/integration boundary tests and direct HTTP probes. | Met |
| AC-4 | The Node gateway accepts only the configured loopback Host/origin, exposes one fixed health BFF route, forwards no browser headers or arbitrary target, returns only a bounded redacted projection, and fails closed when bridge configuration or responses are invalid. | TypeScript unit tests plus production forged-request probes. | Met |
| AC-5 | The supervisor uses fixed shell-free commands, keeps the bridge token process-private, starts Node only after bridge readiness, and terminates the sibling process when Node, Python, or the supervisor stops. | Python supervisor unit tests and production lifecycle integration. | Met |
| AC-6 | The foundation page is keyboard-readable, responsive, stable while health resolves, free of browser-console errors, and preserves the current clean dark/Emerald direction without altering the legacy UI. | Browser smoke at desktop and phone widths, accessibility inspection, screenshots, and legacy browser regression. | Met |
| AC-7 | Three production desktop and three simulated-mobile Lighthouse audits of the minimal shell each score 100 Performance, Accessibility, Best Practices, and SEO; FCP, LCP, TBT, and CLS are recorded alongside category scores. | Six fixed-configuration Lighthouse reports. | Met |
| AC-8 | Focused checks, the complete Python suite, existing package/browser/security gates, exact npm install/build checks, and two independent adversarial reviews pass without including unrelated worktree changes. | Verification tables, raw diff inspection, and reviewer records. | Met |

### Constraints and recovery

- Safety: bind both processes to loopback, use an ephemeral high-entropy bridge
  token, compare it in constant time, never write/log/return it, and expose no
  catch-all proxy or browser-controlled upstream path/header forwarding.
- Compatibility: the current Python server, CLI, package artifacts, data
  authority, and `public/` frontend remain the default installed behavior.
- Rendered behavior: render useful shell content before asynchronous bridge
  health; reserve status geometry; use system fonts and no remote assets; keep
  initial client JavaScript intentionally small.
- Rollback or recovery: stop the preview and revert the isolated branch. There
  is no data/schema migration, bridge token persistence, or installed-product
  cutover. Removing `web/`, the bridge module, preview script, tests, and docs
  fully removes the slice.
- Documentation targets: `README.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`,
  `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`, `CHANGELOG.md`, and this review log.
- Version-control strategy: dedicated
  `feature/2a-a-node-runtime-foundation` branch from synchronized
  `origin/main`, targeting `main`; preserve and exclude all unrelated modified
  and untracked files.

### Scope discussion and approval

- Recommendation and rationale: use the full Node runtime rather than a static
  export so Mentat can keep one browser origin, add a validated backend-for-
  frontend boundary, stream later run state, and split browser bundles by
  route. Stage it as an opt-in source preview so runtime security and
  performance are proven before installer and port-8888 cutover work.
- Alternatives considered: static export under Python (simpler packaging but no
  request-time BFF/proxy features); immediate Node takeover on port 8888
  (combines UI, lifecycle, security, and installer cutover in one risky slice);
  Node spawning Python (reverses the mature process-management boundary too
  early).
- User decisions: the user chose a Node runtime, required Node 24 only instead
  of retaining Node 22 compatibility, requested the latest Node 24 LTS, and
  installed standalone Node 24.19.0 without changing Hermes' private Node
  runtime. The user then explicitly confirmed the revised contract and test
  strategy.
- Approved at: 2026-08-21, user message `confirm`.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | CI references Node 24.18.0, no package engine or source version file exists, and no runtime version gate exists. | Contract tests for `.node-version`, `package.json`, every workflow pin, and preview version parsing across 22/23/24/25/26. | Source, CI, and runtime agree on the approved Node line. | Does not test every future Node 24 patch. |
| AC-2 | No `web/` app, production Node server, bridge, or preview command exists. | Build standalone output, launch the documented command against disposable ports, and inspect public page/health responses. | The smallest end-to-end Node/Python topology actually runs. | Source preview is not installed packaging evidence. |
| AC-3 | Python has same-origin browser API checks but no private token-authenticated Local Bridge endpoint. | Start the bridge on an ephemeral port and probe valid, tokenless, wrong-token, browser-origin, forged-Host, method, path, and bind cases. | The internal capability is fixed, private, and fail-closed. | Same-user processes can inspect process environments; that is inside the local operator trust boundary. |
| AC-4 | A separate Node origin cannot call current Python APIs directly, and no BFF validation exists. | Pure TypeScript request/config/payload tests plus production raw HTTP probes with forged Host/Origin/Sec-Fetch headers and unavailable bridge. | The public gateway does not become a localhost request-confusion or generic-proxy surface. | It does not yet exercise state-changing BFF methods because none are in scope. |
| AC-5 | Current lifecycle launches one Python server only. | Unit-test command construction/version checks/cleanup order; integration-test readiness, sibling death, and final listener cleanup. | Preview supervision is bounded and does not strand a process. | Mocked cleanup logic runs in Windows CI, but real child-death integration is POSIX-only; Windows process-tree behavior remains unverified before any installed-runtime cutover. |
| AC-6 | No replacement shell exists; the legacy Emerald shell is the only rendered surface. | Chromium desktop/phone navigation, status transition geometry, keyboard semantics, console log, screenshot inspection, and unchanged legacy smoke. | The foundation is visibly usable without regressing the compatibility surface. | Chromium does not represent every browser engine. |
| AC-7 | No Node-shell Lighthouse baseline exists; legacy mobile performance remains below the exact replacement goal. | Three cold production desktop and three equivalent simulated-mobile Lighthouse audits with fixed flags and disposable processes. | The new architecture begins without inherited monolithic JS/CSS performance debt. | Local Lighthouse remains sensitive to host contention and is not field telemetry. |
| AC-8 | No implementation evidence or independent review exists. | npm frozen install/check/build/audit, focused Python tests, full Python suite, package/browser/security checks, diff inspection, and two read-only reviewers. | Repository-wide compatibility, dependency integrity, and adversarial scrutiny. | Hosted GitHub CI follows publication. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `git status --short --branch`; compare `HEAD` and `origin/main` | macOS x64, branch point | Pass | `main` and `origin/main` both `5193993d20226774f2a45d1de239d75d868f67d7`; user-owned modified/untracked files identified for exclusion. |
| `node --version`; `npm --version` | standalone system runtime | Pass | Node `v24.19.0`, npm `11.17.0`; Hermes private Node remains independently `v22.23.1`. |
| Inspect `web/`, version files, workflows, and request boundaries | synchronized `main` | Gap confirmed | No web app or Node runtime contract exists; three workflow entries pin `24.18.0`; Python browser APIs require their own exact origin. |
| Inspect pivot roadmap and legacy payload diagnostics | synchronized `main` | Gap confirmed | 2A is proposed; the retained replacement gate is repeatable 100/100/100/100, while the legacy shell still ships monolithic view CSS/JS. |
| `python3 -m unittest tests.test_request_boundary tests.test_ci_quality_gate tests.test_ci_workflow -v` | macOS x64, Python 3.13.14 | Pass | 39 tests passed; existing browser-origin, workflow, and package-gate contracts are green before implementation. |
| Confirm absent `web/package.json` and `.node-version` | synchronized `main` | Gap confirmed | No Node application, source version pin, npm dependency tree, or production build exists. |

### Test discussion and approval

- User questions and decisions: the user challenged the earlier Node-avoidance
  assumption, selected a full Node runtime, then rejected Node 22 compatibility
  in favor of one Node 24 requirement. Node 24.19.0 is the source/CI baseline.
- Accepted coverage gaps: this source-preview slice does not prove bundled
  native installers, an installed pipx Node runtime, non-Chromium rendering, or
  real state-changing BFF routes. Those remain explicit later 2A cutover work;
  no such capability is advertised here.
- Approved at: 2026-08-21, user message `confirm`.

## Implementation record

### Changes

- Added an exact Node 24 source contract (`.node-version`, package engine,
  package-manager pin, frozen lock, and every CI setup at 24.19.0) without
  changing Hermes' private Node 22 runtime.
- Added `web/` with Next.js 16.3.2 App Router, React 19.2.8, TypeScript 6.0.3,
  Tailwind CSS 4.3.3, semantic Emerald tokens, an accessible responsive
  foundation page, a local icon, and fixed security headers.
- Added a strict public Node Host/origin boundary, one fixed BFF health route,
  bounded private-response parsing, and one private Python bridge health
  capability with exact Host/port, loopback-client, duplicate-header,
  browser-header, body-framing, and constant-time token validation.
- Added the source preview supervisor with shell-free child commands, generated
  environment-only token, bridge-first readiness, sibling monitoring, bounded
  Node-first shutdown, and clear source-only failure codes.
- Added a validated production no-hydration transform for the noninteractive
  App Router prerender. The standalone root retains Tailwind output and one
  fixed 1.3 KB progressive-enhancement script for the same-origin bridge
  status; the build fails if any framework script or Flight payload remains.
- Added focused TypeScript/Python contracts, real sibling-death verification,
  a desktop/phone Chromium smoke, and a required Node-foundation CI job covering
  frozen install, checks, build, audit, all-path request probes, six locked
  Lighthouse audits, browser rendering, and process cleanup.
- Pinned the repeatable performance gate to Chrome for Testing 152.0.7923.0
  and Lighthouse 13.4.1. Each audit owns a fresh browser/profile, timeout and
  signal paths clean process trees, and CI retains a bounded failure summary.
- Updated the README, contributor guide, architecture contract, changelog, and
  pivot roadmap; 2A-A is active and 2A-B is the proposed Emerald Operations
  shell follow-up.

### Deviations and decisions

- TypeScript 7.0.2 and ESLint 10.9.0 were evaluated first, but Next 16.3.2's
  supported lint stack rejected those lines. The exact supported pair is
  TypeScript 6.0.3 and ESLint 9.39.5. The npm deprecation notice for ESLint 9 is
  accepted narrowly until the Next lint ecosystem supports ESLint 10; the
  dependency audit reports zero vulnerabilities.
- The initial TypeScript test runner used `tsx`, which opened an unnecessary
  IPC socket in this environment. Node 24's native type-stripping test support
  replaces it, removes that dependency, and keeps all tests shell-free.
- The first live BFF probe returned 503 because Node's server-side `fetch`
  includes `Sec-Fetch-Mode`; the private bridge now rejects the browser-origin
  signal `Sec-Fetch-Site` specifically while still accepting the intended Node
  caller. A focused regression covers both paths.
- The first rendered smoke found a favicon 404. A local SVG App Router icon was
  added, after which desktop and phone browser runs were console-clean.
- The first standard simulated-mobile Lighthouse diagnostic scored
  97/100/100/100: App Router hydration transferred about 149 KB, left about
  54 KB estimated unused JavaScript, produced 128 ms TBT, and delayed LCP to
  2.21 s despite the page having no interactive React state. Server-rendering
  bridge health alone did not remove the framework runtime. The final build
  therefore retains the App Router/Tailwind prerender but validates a narrowly
  no-hydration foundation shell with one post-paint status script. Final
  transfer is 8,905 bytes with no estimated unused JavaScript.
- The real lifecycle verifier initially expected Node's executable path in the
  process title; the standalone server identifies itself as `next-server` on
  macOS. Matching that exact direct-child title fixed the verifier, and both
  child-death cases then passed.
- Chromium 152 reports an unfocused headless tab as hidden, which suspends
  `requestAnimationFrame` and deterministically stalled the legacy compact-nav
  tooltip smoke after a synthetic scroll. The browser harness now uses CDP's
  focused-and-active page emulation before navigation. A disposable diagnostic
  proved `document.visibilityState` changed from `hidden` to `visible`; the
  unchanged legacy product then passed its complete browser matrix.
- The first CI Lighthouse implementation called the module six times in one
  Node process. Its second desktop audit reproducibly stalled first paint for
  about 8.2 seconds even though independent runs were fast. The gate now invokes
  the exact locked CLI in a separate process and fresh browser profile for each
  audit; the resulting three desktop and three mobile runs all scored
  100/100/100/100.
- Adversarial review found that malformed `Sec-Fetch-Site` values could evade
  the first allowlist. The boundary now accepts only absent, `none`, or
  `same-origin`; unknown and comma-combined values fail closed in unit and live
  CI probes.
- The first executable gate selected whichever local Chrome happened to be
  installed. The final gate requires an explicit absolute path, verifies exact
  Chrome for Testing 152.0.7923.0, and CI downloads that non-auto-updating
  version with the exact locked `@puppeteer/browsers` dependency.
- Lighthouse timeout, launch-failure, ordinary-failure, SIGINT, and SIGTERM
  paths now withdraw the CLI process tree, owned Chrome, profile, and raw
  reports. A direct SIGTERM drill exited 143, left no process or report
  directory, and wrote the expected bounded owner-private failure summary.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `npm --prefix web ci --ignore-scripts` | Node 24.19.0, npm 11.17.0 | 0 | 463 packages installed from lock | Lifecycle scripts disabled; exact lock accepted, including Lighthouse 13.4.1. |
| `npm --prefix web audit --audit-level=high` | registry advisory endpoint | 0 | 0 vulnerabilities | Initial sandboxed attempt was network-blocked; host rerun reached the official registry endpoint. |
| `npm --prefix web run check` | exact frozen dependency tree | 0 | ESLint pass; TypeScript pass; 9/9 tests | Covers Host/origin decisions, fixed bridge configuration/request, bounded response, redaction, malformed fetch-site rejection, and timeout process-tree cleanup. |
| `npm --prefix web run build` | Next.js 16.3.2 production standalone | 0 | 4 routes generated | No telemetry output; standalone preparation validates exactly one status script and no hydration/Flight payload. |
| Focused Python bridge, supervisor, Node-contract, CI, request-boundary, architecture, and README suites | Python 3.13.14 | 0 | 65 passed; final review subset 30/30 | An initial sandboxed run denied six ephemeral binds; host-permitted reruns passed, including the final pin, workflow, bridge, and supervisor contracts. |
| Live production HTTP probes | supervised standalone preview | 0 | Valid page/BFF 200; forged Host, cross-site, unknown, and comma-combined fetch-site values 403; forged Host on static/image/favicon paths 403; direct tokenless bridge 403 | The boundary covers every public path and the BFF returned only five fixed health fields plus security/no-store headers. |
| `python3 scripts/verify_web_preview_lifecycle.py` | real POSIX child processes | 0 | 2/2 cases | Killing the bridge removed Node; killing Node removed the bridge; gateway health disappeared in both cases. |
| Build plus `scripts/verify_python_artifacts.py` | clean-room hash-locked CI environment | 0 | wheel and sdist verified | The new bridge module appears in both exact package inventories; no preview cutover artifacts are added to the installed product. |
| Installed wheel lifecycle through disposable pipx | clean-room package root, port 8894 | 0 | version/setup/doctor/start/health/stop all passed | Seed data was created, health became reachable, and the listener disappeared after stop. |
| Python dependency audits and tracked-file secret scan | clean-room candidate | 0 | 2 audits with 0 known vulnerabilities; 0 new secret candidates | Runtime/native locks were audited strictly; intended untracked files were included in a disposable Git index for the scan. |
| Existing `scripts/browser_smoke.mjs` | Chromium 152, clean-room legacy server | 0 | complete interaction matrix passed | Official CDP focus emulation prevents hidden-headless-tab animation-frame suspension; product HTML/CSS/JS remained unchanged. |
| `npm --prefix web run lighthouse:gate` | locked Lighthouse 13.4.1, Chrome for Testing 152.0.7923.0, production standalone | 0 | 6/6 at 100/100/100/100 | Required CI runs three isolated desktop/provided plus three isolated standard simulated-mobile audits at 390×844 and fails unless every category equals 100. Compact evidence: `reviews/2026-08-21-node-runtime-foundation-lighthouse.json`. |
| Forced timeout plus direct SIGTERM drills | spawned descendant and active desktop audit | 0 | all owned processes/profiles/reports removed | Timeout killed both test PIDs; SIGTERM exited 143 and produced a bounded 0600 summary naming the active run. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | live dirty workspace | 1 | 1302 passed, 2 failed, 4 skipped | One stale README assertion belonged to this slice and was corrected. The other failure read the user's unrelated modified `data/projects.json`; those changes were preserved and excluded. |
| Same command in a clean `git archive` candidate with only the approved slice overlaid | disposable `/private/tmp` checkout, Python 3.13.14 | 0 | 1304 passed, 4 skipped | Post-review candidate passed in 238.634 seconds; the final exact candidate including signal evidence and this review record passed again in 223.695 seconds without modifying or including user-owned JSON/design/runtime work. |

### Rendered or manual behavior

- Automated Chromium held `/api/bridge/health` before releasing it. At
  1440×1000, both cards remained 532×214 px; at 390×844, both remained
  362×204 px. The checking-to-ready geometry delta was exactly 0 px, horizontal
  overflow was 0 px, and the mobile cards stacked while desktop cards remained
  aligned.
- The page had one named main landmark, one H1, a named Runtime readiness
  region, polite/atomic live status, one visible 2 px keyboard focus outline,
  no Flight payload, and exactly one browser script (`foundation-status.js`).
- Chromium reported no console or uncaught runtime errors. Desktop and phone
  screenshots were visually inspected from temporary, untracked output; the
  Emerald hierarchy, text wrapping, spacing, cards, and below-fold phone flow
  were coherent.
- The existing Python dashboard passed its full legacy Chromium smoke after
  the focused-page harness correction, including six views across seven
  widths, keyboard/drawer behavior, tasks, calendar, agents, settings,
  diagnostics, and the compact navigation tooltip.
- Final recorded Lighthouse results with pinned Chrome for Testing 152.0.7923.0:

| Mode/run | Performance | Accessibility | Best Practices | SEO | FCP | LCP | TBT | CLS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Desktop 1 | 100 | 100 | 100 | 100 | 238 ms | 238 ms | 0 ms | 0 |
| Desktop 2 | 100 | 100 | 100 | 100 | 236 ms | 236 ms | 0 ms | 0 |
| Desktop 3 | 100 | 100 | 100 | 100 | 239 ms | 239 ms | 0 ms | 0 |
| Mobile 1 | 100 | 100 | 100 | 100 | 758 ms | 1,298 ms | 0 ms | 0 |
| Mobile 2 | 100 | 100 | 100 | 100 | 760 ms | 1,261 ms | 0 ms | 0 |
| Mobile 3 | 100 | 100 | 100 | 100 | 984 ms | 1,270 ms | 0 ms | 0 |

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: uncommitted candidate on
  `feature/2a-a-node-runtime-foundation` against `origin/main`
  `5193993d20226774f2a45d1de239d75d868f67d7`; user-owned JSON/design/runtime
  files were explicitly excluded.
- Verification evidence: frozen npm install/check/build/audit; 65 focused
  Python tests; clean-room 1,304-test suite; package/pipx/audit/secret gates;
  live request probes; both sibling-death cases; legacy and foundation browser
  smokes; and the first six-run Lighthouse evidence.
- Rendered artifacts: inspected desktop 1440×1000 and phone 390×844
  screenshots plus geometry, accessibility, console, script, and Flight
  assertions.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | High | Yes | `web/package.json` exposed `npm start`, and the generated server bound `0.0.0.0` without the supervisor's `HOSTNAME`. | Yes | Remove the unsupported direct production start entry and test its absence. |
| A-2 | Medium | Yes | `web/src/proxy.ts` excluded static/image/favicon paths; a forged Host retrieved an existing static chunk with 200 while `/` returned 403. | Yes | Apply the boundary to every public path and probe excluded-prefix regressions. |
| A-3 | Low | No | WHATWG IPv6 hostnames retain brackets, while bridge and smoke allowlists compared only unbracketed `::1`. | Yes | Normalize IPv6 brackets consistently and add coverage. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | High | Yes | Independently identified the same unsafe `npm start` all-interface bind. | Yes | Remove or safely wrap the shortcut and add a regression. |
| B-2 | Medium | No | README assigned port 8890 to both the normal-dashboard fallback and Node preview. | Yes | Give the legacy fallback a distinct documented port. |
| B-3 | Medium | No | Required CI did not execute the six-run Lighthouse gate; compact evidence lacked a repository command. | Yes | Lock Lighthouse, add an executable exact gate to required CI, and retain its compact results. |
| B-4 | Low | No | The Node parser accepted `v24.19.0-rc.1` as satisfying the stable minimum. | Yes | Reject prerelease suffixes while allowing build metadata; test it. |
| B-5 | Low | No | The log claimed real Windows lifecycle coverage although the sibling-death job runs only on Ubuntu. | Yes | Correct the limitation or add a real Windows lifecycle job. |

### Round 2 findings

| Reviewer/ID | Severity | Blocking | Finding | Disposition |
| --- | --- | --- | --- | --- |
| A-4 | Medium | Yes | Unknown or malformed `Sec-Fetch-Site` values were accepted. | Closed: allowlist only absent, `none`, and `same-origin`; unit and live CI probes cover bogus and comma-combined values. |
| A-5 | Medium | No | A timed-out synchronous Lighthouse CLI could orphan detached Chrome. | Closed: async process-tree supervision, an owned browser per run, `finally` cleanup, and a forced descendant-timeout test. |
| B-6 | Medium | Yes | The Lighthouse browser executable/version was neither required nor pinned. | Closed: explicit absolute `CHROME_PATH`, exact version probe, source pin 152.0.7923.0, and exact CI Chrome for Testing download. |
| B-7 | Low | No | Failed CI audits deleted raw evidence and retained only console tail text. | Closed: bounded 0600 failure summaries retain active/completed runs and are uploaded by required CI. |

### Final cleanup review

- Reviewer A verified the request-boundary and timeout findings closed, then
  identified launch-rejection and signal cleanup gaps. The final gate now calls
  `killAll()` on launch rejection, tracks active CLI/report resources, cleans on
  SIGINT/SIGTERM/exit, and writes failure evidence before signal cleanup.
- Reviewer B verified the exact Chrome for Testing pin/version probe and
  bounded uploaded diagnostics, then returned **No findings**.
- A direct SIGTERM drill and final source inspection closed Reviewer A's last
  low-severity signal-summary note. After this log update, Reviewer A returned
  **No findings**.

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Unsafe direct production start | Corroborated by A-1/B-1 | Closed by both reviewers | Accepted; only the supervisor may launch production preview topology. | Removed `start` from package scripts and added a source/lock contract assertion. |
| Static paths bypassed Host validation | Unique A-2 | Closed by Reviewer A | Accepted; the documented gateway boundary applies to every public path. | Matcher is now `/:path*`; live and CI forged-Host probes cover static, image, and favicon prefixes. |
| IPv6 bracket mismatch | Unique A-3 | Closed by Reviewer A | Accepted. | Normalized URL hostnames in bridge configuration and web smoke; added an IPv6 bridge-config test. |
| Port 8890 documentation collision | Unique B-2 | Closed by Reviewer B | Accepted. | Moved the normal-dashboard fallback example to 8889; preview remains 8890. |
| Lighthouse was manual-only | Unique B-3 | Closed by Reviewer B | Accepted because exact 100s are a durable replacement gate. | Locked Lighthouse 13.4.1, added a six-run fail-closed script and required CI invocation, and documented the contributor command. |
| Prerelease Node passed stable gate | Unique B-4 | Closed by Reviewer B | Accepted. | Version regex now rejects prerelease suffixes and tests `v24.19.0-rc.1`. |
| Windows evidence overstated | Unique B-5 | Closed by Reviewer B | Accepted as a documentation correction; real Windows process-tree evidence remains outside this source-foundation publication gate. | Log now distinguishes mocked Windows CI cleanup from POSIX-only real sibling-death verification. |
| Malformed fetch-site values | Unique A-4 | Closed by Reviewer A | Accepted as a fail-closed boundary requirement. | Exact safe-value allowlist plus unit/live CI regressions. |
| Timeout/launch/signal process cleanup | Unique A-5 and final A follow-ups | Closed by Reviewer A | Accepted; test infrastructure must not strand browser processes or suppress signal diagnostics. | Async process-tree runner, owned Chrome, launch-rejection cleanup, signal handlers, forced-timeout and SIGTERM drills. |
| Unpinned audit browser | Unique B-6 | Closed by Reviewer B | Accepted; repeatability requires both audit and browser versions. | Chrome for Testing 152.0.7923.0 source/CI pin and runtime version verification. |
| Failed-audit evidence discarded | Unique B-7 | Closed by Reviewer B | Accepted while keeping artifacts bounded. | 0600 JSON summary and pinned conditional CI upload; raw reports remain temporary. |

### Reverification

- Focused tests: final npm check passed 9/9; final relevant Python/CI subset
  passed 30/30; the broader focused set passed 65/65.
- Full suite: the final exact clean candidate passed 1,304 tests with 4 expected
  skips in 223.695 seconds after the signal-summary and log overlay.
- Next review round or gate result: both independent reviewers returned **No
  findings**. Reviewer A's signal-summary and documentation notes are closed by
  the direct SIGTERM drill and this completed record.

## Documentation updates

- Roadmap: 2A is split into active 2A-A Node Runtime Foundation and proposed
  2A-B Emerald Operations shell; later dependencies now point through 2A-B.
- Changelog: records the runtime foundation, no-hydration performance decision,
  exact repeated Lighthouse outcome, and retained Python authority.
- Architecture/operator docs: README documents optional preparation and one
  launch command; CONTRIBUTING records Node/web verification; ARCHITECTURE
  defines the public gateway, private bridge, token, request, transform, and
  lifecycle boundaries.
- Project/session notes: this persistent review log.
- Documentation verification: focused architecture/roadmap/README contracts
  pass; the clean-room full suite passed all 1,304 tests.

## Publication gate

- Proposed files:
  - Runtime/toolchain: `.chrome-for-testing-version`, `.node-version`,
    `.gitignore`, `mentat/local_bridge.py`, `scripts/mentat_web_preview.py`,
    `scripts/verify_web_preview_lifecycle.py`, and
    `scripts/web_foundation_smoke.mjs`.
  - Web foundation: `web/eslint.config.mjs`, `web/next-env.d.ts`,
    `web/next.config.ts`, `web/package-lock.json`, `web/package.json`,
    `web/postcss.config.mjs`, `web/public/foundation-status.js`,
    `web/scripts/lighthouse-gate.mjs`,
    `web/scripts/lighthouse-process.mjs`,
    `web/scripts/prepare-standalone.mjs`, `web/scripts/run-next.mjs`,
    `web/src/app/api/bridge/health/route.ts`,
    `web/src/app/bridge-status.tsx`, `web/src/app/globals.css`,
    `web/src/app/icon.svg`, `web/src/app/layout.tsx`,
    `web/src/app/page.tsx`, `web/src/lib/bridge-health.ts`,
    `web/src/lib/request-boundary.ts`, `web/src/proxy.ts`,
    `web/tests/bridge-health.test.ts`,
    `web/tests/lighthouse-process.test.ts`,
    `web/tests/request-boundary.test.ts`, and `web/tsconfig.json`.
  - CI/tests: `.github/workflows/ci.yml`,
    `.github/workflows/quality-gates.yml`, `scripts/browser_smoke.mjs`,
    `tests/test_agent_runtime_architecture.py`,
    `tests/test_ci_quality_gate.py`, `tests/test_ci_workflow.py`,
    `tests/test_mentat_local_bridge.py`, `tests/test_mentat_web_preview.py`,
    `tests/test_next_phase_readiness.py`, and
    `tests/test_node_runtime_foundation.py`.
  - Documentation/evidence: `ARCHITECTURE.md`, `CHANGELOG.md`,
    `CONTRIBUTING.md`, `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`, `README.md`,
    `reviews/2026-08-21-node-runtime-foundation.md`, and
    `reviews/2026-08-21-node-runtime-foundation-lighthouse.json`.
- Explicitly excluded user-owned work: `data/projects.json`, `data/tasks.json`,
  `design/emerald-operations/`, `design/mockups/`, `tmp/`, `uv.lock`, `videos/`,
  and every generated Node/browser/build artifact.
- Branch and base: `feature/2a-a-node-runtime-foundation` into `main`.
- Commit message: `Add the Node 24 runtime foundation`.
- PR title: `Add the Node 24 runtime foundation`.
- PR summary: add the opt-in supervised Next.js/Python bridge topology; enforce
  loopback and fail-closed request/process boundaries; lock Node, npm,
  Lighthouse, and Chrome for Testing; establish repeatable 100-point desktop
  and mobile replacement-shell gates without cutting over the installed Python
  product or moving data authority.
- Unresolved risks: this is source-preview-only and Node is not bundled into
  installers; real child-death integration is POSIX-only while Windows cleanup
  remains mocked; rendered evidence is Chromium-family only; synthetic local
  Lighthouse is not field telemetry; no real product route has migrated yet.
- User authorization and scope: implementation approved; publication not yet
  authorized for this final exact file set.
- Commit hash: Pending.
- Ready PR URL: Pending.

## Outcome review

- Classification: implementation complete and locally verified; ready for
  publication approval.
- Acceptance criteria summary: AC-1 through AC-8 are met.
- Potential bugs or untested paths: real Windows process-tree behavior,
  non-Chromium rendering, installer-bundled Node, field performance, and
  state-changing/migrated BFF routes remain outside this slice.
- Remaining reviewer dissent: none; all blocking and non-blocking findings were
  remediated and independently re-reviewed.
- Compatibility/migration/rollback concerns: no migration or default-runtime
  cutover is planned.
- User decision: final publication approval pending.
- Next slice authorized: No
