# Feature Slice Review: Real HTTPS Hermes interoperability matrix

Status: Published in ready PR #58
Slice: `beta-2-real-https-matrix`
Date: `2026-07-24`
Review log: `reviews/2026-07-24-beta-2-real-https-matrix.md`

## Slice contract

### Goal

Close the remaining Milestone 2 interoperability gate by exercising Mentat's
mandatory remote-Hermes surface against one real operator-managed Hermes
runtime over certificate-verified HTTPS and API-key authentication.

### In scope

- Verify the already-selected remote connection through Mentat without reading,
  printing, or copying its stored API key.
- Exercise the required safe read paths and disposable user workflows from
  `REMOTE_BETA_MATRIX.md` that demonstrate the maintained Hermes runtime works
  through Mentat's HTTPS transport.
- Run the automated hostile, race, privacy, stale-binding, and failure-path
  coverage that is intentionally unsafe or impractical to reproduce manually.
- Record only bounded public evidence: Mentat/Hermes versions, capability
  outcomes, test counts, and safe synthetic prompts.
- Update Milestone 2 status and evidence only if every required criterion is
  proven.

### Out of scope

- Publishing the private endpoint, API key, private network details, raw
  upstream payloads, or operator content.
- Weakening path/credential-shaped content checks to make existing remote
  history render.
- Deleting remote session or Kanban history.
- Claiming the later external-cohort matrix, signed release rehearsal, or
  public beta gates.
- Adding remote profile, provider, credential, MCP, skill-content, or general
  file administration.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Mentat selects one remote Hermes runtime only after certificate-verified HTTPS authentication and exact capability discovery. | Connection result and Settings health/capability inspection. | Pass |
| AC-2 | A fresh remote Console run streams progress and completes exactly once without exposing upstream identity. | Safe synthetic WebUI run. | Pass |
| AC-3 | Remote profiles, skills/toolsets, sessions, continuation/search, interactions, Kanban, Context Packs/images, connection binding, and diagnostics meet their required contract outcomes. | Safe matrix actions plus focused automated evidence. | Pass |
| AC-4 | Credentials, endpoints, host details, private or opaque upstream IDs, paths, and private content stay out of browser-visible and tracked evidence. | Browser inspection, secret scan, and diff review. | Pass |
| AC-5 | Focused remote suites and the full repository suite pass without weakening existing tests. | Exact verification commands and counts. | Pass |
| AC-6 | Roadmap, remote contract, changelog, and prior Milestone 2 outcome log accurately describe the resulting evidence and remaining limits. | Documentation tests and inspection. | Pass |
| AC-7 | Two independent adversarial reviewers clear the complete slice after any accepted fixes. | Review packets and final review round. | Pass |

### Constraints and recovery

- Safety: use only Mentat's fixed capability-gated operations; never extract the
  stored credential or call arbitrary remote paths.
- Compatibility: local mode and unsupported-runtime degradation remain
  unchanged.
- Rendered behavior: verify bounded safe labels and actionable/unavailable
  states in the real WebUI.
- Rollback or recovery: documentation-only evidence changes can be reverted;
  disposable remote runs remain ordinary retained Hermes history.
- Documentation targets: `ROAD_TO_BETA.md`, `REMOTE_HERMES.md`,
  `CHANGELOG.md`, the prior Milestone 2 outcome log, and this log.
- Version-control strategy: `codex/beta-2-real-https-matrix` into `main`.

### Scope discussion and approval

- Recommendation and rationale: close the earliest remaining beta gate with
  real HTTPS evidence before protected signing and cohort work.
- Alternatives considered: treat the successful connection probe as the whole
  matrix (rejected because it does not prove user workflows), or wait for the
  external cohort (rejected because maintainer interoperability is a separate
  Milestone 2 prerequisite).
- User decisions: the project owner directed continuation through the complete
  Road to Beta, approved all slices and pull requests in advance, and reported
  the selected real WebUI connection healthy.
