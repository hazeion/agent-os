# Owner Project plan editor

Status: implemented and reviewed in an isolated branch; publication pending PR.
Scope: an owner-facing preparation workflow for the immutable schema-33 plan
authority in [issue 239](https://github.com/hazeion/agent-os/issues/239).

The selected Project's planning column can open a plan panel. It reads current
plan status and up to 32 retained version summaries through one named,
owner-session-gated Python bridge capability. Editing starts a local draft of
the current version or an empty plan. No read, edit, preview, or save can start
a Run, create a Hermes card, grant context, or approve execution.

The owner adds 1–32 Tasks through a bounded selected-Project picker with an
explicit Load more action for later 50-Task pages; typing never auto-assigns.
Selecting a Task fetches its exact Task-input editor projection. A Task is
offered as prepared only if the current Task revision and Agent assignment
match the current saved input version, and that version's context ID and grant
revision exactly match an eligible live context/grant pair. A revoke/regrant
with the same context ID but a newer grant revision is visibly stale. Server
publication remains the final binding and
may reject a changed private runtime configuration. An unassigned, missing,
stale or revoked input guides the owner to the Task inspector and Prepare
inputs flow; there is no implicit text-only or no-file bypass. The owner can
update assignment in the Task workflow, then refresh this plan draft. An
Agent-suggested plan will arrive later only through a trusted producing-Run
capability, not model prose.

Each node shows the Task title, Agent, exact input version, earlier-node
prerequisites, checkpoint segment and requested attempt, wall-time and work
limits. The UI can add a prerequisite only from earlier nodes, and segments
are contiguous starting at zero. A new segment visibly means an owner review
checkpoint. Removing or reordering a node must first show affected dependency
links and checkpoint renumbering, then apply only after an explicit owner
action; moves that cannot preserve topological order stay disabled. Failed
edits retain the draft. These requested limits are preparation, not runtime
enforcement. Task objectives and Agent assignments remain canonical Task
authority; the plan never silently edits them.

Before Save, fixed bounded reads obtain each selected Task's canonical
dependencies and exact revision. The editor compares that graph with the
draft plan and shows both directions of difference by Task name/ID. The
comparison is advisory; publication rechecks exact Task revisions. A changed
dependency or Task between comparison and Save preserves the draft for another
review. A saved plan never changes canonical Task dependencies.

Save submits a fixed exact body containing Project ID, expected Project and
plan revisions, bounded title and ordered nodes. A saved version's private
`task_revision` maps deliberately to the public `expected_task_revision` only
after refreshing each selected Task/input projection. Python rechecks every
current identity/grant/input and commits one immutable version. A stale or
ambiguous save keeps the draft. A verified response names the new version ID;
only exact readback of that ID clears a matching draft. If the response is
lost, a later matching-looking plan cannot prove ownership of the save: keep
the draft in unresolved state, show the current plan and require an explicit
owner choice to use it or revise/retry. Never auto-submit after ambiguity.
Project switching preserves drafts without submitting them. The panel states
that version-1 plans are permanently ineligible for execution approval; a
later immutable policy-bearing format and qualified adapter are both required.
No misleading Run or Approve button appears.

The current Project lists bounded historical version summaries and can open an
exact old version by opaque ID through a separate fixed read route. Missing or
changed Tasks and Agents are labelled unavailable/stale by ID; detail lookups
are bounded and cannot erase rows. Retired-Project plan history remains private
retained data and needs its own explicit history UI slice before being called
fully browsable.

The Node gateway uses manifest-listed same-origin routes with owner session,
CSRF on mutation and strict bounded projections. Browser responses omit private
incarnations, binding digests, provider references and filesystem paths.

Tests: exact bridge/route/body/response contracts, owner session and CSRF,
one-node and multi-node drafts, later-page selection, Task/input/Agent changes,
local draft survival, ambiguous accepted-write/lost-response, exact old-version
read, source/Project switching, dependency changes between compare/save,
reorder/removal repair, stale labels and no execution transport. Run TypeScript, lint, the relevant
website suite, built desktop/mobile walkthrough, packaging and two independent
read-only reviews before a full PR.

Implementation evidence: the schema-33 Python authority remains unchanged except
for a bounded exact historical read projection. The new fixed Python/Node bridge,
same-origin routes and Projects & Tasks plan panel provide owner drafts, exact
publication, historical disclosure and ambiguous-save reconciliation without
Run or approval transport. The focused Python suite passed 81 tests; all 458
website tests, lint, typecheck and the production build passed. The built
desktop and mobile garage walkthrough passed with a saved plan, retained
plan-referenced Task input, result review, and zero Runs. Python packaging
remains a CI publication gate because the local venv lacks the pinned build
frontend. Two independent
read-only code reviews found no security or correctness defects; one copy issue
was fixed. The retained-input walkthrough was updated to assert the schema-33
protection that correctly prevents pruning a plan-referenced version.
