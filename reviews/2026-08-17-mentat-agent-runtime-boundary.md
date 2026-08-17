# Feature Slice Review: Mentat AgentRuntime boundary

Status: Verified; ready for publication
Slice: `mentat-agent-runtime-boundary`
Date: `2026-08-17`

## Slice contract

### Goal

Introduce the first runtime-neutral Mentat orchestration seam around the current
Hermes Agent Console path, while preserving every existing Hermes behavior and
safety boundary.

### In scope

- Define minimal runtime-neutral contracts for Mentat Agent, Task, Run,
  AgentEvent, RuntimeContext, runtime capabilities, and AgentRuntime.
- Add a Hermes runtime adapter that keeps Hermes profile, transport, session,
  and upstream-run references behind the adapter boundary.
- Normalize current Console lifecycle/progress events into the initial Mentat
  event vocabulary without trusting native webhook payload fields.
- Route current Console transport selection through one runtime registry entry
  before delegating to the unchanged Hermes local/remote transport adapter.
- Preserve legacy browser payloads and globally single-Hermes-run behavior.
- Add focused contract/integration tests, update architecture/release docs, run
  full automated and rendered verification, and obtain two independent
  adversarial reviews.

### Out of scope

- A Codex or Claude runtime, concurrent execution, dynamic routing, or A2A/MCP.
- A durable Mentat Agent registry or migration of existing project/task stores.
- New Next.js UI, new browser routes, or changes to the legacy dashboard.
- Replacing Python server/runtime code with TypeScript.
- Retiring polling, reconciliation, private Console telemetry, or any Milestone
  9 compatibility path.

### Acceptance criteria

| ID | Observable criterion | Planned evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Runtime-neutral domain contracts keep Mentat IDs distinct from runtime references and reject malformed/unknown states. | Unit tests for every contract and status vocabulary. | Pass |
| AC-2 | One AgentRuntime protocol exposes start, message, stop, status, and event-stream operations with explicit optional capabilities. | Protocol/registry tests and static source assertions. | Pass |
| AC-3 | Hermes is registered as the first runtime and existing Console transport selection crosses that registry before invoking the unchanged local/remote selector. | Server integration tests with a recording transport factory. | Pass |
| AC-4 | Hermes event/run projections emit only normalized Mentat vocabulary and retain upstream identifiers only in private adapter context. | Projection tests covering lifecycle, tools, approvals, artifacts, cost, and unknown events. | Pass |
| AC-5 | Existing Hermes behavior, single-run constraints, webhook authority, and legacy browser payloads remain unchanged. | Existing focused suites plus full repository suite. | Pass |
| AC-6 | Package, secret scan, computer-use, Lighthouse 100/100/100/100, and two independent adversarial reviews pass. | Verification and review records below. | Pass |

### Constraints and recovery

- Compatibility: this is an additive strangler seam; Hermes remains the only
  registered runtime and existing HTTP/browser contracts do not change.
- Authority: runtime adapters execute only through existing capability-gated
  handlers. Native webhook bodies remain discarded wakeups, never event truth.
- Identity: this slice defines the canonical Mentat identity contract but does
  not invent a profile-derived durable Agent registry. Existing profile IDs
  remain compatibility input until the later registry migration.
- Recovery: retained Console history remains schema 3 and gains only optional
  runtime type and Mentat Agent/Task fields, which the prior reader safely
  ignores. Schemas 1-2 remain readable and rollback preserves history.
- Version control: branch `codex/mentat-agent-runtime-boundary`, stacked on 9I
  and merged with the `origin/main` pivot documents in an isolated worktree.
- User approval: standing approval applies to this in-scope slice; destructive
  actions and unrelated local-worktree changes remain excluded.

## Test strategy

| Criterion | Pre-change gap | Test/evidence | Limitation |
| --- | --- | --- | --- |
| AC-1 | Current dictionaries conflate Hermes profile and agent identity. | Constructor and serialization tests enforce separate opaque IDs/references. | Durable Agent persistence is intentionally deferred. |
| AC-2 | No generic runtime contract or capability model exists. | Fake runtimes prove exact registry and operation behavior. | Only Hermes is registered in production. |
| AC-3 | `server.py` selects Hermes transport directly. | Recording adapter proves registry dispatch before the existing transport selector. | Generic task dispatch is the next slice because Console prompts are not yet durable Mentat Tasks. |
| AC-4 | Existing event kinds are Console/Hermes-shaped. | Table-driven normalization and privacy tests. | Historical browser payloads remain unchanged for compatibility. |
| AC-5 | A new seam could weaken current locks or validation. | Existing Console, transport, webhook, and event suites plus full suite. | Runtime #2/concurrency is a later proof milestone. |
| AC-6 | No release evidence exists for this slice. | Existing package, secret, browser, Lighthouse, and review gates. | Platform CI follows publication. |

