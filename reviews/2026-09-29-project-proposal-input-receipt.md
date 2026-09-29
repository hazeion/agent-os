# Project proposal Run-input receipt foundation

Scope: schema 42 reserves a separate, bounded, immutable receipt for the exact
owner-prepared Project planning input and its selected file evidence. This is
the Project counterpart of schema-30 Task Run-input evidence, not a reuse of
`mentat_run_input_receipts`. It binds a `project_proposal` Run to one live
Project incarnation, lead role, canonical Agent/runtime binding, grant,
context, input version, and ordered retained bytes. Fixed proposal operations,
attempt/wall/work ceilings, qualification and owner authorization must be
recorded before an adapter call.

This slice keeps schema-41's proposal Run INSERT/source-UPDATE guards. The
receipt table's presence alone neither admits a Run nor qualifies a runtime.
Actual admission needs a separately reviewed atomic Run/receipt transaction,
Linux isolation proof, generated-output registration, Run attention/Inbox and
retention support. Historical receipt validity never proves that a grant or
Agent remains current. No browser or adapter route is added here.

Verification: migrate a populated exact schema-41 root, validate exact schema
and foreign keys, and retain the direct-SQL proposal guard. Exercise private
graph validation for source/input/lead/Project/context/Agent/file mismatches,
capacity, ordered file bytes and missing blobs. Prove empty schema-42
backup/restore, compatible export omission, and the attachment-retention view.
Nonempty proposal receipt backup and GC acceptance remain an admission-slice
gate because the guarded Run is deliberately rejected by current Run-attention
and Inbox validation. Also prove rollback on source schema drift. Run targeted
Python tests and the repository's CI contract tests.
Two independent read-only reviews must inspect the implementation before a
full PR is pushed.
