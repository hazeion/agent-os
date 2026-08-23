# Feature Slice Review: Runtime coexistence view

Status: Approved for publication

Slice: `3b-runtime-coexistence-view`

Date: `2026-08-22`

## Slice contract

### Goal

Prove that Hermes and Codex Runs can be active together, remain clearly
visible, and use the same exact runtime-neutral controls without crossing
Agent, Task, Run, event, or runtime identities.

### In scope

- Load canonical Agents and Runs together on `/runs` and join them only when
  both Mentat Agent ID and runtime type match.
- Show the Agent name, runtime, canonical Run status, Task ID, and Mentat Run
  ID on each card, with safe ID fallbacks when Agent data is missing or stale.
- Keep timeline, message, response, and preview-confirm Stop controls bound to
  each exact Mentat Run.
- Reject a runtime status readback after message or response when its Run,
  Task, Agent, or runtime identity does not match the selected canonical Run.
- Add a deterministic non-billable integration proof using strict fake Hermes
  and Codex adapters that enter submission concurrently and remain isolated
  through events, message, and Stop.
- Keep active Runs visible ahead of terminal history in the bounded Runs
  workspace projection.

### Out of scope

- Starting or dispatching work from the Next.js interface.
- Creating or assigning Agents or Tasks.
- Dynamic routing, runtime pickers, provider/model setup, sign-in, or
  credentials.
- New bridge routes, generic Python forwarding, readiness polling, or live
  billable runtime tasks.
- Agent Registry database convergence; that remains Slice 3C.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Two fake runtime submissions enter concurrently and produce exact canonical Hermes and Codex Runs. | Isolated Python integration test | Pass |
| AC-2 | Reconciliation, events, message, and Stop stay attached to the selected Agent, Task, Run, and runtime. | Integration and control tests | Pass |
| AC-3 | `/runs` shows `Hermes Researcher — Running` and `Codex Engineer — Running` from exact canonical joins. | Production browser smoke | Pass |
| AC-4 | Missing or mismatched Agent data never relabels or hides a controllable Run. | Browser and static contract tests | Pass |
| AC-5 | Browser data remains bounded and excludes runtime references, credentials, raw adapter payloads, and legacy heartbeat authority. | Existing bridge contracts plus smoke assertions | Pass |
| AC-6 | Desktop and mobile Lighthouse remain 100/100/100/100. | Six-run Lighthouse gate | Pass |

### Constraints and recovery

- Canonical Run status and runtime type come only from `mentat.sqlite3`.
- Canonical Agent names come only from the Mentat Agent Registry. Never join
  against legacy `data/agents.json` observations.
- Agent data is optional for display. A failed or malformed Agent read must
  leave safe Run IDs and all valid Run controls available.
- The page remains static-first and fetches after first paint without polling
  or a React hydration dependency.
- Revert removes the display join, active-first workspace ordering, shared
  readback check, and tests. No durable data migration occurs.

### Scope and test approval

- Two independent pre-implementation audits agreed that the runtime router,
  bridge, and controls already provide the needed structural boundary. The
  missing work is an honest coexistence view and an integrated isolation proof.
- Standing pivot authorization approves this scope, test strategy,
  publication, merge, and continuation as an explicit exception to repeated
  approval prompts.

## Test strategy

| Acceptance criterion | Planned evidence | What it proves | Limitation |
| --- | --- | --- | --- |
| AC-1/2 | Two strict fake adapters, a submission barrier, canonical repositories, reconciliation, and exact message/Stop controls. | Real Mentat orchestration allows independent runtimes without a paid task. | Does not call external runtimes. |
| AC-3/4 | Production browser fixture with two Agents, two active Runs, mismatched Agent data, and exact action URL checks. | Users can distinguish and control both runtimes safely. | Browser fixture is deterministic rather than live-provider data. |
| AC-5 | Existing Python/Node bridge validation and private-field assertions. | No broader bridge or browser authority was introduced. | The display still depends on JavaScript after first paint. |
| AC-6 | Three desktop and three mobile Lighthouse audits. | Performance, accessibility, best-practices, and SEO gates remain perfect. | Local timing varies; category scores are the contract. |

## Implementation record

- Added an active-first, bounded 50-Run repository projection.
- Loaded Runs and canonical Agents together and joined names only on the exact
  Agent ID plus runtime type. Run IDs remain visible as the safe fallback.
- Kept runtime and status labels on the canonical Run card and made Stop copy
  runtime-neutral.
- Labelled every Run article by its Agent heading and gave repeated controls
  unique Agent-and-Run accessible names.
- Added one shared post-control identity check for message and response
  readback.
- Added deterministic Python and browser coexistence proofs without calling a
  paid or external runtime.

## Verification

### Toolchain and static web checks

