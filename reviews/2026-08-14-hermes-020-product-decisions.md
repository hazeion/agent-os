# Feature Slice Review: Hermes 0.20 Product Decisions

Status: Locally successful; publication and CI pending
Slice: `hermes-020-product-decisions`
Date: `2026-08-14`
Review log: `reviews/2026-08-14-hermes-020-product-decisions.md`

## Slice contract

### Goal

Close Milestone 9G with four explicit, evidence-backed product decisions for
stock Hermes 0.20.1 A2A v1.0, grounded citations, deliverable artifacts, and
voice without treating release adjacency as webhook compatibility or creating
an unreviewed authority.

### In scope

- Inspect the immutable stock Hermes v0.20.1 tag `v2026.8.13`, commit
  `f80f453ae0679347e38abc917c7f94f717bf96c5`.
- Record one adopt, defer, or reject decision for each of A2A v1.0, grounded
  citations, deliverable artifacts, and voice.
- State each capability's authority, privacy, compatibility, verification,
  rollback, and future entry gates.
- Preserve Mentat's existing safe Markdown-link rendering, run-owned artifact
  discovery, and capability-gated remote Kanban artifact import.
- Add contract tests that prevent these product decisions from being
  mislabeled as webhook events or from authorizing direct Hermes-file writes,
  response-path scraping, or unverified browser audio/interrupt behavior.
- Reconcile the detailed Milestone 9 plan with the authoritative 9H and 9I
  slices already recorded in `ROAD_TO_BETA.md`, without modifying the user's
  current roadmap edits.
- Run focused and full tests, browser/computer-use regression, Lighthouse
  100/100/100/100, two independent adversarial reviews, and publish a stacked
  ready PR under the recorded standing approval.

### Out of scope

- Enabling, configuring, exposing, or proxying Hermes A2A.
- Parsing assistant prose into trusted citation objects.
- Importing files because a model response mentions a path or `MEDIA:` token.
- Adding microphone capture, transcription, TTS, voice-provider setup, or
  barge-in controls.
- Adding new outbound webhook events, accepting private tool/model payloads,
  retiring polling, or changing Kanban mutations; those belong to 9H/9I.
- Editing Hermes config, credentials, skills, conversations, audit logs, or
  other Hermes-owned files.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A versioned decision record covers all four named Hermes 0.20 surfaces and cites exact stock source entry points. | Decision document and immutable tag/commit provenance. | Pass |
| AC-2 | A2A remains a native Hermes opt-in capability outside Mentat until a separately approved remote-authority contract exists. | Authority/threat analysis and contract tests. | Pass |
| AC-3 | Grounded citations remain ordinary safely rendered response content; Mentat does not infer trusted provenance from prose. | Structured-output gap analysis and contract tests. | Pass |
| AC-4 | Existing Mentat artifact boundaries remain authoritative; Hermes response-path extraction is not imported. | Artifact comparison, existing safety tests, and decision contract. | Pass |
| AC-5 | Voice is deferred until a transport advertises explicit audio and verified interruption semantics with browser privacy controls. | Voice transport analysis and future entry gate. | Pass |
| AC-6 | None of the four decisions expands the signed webhook receiver or weakens loopback, privacy, confirmation, or read-back rules. | Exact receiver allowlist regression and documentation assertions. | Pass |
| AC-7 | Detailed planning includes 9H native-event migration and 9I fallback/fork audit without changing the user's dirty roadmap file. | Plan diff and worktree status. | Pass |
| AC-8 | Focused/full/browser/Lighthouse/reviewer/CI gates pass, including 100/100/100/100 Lighthouse. | Recorded verification and two independent reviewer conclusions. | Pending |

### Constraints and recovery

- Safety: documentation cannot become implicit authority. Any future product
  implementation must start a new reviewed slice with explicit capabilities.
- Compatibility: stock Hermes may use these features independently; Mentat
  neither requires nor disables them.
- Rendered behavior: this slice intentionally adds no controls. Computer-use
  verifies the current console, attachments, links, and Settings remain sound.
- Rollback: remove this slice's documentation/tests; no runtime state or Hermes
  configuration is migrated.
- Version-control strategy: branch `codex/hermes-020-product-decisions` stacked
  on the published 9F head `5235363`.

### Scope discussion and approval

- Recommendation and rationale: close 9G as a decision gate. Adding adapters
  simply because features share a Hermes release would conflate messaging,
  skill output, file delivery, audio transport, and webhook observation.
