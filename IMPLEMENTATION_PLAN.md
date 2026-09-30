# Mentat implementation roadmap

Status: active · updated September 30, 2026

This is the short resume map, not permission to implement an unspecified slice.
Read [AGENTS.md](AGENTS.md), [ARCHITECTURE.md](ARCHITECTURE.md),
[CONTEXT.md](CONTEXT.md), the active GitHub issue and its narrow review record.
For website work also read [MENTAT_WEB_DESIGN.md](MENTAT_WEB_DESIGN.md).
Detailed contracts, test counts and historical fixes belong in those records.

## Destination

The [Wayfinder map: secure owner access and coordinated Project delivery](https://github.com/hazeion/agent-os/issues/234)
targets one owner on an always-on Linux Mentat host, signing in from ordinary
desktop/mobile browsers. Guided CLI onboarding connects Google owner login and
Agent providers separately. The owner creates Projects and Tasks, assigns
Agents manually or reviews a lead's proposed plan, approves bounded work
between checkpoints, and reviews versioned results in one durable Inbox.

The garage journey uses the owner's actual goals, floorplan and measurements
to produce a dimensioned layout, an editable shopping document with product
links, and an implementation order. Missing measurements become questions;
revisions retain prior evidence and final results require owner acceptance.

Python owns Tasks, Runs, context, files, credentials and runtime authority.
Browser access grants no provider consent. Saving a plan or choosing a lead
never starts work. Unknown external outcomes never retry automatically.

## Current position

The older foundation is merged through [PR #231](https://github.com/hazeion/agent-os/pull/231)
and [PR #233](https://github.com/hazeion/agent-os/pull/233). The newer owner
workflow remains a stack of full, open PRs starting at
[PR #243](https://github.com/hazeion/agent-os/pull/243), most recently
[PR #313](https://github.com/hazeion/agent-os/pull/313), with the subsequent
private [scope readback slice](reviews/2026-09-30-project-scope-readback.md).
Open PRs, passing local
checks and clean mergeability are not merged-product or issue-close evidence.
Hosted CI, normal review and integrated acceptance remain gates. No blanket
GitHub PR merge authorization is recorded.

| Required outcome | Evidence on the open stack | Acceptance still missing |
| --- | --- | --- |
| Secure owner access from any device | Google OIDC, enrollment, sessions, recovery, authenticated gateway and website sign-in slices | Operator Google client/HTTPS setup, human non-loopback security review, actual desktop/mobile login, rejection, revocation and recovery |
| Easy CLI onboarding | Named owner/provider setup and protected lifecycle operations; backed-up official Hermes host activation recorded | Clean-host end-to-end setup, qualified Project-provider connection and host replacement/update/recovery |
| Projects, Tasks and Agent access | Canonical storage, explicit context grants, immutable selected Task inputs, lead selection and owner-edited format-2 plans | Atomic qualified Run admission and exact input/capacity/work/Stop enforcement through production execution |
| Lead plans and manual assignment | Lead/planning-input preparation, guarded proposal receipt, bounded artifact parser, isolated worker and synthetic broker evidence | Trusted producing Run, proposal intake/owner Apply, exact plan approval, budget debit, checkpoints and verified handoffs |
| Garage research and results | Private public-page reader, retained editable result versions and exact three-slot owner review | Public search/tool/work admission, generated-output provenance, real research/synthesis and coordinated revisions using actual owner inputs |
| Durable communication and recovery | Owner Inbox for exact Project-review and Run sources, retained unknown outcomes and tested backup graphs | Canonical plan requests/questions/checkpoint sources, integrated restart/disconnection behavior and whole journey acceptance |

[Reconcile merged QA fixes and verify the current baseline](https://github.com/hazeion/agent-os/issues/235)
and [Fresh-install release readiness: Project, Task, and Agent journey](https://github.com/hazeion/agent-os/issues/223)
remain acceptance work against the appropriate integrated branch. Do not close
residual QA based on a fixture or an unmerged change alone.

## Next steps and dependencies

1. **Finish CI and integration review.** The dedicated CI workstream repairs
   exact failed heads, preserves full PRs and existing test/deadline coverage,
   and resolves proven stack conflicts. [PR #276](https://github.com/hazeion/agent-os/pull/276),
   [PR #293](https://github.com/hazeion/agent-os/pull/293),
   [PR #294](https://github.com/hazeion/agent-os/pull/294) and
   [PR #309](https://github.com/hazeion/agent-os/pull/309) carry reviewed
   efficiency work. Report local timing as local evidence, not hosted speed.
   Revalidate current heads; queued or unavailable checks are not passes.

2. **Qualify the real Project provider before dispatch or execution approval.**
   The [provider compatibility audit](reviews/2026-09-30-project-provider-compatibility.md)
   establishes that stock Codex OAuth omits the existing output-token limit
   and has an outer retry. A configured provider or working Console is not
   Project qualification. The owner has been asked whether to evaluate the
   documented ChatGPT-plan OAuth route first or a supported API-key provider
   through Hermes. Neither is selected or qualified by this map. Credential
   custody, exact profile/account/model/token/image behavior, fixed transport
   and unknown-outcome handling need direct evidence. Do not read Hermes
   credential stores directly, change auth, silently drop a policy field or
   create a fallback. Credential use, live provider submission and production
   provider enablement require the resolved owner choice and proven authority.
   Independent credential-free source and synthetic qualification may continue
   within already approved contracts.

3. **Connect the already implemented prerequisites to canonical work.**
   The owner approved the [unchanged-stock Mentat controller direction](reviews/2026-09-29-official-hermes-project-controller.md):
   Mentat owns isolated workers; supported Hermes Kanban is a separate fixed
   delegation ledger, not its dispatcher. [Official release compatibility](reviews/2026-09-29-official-hermes-compatibility.md),
   [worker scope](reviews/2026-09-30-project-worker-scope.md),
   [namespace handoff](reviews/2026-09-30-project-worker-namespace.md),
   [durable journal](reviews/2026-09-30-project-worker-journal.md),
   [durable scope bookkeeping](reviews/2026-09-30-project-scope-journal.md),
   [private restart scope readback](reviews/2026-09-30-project-scope-readback.md),
   [synthetic inference broker](reviews/2026-09-30-project-inference-broker.md),
   [immutable image](reviews/2026-09-30-project-runtime-image.md),
   [sealed libraries](reviews/2026-09-30-project-runtime-libraries.md),
   [public artifact origin](reviews/2026-09-30-project-runtime-origin.md) and
   [public-page reader](reviews/2026-09-30-project-public-page-reader.md)
   have component evidence. Complete loader/system/helper/model qualification
   is still separate. Restart readback is observation only: it cannot recover
   a lost token, settle a Run, prove durable closure or release capacity.
   Implement reviewed atomic admission with shared
   cross-source capacity, exact inputs and durable scope/work receipts; then
   registered proposal output and owner Apply. The existing Task/Console gate
   now preserves [canonical Agent capacity continuity](reviews/2026-09-30-agent-capacity-continuity.md)
   across changed adapter scopes; this is a shared admission prerequisite, not
   complete Project reservation. The schema-41 no-dispatch guard
   and default live proposal validation remain closed until their complete
   admission/provenance/Inbox/backup requirements pass.

4. **Finish approved Task execution and review.** Under
   [Define and implement approved lead-agent plans and scoped Task handoffs](https://github.com/hazeion/agent-os/issues/239),
   bind exact format-2 plan approval to current immutable inputs and qualified
   runtime. Reserve finite attempts/work, reconcile the isolated Kanban ledger
   before Task execution, and implement exact checkpoint/handoff receipts.
   Verify dependency readiness, failure propagation, cancellation, reassignment
   and crash recovery without granting new scope or repeating uncertain work.
   Public research receives only the approved public brief; private synthesis
   has selected files and no public-web capability. Under
   [Retain and edit versioned Project deliverables](https://github.com/hazeion/agent-os/issues/263)
   and [Implement Project review, coordinated revisions, and the owner inbox](https://github.com/hazeion/agent-os/issues/240),
   register outputs from exact verified producer Runs and expose questions,
   approvals and revisions only through canonical sources. A parser, owner edit,
   successful Run or Inbox acknowledgment cannot substitute for those proofs.

5. **Activate and accept the real host and garage journey.** Under
   [Implement Google owner login and qualify explicit Linux remote activation](https://github.com/hazeion/agent-os/issues/241)
   and [Secure all Mentat APIs before supporting non-loopback access](https://github.com/hazeion/agent-os/issues/10),
   use actual operator Google/HTTPS configuration and the required human
   security review before remote activation. Under
   [Verify fresh onboarding and the complete garage Project journey](https://github.com/hazeion/agent-os/issues/242),
   test ordinary physical desktop/mobile devices, real provider/tool work,
   missing-dimension questions, all three deliverables, owner changes,
   restart/disconnection and host recovery. Record fixtures versus live
   integrations explicitly, then reconcile child issues and the Wayfinder map.

## Operator inputs and independent work

The [Google setup guidance slice](reviews/2026-09-30-google-setup-guidance.md)
adds fixed failure-step guidance to the existing CLI ceremony; it grants no
authentication or remote activation and does not satisfy live acceptance.

Provider route choice is pending. Google OAuth application configuration,
HTTPS host activation/security acceptance and actual garage goals, floorplan,
measurements and budget are not supplied or proven by component tests. Do not
invent them or request secrets in chat. Continue independent authorized CI,
source qualification and integration work while those inputs are pending;
elapsed time never approves credential changes or execution.

## Working rules

- Work on a focused codex/ branch and keep Python authoritative with named,
  bounded Node capabilities. Runtime identities remain private beneath Agents.
- Record each nontrivial contract/test strategy, test proportionately, obtain
  two independent reviews, fix/re-review to clear, then push a full PR.
- Preserve unrelated state, the explicit legacy UI rollback and truthful
  unknown outcomes. Conversation Turns remain outside the Task scheduler.
- [Add an atomic Hermes cron queue capability for Mentat](https://github.com/hazeion/agent-os/issues/14)
  remains an upstream blocker, not a trigger/direct-store workaround.
- [Historical access map](https://github.com/hazeion/agent-os/issues/171) is
  superseded tracking, not proof that remote access shipped. Update the relevant
  issue and this resume point on slice close-out; close only with scoped evidence.
