# Retained Project-schema backup compatibility

The inherited template regression exposed validators that admitted historical
versions through 37 plus only the current version, although private-unit backup
explicitly supports the intervening Project schemas. Schema 41 first failed
at provider validation of historical schema 40. The same omission affects the
registry, Task, Project, Conversation and Run validators.

Repair each affected branch with explicit already-supported historical versions
below that branch's current schema: schema 39 adds 38; schema 40 adds 38 and 39;
schema 41 adds 38 through 40. Keep all existing fingerprints, authority receipts,
row and relationship validation. Do not turn the production allowlists into a
version range, admit a future schema or change runtime capabilities.

The regression selects only implemented, explicitly supported historical members
of the fixed set 38 through 42. It constructs a real complete empty private unit,
filters and validates it, requires the same schema version and verifies that
validation leaves the database bytes unchanged. This is empty-unit compatibility
coverage, not populated-backup, live-provider or production-execution acceptance.
The original cache-recipe change test remains intact and must also pass.

Two independent read-only reviews clear the schema-39 and schema-41 repairs.
Individual carry records retain each branch's exact test evidence and any
additional review. Initial failed runs are not passing evidence. Previously
published affected heads require updated normal commits and current hosted CI;
passing ancestor checks cannot substitute for the repaired head.