- Alternatives considered: expose all four immediately (rejected because no
  common authority or wire contract exists); call all four unsupported
  (rejected because stock Hermes may use them natively and Mentat already has
  compatible link/artifact behavior); fold them into 9H (rejected because 9H
  is specifically the privacy-minimized native-event migration).
- User decisions: the user requested the reviewed-feature-integration process,
  complete Milestone 9, perfect Lighthouse scores, computer-use verification,
  GitHub publication, and standing approval. That standing approval is
  recorded as a process exception for in-scope decisions and publication;
  destructive actions and scope expansion still require separate authority.
- Approved at: `2026-08-14`, under the user's standing approval instruction.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | 9G is one paragraph with no decisions. | Exact decision-table and stock-provenance assertions. | Every required surface has a durable disposition. | Source behavior is pinned to v0.20.1, not future Hermes releases. |
| AC-2 | No Mentat A2A policy exists. | Assert separate-authority, no-config-write, and non-webhook language. | A2A cannot silently widen Mentat or inject work through the receiver. | Does not test Hermes's own A2A implementation. |
| AC-3 | No citation trust policy exists. | Assert Markdown-only compatibility and structured-provenance entry gate. | Prose cannot become trusted source metadata. | Link correctness still belongs to the model/user. |
| AC-4 | Hermes deliverable mode and Mentat artifacts have different trust boundaries. | Assert no response-path/`MEDIA:` discovery and retain existing artifact tests. | Model prose cannot select local files for browser exposure. | Native Hermes messaging delivery remains outside Mentat. |
| AC-5 | Mentat has no voice transport contract. | Assert explicit microphone consent, bounded audio, transcript handling, and verified-steer prerequisites. | Voice cannot bypass browser privacy or active-run controls. | No audio device is exercised because no voice feature is added. |
| AC-6 | Release notes could be mistaken for webhook support. | Keep exact four-event receiver allowlist tests and assert all four 9G surfaces are non-webhook decisions. | Receiver scope remains unchanged. | 9H will separately assess additional stock event hooks. |
| AC-7 | Detailed plan stops at 9G. | Assert 9H/9I headings and their required migration/retirement gates. | The remaining milestone scope survives interruption. | User-owned roadmap status text remains intentionally untouched. |
| AC-8 | No 9G verification exists. | Focused/full suite, browser smoke, computer-use, Lighthouse, dual review, CI. | Documentation and unchanged product remain releasable. | Lighthouse is a deterministic local fixture, not a live provider run. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Exact stock checkout identity | Isolated Hermes source | Pass | `v2026.8.13` at `f80f453ae0679347e38abc917c7f94f717bf96c5`. |
| Stock A2A source/docs inspection | Exact checkout | Gap confirmed | A2A is an opt-in bidirectional platform that can inject tasks into a live Hermes session and persist Hermes-owned conversations/audit records. |
| Grounded-citations and `x_search` inspection | Exact checkout | Gap confirmed | The skill produces cited Markdown and xAI `x_search` has structured private tool results, but no provider-independent, privacy-minimized citation API/event is advertised; `degraded: false` does not prove citations exist. |
| Desktop/deliverable artifact inspection | Exact checkout plus Mentat source | Gap confirmed | Hermes Desktop indexes transcript paths/URLs and messaging accepts `MEDIA:` paths; Mentat deliberately discovers only files inside a trusted run-owned export boundary. Stock 0.20.1 lacks Mentat's custom remote Kanban artifact API. |
| Voice source/docs inspection | Exact checkout plus Mentat transports | Gap confirmed | Hermes has native microphone/STT/TTS/barge-in and authenticated Dashboard audio routes, but Mentat transports do not advertise an equivalent stable audio/interrupt integration contract. |
| Existing 9G plan | Mentat 9F head | Fail | One paragraph names four decisions but records none; detailed plan also omits 9H and 9I. |

### Test discussion and approval

- User questions and decisions: the user's standing approval covers the
  documented strategy, while the no-runtime-change nature of 9G keeps the
  implementation within the requested product-decision slice.
- Accepted coverage gaps: no A2A peer, citation provider, artifact generator,
  microphone, STT, or TTS integration run is claimed. Those would test features
  that this slice explicitly does not expose. Browser and Lighthouse checks
  remain mandatory regression gates.
- Approved at: `2026-08-14`, under the recorded standing approval exception.

## Implementation record

### Changes

- Added `HERMES_020_PRODUCT_DECISIONS.md` with a disposition, authority model,
  stock-source evidence, privacy constraints, and future entry gates for A2A,
  grounded citations/`x_search`, Desktop and messaging artifacts, and voice.
- Distinguished A2A task push from outbound lifecycle hooks: its wire contract
  differs and its payload can contain reply text.
