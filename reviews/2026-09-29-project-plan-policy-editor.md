# Policy-bearing Project plan editor

Status: implemented in an isolated branch, reviewed; publication and hosted CI
remain pending. Scope: the format-2 preparation portion of [approved plans and
scoped handoffs](https://github.com/hazeion/agent-os/issues/239) and exact Task
admission preparation in [issue 262](https://github.com/hazeion/agent-os/issues/262).

The owner can publish a format-2 plan through the existing session-gated,
same-origin Project plan route. Each immutable version freezes its ordered
Task/Agent/input graph, requested operations, typed final and intermediate
output slots, direct dependency-bound transfers and whole-plan attempt, wall
and work ceilings. The owner can still read historical format-1 plans, but a
new edit publishes format 2. No plan save starts a Run, calls an adapter,
creates a Hermes card, grants context or approves execution. The website keeps
Save unresolved after an ambiguous result until exact version readback.

Public research is a separate node choice. It cannot combine public-web access
with selected private inputs or a Mentat owner answer. Its public brief is the
exact immutable, fileless Task-input instructions reviewed by the owner; the
version ID and UTF-8 digest are frozen privately in the plan. Publication and
retained-backup validation reject selected files or a changed brief. A web
result requires owner review and a later checkpoint before a private synthesis
node can receive its exact registered output version. A public-citation use
code requires a web producer and a research-typed output. These are requested
intent, not proof that a runtime can enforce it. Actual Run admission and host
qualification remain separate, unavailable capabilities.

Output-slot names and producer/consumer indexes are revalidated in Python and
the browser. The editor keeps a handoff when its output is renamed; changing
the producing Task, web/input channel, direct dependency or required checkpoint
requires explicit handoff removal. Removing a Task previews the number of
affected output slots and handoffs. Read projections omit the private brief
digest and all runtime bindings. Format-2 content is capped at 24 KiB UTF-8;
the existing private-backup metadata allowance was measured with a dense
32-node, 256-version, 8,192-reference graph close to the content ceiling.

Validation: nine focused policy tests, 20 Project plan bridge tests, 30
existing plan tests (59 together), and a broader 133-test Python group passed. The full
website suite passed 492 tests, including garage public research to private
synthesis with a protected checkpoint; lint, typecheck and production build
passed. A staged Python wheel passed the exact package inventory verifier and
includes the new policy module. Built Chromium acceptance on a disposable
loopback preview at 1280 px and 390 px used a synthetic Project and fileless
public research brief. Through the actual website, the owner saved format 2
with a `research_1` intermediate output from node 0, a `products` final output
from node 1, and an exact node-0-to-node-1 handoff at checkpoint 1. Readback
matched the saved plan, the durable Run count remained zero, and neither
viewport had horizontal overflow. Visual inspection found cramped default
controls; the policy cards, checkbox rows, touch targets, numeric fields and
single-column handoff were corrected and rechecked. The preview and its
synthetic data were removed after acceptance. No real Linux worker or Google
provider was qualified by this slice.

Two independent read-only reviews found and then cleared issues: public web
could initially combine with owner answers, public citation use could name a
private producer, some valid intermediate names differed between Python and
TypeScript, and editor changes could silently remove a handoff. Each was fixed
and covered by a focused test or exact UI guard. The final reviewers reported
no remaining actionable issue in their assigned backend and browser scopes.
