# Feature Slice Review: Hermes 0.20.1 Live Validation and Rollout

Status: Successful
Slice: `hermes-020-live-validation`
Date: `2026-08-14`
Review log: `reviews/2026-08-14-hermes-020-live-validation.md`

## Slice contract

### Goal

Qualify stock Hermes v0.20.1 as Mentat's maintained local webhook baseline by
proving signed CLI and Gateway lifecycle delivery, failure recovery, privacy,
safe mode, and rollback against the real loopback receiver.

### In scope

- Run stock upstream Hermes tag `v2026.8.13` (Hermes v0.20.1) from an isolated
  test installation and isolated Hermes home/profile.
- Exercise real CLI and Gateway lifecycle hooks where the stock runtime exposes
  them, covering all four allowlisted events across live and exact stock-hook
  evidence.
- Complete the rollout hardening explicitly deferred by the receiver foundation:
  owner-only SQLite replay retention with bounded 24-hour cleanup and a
  per-binding bounded rate limiter.
- Validate exact-body HMAC signatures, clock skew, duplicate retry, restart,
  dropped delivery, event storms, out-of-order end/start, reconciliation, safe
  mode, disabled binding, and rollback.
- Add a reproducible redacted live-verification harness or fixtures that never
  print or persist the shared secret, signatures, delivery/session identifiers,
  payload bodies, prompts, tool input, or local paths in tracked evidence.
- Preserve Hermes 0.19 and unconfigured behavior, and update the maintained
  baseline only after every required gate passes.
- Run focused tests, the full suite, browser/computer-use checks, Lighthouse
  100/100/100/100, two independent adversarial reviewers, packaging/CI, and a
  ready stacked PR.

### Out of scope

- New webhook event types, tool/LLM payloads, or payload-derived authority.
- Mentat-written Hermes configuration, credentials, profile content, or target
  registration.
- Public/non-loopback ingress, tunnels, relays, remote webhook delivery, or
  browser push/polling retirement.
- Kanban mutation changes, steer expansion, attachment steering, and the 9G
  A2A/citation/artifact/voice product decisions.
- Modifying or merging the user's custom Hermes fork; stock validation uses an
  isolated upstream release checkout.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Stock Hermes v0.20.1 sends signed raw bodies that Mentat accepts for the four allowlisted lifecycle events through real CLI/Gateway paths where available. | Redacted live harness transcript, exact stock source/fixture provenance, receiver health counters. | Pass |
| AC-2 | Valid retries are idempotent across concurrent requests and a Mentat process restart; replay state expires through bounded 24-hour cleanup in owner-only private SQLite. | Migration/store unit tests, concurrent HTTP test, restart integration test, file-mode checks. | Pass |
| AC-3 | Per-binding storms are bounded and rate limited; dropped and out-of-order hints cannot create false terminal state and converge through authoritative reconciliation. | Token-bucket tests, 1,000-event stress test, dropped/out-of-order/reconciliation tests. | Pass |
| AC-4 | Clock skew, malformed signatures, safe mode, disabled binding, and unconfigured/0.19 runtimes fail closed and remain quiet. | Negative contract tests plus stock safe-mode/disabled and isolated 0.19 fallback runs. | Pass |
| AC-5 | No payload-private value reaches tracked files, request/error logs, SQLite values exposed to users, health APIs, diagnostics, or rendered UI. | Canary scan of live artifacts/logs/database/API/DOM; tracked-secret scan; browser contracts. | Pass |
| AC-6 | Rollback works by disabling the Mentat binding, removing the operator-managed Hermes target in the isolated fixture, and restarting while polling/reconciliation remains available. | Isolated rollback transcript and post-rollback health/read-path checks. | Pass |
| AC-7 | Maintained runtime documentation changes from Hermes 0.19.0 to stock 0.20.1 only after AC-1 through AC-6 pass, with capability-gated fallback retained. | Documentation diff and contract tests. | Pass |
| AC-8 | Focused/full tests, package checks, computer-use, Lighthouse 100/100/100/100, two-reviewer adversarial review, ready PR, and CI all pass. | Recorded commands, artifacts, reviews, PR checks. | Pass |

### Constraints and recovery

- Safety: webhooks remain untrusted wakeups; authoritative adapters prove state.
  Secrets and raw/private event fields stay outside browser and tracked storage.