- Process exception: this standing authorization replaces the skill's separate
  scope, test, publication, and outcome pauses. The required evidence and
  two-reviewer gates remain unchanged.
- Approved at: 2026-07-24 through the active Road-to-Beta goal and standing
  authorization.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Loopback runtime and separate TLS tests existed, but no real HTTPS selection had passed. | Inspect the successful connection result and current Settings health. | Real certificate, bearer authentication, schema, version, and capability discovery interoperate. | Does not exercise every mutation. |
| AC-2 | Prior run evidence used the loopback runtime. | Submit one bounded exact-reply prompt in the WebUI and observe progress plus terminal output. | The selected HTTPS transport handles submission, events, status, and completion. | Does not force an interactive event. |
| AC-3 | Required rows were implemented but not all exercised on this endpoint. | Follow safe matrix actions; pair them with the named automated-only suites. | Mandatory reads, mutations, bindings, and degradation rules work together. | Provider-driven approval and clarification prompts may be nondeterministic. |
| AC-4 | The live endpoint contains real operator state. | Inspect only normalized WebUI surfaces; run tracked-secret and diff checks. | Evidence remains public-safe. | Browser inspection cannot prove untracked runtime storage contents. |
| AC-5 | The last merged full suite predated this real endpoint. | Focused remote suites, then full discovery suite. | Existing safety and compatibility contracts remain green. | Hosted OS matrix remains GitHub evidence. |
| AC-6 | Roadmap still says real HTTPS is pending. | Focused documentation tests and manual consistency review. | Project records do not overclaim or omit the new proof. | Documentation cannot replace runtime evidence. |
| AC-7 | No review exists for this new evidence slice. | Two independent read-only reviews, fixes, retest, and re-review. | Correctness, safety, compatibility, product, and evidence quality receive independent challenge. | Reviewers cannot independently access the private endpoint. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Confirm remote selection through Mentat | macOS Mentat to operator-managed WSL Hermes | Pass | Certificate-verified HTTPS, bearer authentication, Hermes `0.19.0`, healthy readiness, and exact capabilities accepted; credential omitted. |
| Settings → Hermes Capabilities and Subsystem Health | Mentat WebUI | Pass | Remote label, healthy state, safe version/model summary, 75 skills, and 13 of 25 enabled toolsets shown without endpoint or credential. |
| Safe exact-reply Console run | Mentat WebUI to remote Hermes | Pass | One submission showed queued, submitted, working, reasoning, terminal, and complete states; exact bounded response returned once. |
| Agents profile inventory | Mentat WebUI | Pass | One bounded active `default` profile shown; unsupported remote identity/provider mutations remain disabled. |
| Session History | Mentat WebUI | Expected fail-closed baseline | A recent upstream transcript contains private/path-shaped content, so the all-or-nothing recent window is blocked rather than leaked. No content was copied into this log. |
| `python3 -m unittest tests.test_remote_hermes tests.test_remote_console_runs tests.test_remote_sessions tests.test_remote_capability_inventory tests.test_hermes_kanban tests.test_task_delegation -v` | macOS, Python 3.13 | Pass | 117 passed, 0 failed, 0 skipped. |

### Test discussion and approval

- User questions and decisions: standing authorization applies; do not pause
  between safe Road-to-Beta slices.
- Accepted coverage gaps: provider wording after the accepted approval remained
  misleading, but exact transport evidence proved the bound response resumed
  once. Approval and clarification control-plane behavior both passed.
- Approved at: 2026-07-24 under the recorded process exception.

## Implementation record

### Changes

- Project completed remote run session identity into a connection-bound opaque
  alias so the next turn can request the exact continuation descriptor without
  exposing the upstream session ID.
- Accepted and normalized Hermes' advertised
  `waiting_for_clarification` run state.
- Split the outbound Runs request ceiling from the much smaller response
  ceiling, allowing the advertised bounded image input while retaining the
  per-image and aggregate limits.
