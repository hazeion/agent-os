# Hermes 0.20 product decisions

Status: Approved product boundary for Mentat Milestone 9G
Baseline: stock Hermes Agent 0.20.1, tag `v2026.8.13`, commit
`f80f453ae0679347e38abc917c7f94f717bf96c5`

Hermes 0.20.1 shipped several useful features beside outbound lifecycle
webhooks. Sharing a release does not give those features a shared transport,
authority, or privacy model. This document records how Mentat treats each one
and what would have to be true before a future Mentat surface could expose it.

## Decision summary

| Hermes surface | Mentat 9G decision | Current Mentat behavior | Webhook relationship |
| --- | --- | --- | --- |
| A2A v1.0 | **Native Hermes only; defer a Mentat control surface.** | Hermes may use its opt-in A2A plugin independently. Mentat does not configure peers, proxy tasks, expose an Agent Card, or inspect A2A conversations/audit data. | Not a Mentat webhook event. A2A push notifications are a separate task protocol and must not enter the lifecycle receiver. |
| Grounded citations | **Compatible as response Markdown; defer structured citation UI.** | Safe public links remain visible in ordinary assistant responses. Mentat does not infer source identity, support, or truth from prose or expose raw tool results. | Not an event. Citation/query/answer data must not be persisted as webhook observation data. |
| Desktop and deliverable artifacts | **Keep Mentat's existing owned artifact boundary; reject response-path discovery.** | Local Console outputs come only from the run-owned export directory. The custom remote Kanban artifact contract remains capability-gated; stock 0.20.1 degrades to summary-only. | Artifact availability may eventually have a privacy-minimized wakeup, but bytes and paths never belong in a webhook payload. |
| Voice | **Defer a Mentat voice surface.** | Mentat remains text and attachment based. Native Hermes CLI/TUI/Desktop/messaging voice can be used outside Mentat. | Audio, transcripts, and generated speech are content, not lifecycle wakeups. Barge-in requires a verified steer/interrupt capability, not event receipt. |

These decisions neither disable stock Hermes features nor make them mandatory
for Mentat. They prevent an optional Hermes feature from silently widening an
unauthenticated, loopback Mentat process or bypassing an existing safety
boundary.

## A2A v1.0

### Stock capability evidence

The exact stock checkout implements A2A as an opt-in platform plugin under
`plugins/platforms/a2a/`. Its `README.md`, `DESIGN.md`, `adapter.py`,
`protocol.py`, and `security.py` show a bidirectional JSON-RPC v1.0 surface:

- outbound tools discover and call configured peers;
- inbound tasks enter a live Hermes gateway session with its memory and tools;
- remote exposure requires explicit host and token configuration;
- push callbacks are SSRF guarded and are HMAC signed only when
  `A2A_PUSH_SECRET` or the shared bearer token supplies a signing secret;
- push status payloads can contain up to 2,000 characters of reply text and use
  a different signature/header/envelope from outbound lifecycle hooks;
- task/conversation/audit state is Hermes-owned;
- cancellation changes A2A task state but does not guarantee abortion of the
  live in-flight Hermes turn.

This is a remote work authority, not an observation hint. An A2A task can cause
model and tool execution and may cross machine/framework boundaries.

### Decision

Mentat does not add an A2A server, client, peer editor, task proxy, or A2A push
receiver in Milestone 9. Operators may enable stock Hermes A2A independently,
but Mentat does not read or write its configuration, credentials,
`a2a_conversations`, or `a2a_audit` files.

A future Mentat A2A slice must independently define:

1. a supported capability-advertised API rather than direct config/file access;
2. configured, authenticated peer aliases only, with no browser-supplied URL,
   token, Agent Card endpoint, redirect target, or host substitution;
3. executable negative-path tests that independently reject redirects, DNS
   rebinding, private, loopback, link-local, metadata-service, and Agent
   Card-advertised endpoint substitution, while proving that only configured
   peer aliases can select a destination;