- Compatibility: additive private-schema migration; Hermes 0.19, absent, partial,
  and unconfigured installations continue to fail closed without noisy errors.
- Rendered behavior: existing Webhook Health states and sanitized setup text stay
  stable; computer-use must show no private fields or regressions.
- Rollback or recovery: disable/unset the binding and remove the isolated Hermes
  target; old dedupe rows expire and existing polling/reconciliation continues.
- Documentation targets: this log, `MILESTONE_9_WEBHOOK_IMPLEMENTATION_PLAN.md`,
  `ARCHITECTURE.md`, `REMOTE_HERMES.md`, and `CHANGELOG.md` only where evidence
  makes an existing maintained-baseline statement inaccurate.
- Version-control strategy: branch `codex/hermes-020-live-validation`, stacked on
  `codex/hermes-active-run-steer`; ready PR targets that 9E branch.

### Scope discussion and approval

- Recommendation and rationale: treat 9F as a qualification gate plus the two
  missing rollout hardening requirements (durable replay and rate limiting).
  Promoting 0.20.1 while either remains absent would contradict the established
  Milestone 9 contract and make restart/storm evidence misleading.
- Alternatives considered: validate only the current process-local receiver
  (rejected because it cannot pass restart-safe replay or rate-limit gates);
  update the custom Hermes fork in place (rejected because the product goal is
  stock-Hermes portability and the fork has unique commits); validate upstream
  `main` (rejected in favor of the immutable v0.20.1 release tag).
- User decisions: standing approval applies to in-scope feature, test, review,
  and publication choices. Per the reviewed-feature skill, this is recorded as
  an explicit process exception; destructive actions and scope expansion still
  require a separate decision.
- Approved at: `2026-08-14`, under the user's standing approval instruction.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Installed Hermes is v0.19.0 and no tracked live 0.20 evidence exists. | Isolated stock v0.20.1 CLI/Gateway runs against the real Mentat route; freeze only sanitized provenance/results. | Real stock serialization, headers, signature, and receiver compatibility. | Provider-free paths may not naturally emit every subagent event; exact stock dispatcher evidence supplements only unavailable live paths. |
| AC-2 | `WebhookDeliveryCache` is process-local. | Private DB migration/store tests, same-process concurrent duplicate HTTP, fresh-process replay HTTP, expiry cleanup bounds. | Restart-safe idempotency and owner-only retention. | Does not protect against deliberate local DB deletion, which rollback permits. |
| AC-3 | Coordinator is bounded but receiver has no token bucket. | Deterministic limiter unit tests, 1,000-event stress, queue-drop reconciliation, out-of-order projection assertions. | Storm memory/read bounds and eventual authoritative convergence. | Timing tests use an injected monotonic clock; live storm confirms integration only. |
| AC-4 | Pure skew/malformed tests exist; stock safe mode has not been run. | Boundary tests plus isolated `HERMES_SAFE_MODE=1`, no-target, disabled-secret, and v0.19 compatibility runs. | Fail-closed compatibility and no unexpected delivery. | 0.19 does not contain outbound hooks and is checked for quiet fallback only. |
| AC-5 | Static/privacy tests exist but no live canary corpus exists. | Unique canaries in ignored temp roots; scan stdout/stderr, private DB, public APIs/diagnostics, DOM, and tracked diff. | No live private payload leakage across observable surfaces. | Cannot prove absence from OS-level telemetry outside Mentat/Hermes test processes. |
| AC-6 | Rollback is documented but unexecuted. | Remove isolated target/unset binding, restart both sides, verify receiver off and read paths healthy. | Operational reversibility without data migration rollback. | Does not alter the operator's real Hermes home or fork. |
| AC-7 | Maintained docs still name 0.19.0. | Delay edits until live gates pass; run source/contract searches afterward. | Baseline claims match reproduced evidence. | External beta environments remain separately operator-managed. |
| AC-8 | 9F-specific verification absent. | Focused and full suites, browser smoke, computer-use, Lighthouse 13.4.1, package checks, dual review, CI. | Repository, rendered, accessibility, performance, packaging, and review gates. | Lighthouse uses the deterministic local fixture, not a paid model run. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `hermes --version` | macOS, installed git runtime | Fail | Reports Hermes v0.19.0 at fork commit `77614c6a`; insufficient for 9F. |
| Fetch official upstream tags and inspect `v2026.8.13` | Clean custom Hermes checkout | Pass | Immutable tag identifies Hermes v0.20.1; custom fork is 26 commits ahead and 5,309 behind upstream main, so it will not be modified. |
| Receiver/storage source inspection | Mentat 9E head | Fail | Replay cache is process-local and no per-binding rate limiter exists. |
| Existing coordinator/health tests | Mentat 9E head | Partial | Bounded coalescing/reconciliation and privacy contracts exist; no stock live evidence. |
| Stock v0.20.1 source and command audit | Isolated checkout at `f80f453ae0679347e38abc917c7f94f717bf96c5` | Pass | Confirmed exact config, raw-body HMAC wire shape, two-attempt retry behavior, 256-item sender queue, safe-mode suppression, CLI/Gateway registration, and that `hermes hooks test` covers shell hooks only. |

