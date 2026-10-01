# Mentat implementation roadmap

Status: active · updated September 24, 2026

This is the short resume map. It records sequence and evidence, not authority to
implement a provisional slice. Use [AGENTS.md](AGENTS.md) and
[ARCHITECTURE.md](ARCHITECTURE.md) for implemented contracts and safety
boundaries, [CONTEXT.md](CONTEXT.md) for language, and
[MENTAT_WEB_DESIGN.md](MENTAT_WEB_DESIGN.md) for website work. Read the active
GitHub issue and its narrow review record before changing architecture.
Historical detail belongs in issues, reviews, and pull requests.

## Destination

The [approved Wayfinder map](https://github.com/hazeion/agent-os/issues/234)
targets one owner on an always-on Linux Mentat host, authenticated from ordinary
browsers. Guided CLI setup attaches the owner's Google OIDC application and
providers. The owner creates Projects and Tasks, assigns Agents manually or
reviews a lead Agent's plan, approves bounded work between checkpoints, and
reviews versioned results in one durable Inbox. The garage acceptance journey
uses owner-supplied goals and floorplan measurements to produce a dimensioned
layout, linked editable shopping document, and implementation order. It must
ask for missing dimensions rather than invent them.

Python owns Tasks, Runs, context, files, credentials, and adapter authority.
The browser reaches only fixed, owner-authenticated Node capabilities. Existing
local operation remains available; browser access never grants provider consent.
No task, plan, Inbox item, or model prose silently approves execution, grants
context, retries uncertainty, purchases anything, or sends an external message.

## Current position

The old Beta/MDA foundation is merged through
[PR #231](https://github.com/hazeion/agent-os/pull/231) and
[PR #233](https://github.com/hazeion/agent-os/pull/233). The newer owner
workflow is a stack of **full, open PRs** starting at
[PR #243](https://github.com/hazeion/agent-os/pull/243) and currently ending
at [PR #281](https://github.com/hazeion/agent-os/pull/281). The PRs being open
is not merged-product or issue-close evidence. Hosted CI and ordinary review
remain gates. [PR #276](https://github.com/hazeion/agent-os/pull/276) is a
separate Windows CI-shard correction based on the results-review UI branch;
integrate it deliberately when advancing that part of the stack.

- [Baseline and fresh-install readiness](https://github.com/hazeion/agent-os/issues/235):
  PRs [#243](https://github.com/hazeion/agent-os/pull/243)–[#245](https://github.com/hazeion/agent-os/pull/245)
  address readable next-Run objectives, Task/Run completion, navigation, and
  responsive/transcript findings. The older
  [fresh-install audit](https://github.com/hazeion/agent-os/issues/223) and
  residual QA tickets remain open until current-main acceptance proves them.
- [Google owner access](https://github.com/hazeion/agent-os/issues/241):
  the [OIDC contract](https://github.com/hazeion/agent-os/issues/236) is
  resolved. Full PRs [#247](https://github.com/hazeion/agent-os/pull/247),
  [#249](https://github.com/hazeion/agent-os/pull/249),
  [#252](https://github.com/hazeion/agent-os/pull/252),
  [#254](https://github.com/hazeion/agent-os/pull/254),
  [#255](https://github.com/hazeion/agent-os/pull/255),
  [#258](https://github.com/hazeion/agent-os/pull/258), and
  [#259](https://github.com/hazeion/agent-os/pull/259) contain the verifier,
  one-use login, owner-session, host-admin setup, and
  website sign-in slices. Operator-owned Google configuration, live
  cross-device login, Linux/Caddy activation, recovery, and revocation need
  real-host acceptance. The independent
  [non-loopback security gate](https://github.com/hazeion/agent-os/issues/10)
  also requires a human security review before activation. Do not claim
  remote readiness from fixture tests.
- [Project context and deliverables](https://github.com/hazeion/agent-os/issues/238):
  PRs [#264](https://github.com/hazeion/agent-os/pull/264)–[#272](https://github.com/hazeion/agent-os/pull/272)
  cover owner context grants, exact Task inputs, retained Run-input evidence,
  editable garage results, and exact three-result owner review. Trusted
  generated-output promotion and qualified Project execution remain missing.
  Child [input admission](https://github.com/hazeion/agent-os/issues/262)
  and [generated deliverables](https://github.com/hazeion/agent-os/issues/263)
  are not complete.
- [Approved plans and handoffs](https://github.com/hazeion/agent-os/issues/239):
  [PR #273](https://github.com/hazeion/agent-os/pull/273) stores owner-edited
  immutable plan versions and [PR #274](https://github.com/hazeion/agent-os/pull/274)
  provides the owner editor. Version-1 plans lack immutable allowed-operation
  policy and cannot receive execution approval. Agent-authored proposals,
  qualified adapter enforcement, exact approval, budget debit, checkpoint
  admission, and scoped handoffs are still absent. The
  [runtime candidate research](https://github.com/hazeion/agent-os/issues/237)
  is resolved; real Linux runtime qualification is not.
- [Project review and owner Inbox](https://github.com/hazeion/agent-os/issues/240):
  PRs [#275](https://github.com/hazeion/agent-os/pull/275) and
  [#277](https://github.com/hazeion/agent-os/pull/277)–[#281](https://github.com/hazeion/agent-os/pull/281)
  retain exact Project review items and Run outcomes, then show them in a
  unified owner Inbox and Home attention card. Run notices cannot retry work.
  Trusted plan-approval requests, Agent questions, checkpoint decisions, and
  coordinated revision routing still need canonical sources and exact guards.
  See the [Run Inbox review](reviews/2026-09-24-run-attention-contract.md).
- [Complete garage journey](https://github.com/hazeion/agent-os/issues/242):
  built synthetic desktop/mobile paths prove preparation and owner review
  surfaces, but not approved Agent execution, real provider qualification,
  operator-supplied garage inputs, or integrated cross-device acceptance.

## Next frontier

1. Clear the open PR stack's CI/review findings, preserve the full PRs, and
   advance merge decisions through the normal repository review flow. Recheck
   the old QA tickets against merged main; close only a finding with direct
   current-main or integrated-browser evidence.
2. For Project execution, first record the policy-bearing immutable plan
   format, exact owner approval, budget/checkpoint receipts, and a real
   capability-qualified runtime operation. Prove prepared-file containment,
   allowed tools, time/work ceilings, interruption, and no-follow cleanup on
   the actual Linux host before advertising dispatch. Agent proposals must
   come from a trusted producing Run, never arbitrary model prose. Preserve
   manual assignment.
3. Extend the canonical Project/Run sources for generated deliverable
   promotion, missing-dimension questions, checkpoint approvals, and
   coordinated change requests. The Inbox may index only those exact source
   generations. Keep unknown external outcomes visible and unretried.
4. Qualify operator-configured Google sign-in, recovery, session revocation,
   CLI onboarding, and the disabled-until-proven Linux/Caddy profile from
   ordinary desktop/mobile browsers. Do not invent domains, credentials,
   garage measurements, or provider readiness.
5. Repeat the complete garage journey on an integrated supported host, record
   actual fixtures/devices/provider evidence, then reconcile child issues and
   the [current Wayfinder map](https://github.com/hazeion/agent-os/issues/234).
   The [older access map](https://github.com/hazeion/agent-os/issues/171) is
   closed as superseded tracking, not proof that remote access shipped. Issue closure
   requires evidence, not a published PR.

## Working rules

- Work from a focused `codex/` branch. Keep Python authoritative and Node
  capabilities named and bounded.
- Keep runtime identities private beneath canonical Mentat Agent and Run IDs;
  never turn Conversation Turns into a Task scheduler or bypass Hermes Kanban
  confirmation.
- For each nontrivial slice, write its scope and test strategy in a narrow
  review record, run proportionate tests and built acceptance, obtain two
  independent read-only reviews, fix findings, then push a full PR.
- Preserve unrelated local state and the explicit legacy UI rollback path.
  Leave a blocked capability visibly unavailable instead of substituting an
  unverified execution path.
- [Hermes cron queueing](https://github.com/hazeion/agent-os/issues/14)
  remains an upstream-dependent, read-only capability. Do not approximate its
  missing atomic operation with a direct store write or trigger sequence.
- On slice close-out, update the relevant GitHub child and this resume point.
  Close a ticket only after its accepted behavior is verified on the required
  branch/host.