4. authenticated peer identity, trust approval, explicit local-versus-remote
   exposure, and a mandatory callback signing secret; executable callback
   tests must reject missing or invalid signatures and prove that the verified
   HMAC binds the exact task, context, and peer before authoritative read-back;
5. exact task preview, confirmation, cancellation semantics, read-back, and
   partial-failure language;
6. prompt-injection framing, outbound redaction, bounded transcript exposure,
   and browser-safe aliases;
7. recovery and rollback without claiming that A2A cancellation stopped a
   live Hermes turn.

Until then, A2A is neither a Mentat Kanban replacement nor a lifecycle webhook.

## Grounded citations

### Stock capability evidence

The exact stock checkout ships two relevant layers:

- `skills/research/grounded-citations/SKILL.md`, its `scripts/sources.py`, and
  `tests/skills/test_grounded_citations_skill.py` guide Hermes to gather
  sources, support claims, and produce linked Markdown.
- `tools/x_search_tool.py`, documented by
  `website/docs/user-guide/features/x-search.md` and covered by
  `tests/tools/test_x_search_tool.py`, returns xAI-specific structured
  `citations` and `inline_citations` inside the private tool result.

The `x_search` result also includes the query, synthesized answer, provider,
model, and credential-source metadata. Its `degraded: false` value does not
prove grounding: without narrowing filters, an empty-citation answer is still
reported as not degraded. Stock 0.20.1 does not advertise a versioned,
provider-independent citation API or privacy-minimized outbound citation event.

### Decision

Mentat remains compatible with grounded-citation output as ordinary assistant
Markdown. Existing URL safety and rendering rules apply. A visible link is not
proof that Mentat fetched, verified, or endorses the source, and Mentat must not
parse assistant prose into trusted provenance records or expose the raw
`x_search` tool result. A future grounded indicator must require at least one
valid structured citation; `degraded: false` alone is insufficient.

A future structured citation surface requires an upstream schema with stable
source IDs, public canonical URLs, claim/source association, bounded title and
snippet fields, explicit verification state, and a capability version. Mentat
would still revalidate browser-safe URLs and label model-provided versus
independently verified evidence. Raw page content, credentials, private URLs,
local paths, and browsing traces would remain excluded.

## Desktop and deliverable artifacts

### Stock capability evidence

Stock Hermes Desktop's `apps/desktop/src/app/artifacts/artifact-utils.ts`
searches recent assistant/tool transcripts for URLs, Markdown links, and
filesystem-looking paths. `apps/desktop/src/lib/artifact-detect.ts` separately
recognizes substantial HTML, SVG, and code fences for transcript-backed cards.
These are presentation features, not a stable generated-file integration API.

Stock Hermes also documents messaging deliverables in
`website/docs/user-guide/features/deliverable-mode.md`. Native messaging paths
support explicit `MEDIA:<path>` directives and file extraction in the gateway
platform boundary. Hermes Kanban workers can also name artifact paths when
completing a task.

Mentat already uses a different, narrower contract:

- `agent_console_artifacts.py` discovers only validated regular files inside a
  server-created, run-owned export directory;
- content is copied into project-owned private storage and exposed through
  opaque content URLs, never local filesystem paths;
- remote Kanban artifacts are imported only through Mentat's advertised,
  authenticated, digest-aware custom-host capability;
- assistant prose never selects an arbitrary file for browser exposure.

The exact stock Hermes 0.20.1 source does not expose the custom
`/v1/kanban/tasks/.../artifacts` manifest/download API Mentat currently
supports. Stock compatibility is therefore summary-only for remote Kanban
artifacts until an upstream equivalent exists; this remains an explicit 9I
fork-audit item.

### Decision

Mentat keeps its existing artifact implementation. It does not scan response
text for absolute paths, home-relative paths, Markdown file references, or
`MEDIA:` tokens. It does not open a path merely because Hermes or model prose
mentions it.