### Test discussion and approval

- User questions and decisions: the user requested stock-Hermes migration,
  complete Milestone 9 verification, perfect Lighthouse scores, computer-use,
  adversarial review, and standing approval. The strategy directly maps those
  requirements and preserves the user's real Hermes home/fork.
- Accepted coverage gaps: no paid-provider call is required. If a stock
  lifecycle path cannot be triggered without credentials, the live CLI/Gateway
  boundary is combined with exact stock dispatcher/fixture evidence and the gap
  remains explicit rather than simulated as a live event.
- Approved at: `2026-08-14`, under the recorded standing approval exception.

## Implementation record

### Changes

- Added private database migration 3 with keyed, 24-hour Hermes delivery
  retention and an expiry index.
- Replaced process-local replay caching with an atomic SQLite claim/release
  boundary and bounded cleanup.
- Added a per-binding token bucket (120-event burst, two events/second refill)
  before SQLite and refresh admission. Rate-limited deliveries receive the
  documented best-effort 429 and converge through reconciliation; queue-
  rejected deliveries receive 503 and their transactional claim rolls back so
  Hermes's supported retry is not mistaken for a duplicate.
- Corrected lifecycle normalization for the stock v0.20.1 wire shape, where
  `completed`, `interrupted`, and `platform` are nested under `extra`; legacy
  top-level values remain compatible.
- Added migration, concurrency, restart, expiry, owner-only permissions,
  rate-limit, storage-failure, and stock-payload tests.
- Serialized private-database setup for concurrent webhook receiver threads
  after the isolated full suite exposed a WAL-initialization race.
- Added a redacted, reproducible stock-runtime harness covering exact dispatcher
  events, real CLI and Gateway turns, retry/restart, rollback, safe mode,
  privacy canaries, authoritative reconciliation, and a 1,000-request storm.
- Extended the harness after round-one review to scan captured process output,
  Gateway/Mentat logs, private data, public health/diagnostics payloads, and the
  tracked diff; rollback now proves session/agent reads and the existing Home
  delegation refresh fallback, and the storm uses 32 concurrent clients.

### Deviations and decisions

- `hermes hooks test <event>` cannot prove outbound delivery because stock
  Hermes routes that command only through the shell-hook runner. The live
  harness therefore uses registered plugin callbacks and real CLI/Gateway
  startup registration, with real local-provider turns only where the
  environment can supply a local model.
