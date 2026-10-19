# Exact schema-36 plan fixture after schema 42

At PR #291 head `aef6f08`, the plan-policy migration test reconstructs released
schema 36 but leaves the two empty schema-42 Project proposal Run-input tables
in its fixture. Its exact signature correctly rejects that hybrid graph.
Reproduced the hosted `invalid != expected` failure locally before correction.

The fixture saves only owner Task inputs and a plan. Before rebuilding the
released schema-36 Run table and view, explicitly assert zero rows in both
proposal input tables and remove only those known newer objects. No saved
input, plan, reference, Agent, blob or Run evidence may be discarded to make
the fixture fit. Keep exact schema signature, foreign-key, saved-row, private
backup/restore and immutable-plan assertions unchanged. Unknown later objects
continue to fail rather than being removed generically.

This is a test-only repair; production schema/migration/retention code, owner
data and runtime authority are untouched. All six plan-policy migration tests
pass locally; review B independently reran those six tests. Both independent
read-only reviews are clear before publication/propagation.