- Distinguished deterministic local/HTTP request rejections from ambiguous
  submission responses so 429 and server failures remain partial and
  unverified instead of encouraging a duplicate run.
- Rebound Kanban action confirmations to the persisted Mentat task and exact
  remote revision rather than a newly generated synchronization timestamp,
  then rechecked the stable profile/board/task binding under the shared
  mutation lock.
- Serialized delegation refresh across its remote read and persistence so it
  cannot overwrite a confirmed action with a stale pre-action snapshot.
- Added focused regression coverage for every change.

### Deviations and decisions

- Existing remote history exercised the intended fail-closed content boundary.
  Twelve safe synthetic sessions moved the unsafe transcript outside the
  bounded recent window without deleting operator history or weakening the
  content guard.
- The first approval prompts used commands that Hermes classified as harmless.
  A disposable command targeting a nonexistent marker produced the required
  bound approval request; one `Allow once` response resumed the same run.
- The first supported full-size image failed before submission because the
  client reused the response-size ceiling. A 9 KB image proved the rest of the
  path, the ceiling was fixed, and the original 779 KB image then completed
  through the WebUI.
- The first Kanban result-acceptance confirmation failed closed as stale on
  every attempt because its token included a fresh sync timestamp. The binding
  was corrected and the same live action then confirmed once. The disposable
  Mentat task and Context Pack were removed after verification; ordinary
  retained Hermes history remains.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| Remote focused suite command above | macOS, Python 3.13 | Exit 0 | 117 passed | Includes TLS/auth/schema, Console, session, capability inventory, Kanban, and delegation boundaries. |
| `python3 -m unittest tests.test_remote_console_runs tests.test_task_delegation -v` | macOS, Python 3.13 | Exit 0 | 36 passed | Covers continuation projection, clarification status, image request sizing, deterministic/uncertain submission classification, and timestamp-independent, stable-binding Kanban confirmation. |
| `python3 -m unittest tests.test_beta_contract -q` | macOS, Python 3.13 | Exit 0 | 12 passed | Verifies the updated milestone count, remote contract, roadmap wording, and first-user README contract. |
| `python3 -m py_compile server.py remote_hermes.py hermes_transport.py` | macOS, Python 3.13 | Exit 0 | 3 modules | Syntax check. |
| Targeted endpoint/key pattern scan plus `git diff --check` | Tracked slice files | Exit 0 | 0 matches; clean diff | Confirms the private endpoint/key were not copied into evidence and no whitespace errors remain. |

### Full suite

The final `python3 -m unittest discover -s tests -q` rerun passed on macOS with
Python 3.13 after all accepted reviewer fixes: 768 passed, 0 failed, and 4
platform-specific skips in 157.497 seconds.

### Rendered or manual behavior

- Current selected connection renders healthy with only its operator-provided
  safe label, Hermes `0.19.0`, model label, readiness, and normalized counts.
- A fresh exact-reply Console run completed once over the selected remote
  transport.
- Unsafe recent session content failed closed with bounded public wording. A
  safe 12-session window then listed, replayed, and searched with explicit
  coverage limits.
- A fresh two-turn Console conversation remained in one remote session after
  safe alias projection.
- One clarification choice and one approval choice resumed their exact paused
  runs; stop and immediate-stop race checks both reached verified cancellation.
- One path-free Context Pack run and separate 9 KB and 779 KB image runs
  completed. A direct text-file attachment failed clearly before remote
  submission.
- A disposable Mentat task previewed and created exactly one remote Kanban
  task, refreshed to one result, previewed result acceptance, and completed
  with one audit action after the confirmation-binding fix.
- Unsupported profile/provider administration stayed visible but disabled.
- Live invalid-certificate and missing-authentication setup attempts returned
  bounded errors; automated diagnostics cover unreachable, degraded,
  unsupported, stale-binding, and active-run cases without disrupting the
  selected runtime.

## Adversarial review

### Round 1

Two independent read-only reviewers received the same scope, acceptance
criteria, constraints, live evidence, and test packet with different review
emphases.