- Outbound payloads are not generally redacted by Hermes. Live evidence will
  retain only boolean/count/provenance results and canary-scan observable
  surfaces; raw bodies, headers, IDs, prompts, and paths remain temporary.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m py_compile` on changed receiver/storage/tests | Project venv | 0 | Pass | Syntax gate. |
| Expanded webhook/refresh/attachment/private-state suite | Host loopback | 0 | 131 passed | Covers durable replay, restart, concurrency, cleanup, rate limiting, stock payload shape, real HTTP route, refresh behavior, health/UI privacy, attachment schema migration, and private state. |
| Same focused suite in filesystem/network sandbox | Restricted sandbox | Nonzero | 35 passed, 5 loopback permission errors, 1 skipped | Environmental baseline only; all five socket-bind cases passed in the authorized host-loopback rerun. |
| Stock Hermes outbound-hook tests | Isolated v0.20.1 virtual environment | 0 | 42 passed | Upstream sender, stop-hook, and subagent lifecycle contract tests. |
| `scripts/hermes_webhook_live_validation.py` | Isolated stock commit `f80f453ae0679347e38abc917c7f94f717bf96c5` plus isolated installed Hermes 0.19.0 | 0 | All gates passed | Real CLI/Gateway, 0.19 fallback, 32-client storm, restart, rollback fallback, and expanded privacy scans; sanitized evidence in the JSON companion. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -q` | Clean detached checkout with only 9F changes, authorized host loopback | 0 | 1,021 passed, 4 skipped | Exact final post-review-fix suite. User's unrelated dirty roadmap/data fixtures were excluded; earlier sandbox socket errors were environmental. |
| `uv build` plus `scripts/verify_python_artifacts.py` | Host build cache, temporary artifact directory | 0 | Wheel and sdist verified | Both artifacts contain `hermes_webhook_store.py` and match the exact public inventory. |
| Clean wheel install/import/version smoke | Temporary Python 3.11 virtual environment | 0 | Pass | Installed pinned dependencies, imported `hermes_webhook_store` and `server`, and reported `v0.1.0-beta.1`. |

### Publication CI diagnosis

| Check | Result at commit `44254b5` | Root cause | Corrective action |
| --- | --- | --- | --- |
| Dependency and secret scan | Fail | The stock Hermes commit ID in the harness/evidence was intentionally retained provenance, but its reviewed fingerprint was absent from `.secrets.baseline`. | Add the exact non-secret commit fingerprint for both tracked files; retain the immutable provenance value. |
| Ubuntu Python 3.11/3.13 and Windows Python 3.11/3.12/3.13 group 2 | Fail | One route test used a brittle `< 0.1s` wall-clock threshold. Loaded runners returned in 109–181 ms while still completing before the intentionally blocked refresh adapter. | Assert the behavioral boundary directly: the 202 response must return while the adapter is entered but not completed, then release it in guaranteed cleanup. |
| Aggregate CI/quality gates | Fail | Expected downstream consequence of the two primary failures above. | Re-run the complete matrices after the focused correction passes locally. |
| Reproducible live qualification | Reviewer B P2, corroborated by Reviewer A | `--legacy-hermes` was optional and the aggregate considered only evidence keys that existed, allowing a future run to omit required AC-4 evidence yet report success. The retained run did supply and pass Hermes 0.19, so its result remains valid. | Require `--legacy-hermes` at argument parsing and add a parser contract test proving omission fails before qualification begins. |

The initial matrix otherwise passed Ubuntu Python 3.12, all three macOS
versions, 33 of 36 Windows groups, package/install, browser smoke, and both
unsigned installer builds. No product-runtime failure was reported.

Corrective local verification:

- `python -m unittest tests.test_hermes_webhook_routes -v` on authorized macOS
  loopback: 13 passed.
- `python -m unittest discover -s tests -q` in an isolated temporary worktree:
  1,021 passed, 4 skipped, exit 0 in 129.612 seconds.
- `python scripts/check_tracked_secrets.py` with the exact hash-locked quality
  environment, both in the source worktree and isolated verification worktree:
  passed with no unreviewed candidate.
- After the qualification-gate review fix, the isolated full suite passed
  1,022 tests with 4 skipped in 153.322 seconds; the focused qualification
  module passed 11 tests, and the exact secret scan remained green.
- The complete redacted live harness was rerun with explicit stock Hermes
  0.20.1 and legacy Hermes 0.19 executables. Every gate passed, including
  `legacy_019_quiet_fallback`; the 32-client storm accepted 123 requests and
  safely rate-limited 877.
- Product/frontend code did not change in the corrective delta, so the exact
  final Lighthouse 100/100/100/100 artifact above remains the rendered build
  evidence for this slice; no score-affecting bytes changed.

### Rendered or manual behavior

- Opened Settings in the in-app browser against an isolated Mentat server.
- Webhook Health began in Ready state; activating **Verify Signed Probe** showed
  the accepted confirmation and changed the card to Receiving with count 1.
- The DOM contained no shared secret and browser warnings/errors were empty.
- At 390×844 there was no document/body horizontal overflow and both setup
  actions remained visible; the desktop viewport was restored afterward.
