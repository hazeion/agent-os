# Project deliverable review storage

Status: reviewed implementation, published in full PR #271; CI pending.

This slice adds the private schema-32 owner decision record for the three
garage result slots. A decision binds the current layout, products and steps
versions together with Project identity and revision. Acceptance covers all
three; a change request selects affected slots and records a bounded note.
Confirmation is exact, idempotent and serialized. It does not dispatch work,
certify Agent provenance, or make a generated result. The website action and
generated promotion remain separate slices.

Project deletion preserves the immutable decisions and now discloses their
retained count beside result versions. Deletion preview binds current-incarnation
decisions, so a new decision invalidates an older delete preview. Backup
validation covers the review graph. Restore retains decisions and rotates the
confirmation epoch. Empty virtual snapshots keep a stable zero epoch; the
first real review preview activates a private random epoch before confirmation.

Verification: 69 focused Python tests pass across review, deliverable, Project
context, deletion, bridge and Run input behavior. The two focused deletion
website tests pass; the complete 82-test planning/deletion website selection
passed before its last disclosure assertion, which then passed in the focused
rerun. TypeScript typecheck and focused lint pass. The previously failing
durable backup/restore test passes after the empty-snapshot epoch correction.

Independent read-only reviews: reviewer A found no remaining concrete issue
and confirmed the restore correction. Reviewer B found missing schema-31
allowlist compatibility, incomplete-Project status failure and missing deletion
disclosure; all three were fixed and its re-review found no further issue.