- Distinguished the grounded-citations skill from xAI-specific structured
  `x_search` tool output. A non-degraded result is not treated as proof of a
  citation, and raw tool output remains private.
- Rejected Hermes Desktop/model-response path discovery for Mentat and retained
  only the run-owned export boundary. Recorded that stock 0.20.1 lacks Mentat's
  custom remote Kanban artifact manifest/download API and therefore remains
  summary-only for that capability.
- Deferred voice until a stable advertised transport, explicit browser audio
  permission/privacy, byte-level validation, local/cloud disclosure, and
  verified steer/interrupt semantics exist.
- Expanded the detailed Milestone 9 plan with 9H native-event migration and 9I
  fallback/fork audit, including the preference for value-minimized Kanban
  observer wakeups and authoritative read-back.
- Updated architecture and changelog context without adding runtime controls or
  modifying `ROAD_TO_BETA.md`.
- Added nine decision contract tests that pin stock provenance, all four
  dispositions, receiver non-expansion, artifact/citation/voice safety, and the
  remaining Milestone 9 slices.

### Deviations and decisions

- Initial inspection of the grounded-citations skill alone understated the
  stock surface. A separate upstream audit found structured citation arrays in
  the xAI `x_search` tool result. The decision was corrected to acknowledge the
  data while deferring UI until a provider-independent, privacy-minimized API
  exists.
- "Artifacts" covers both Hermes Desktop transcript-derived cards/gallery and
  messaging deliverable mode. Neither presentation mechanism changes Mentat's
  file authority.
- No production code or UI was added because 9G is the milestone's explicit
  product-decision gate. Implementing any deferred surface here would violate
  the approved scope rather than complete it.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_hermes_020_product_decisions -q` | Isolated 9G worktree | 0 | 9 passed | Exact decision and remaining-slice contracts. |
| Product decisions plus Console artifact, artifact integration, remote Kanban artifact, and webhook suites | Isolated 9G worktree | 0 | 45 passed | Existing byte authority and four-event receiver remain intact. |
| Next-phase, beta-contract, and CI-workflow suites | Isolated 9G worktree | 0 | 27 passed | Documentation and repository gates remain coherent. |
| `git diff --check` | Isolated 9G worktree | 0 | Pass | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | macOS host with loopback integration access | 0 | 1,031 passed, 4 skipped | Required post-fix full suite; skips are native-Windows-only platform coverage. |

Post-fix focused and full verification are current. Publication CI remains
pending.

### Package, browser, and quality gates

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python scripts/check_tracked_secrets.py` | Hash-locked isolated quality environment | 0 | Pass | No unreviewed tracked secret candidate. |
| `uv build` plus `scripts/verify_python_artifacts.py` | Isolated 9G worktree and temporary output | 0 | Wheel and sdist verified | No production/package inventory changed; private/runtime exclusions remain intact. |
| In-app browser computer-use | Isolated owner-only fixture, empty Hermes/Obsidian roots | Pass | Home and Settings inspected; signed probe accepted | Verified all dashboard APIs returned 200, the Console composer/attachment control remained available, Webhook Health changed to Receiving after the real probe, horizontal overflow was zero, and no A2A/voice/citation controls were introduced. |
| Lighthouse 13.4.1 desktop/provided audit | Same isolated fixture after server stabilization | 0 | 100/100/100/100 | Performance 100, Accessibility 100, Best Practices 100, SEO 100; FCP 478 ms, LCP 582 ms, TBT 0 ms, CLS 0.028. Compact evidence: `reviews/2026-08-14-hermes-020-product-decisions-lighthouse.json`. |

The first corrected-fixture cold audit scored 97/100/100/100 because the
connection-status render made LCP 1.34 seconds. It was not accepted. The exact
gate was rerun after the isolated server stabilized and reached the required
100/100/100/100 without changing product bytes. An earlier attempt had no
scores because the sandbox blocked the listener and is excluded as invalid
environmental evidence.

## Reviewer rounds

### Round 1

- Reviewer A reported four blocking or material findings:
  - P1: future A2A criteria did not prohibit browser-supplied/direct URLs or
    require redirect, DNS-rebinding, private/link-local/metadata, and Agent Card
    endpoint-substitution tests.
  - P1: `on_kanban_task_updated` does not cover claim/complete/block and the 9H
    gate lacked dispatcher/worker emitter-registration evidence.
  - P2: A2A push is only optionally signed; a push secret or shared bearer token
    is required, while per-peer tokens alone do not provide the fallback.
  - P2: the receiver allowlist test checked presence rather than exact equality.