- The exact final build's Lighthouse 13.4.1 desktop scores were 100
  Performance, 100 Accessibility, 100 Best Practices, and 100 SEO (FCP 366 ms,
  LCP 561 ms, TBT 9 ms, CLS 0.0535; report SHA-256
  `dbdfe31eede0ff89c846978c893084622b28652c7c400f4ede4dc9477d02d262`).
  The first restricted-browser attempt's delayed paint was discarded
  after server logs showed immediate responses and the authorized host rerun
  reproduced the canonical perfect scores.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: uncommitted 9F implementation on
  `codex/hermes-020-live-validation` after initial live/full/browser evidence.
- Verification evidence: initial 1,017-test clean suite, stock 42-test suite,
  live harness, browser interaction, and Lighthouse report.
- Rendered artifacts: Settings Webhook Health desktop/mobile interaction.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | P1 | Yes | 429 is not retried by stock Hermes, while the implementation record called rate-limited deliveries retryable. | Yes | Make best-effort loss explicit and retain reconciliation as recovery. |
| A-2 | P1 | Yes | A failed release after queue/rate rejection could leave an unqueued delivery appearing as a durable duplicate. | Yes | Couple durable claim and queue admission transactionally. |
| A-3 | P2 | Yes | Rate limiting occurred after SQLite and the live storm was sequential. | Yes | Limit before storage and run a concurrent storm. |
| A-4 | P2 | Yes | Canary evidence omitted captured process output, Gateway logs, diagnostics, DOM, and tracked-diff claims. | Yes | Expand automated surfaces and separate manual DOM evidence. |
| A-5 | P2 | Yes | Live dropped/out-of-order gates observed counters rather than authoritative projection values. | Yes | Bind the claim to coordinator tests that assert adapter-derived projection snapshots; describe the live counter evidence narrowly. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | P1 | Yes | The new store module was absent from wheel/sdist module inventories. | Yes | Add both package manifests, a contract assertion, artifact verification, and clean install smoke. |
| B-2 | P2 | Yes | 0.19/absent-runtime and Windows compatibility evidence was broader than the recorded harness. | Yes | Add isolated 0.19 fallback evidence; leave Windows explicitly pending CI. |
| B-3 | P2 | Yes | Privacy scan omitted CLI/Gateway output. | Yes | Same root cause and fix as A-4. |
| B-4 | P2 | Yes | Rollback proved only webhook health, not surviving authoritative fallback reads. | Yes | Prove session/agent reads and Home delegation refresh after target removal. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Retry semantics wording | Corroborated contract mismatch | Clean in final review | 429 is documented as intentional best-effort loss; 503 queue rejection is retryable. | Docs and comments corrected. |
| Claim/release race and storage-before-limit | Unique correctness findings | Clean after rounds 2–4 | Limiter precedes SQLite. Queue rejection rolls back; commit failure after admission is explicitly acknowledged, including compound rollback/close failure. | State handling and exact failure tests added. |
| Privacy surface gap | Corroborated | Clean in final review | Harness scans captured outputs, both logs, private data, public health/diagnostics, and `git diff HEAD`; manual browser evidence covers DOM. | Harness/evidence expanded. |
| Projection evidence wording | Unique evidence-scope finding | Clean in final review | Live run proves delivery/drop/reconciliation execution; unit tests prove authoritative snapshots and payload non-authority. | Evidence language narrowed; existing exact tests retained. |
| Package omission | Unique release finding | Reviewer B clean in round 3 | Exact final wheel/sdist verification and clean install/import/version smoke pass. | Package inventories/tests updated. |
| Compatibility and rollback | Unique compatibility findings | Reviewer B clean in round 3 | Real isolated 0.19 chat is quiet and Mentat reads that home; rollback keeps session/agent/Home refresh paths live; Windows stays pending CI. | Harness and AC status updated; baseline remains candidate until CI. |

### Final reviewer result

- Reviewer A (correctness/safety): no findings after round 4.
- Reviewer B (compatibility/product): no findings after round 3.
- Remaining dissent: none. Both completed reviewer agents were closed.

### Corrective publication review

- Reviewer A independently reported no findings on the complete slice and
  initial CI correction.
