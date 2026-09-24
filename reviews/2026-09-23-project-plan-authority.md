# Project plan authority

Status: implementation reviewed and published in full PR #273; CI pending.
No execution capability is approved or advertised by this slice.

Scope: the immutable owner-editable plan preparation authority beneath
[approved plans and scoped handoffs](https://github.com/hazeion/agent-os/issues/239).
The already reviewed Task-input and admission contract remains authoritative.
This slice must make manual assignments and dependency plans reviewable without
turning a saved plan into a Run, Hermes Kanban card, context grant, or execution
approval. Agent-generated proposals and their exact producing-Run admission are
a later capability; ordinary model prose never becomes a plan mutation.

## Product and authority

A Project has one private plan scope bound to both its current schema-31
Project incarnation and its exact live schema-27 context scope.
An owner edit publishes a numbered immutable plan version at the exact current
scope and Project revision. Deleting a Project retires its scope but retains
versions; an ID-reused Project gets a new scope. Renames preserve scope.

A plan version has a bounded title and 1–32 existing Task nodes. Each node
binds the Task's current private incarnation, Project membership and revision,
the exact current Task-input version, selected canonical Agent incarnation,
an acyclic list of predecessor Task IDs, finite requested attempt/time/work
limits and a checkpoint segment number. Segment IDs start at zero and are
contiguous. Every transition to the next segment is an explicit owner review
checkpoint; no dependency or segment label authorizes work by itself. No Task
appears twice; every predecessor is a node in the same plan and its segment
is no later than the successor's. One node is allowed, so a manual assignment
uses the same structure.
The Task owns its objective and assignment; the plan stores only their exact
versions and IDs, not duplicate descriptions or hidden prompts. At publication
the selected Agent must equal the Task's current assigned canonical Agent,
including incarnation, and the selected current Task-input version must be
bound to that Agent with a still-live exact context grant. For no-file work the
owner still saves an explicit zero-file Task-input version; a missing input
version is never an implicit text-only fallback. The UI must guide the owner
through that preparation. The owner may edit Task assignments independently,
which makes an unstarted plan stale until republished.

The plan's dependency graph is execution preparation, separate from the
canonical Task dependency graph. Publication stores exact Task revisions
that cover canonical dependency edits. Before approval, the owner must see both
graphs and any mismatches; a successor cannot silently bypass a canonical
prerequisite. No dependency edge grants context or handoff permission.

Version publication takes one private lock and immediate SQLite transaction.
It validates current Project, Tasks, Agent identities, input scopes and all
revisions before writing, then validates the complete bounded graph before
commit. Current membership, assignment, grant and input checks apply here and
again before any future approval or reservation. Historical graph validation
must accept retired Project scopes, deleted Tasks/Agents and revoked grants,
while retaining immutable Task-input references as protected foreign-key roots.
A stale or ambiguous request has no partial write. The browser can see
names, IDs, revisions, dependencies, requested limits and stale reasons but not
runtime binding references, credentials or raw provider data.

Schema 33 caps history at 32 versions per immutable Project plan scope and
256 versions globally, including retired scopes and reused display IDs.
At either cap, publication fails closed; this slice does not prune plan
versions. Any future pruning must preserve versions referenced by an approval,
Run or handoff receipt and validate the full retained graph in backup/restore.
Actual Project deletion retires the live plan scope in the deletion transaction;
its preview binds and discloses retained plan versions so an intervening plan
publication invalidates confirmation. ID reuse cannot revive old plan history.
It retains history through backup/restore and actual Project deletion. It adds
no Agent proposal, approval grant, coordinator, dispatch, scheduler, automatic
handoff, retry, budget debit or provider call. A saved plan is explicitly
unapproved; its requested limits are not enforcement claims.
Version-1 plan content does not yet contain the immutable allowed-operation
and conditional-transfer policies required by the reviewed admission contract.
No version-1 plan may receive execution approval. A later version format must
bind those policies inside the immutable plan before approval; mutable
out-of-band policy must never fill that gap.

## Tests and gates

Test exact schema-32-to-33 migration and drift rejection; preserve old schema-32
backup/restore compatibility; empty virtual backup
stability; owner-safe version/read projection; acyclic and same-Project graph;
Task/Agent/incarnation/assignment/input/grant revision changes; zero-file
input preparation; canonical dependency changes and mismatch disclosure;
missing or retired Project; concurrent publication; deletion and ID reuse; history bounds;
backup/restore and shared metadata budget. Browser tests will follow only when
the fixed plan editor is added. Two independent reviews must find no remaining
issue before a full PR.

The execution gate remains separate. The current official Hermes Kanban guide
documents full file/terminal access for task workers and no per-task allowed-tool
flag on `kanban create`; it supplies `--max-runtime` and `--idempotency-key` but
not the required exact input/tool/work enforcement. A real Linux Hermes/provider
combination must be qualified before a plan version can authorize dispatch.
Sources: [Hermes Kanban guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/kanban.md),
[Hermes CLI implementation](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/kanban.py).

## Verification and review

The schema-33 migration has an exact schema-32 source gate and tested
schema-32 backup materialization/reopen. Tests cover manual and two-node plans,
both directions of canonical dependency mismatch, stale Project/Task/grant
revisions, Task and Project ID reuse, immutable input protection, deletion
preview invalidation, concurrent publication, 32-version scope and 256-version
global ceilings, backup/restore and no Run creation. The final focused plan
suite passed 30 tests. The broader affected Python suite passed 81 tests
before the final bounded-query refinement; its targeted global-cap,
checkpoint and revoked-grant tests passed afterward.

The 443-test website suite, TypeScript check, focused lint, production build,
wheel/sdist verification and isolated installed-wheel import passed. Two
independent read-only design and code reviews found issues that were fixed;
both final code reviewers reported no remaining concrete concern.
