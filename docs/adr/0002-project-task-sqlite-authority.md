# Store Projects and Tasks in one SQLite authority

Status: accepted

Mentat will move canonical Projects into the owner-private SQLite database and
store Task membership through immutable Project IDs. Keeping Projects in JSON
would preserve a cross-store race during rename, archive, Task movement,
dependency editing, backup, and restore. The migration must preserve stable
Project identity and make the old Project document a seed or recovery artifact,
not live fallback authority.

Mentat has no external users during this development cutover, so it does not
need dual writes or a long compatibility period. The one-time migration must
still preserve the operator's existing data through preview, backup,
confirmation, verification, and rollback evidence.
