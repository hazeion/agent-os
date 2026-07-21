# Remote Hermes Beta Checks

Matrix version: **1**

Use this guide only with the exact Mentat candidate and verified Hermes build
named in the invitation. The maintainer prepares the connection and any
controlled failure state; testers never probe an endpoint or handle another
person's credential.

For every assigned check, record `pass`, `pass-with-help`, `blocked`, or
`not-run`. A row passes only when every numbered action has its same-numbered
pass result.
Record the matrix version, Mentat version, Hermes build, and outcome privately.
Public issues must not contain endpoints, hostnames, IP addresses, credentials,
private content, or unrestricted logs.

## Public connection liveness

- Performer: maintainer prepares the states; tester observes Mentat.
- Action 1: with the runtime live but authentication withheld, refresh Hermes
  health.
- Pass 1: Mentat never calls that state ready or healthy and reveals no private
  connection data.
- Action 2: after the maintainer restores the valid invitation connection,
  refresh again.
- Pass 2: Mentat can proceed through authenticated readiness.

## Authenticated readiness and capability discovery

- Performer: tester, after the maintainer restores the invited connection.
- Action 1: refresh Settings health and Hermes Capabilities.
- Pass 1: authenticated readiness and the supported capability inventory load
  together and match the invitation's expected safe state.

## Hermes configuration and overview summary

- Performer: tester.
- Action 1: inspect the selected connection summary and active agent/model status.
- Pass 1: the summary matches the invitation's safe labels and selected identity,
  while paths, headers, raw errors, endpoints, and credentials stay absent.

## Agent Console conversation and streaming

- Performer: tester.
- Action 1: send the invitation's harmless prompt and watch it finish.
- Pass 1: progress is visible and exactly one response completes.

## Run status, progress, approval, cancellation, and stopping

- Performer: tester using the invitation's disposable approval and long-run
  prompts; maintainer observes the private runtime status when assigned.
- Action 1: complete one bound approval request.
- Pass 1: the approved run resumes once and shows its verified state.
- Action 2: cancel a separate disposable run.
- Pass 2: Mentat shows the verified cancelled or already-terminal state.
- Action 3: stop another disposable long run.
- Pass 3: Mentat shows the verified stopped or already-terminal state.
- Action 4: inspect all three run summaries.
- Pass 4: each action stayed with its visible run and no upstream run ID appears.

## Clarification requests and responses

- Performer: tester using the invitation's disposable clarification prompt.
- Action 1: answer the visible typed question once.
- Pass 1: the same run resumes and completes without a second prompt submission.

## Session list, replay, continuation, and search

- Performer: tester.
- Action 1: finish a run containing the invitation's safe search phrase, then
  open and replay it from Sessions.
- Pass 1: the bounded transcript matches and no upstream session ID appears.
- Action 2: search for the safe phrase.
- Pass 2: the result opens the same projected transcript.
- Action 3: continue that session once.
- Pass 3: continuation stays in the same projected identity.

## Read-only agent/profile discovery

- Performer: tester.
- Action 1: open Agents and compare the visible active/profile choices with the
  safe profile list in the invitation.
- Pass 1: the list is bounded and accurate, remains read-only, and exposes no
  profile path, credential, or raw runtime record.

## Skill and toolset visibility

- Performer: tester.
- Action 1: open Settings → Hermes Capabilities and refresh it.
- Pass 1: advertised skill/toolset identifiers, enabled state, and counts appear;
  descriptions, contents, paths, and tool names do not.

## Durable Kanban delegation and follow-up

- Performer: tester with an invitation-provided disposable Mentat task.
- Action 1: preview and confirm delegation, then refresh its remote state.
- Pass 1: the exact task/intent was shown and the refreshed Hermes task verifies
  one delegation.
- Action 2: preview and confirm the assigned follow-up, then refresh again.
- Pass 2: the exact follow-up was shown and the refreshed task/run state verifies
  one result.

## Console input attachments and Context Packs

- Performer: tester using invitation-provided disposable text and image data.
- Action 1: apply one Context Pack and complete the harmless run.
- Pass 1: the bounded text reaches the run without a local path.
- Action 2: complete a separate run with one supported image.
- Pass 2: the image is accepted without revealing its local path.
- Action 3: try the assigned unsupported direct-file or artifact input.
- Pass 3: it fails clearly before remote submission.

## Connection setup and local/remote runtime selection

- Performer: maintainer performs the supported preview/confirmation operation;
  tester observes Mentat before and after the controlled change.
- Action 1: with no active run, change away and back to the invited connection.
- Pass 1: each confirmed idle change succeeds and the tester sees the selected
  mode without receiving connection secrets.
- Action 2: attempt a change during a disposable active run.
- Pass 2: the active run blocks the change.
- Action 3: after a confirmed change, try to reopen the pre-change session and
  submit the invitation's pre-change preview.
- Pass 3: both stale operations are refused.

## Hermes diagnostics

- Performer: maintainer prepares controlled unreachable, unauthenticated,
  degraded/unsupported, and restored-healthy states; tester refreshes Settings.
- Action 1: refresh Settings in the unreachable state.
- Pass 1: Mentat reports unreachable with bounded public wording.
- Action 2: refresh in the unauthenticated state.
- Pass 2: Mentat reports unauthenticated without exposing connection data.
- Action 3: refresh in the degraded/unsupported state.
- Pass 3: Mentat distinguishes degraded or unsupported and offers no unsafe
  unavailable control.
- Action 4: refresh after the maintainer restores healthy state.
- Pass 4: healthy status returns without revealing private transport data.

## Automated-only boundary evidence

These hostile/race checks are not implied by an external row result. They stay
release-gated by the named automated evidence because asking a cohort tester to
forge malformed server responses or replay private requests would be unsafe or
non-reproducible:

- malformed/missing capability and partial skill responses:
  `tests/test_remote_hermes.py` and `tests/test_remote_capability_inventory.py`;
- stream interruption without resubmission and stale clarification refusal:
  `tests/test_remote_console_runs.py`;
- compacted/partial session labeling: `tests/test_remote_sessions.py`;
- Kanban idempotency and duplicate-delegation refusal:
  `tests/test_hermes_kanban.py` and `tests/test_task_delegation.py`.

These tests must pass for the candidate, but their results are not recorded as
external tester `pass` evidence.
