# Mentat - Website-to-Agent Messaging Plan

Created: 2026-06-25
Related: Obsidian: `Mentat - Website-to-Agent Messaging Plan.md`
Repo reference: `E:/code/agent-os/docs/website-to-agent-messaging-plan.md`

## Purpose

Add a safe, local-first way to send a message from the Mentat website to an agent or agent context. This should extend Agent Pulse and task/replay workflows without giving the browser unrestricted power to run shell commands or mutate Hermes core files.

## Product goal

From Mentat, Brandon should be able to:

1. See which agents or agent contexts are available.
2. Pick a recipient or context.
3. Send a message / instruction / question.
4. See whether that message is queued, acknowledged, being worked, answered, failed, or needs Brandon follow-up.
5. Link the message to a task, replay, project, or Agent Pulse record when useful.

## Recommended v1 shape

Start with a project-owned message queue and API instead of full live chat.

### Data store

Use a project-owned local JSON file:

```text
data/agent_messages.json
```

Suggested message fields:

```json
{
  "id": "msg_<uuid>",
  "recipient_type": "agent|project|default_assistant",
  "recipient_id": "optional stable agent id",
  "project": "Mentat",
  "related_task_id": null,
  "related_session_id": null,
  "body": "message text",
  "status": "queued|acknowledged|running|answered|failed|cancelled",
  "priority": "normal|high",
  "created_by": "Brandon",
  "created_at": "iso timestamp",
  "updated_at": "iso timestamp",
  "acknowledged_at": null,
  "answered_at": null,
  "response_summary": null,
  "response_payload": null,
  "error": null
}
```

### API contract

Initial routes:

```text
GET  /api/agent-messages
POST /api/agent-messages
POST /api/agent-messages/<id>/status
```

Later routes, only when needed:

```text
POST /api/agent-messages/<id>/cancel
POST /api/agent-messages/<id>/link-task
```

### Dashboard UI

Good first placement:

- Agent Pulse panel: compact "Send message" button or compose drawer.
- Agents / Sessions page: larger compose surface with recipient selector and message history.
- Selected Task inspector later: "Ask agent about this task" action.

V1 controls:

- recipient selector
- message textarea
- optional related task/session context
- submit button
- status/history list

## Relationship to Agent Pulse

Agent Pulse should surface message state, not become a full chat database.

Recommended coupling:

- If an agent has queued messages, show a small `messages pending` pill.
- If a message is running, show it as current task context when the producer acknowledges it.
- If an agent needs Brandon input, reuse the existing `needs_user_input` signal.
- Keep `data/agents.json` for live status and `data/agent_messages.json` for message history.

## Agent consumer model

Do not assume every agent can consume messages immediately.

Possible consumers:

1. **Manual/Hermes consumer** — Hermes reads pending messages and acts on them.
2. **Wrapper consumer** — `scripts/agent_heartbeat.py run` or a future helper polls messages for a specific `--agent-id`.
3. **Default assistant consumer** — a local default worker checks queued messages and writes responses.
4. **Future Hermes-native consumer** — deeper integration if Hermes exposes a safe local API/gateway.

Recommended v1: build the queue/API/UI first, then wire one simple consumer path after the safety and status model are stable.

## Safety boundaries

Hard rules:

- Keep the feature local-only by default.
- Write only to project-owned data files.
- Do not mutate Hermes core files.
- Do not allow arbitrary shell execution directly from browser input.
- Treat messages as instructions requiring an agent/worker to interpret, not commands to execute.
- Add audit trail fields for who sent the message, when, target, status, and response/error.
- Validate payload size and required fields.
- Escape rendered message and response content.

## Testing checklist

Backend behavior tests:

- Creating a valid message writes to `data/agent_messages.json`.
- Invalid payloads are rejected.
- Message status transitions are validated.
- API never writes outside allowlisted project-owned data files.
- Message list is sorted newest-first or by status as documented.

Frontend/contract tests:

- Compose control exists in the intended view.
- Recipient selector uses stable native controls unless a richer widget is justified.
- Empty, queued, running, answered, and failed states render honestly.
- Agent Pulse shows pending-message indicators without duplicating full chat history.

Browser smoke path:

- Load Today View.
- Open Agent Pulse / Agents page.
- Submit a message.
- Confirm it appears as queued.
- Confirm status update renders.

## Implementation phases

### Phase A — Prep / cleanup

- Review Wilson big-file recommendations: `docs/wilson-code-review-2026-06-25.md`.
- Add browser smoke-test foundation.
- Organize CSS/app.js enough that new messaging UI does not make hotspots worse.

### Phase B — Queue and API

- Add `data/agent_messages.json` seed.
- Add validation helpers.
- Add `GET /api/agent-messages`.
- Add `POST /api/agent-messages`.
- Add status update route.
- Add tests.

### Phase C — UI v1

- Add compose surface to Agents / Sessions or Agent Pulse.
- Add message status list.
- Add pending-message pill in Agent Pulse.
- Smoke test live dashboard.

### Phase D — Consumer bridge

- Add a simple polling helper or extend heartbeat producer guidance.
- Prove one queued message can be acknowledged and answered without browser shell execution.
- Keep deeper Hermes-native chat for a later deliberate integration.

## Open decisions

- Should the first compose surface live in Today / Agent Pulse, Agents / Sessions, or both?
- Should v1 messages target a specific `agent_id`, the `Mentat` project, or a default assistant?
- Should responses be free text only, or can they suggest project-owned task writes?
- Should messages expire/archive after a retention period?
- Should message sending require a local confirmation if remote access is ever enabled?

## Task references

- `task_agent_messaging_plan_20260625` — planning note created.
- `task_agent_messaging_v1` — implementation task.
- `task_browser_smoke_tests_before_agent_messaging` — quality gate before heavier interactions.
- `task_appjs_view_modularization_before_chat` — frontend hotspot cleanup.
- `task_server_api_domain_split_before_chat` — backend hotspot cleanup.