Future native artifact wakeups may mark a known run/task stale only when stock
Hermes offers a privacy-minimized event carrying a trusted run/task binding and
no path, filename, bytes, prompt, or response text. Mentat must then perform the
same authoritative API/export-directory read-back and validation it uses now.
The event is never completion proof and never a file-transfer channel.
For manual field edits, `on_kanban_task_updated` is the preferred observer
because it can identify changed field names without field values. It does not
cover claim, complete, or block transitions. A 9H Kanban contract therefore
needs an event-to-transition matrix and proof that outbound hooks register in
every dispatcher and worker process that can emit claim, complete, block, or
manual-update events. A `kanban_task_completed` payload may contain a private
summary and must be discarded after extracting only a verified binding/wakeup
hint. Missing processes/events still converge through periodic reconciliation.

## Voice

### Stock capability evidence

Stock Hermes documents microphone recording, STT, TTS, streaming speech,
voice replies, and barge-in in
`website/docs/user-guide/features/voice-mode.md` and
`website/docs/guides/use-voice-mode-with-hermes.md`. The implementation spans
native CLI/TUI/Desktop and messaging surfaces, optional Python/system
dependencies, local or cloud providers, browser/Desktop audio endpoints, and
active-turn interruption behavior.

Its authenticated Dashboard exposes profile-scoped `/api/audio/transcribe`,
`/api/audio/speak`, and `/api/audio/speak-stream` surfaces. They are not
advertised as stable `/v1` integration capabilities. Transcription is bounded
to 25 MiB and cleans up its temporary file, but the route's MIME declaration is
not itself byte-level format verification. Providers may be local or cloud;
cloud STT receives user audio and cloud TTS receives assistant text.

Mentat's local one-shot and remote Runs transports do not currently advertise
one common audio-input, transcription, streamed-audio-output, or barge-in
contract. A lifecycle event cannot supply one.

### Decision

Mentat does not add voice controls in Milestone 9. Native Hermes voice remains
available on its own supported surfaces.

A future Mentat voice slice must require:

1. explicit browser microphone permission from a direct user action and a
   visible recording state;
2. allowlisted audio types, strict byte/duration limits, bounded decoding, and
   no retained recording by default;
3. a declared local/cloud STT and TTS privacy boundary without exposing provider
   credentials or returning local audio paths, with explicit opt-in before
   cloud processing;
4. transcript preview/correction before a new run unless the user explicitly
   selects direct-submit mode;
5. capability-advertised, run-bound, post-verified steer/interrupt semantics for
   barge-in, with Stop remaining distinct;
6. accessibility and non-audio equivalents for every action.

Only visible assistant text may be spoken; hidden reasoning, tool results,
secrets, stale replies, and raw Markdown directives remain excluded.

Voice attachments during a running turn remain unsupported until the selected
Hermes transport explicitly advertises and verifies that exact operation.

## Relationship to Milestone 9H and 9I

9H may add only separately reviewed, privacy-minimized stock Hermes event
contracts. It must also add a Mentat-to-browser push channel before claiming
that Hermes webhooks replace browser polling. A2A messages, citation content,
artifact paths/bytes, audio, transcripts, prompts, tool arguments/results, and
model response text are not acceptable lifecycle projections.
In particular, `post_tool_call` can contain a search query and complete raw
result, A2A push can contain reply text, and `pre_transcription` can contain a
temporary audio path and provider details. None is an acceptable browser or
storage projection.

9I may retire a polling or custom telemetry path only after the matching native
event path passes compatibility, dropped-event convergence, rollback, and soak
evidence. This decision record does not claim that stock Hermes replaces
Mentat's approvals, continuation, provider mutation, artifact download, Kanban
mutation, or other command/API capabilities.

## Verification and rollback

Contract tests pin the four decisions, the exact stock provenance, the unchanged
four-event receiver allowlist, the no-path-scraping artifact rule, and the 9H/9I
entry gates. Browser smoke and Lighthouse are regression gates because 9G adds
no user-facing control. Rolling back 9G removes only documentation and tests;
it does not migrate runtime state or touch Hermes configuration.