- Reviewer B reported B-5 (P2 blocking): the live harness could omit the
  required Hermes 0.19 gate and still aggregate only the evidence keys that
  existed. Reviewer A independently critiqued the exact finding and maintained
  it as blocking and in scope. The retained evidence remained valid because
  its invocation supplied and passed Hermes 0.19.
- Reviewer B reported B-6 (P3 non-blocking): the publication line still said
  focused/full/security verification was pending after those checks had
  completed. Reviewer A independently maintained that documentation finding.
- Disposition: accepted both. `--legacy-hermes` is now required by the
  qualification parser, a regression test proves omission exits before a run,
  and the publication line now names only final re-review/publication as
  pending.
- Post-fix evidence: 11 qualification/verifier tests passed; 1,022 full-suite
  tests passed with 4 skipped; exact tracked-secret scan passed; the complete
  stock 0.20.1 plus legacy 0.19 redacted live harness passed every gate.
- Final corrective re-review: Reviewer A and Reviewer B independently reported
  **No findings** on the complete slice and corrective delta. Remaining dissent:
  none. Both reviewer agents may be closed.

### Reverification

- Focused tests: 74 webhook/coordinator/packaging tests passed before the final
  compound-failure addition; the resulting 9-store-test module also passed.
- Full suite: 1,021 passed, 4 platform skips in the exact isolated checkout.
- Next review round or gate result: complete; both independent reviewers clean.

## Documentation updates

- Roadmap: Milestone 9 plan updated. `ROAD_TO_BETA.md` contains unrelated user
  edits and is intentionally excluded from this slice rather than overwritten.
- Changelog: updated with the 9F operator-visible behavior and safety semantics.
- Architecture/operator docs: `ARCHITECTURE.md` and `REMOTE_HERMES.md` updated;
  stock Hermes 0.20.1 is now the maintained local webhook baseline.
- Project/session notes: this review log.
- Documentation verification: exact clean full-suite contract tests passed.
- Post-CI baseline-promotion verification: 27 beta, next-phase, and CI contract
  tests passed in an isolated clean worktree; tracked-secret scan and
  `git diff --check` passed.

## Publication gate

- Proposed files: `ARCHITECTURE.md`, `CHANGELOG.md`,
  `MILESTONE_9_WEBHOOK_IMPLEMENTATION_PLAN.md`, `REMOTE_HERMES.md`,
  `hermes_webhooks.py`, `hermes_webhook_store.py`, `mentat_db.py`,
  `pyproject.toml`, `scripts/hermes_webhook_live_validation.py`,
  `scripts/verify_python_artifacts.py`, `server.py`, six webhook/attachment/
  packaging test files, and the Markdown/JSON review evidence.
- Branch and base: `codex/hermes-020-live-validation` onto
  `codex/hermes-active-run-steer`.
- Commit message: `feat: qualify stock Hermes 0.20 webhooks`
- PR title: `feat: qualify stock Hermes 0.20 webhooks`
- PR summary: durable replay and storm admission, stock 0.20.1/legacy 0.19 live
  qualification, package inventory, privacy/rollback evidence, and docs.
- Unresolved risks: rate-limited wakeups are intentionally best-effort and rely
  on authoritative reconciliation; this is a documented transport property,
  not an unresolved acceptance gap.
- User authorization and scope: standing approval recorded; exact publication
  inventory will still be logged before action.
- Initial commit hash: `44254b5376db3765107671eb477ee9674170ae2b`.
- Ready PR URL: <https://github.com/hazeion/agent-os/pull/101>.
- Corrective commit: `b31419bc01bedc276f9e889827cadfc53c7a3dca`.
- PR CI: all quality, security, package, native-installer, Ubuntu Python
  3.11–3.13, macOS Python 3.11–3.13, and 36 Windows shard checks passed in runs
  `31863627628`, `31863627626`, and `31863627597`.

## Outcome review

- Classification: Successful.
- Acceptance criteria summary: AC-1 through AC-8 pass; stock Hermes 0.20.1 is
  promoted to the maintained local webhook baseline.
- Potential bugs or untested paths: OS-level telemetry remains outside the
  bounded harness scope; no required test path remains unverified.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: schema migration is additive;
  0.19/unconfigured/disabled fallback and target-removal rollback passed.
- User decision: accepted under the recorded standing approval after every
  required gate passed.
- Next slice authorized: Yes, proceed to 9G under the standing approval.