```sh
/usr/local/bin/node --version
/usr/local/bin/node --check web/public/shell-runtime.js
/usr/local/bin/node --check scripts/web_foundation_smoke.mjs
/usr/local/bin/node /usr/local/lib/nodejs/node-v24.19.0-darwin-x64/lib/node_modules/npm/bin/npm-cli.js --prefix web run check
git diff --check
.venv/bin/python scripts/check_tracked_secrets.py
```

Result: every command exited `0`; Node reported `v24.19.0`; lint, typecheck,
all 39 Node tests, and the tracked-file secret scan passed. Static evidence
lives in `web/tests/shell-contract.test.ts`.

### Python boundary and coexistence checks

```sh
.venv/bin/python -W error::ResourceWarning -m unittest tests.test_runtime_coexistence tests.test_run_repository tests.test_run_stop_control tests.test_run_response_control tests.test_mentat_local_bridge tests.test_mentat_web_preview -v
```

Result: exit `0`; all 109 tests passed with `ResourceWarning` promoted to an
error. The deterministic two-adapter artifact is
`tests/test_runtime_coexistence.py`.

### Production build

```sh
env PATH=/usr/local/bin:/usr/bin:/bin /usr/local/bin/node /usr/local/lib/nodejs/node-v24.19.0-darwin-x64/lib/node_modules/npm/bin/npm-cli.js --prefix web run build
```

Result: exit `1` locally because the macOS execution sandbox denied
Turbopack's internal CSS worker loopback bind with `EPERM`. The same retry with
host permission produced the same environmental error. CI is the authoritative
Turbopack build.

```sh
env PATH=/usr/local/bin:/usr/bin:/bin /usr/local/bin/node web/scripts/run-next.mjs build --webpack
env PATH=/usr/local/bin:/usr/bin:/bin /usr/local/bin/node web/scripts/prepare-standalone.mjs
```

Result: both commands exited `0`; all four static routes and fixed API routes
were emitted and the no-hydration standalone contract passed.

### Production browser matrix

```sh
env PATH=/usr/local/bin:/usr/bin:/bin MENTAT_DATA_DIR="$PWD/data" .venv/bin/python scripts/mentat_web_preview.py --port 8896
env PATH=/usr/local/bin:/usr/bin:/bin CHROME_PATH=/Applications/Chromium.app/Contents/MacOS/Chromium MENTAT_WEB_BASE_URL=http://127.0.0.1:8896 MENTAT_WEB_BROWSER_DEBUG_PORT=9336 MENTAT_WEB_BROWSER_RUNTIME_DIR=/private/tmp/mentat-3b/web-foundation-smoke-runtime /usr/local/bin/node scripts/web_foundation_smoke.mjs
```

Result: browser smoke exited `0` with no console errors or horizontal overflow.
It rendered the current local 15 Tasks and active-first 50 Runs. Its deterministic
fixture verified unique accessible control names, both runtime timelines,
Hermes message confirmation, Codex approval response, Codex confirmed Stop,
exact action paths and bodies, and three safe Agent-data fallbacks. The
executable evidence is `scripts/web_foundation_smoke.mjs`. The preview exited
`0` after Ctrl+C stopped both child processes.

### Lighthouse replacement gate

```sh
env PATH=/usr/local/bin:/usr/bin:/bin CHROME_PATH=/Applications/Chromium.app/Contents/MacOS/Chromium MENTAT_WEB_BASE_URL=http://127.0.0.1:8896 MENTAT_LIGHTHOUSE_FAILURE_PATH=/private/tmp/mentat-3b/mentat-lighthouse-failure.json /usr/local/bin/node web/scripts/lighthouse-gate.mjs
```

Result: exit `0`; Lighthouse 13.4.1 with Chrome 152.0.7923.0 produced
100/100/100/100 on all three desktop and three mobile audits. Desktop LCP was
218–258 ms; mobile LCP was 1.12–1.37 s; TBT was `0`; effective CLS was `0`;
transfer was 44,862 bytes. No failure artifact was emitted because the gate
passed.

### Shutdown check

```sh
./status.sh
lsof -nP -iTCP:8896 -sTCP:LISTEN
lsof -nP -iTCP:52747 -sTCP:LISTEN
```

Result: `status.sh` exited `0` with no managed listeners; both `lsof` commands
exited `1` with no matching listener.

## Adversarial review

- Correctness/security reviewer: **Approve**, no actionable findings.
- Product/compatibility/performance first pass: **Request changes** for complete
  two-runtime browser action coverage, distinct accessible control names, and
  exact reproducible verification evidence. All three findings are addressed;
  a fresh independent final reviewer returned **Approve** with no remaining
  actionable findings.

## Documentation updates

Updated the implementation roadmap, architecture contract, changelog, and this
slice record.

## Publication gate

Standing authorization is recorded. Tests, Lighthouse, and both independent
reviewers passed. The slice is approved for commit and PR publication; GitHub
CI remains required before merge.

## Outcome review

Pending.
