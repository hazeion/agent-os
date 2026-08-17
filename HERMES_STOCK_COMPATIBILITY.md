# Hermes stock compatibility and fallback audit

Status: Milestone 9I reviewed baseline
Stock reference: Hermes Agent `v2026.8.13` (`0.20.1`), commit
`f80f453ae0679347e38abc917c7f94f717bf96c5`

## Outcome

Milestone 9 moves every qualified stock outbound event to the signed webhook
receiver, but retires no correctness fallback and no custom-host contract.
Webhooks are authenticated, payload-discarding wakeups. They reduce observation
latency; they do not prove state, carry trusted token/tool/model details, or
grant mutation authority.

The 30-second browser refresh and 60-second server reconciliation remain
enabled. This is intentional: stock hooks are best effort, Safe Mode and
unconfigured targets emit nothing, browser streams can disconnect, queues can
drop hints, and the required full-day production soak has not occurred.

## Machine-checked compatibility inventory

The `Contract ID` values are defined by `hermes_stock_compatibility.py`, mapped
exactly once to every boolean feature accepted by `remote_hermes.py`, and
asserted against this table by `tests/test_hermes_stock_compatibility.py`.
“Custom” means Mentat currently depends on a hardened contract that the pinned
stock capability document does not completely advertise; it does not mean the
stock runtime has no related feature.

| Contract ID | Mentat surface | Pinned stock evidence | Current class | Webhook eligibility | 9I decision and stock behavior |
| --- | --- | --- | --- | --- | --- |
| `native_observer_hooks` | Session, subagent, API, tool, and Kanban observation freshness | The exact 17 hook names, emitters, and CLI/Gateway/worker registration sites are pinned by `scripts/validate_hermes_native_events.py`. | Stock equivalent | Qualified wakeup | **Migrated.** Discard payload fields and perform authoritative readback. |
| `browser_projection_stream` | Immediate refresh of open Mentat views | Hermes does not need this same-origin Mentat SSE route. | Mentat-local | Not applicable | **Retain.** Keep the bounded projection-only stream; it complements browser polling. |
| `browser_periodic_refresh` | Whole-dashboard convergence | Stock hooks can be absent, disabled, dropped, delayed, or disconnected. | Supported fallback | Not replaceable yet | **Retain.** Keep `REFRESH_MS = 30_000` until the retirement gates below pass. |
| `server_periodic_reconciliation` | Authoritative session, agent, attention, and Kanban convergence | Hook delivery and coordinator admission are best effort. | Supported fallback | Not replaceable yet | **Retain.** Keep the 60-second reconciliation sweep until the retirement gates below pass. |
| `local_console_live_progress` | Live local tool activity and context percentage | Pinned stock contains no `MENTAT_HERMES_PROGRESS_FILE` contract. Outbound post-tool/API hooks are discarded and not run-bound telemetry. | Custom enhancement | Wakeup only, not data | **Retain.** Keep the private bounded progress file for compatible forks. Stock local CLI runs safely show generic progress and Unavailable context usage. |
| `local_console_final_usage` | Final per-run token/API/model/provider accounting | Stock `hermes -z --usage-file` writes a fixed-field, best-effort one-shot report to an arbitrary caller path, but Mentat launches `chat -q`; stock output may include private session/provider/failure fields and lacks Mentat's context-window pair. Exact source/schema evidence is pinned by `scripts/validate_hermes_stock_compatibility.py`. | Stock partial | Not a webhook data source | **Migration candidate.** Keep the validated private fork file now. A future slice needs a Mentat-owned path, bounded read/minimization, and chat-continuity solution. |
| `remote_openai_api` | OpenAI-compatible chat and Responses | Stock advertises authenticated chat/Responses endpoints and request-scoped model/provider options. | Stock equivalent | Existing direct stream | **Prefer stock.** Keep capability validation; this is separate from profile-default mutation. |
| `remote_runs_core` | Run submission, status, SSE tool progress, stop, and text steer | Stock advertises these exact base Runs surfaces. | Stock equivalent | Existing run stream | **Prefer stock.** Retain schema validation and use stock when it passes; outbound webhooks are unrelated. |
| `remote_run_recovery` | Replay cursor, pending-action recovery, and runtime identity | Stock Runs SSE is not replayable and does not advertise Mentat's exact recovery/runtime identity versions. | Custom required | Not a webhook authority | **Retain.** Keep optional hardened features; base stock Runs continue with status reconciliation and unavailable enhanced metadata. |
| `remote_approval_and_clarification` | Human-in-the-loop responses | Stock advertises approval response/events but not Mentat's exact request-binding and structured-preview flags; no equivalent typed clarification response contract is advertised. | Custom required | Not a webhook authority | **Retain.** Keep the exact capability gate. Unsupported hosts do not show actionable controls. |
| `remote_session_resources` | Session list, messages, chat, and fork | Stock advertises authenticated session resources. | Stock equivalent | Existing direct reads | **Prefer stock.** Use the stock resource APIs when their complete browser privacy schema passes. |
| `remote_session_continuation` | Revision-bound continuation after selecting history | Stock session resources are related but do not advertise Mentat's exact revision-bound, stoppable continuation descriptor. | Custom required | Not a webhook authority | **Retain.** Keep the custom contract; stock degrades to safe session visibility/new turns where supported. |
| `remote_inline_images` | Bounded Console image inputs | Pinned stock Runs does not advertise Mentat's exact data-URL-only count/byte contract. | Custom required | Not a webhook authority | **Retain.** Keep image input capability-gated; stock text runs remain available without it. |
| `remote_profile_inventory` | Complete API-key-authenticated profile list | Stock multi-profile routing exists, but the pinned capability document does not advertise Mentat's complete profile inventory contract. | Custom required | Not a webhook authority | **Retain.** Keep the exact gate; stock may expose only the active/default profile safely. |
| `remote_profile_runtime` | Provider/model options plus verified profile-default switching | Stock has `/api/model/options` and request-scoped selection, but not Mentat's complete runtime inventory or revision-bound, idempotent, active-run-locked default switch. | Stock partial | Not a webhook authority | **Migration candidate.** Use stock options/per-run selection in a future slice; retain custom default-switch gates and unavailable/read-only degradation. |
| `remote_skill_toolset_inventory` | Read-only skills and toolsets | Stock advertises authenticated `/v1/skills` and `/v1/toolsets`. | Stock equivalent | Existing direct reads | **Prefer stock.** Use Mentat's bounded identifier-only projection; selection mutation remains separate and unavailable remotely. |
| `remote_kanban_mutation` | Durable delegation and task follow-up | Stock Kanban CLI/tools and observer hooks do not advertise Mentat's bearer-authenticated, revisioned, idempotent Kanban HTTP contract. | Custom required | Observation wakeup only | **Retain.** Keep the local adapter and custom remote capability gate. Never infer mutation success from an event. |
| `remote_artifact_download` | Digest-verified delegated artifacts | Stock can retain native Kanban artifacts, but does not advertise Mentat's authenticated manifest/download limits and digest contract. | Custom required | Availability wakeup only | **Retain.** Keep the custom import contract; pinned stock remains summary-only and Mentat never parses response paths. |
| `remote_cron_inventory` | Read-only scheduled-work inventory | Stock documents an authenticated `/api/jobs` admin family, not Mentat's exact read-only `/v1/jobs` inventory contract with bounded complete response and revision. | Custom required | Observation wakeup only | **Retain.** Keep the exact read-only gate. Do not substitute broader jobs administration or enable mutations. |
| `remote_prohibited_admin` | Remote config and jobs mutation | Stock's capability document denies these stable surfaces; Mentat also prohibits them. | Explicitly prohibited | Not a webhook authority | **Prohibit.** A broader native admin route is not a substitute for Mentat's approved read-only boundaries. |