- Reviewer B independently corroborated the allowlist finding and reported a P2
  milestone-integrity gap: phrase checks did not prove 9H/9I remained Pending or
  retained their complete migration, privacy, and retirement gates.
- Disposition: all findings accepted. A2A now permits only configured peer
  aliases and requires a callback secret plus explicit SSRF/rebinding coverage;
  signing language is conditional; the Kanban plan requires an event-transition
  matrix, dispatcher/worker registration, and absent-emitter reconciliation;
  the test imports `ALLOWED_EVENTS` and asserts exact equality; and bounded 9H
  and 9I sections are asserted Pending with their complete required conditions.
- Post-fix focused decision tests: 9 passed.

### Round 2

- Reviewer A verified the Round 1 corrections and reported two remaining
  findings:
  - P1: the A2A future gate named SSRF/rebinding attack classes but did not
    require executable evidence for every class, configured-peer enforcement,
    unsigned/invalid callback rejection, or exact task/context/peer HMAC
    binding before authoritative read-back.
  - P2: this persistent log had not yet recorded the accepted Round 1
    findings, corrections, and current re-review state.
- Reviewer B reported no findings and independently verified the exact receiver
  allowlist, bounded Pending 9H/9I contracts, conditional A2A-signing language,
  Kanban event/process coverage, and focused verification.
- Disposition: both Reviewer A findings accepted. The decision now requires
  executable negative-path tests for each enumerated destination attack,
  configured-peer-only selection, missing/invalid signature rejection, and
  exact task/context/peer HMAC binding before authoritative read-back. This log
  now preserves both rounds and their dispositions.

### Round 3

- Reviewer A reported **No findings**. It verified the configured-peer-only A2A
  boundary, executable destination-attack tests, callback signature rejection,
  exact task/context/peer HMAC binding, exact receiver allowlist, Kanban
  emitter/reconciliation requirements, review history, and Lighthouse evidence.
- Reviewer B reported **No findings**. It independently verified the same A2A
  corrections, preserved 9H/9I contracts, exact receiver allowlist, no runtime
  or UI changes, and focused checks.
- Gate result: both original independent reviewers found no blocking or
  non-blocking issues in the complete corrected slice. Both finished reviewer
  agents were closed after their conclusions were recorded.

## Documentation and publication

- Documentation updated: `HERMES_020_PRODUCT_DECISIONS.md`, `ARCHITECTURE.md`,
  `CHANGELOG.md`, and `MILESTONE_9_WEBHOOK_IMPLEMENTATION_PLAN.md`.
- Verification artifacts: this log, the compact Lighthouse JSON evidence, and
  the decision-contract test module.
- Proposed publication inventory is exactly seven files:
  `ARCHITECTURE.md`, `CHANGELOG.md`,
  `MILESTONE_9_WEBHOOK_IMPLEMENTATION_PLAN.md`,
  `HERMES_020_PRODUCT_DECISIONS.md`,
  `tests/test_hermes_020_product_decisions.py`, this review log, and
  `reviews/2026-08-14-hermes-020-product-decisions-lighthouse.json`.
- Branch: `codex/hermes-020-product-decisions`.
- Base: `codex/hermes-020-live-validation` at `5235363`.
- Commit message and ready PR title: `docs: record Hermes 0.20 product decisions`.
- PR summary: record the four 9G decisions and safety gates, preserve the exact
  four-event webhook receiver, and make 9H/9I explicit Pending slices.
- Unresolved implementation risk: none. Deferred features remain intentionally
  unavailable until their separate entry gates are met.
- Authorization: the user explicitly instructed the workflow to assume approval
  for in-scope features and publication. This standing-approval process
  exception authorizes staging only the seven files above, committing, pushing,
  and opening a ready (non-draft) stacked PR. It does not authorize destructive
  actions or scope expansion.
- Commit hash and ready PR URL: pending publication.

## Outcome review

- Classification: locally successful; publication CI pending.
- Acceptance criteria: AC-1 through AC-7 pass; AC-8 has passing focused, full,
  package, computer-use, Lighthouse, secret-scan, and dual-review evidence, with
  ready-PR CI still pending.
- Potential bugs or untested paths: no runtime surface was added. Deferred A2A,
  structured citations, response-path artifact discovery, and voice paths were
  intentionally not exercised or exposed.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback: documentation/tests only; rollback removes
  these seven files/edits and requires no runtime or Hermes-state migration.
- User decision: standing acceptance applies after the ready PR is green.
- Next slice authorized: 9H, after 9G publication and CI succeed.