- Correctness/security review: found that unexpected POST status handling made
  429/5xx submissions look definitively rejected, and that the Kanban
  lock-time check covered only the remote task ID rather than the stable
  profile/board/task binding.
- Product/evidence review: independently found the same submission ambiguity,
  plus two evidence-log wording contradictions.
- Cross-critique: both reviewers accepted the submission finding as blocking;
  both accepted stable binding plus serialized refresh as the appropriate
  Kanban fix without rebinding to changing timestamps; both agreed the
  evidence wording findings were documentation precision issues.

### Accepted fixes

- Only explicit request-rejection statuses `400`, `404`, `405`, `413`, `415`,
  and `422` are definitive for run submission. `429`, `500`, `502`, and other
  ambiguous responses remain partial/unverified. Regression coverage exercises
  those real status paths.
- Kanban action execution compares normalized profile, board, and task binding
  under `HERMES_KANBAN_LOCK`; refresh holds the same lock across local read,
  remote read, and persistence. A regression changes board/profile between
  preview recomputation and lock-time validation.
- AC-4 now distinguishes safe advertised profile metadata from private/opaque
  upstream IDs, and the interaction discussion records the completed result
  rather than a stale pre-execution requirement.

### Round 2

Both reviewers found no remaining code, security, compatibility, privacy, or
roadmap-scope issue. They correctly held final clearance until the focused and
full-suite evidence was rerun against the accepted fixes. The final evidence is
117 focused tests, 36 Console/delegation tests, and 768 complete-suite tests,
all passing with four platform-specific full-suite skips.

### Final clearance

Both reviewers cleared the corrected code and evidence with no remaining
findings after one final mechanical count correction.

## Documentation updates

- Roadmap: records Milestone 2 complete for the maintained Hermes `0.19.0`
  contract while retaining signed-RC and external-cohort gates.
- Changelog: records the real HTTPS matrix and five live-found fixes.
- Architecture/operator docs: `REMOTE_HERMES.md` records the verified runtime,
  corrected profile-inventory status, and capability-driven compatibility.
- Project/session notes: this log.
- Prior evidence: the merged Milestone 2 contract log now records PR #50 and
  links its later real-HTTPS follow-up.
- Documentation verification: the focused 12-test beta-contract suite and the
  complete 768-test repository suite pass.

## Publication gate

- Proposed files: `remote_hermes.py`, `hermes_transport.py`, `server.py`,
  `tests/test_remote_console_runs.py`, `tests/test_task_delegation.py`,
  the Milestone 2 assertion in `tests/test_beta_contract.py`,
  `ROAD_TO_BETA.md`, `REMOTE_HERMES.md`, `CHANGELOG.md`, the prior Milestone 2
  review log, and this review log.
- Branch and base: `codex/beta-2-real-https-matrix` → `main`.
- Commit message: `Record verified HTTPS Hermes interoperability`
- PR title: `Close the real HTTPS Hermes interoperability gate`
- PR summary: verified HTTPS matrix evidence plus live-found continuation,
  clarification, image-size, rejection-classification, and Kanban-binding
  fixes.
- Unresolved risks: the later protected signed-RC, second-person clean-platform,
  external-cohort, and final-promotion gates remain intentionally open.
- User authorization and scope: standing Road-to-Beta authorization recorded
  above.
- Reviewed implementation commit: `4936a3d`.
- Ready PR: [#58](https://github.com/hazeion/agent-os/pull/58).

## Outcome review

- Classification: Accepted; ready to publish.
- Acceptance criteria summary: AC-1 through AC-7 pass.
- Potential bugs or untested paths: provider output after the accepted approval
  said it was awaiting approval even though transport evidence proved one
  exact resume; this is retained as a provider-output quirk rather than a
  control-plane failure.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: none observed.
- User decision: standing authorization to continue.
- Next slice authorized: standing authorization applies only after this slice's
  required gates pass.