## Baseline evidence

- Milestone 9A-9I is complete; PR #104 has 51 passing checks.
- `origin/main` adds the multi-agent pivot at commits `4ebe1a0` and `831e372`.
- Current Agent Console execution is globally single-run and resolves
  `HermesConsoleTransport` directly from `server.py`.
- Existing `run_*` IDs are Mentat-owned, while current `agent_id` values are
  Hermes profile compatibility identifiers.

## Implementation record

- Added `agent_runtime.py` with strict runtime-neutral domain contracts,
  capabilities, protocol, and deterministic adapter registry.
- Added `hermes_runtime.py` with the first runtime adapter, fixed normalized
  event vocabulary, cursor-continuity failure, and legacy route bridge.
- Routed current Console transport and HTTP compatibility handlers through the
  Hermes registry without moving mature local/remote execution code.
- Generic Hermes task starts now retain separate Mentat Agent/Task IDs through
  owner-private history schema 3; legacy Console starts retain their profile-ID
  compatibility shape. Generic status and verified remote message/steer use the
  retained binding and existing revision checks.

## Verification record

- Focused runtime/history/server suite: 52 tests passed; the final cursor-gap
  recheck subset passed 40 tests and `git diff --check`.
- Final full repository suite: 1,091 tests passed with 4 native-platform skips.
- Package: wheel and source distribution built with `uv build`; both passed the
  exact artifact inventory and integrity verifier.
- Browser smoke: the complete 46-check responsive and interaction matrix
  passed against an isolated owner-private fixture.
- In-app browser: Home loaded, navigation reached Managed Agents, and no
  browser-console errors were present.
- Lighthouse 13.4.1 desktop/provided: 100 performance, 100 accessibility, 100
  best practices, and 100 SEO; FCP 327.92 ms, LCP 528.657 ms, TBT 0 ms, CLS
  0.02783332790656102. Compact evidence is in
  `reviews/2026-08-17-mentat-agent-runtime-boundary-lighthouse.json`.
- Pinned `detect-secrets==1.5.0` staged-file gate passed; the only new candidate
  is the reviewed Lighthouse report SHA-256 fingerprint recorded narrowly in
  `.secrets.baseline`.

## Adversarial review record

### Round 1

Both reviewers found that the first event map used synthetic rather than actual
Console kinds, treated every error as terminal, ignored retention gaps, copied
live summaries, and could not reconstruct Mentat Agent/Task identity after a
generic start. One also found that unknown persisted runtime types were silently
relabeled as Hermes and that the durability claim was inaccurate.

Resolution: map the actual `complete`, `approval`, `clarification`, `artifact`,
tool, and lifecycle kinds; require verified terminal run state for ambiguous
errors; use fixed summaries; fail closed on cursor gaps; persist the caller's
separate Mentat Agent/Task binding in additive private history schema 3; make
generic status and revision-bound remote messaging functional; and reject
unknown runtime history. Tests now use production event vocabulary and the real
server generic-start path.

### Round 2

Reviewers found that final run state could still relabel multiple historical
errors as terminal; a schema-4 bump would break rollback to the prior reader;
generic start did not reject conflicting Agent/Task bindings; message support
was not discoverable per run; and normalized consumers lacked bounded assistant
output and usage events.

Resolution: choose exactly one matching verified terminal transition (or the
last reconciliation event when no explicit terminal event exists); keep history
at backward-readable schema 3 with optional binding fields; reject Agent/Task
identity mismatch before launch; expose run-scoped capabilities; and derive
bounded redacted message and allowlisted usage events at completion using a
stable four-slot sequence projection over the legacy cursor.

### Round 3

Reviewers found that terminal projection could happen before artifact
discovery completed, the first finalization implementation also changed legacy
unbound Console histories, and the additive top-level Agent/Task binding could
be erased by a prior schema-3 reader or event retention. Pinning the binding
then exposed a final incremental-cursor gap bug.

Resolution: emit a stable `runtime.finalized` boundary only after artifact
collection and only for valid runtime-bound runs; recover Agent/Task identity
from a validated `runtime.bound` event while keeping history schema 3; retain
that binding within the bounded event window; and calculate cursor continuity
across the complete returned sequence so pinned gaps fail closed. Both
reviewers rechecked the final code and reported no actionable findings.

## Documentation and publication

Architecture, contributor boundary, pivot status, remote module inventory,
package inventory, and changelog documentation are updated. Publication awaits
commit, push, ready PR, and CI observation.