## Retirement gates

A fallback can be reduced only in a new reviewed slice with evidence for all of
these gates:

1. At least 24 continuous hours of representative CLI, Gateway, Kanban, API,
   Safe Mode, restart, and reconnect traffic with per-binding health evidence.
2. Measured delivery coverage and bounded latency for every projection that the
   fallback currently repairs, including a deliberately dropped delivery.
3. Compatibility evidence for stock, legacy, disabled, absent, and partially
   configured Hermes runtimes on Linux, macOS, and Windows.
4. A rollback that restores convergence without reversing private schema
   migrations or trusting webhook payloads.
5. Separate proof that any data-bearing telemetry replacement is run-bound,
   authenticated, bounded, privacy-minimized, and authoritative. A wakeup event
   alone cannot satisfy this gate.

Until then, duplicate wakeups are harmless and the existing polls remain the
correct recovery cost: up to one ordinary dashboard refresh every 30 seconds
and one bounded server reconciliation every 60 seconds, without delaying the
webhook response.

## Stock-first migration rule

Mentat should prefer a stock Hermes capability whenever it reaches the same
security and verification contract. Each remaining custom row must eventually
end in exactly one state: an upstream stock equivalent, the supported degraded
behavior documented above, or a separately approved product removal. Matching
route names or related native features are not enough; request binding,
revision/idempotency semantics, limits, authentication, and readback must match.
