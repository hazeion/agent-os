# Garage Project runtime qualification

Date: 2026-09-21. Research for [Qualify one runtime for the garage Project workflow](https://github.com/hazeion/agent-os/issues/237).
Repository inspected: `038f1d189fc952193728b1c596c4aabbff1ddb58`.

## Decision

**Select local Hermes on the always-on Linux host as the first qualification candidate. No existing adapter is yet qualified for the complete garage workflow.** This is a recommendation to extend and test one bounded path, not permission to enable all Hermes tools or a claim of live success.

Hermes has the closest combination of supported durable delegation and Mentat-owned image/text input and generated-file handling. Codex and Vercel remain useful existing adapters, but their current Mentat boundaries do not provide equivalent file intake. Keep orchestration contracts runtime-neutral; do not make an Agent identical to a Hermes profile. “Local Hermes” means co-located with the server; the owner can still use a remote authenticated browser. It does not require a fleet of owner computers. [Repository contracts](../../ARCHITECTURE.md#agent-console-file-boundary), [Hermes adapter](../../hermes_runtime.py), [runtime contracts](../../agent_runtime.py).

## Evidence and its limits

| Candidate | Implemented Mentat behavior | Qualification consequence |
| --- | --- | --- |
| Local Hermes | Fixed runtime adapter; immediate Console image/text inputs and trusted export discovery after explicit file capability enablement; separate supported Kanban delegation adapter. | Best starting candidate, but Project context, permissions, budget enforcement, handoffs and result bundles need additional contracts. |
| Codex | Fixed local App Server identity; canonical Task execution, continuity, scoped Inbox Task creation tool, stop/status/events; workspace-write and approvals disabled. Attachments remain unsupported. | Existing text/code execution does not establish floorplan input or bounded garage artifact generation. Do not broaden executable, cwd, arbitrary dynamic tools or browser authority to make it fit. |
| Vercel | One bounded synchronous AI Gateway generation, status/events/model generation; separate optional infrastructure adapters. | No complete web-research, image-input, artifact, or durable coordination loop in this adapter. Sandbox availability is not permission for arbitrary commands. |
| Remote Hermes | Capability-advertised remote Runs and Kanban paths, including separately gated remote artifact transfer. | Preserve existing support, but do not assume parity with local Conversation files or durable recovery after abrupt process death. Not needed for the first co-located Linux qualification. |

Sources: [Hermes runtime](../../hermes_runtime.py), [Codex runtime](../../codex_runtime.py), [Vercel runtime](../../vercel_runtime.py), [Kanban adapter](../../hermes_kanban.py), [remote and file contracts](../../ARCHITECTURE.md).

The attachment-run tests patch profile discovery, command availability and worker startup. Conversation attachment orchestration uses a fake runtime. These establish boundary behavior under fixtures, not successful vision, research, provider billing control or artifact generation. The September first-use audit explicitly left positive Hermes delegation, uploads, Context Packs and generated-file execution unqualified. This investigation inspected code and public documentation; it did not inspect credential values, run providers, upload owner files, or re-run tests. Current installed runtime/model/tool availability is therefore **unknown**. [Attachment fixtures](../../tests/test_agent_console_attachment_runs.py), [orchestration fixtures](../../tests/test_conversation_attachment_orchestration.py), [audit limits](../../reviews/2026-09-09-first-use-audit.md#limits-cleanup-and-next-order).

Upstream Hermes documents public web search/extraction, vision, file and terminal tools, with toolsets controlling availability. This establishes upstream capability candidates, not which tools an installed profile has or whether they satisfy Mentat isolation. An enabled toolset is not a demonstrated per-Project security boundary. [Official tools documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools), [official toolsets reference](https://hermes-agent.nousresearch.com/docs/reference/toolsets-reference).

Upstream Kanban documents persistent named workers, dependency gating and review handoffs. It distinguishes durable Kanban work from transient `delegate_task` calls. Declared scratch artifacts are retained before cleanup; undeclared scratch files can disappear. Workers operate under a trusted local-user model, and documented finite iteration limits do not prove a monetary cap. These are reasons to test and constrain the adapter, not to expose upstream board tools wholesale. [Official Kanban documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban).

Upstream pages track a moving release. Record the exact Hermes version and supported capability inventory during qualification; documentation alone cannot establish compatibility with the host.

## Authority that must be explicit

Three existing paths must remain distinct:

1. **Task Run once** already supports explicit canonical Task execution through `OrchestrationService`, exact revision/confirmation and an idempotency receipt. It is not a durable automatic multi-Task planner.
2. **Console** owns Conversations, user Turns and their Runs. A bounded queued Turn is not a scheduled Task; a planning association grants no implicit Project context or dispatch rights.
3. **Delegation** currently permits durable mutations only through the supported Hermes Kanban adapter, with exact preview, confirmation, reservation, lock and readback.

Sources: [`mentat_planning_task_run_once` and `_start_hermes_runtime_task`](../../server.py), [Console and Kanban contracts](../../ARCHITECTURE.md), [domain language](../../CONTEXT.md).

The accepted product scope extends this authority: approving a plan should authorize bounded later Tasks and handoffs. That cannot be implemented by silently turning Console messages into a scheduler, treating `task.create` as permission to execute, or letting a lead agent issue arbitrary Kanban mutations. A revisioned **approved plan execution grant** must bind canonical Project/Task/Agent IDs, dependency graph, context snapshots, permitted operations, budget and review checkpoints. A changed assignment, scope, context or limit must invalidate affected unstarted authorization. Active reassignment requires an explicit stop/handoff decision.

Recommended first implementation retains Hermes Kanban as the durable execution backend and adds narrowly named operations only where the qualification contract requires them. Mentat owns plan approval, permissions, results and review; Hermes owns its private execution references. Decide explicitly how a plan approval produces exact per-operation authorizations under the existing confirmation contract. Until that amendment is reviewed, automatic handoff remains unavailable. A new runtime-neutral durable dispatcher would be a separate architectural replacement, not a hidden extension of Run once. This section is a proposed design, not implemented behavior.

## Files, context and deliverables

Current Conversation staging is capped at eight items, five direct files and one image. Validated raster image types include PNG/JPEG/GIF/WebP; text uses a fixed extension allowlist. Image and text limits are 10 MiB and 2 MiB respectively. SVG is blocked, and PDF/DOCX are not accepted text/image formats. Run export discovery is capped at twenty files. Therefore “accept any floorplan” and “export editable CAD/Word/PDF” would overstate existing behavior. [Attachment validation](../../agent_console_attachments.py), [staging limits](../../conversation_attachments.py), [artifact discovery](../../agent_console_artifacts.py).

The minimal proposed qualification contract is one raster floorplan plus a structured measurements/goals document; output an editable Markdown shopping document and implementation checklist, a validated dimension/placement JSON source, and a rendered PNG layout. A fixed renderer should render the bounded schema, not execute model-generated code. This is a new capability to implement; a PNG alone is not an editable dimensioned source. Missing measurements, uncertain scale, conflicting units or obstructed doors must cause a clarification checkpoint. Do not infer exact dimensions from pixels. PDF ingestion and DOCX/PDF export require separate safe conversion/validation work if they become required.

Context Packs currently hold revalidated references, not persistent shared Project files or permission grants. Build Project brief/files as explicit private authority and snapshot only permitted content into the exact Run. Preserve no-follow input cleanup, output discovery within the trusted Run export directory, opaque browser IDs, validated downloads, reference-aware retention and backup consistency. Never open a path extracted from model prose. Result handoffs should reference verified retained artifacts and bounded findings, with producer Run and revision provenance; they must not carry arbitrary local paths or grant extra tools. [Context/file contract](../../ARCHITECTURE.md#agent-console-file-boundary), [execution-context builder and cleanup](../../agent_console_artifacts.py).

## Permissions and budgets

The approved garage scope allows public research, supplied-file reading and deliverable creation; it does not grant arbitrary shell access, account access, messages, purchases or agent self-provisioning. Web pages and supplied files are untrusted input. Qualification must demonstrate that prompt injection cannot widen tool permissions, fetch private host services, read unrelated Projects or write outside the controlled output boundary. Reuse fixed capability adapters or introduce bounded tools; do not solve missing document generation by exposing a generic command proxy.

Existing operation timeouts and observed usage are not an enforceable total Project spending ceiling. The Codex start deadline, Kanban CLI timeout and Vercel request timeout bound individual operations, not all descendant work. [Codex deadlines](../../codex_runtime.py), [Kanban timeout](../../hermes_kanban.py), [Vercel request](../../vercel_runtime.py).

Proposed enforcement requires durable budget reservations across active work, bounded concurrency, monotonic execution deadlines and a watchdog, plus a runtime-enforced finite work limit. Dollar limits need preflight worst-case reservations or provider-enforced limits with explicit reconciliation; late usage reports alone cannot guarantee no overspend. If the provider cannot support a hard money limit, report the limitation and fail qualification for that promise rather than relabeling an estimate as enforcement. Budget exhaustion stops new dispatch and produces an owner checkpoint; it must not trigger unlimited retries. Ambiguous remote outcomes preserve evidence and require reconciliation before spending again.

## Bounded implementation and acceptance slices

| Slice | Deliverable | Required evidence |
| --- | --- | --- |
| Runtime qualification harness | Read-only version/capability inventory and a disposable Linux profile; explicit fixture vs live status. | Missing model/search/vision tools fail clearly; no secret leakage; no availability claims from sign-in alone. |
| Project context authority | Revisioned brief, private file references and exact Task input snapshots. | Cross-Project denial, stale approvals, revoked context, malformed/oversized images, symlink races, whole-pack failure and backup/cleanup checks. |
| Approved plan and handoff contract | Durable plan revision, assignments, dependency/review checkpoints, bounded execution grant and receipts through fixed Hermes operations. | Duplicate approval, concurrent edits, cycle rejection, reassign race, failed prerequisites, restart reconciliation, uncertain submission and cancellation prevent duplicate/hidden work. |
| Runtime isolation and budget enforcement | Fixed research/input/output capabilities, host-enforced limits and safe pause. | Malicious page/file cannot read unrelated data or expand permissions; timeout and provider loss stop admission; concurrent budget reservations cannot overspend the chosen enforceable limit. |
| Result bundle and review | Verified artifact bundle, dimension schema/renderer, sources and coordinated revisions. | Missing/spoofed exports rejected; downloads validated; measurements/units correct; rejected shelving revises affected outputs while retaining prior versions. |
| Live garage qualification | Exact supported Linux/runtime/provider combination completes the agreed scenario. | Owner reviews useful researched options, dimensioned layout, linked editable product list and implementation order; interruption and browser disconnect tests pass. |

These slices need their own scope/review records and implementation issues. Public-source tests should include URLs and retrieval dates, distinguish sourced product dimensions/prices from estimates, and verify links when producing the final shopping document. Keep a synthetic floorplan for repeatable checks; use owner data only in the explicitly authorized live acceptance run.

## Remaining blockers

- The exact installed Hermes release, configured model, web/vision services and permitted tool boundary have not been qualified.
- Project-shared context and approved plan execution are new authority, not existing Conversation association behavior.
- Kanban handoff/image/artifact semantics must be verified through supported operations without direct Hermes storage access; local Console files do not prove Kanban parity.
- Hard cost/time enforcement and isolated file/tool access need implementation evidence before autonomous work can satisfy the accepted scope.
- The agreed garage deliverables have no live end-to-end evidence yet. This research resolves candidate selection and qualification requirements; it does not mark product acceptance complete.
