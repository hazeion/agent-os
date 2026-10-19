# Owner-selected Project lead role

Status: implemented and independently reviewed for the role portion of
[lead-agent plans](https://github.com/hazeion/agent-os/issues/239). The broader
[proposal/Apply contract](2026-09-29-project-lead-proposals.md) remains
the execution boundary. Selecting a lead neither starts a Run nor grants
Project context, provider access, Task writes or plan approval.

Schema 38 stores immutable, bounded lead-role versions beneath the private
Project incarnation (`mentat_projects.deliverable_incarnation`), which schema
31 backfilled for existing Projects and assigns through an insert trigger on
new Projects, including those without context. Schema 38 reuses and validates
that identity; it does not invent a second Project incarnation. A
version is an owner selection of one canonical Mentat Agent, or an explicit
clear. It freezes the Agent incarnation, registry revision and validated
private runtime-binding digest; the registry has no independent binding
revision. The owner may select a lead before publishing Project context. Such
a selection is visibly **unready** and cannot reserve a proposal Run. When a
current Project context exists, a ready selection additionally freezes that
exact context version and an active grant whose Agent incarnation, context ID
and revision all match it. A grant to an earlier context cannot make the lead
ready. Creating context or regranting after an unready/stale selection never
auto-activates it: the owner explicitly reselects the lead against the new
context/grant to create a fresh role version.

One selected lead is current per live Project incarnation; previous versions
remain history. A new Project using the same display ID gets a new private
incarnation and cannot inherit an old lead. A deleted/rebound Agent, changed
context/grant/binding, retired Project or restore leaves the selection stale
and unavailable for proposal admission. Manual Task assignments are separate.

Owner readback exposes only Project ID/revision, safe Agent ID/name, lead
revision and bounded stale reasons. Runtime refs, binding digests, context
secrets and private incarnations stay in Python. Selecting or clearing a lead
uses the Project private lock, exact expected Project and role revisions, and
one guarded SQLite transaction. It does not alter manual Task assignments or
the Agent registry. A lost response is reconciled by exact role version ID;
the browser never repeats a changed selection automatically. The website may
show that lead proposal execution is unavailable until the separately
qualified proposal Run and owner Apply slices pass.

Tests: exact schema-37 gate and drift rejection; old backup restore; retained
history and Project/Agent ID reuse; select before context, explicit reselect
after a new grant, rejection of a grant to a prior context, grant revoke/regrant,
context edit, runtime binding change and restore; two-device concurrent selection, revision
conflict, capacity and backup tampering; no Run/Task/adapter side effects; exact
safe Python/Node/browser projection and ambiguous-write reconciliation. A
built desktop/mobile owner selection walkthrough and two independent read-only
reviews precede a full PR. This slice does not claim a lead has produced a
proposal or that any Linux runtime is qualified.

Implementation acceptance on September 29: the built local preview showed a
synthetic Garage Project and canonical Research Agent. The owner selected the
lead in the browser; readback showed the Agent ID and the missing-context
state, while the private database retained one role version and zero Runs.
At a 390-pixel browser viewport the Project Lead panel remained in the
single-column planner and its controls were present in the accessibility tree.
The role contract, route, bridge, UI, and Python migration/storage tests passed;
the production Next.js build passed. Independent Python and browser reviews
found no remaining actionable issue after corrections for maximum Agent-list
responses, duplicate names, deleted-Agent clearing, and stale guidance.
