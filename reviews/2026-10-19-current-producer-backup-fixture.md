# Current producer backup fixture

The owner retired schema-migration capabilities. The Linux producer transaction
backup test must use current durable document metadata without changing its
canonical Project, Task, Run or producer evidence. Its pre-tamper backup must
still succeed; forged input provenance must block the next backup without
publishing an archive. No production code or runtime qualification changes.

The method-only fixture port constructs current manifest bytes through real
reserved fresh initialization of an owned empty staging root. It publishes
only that manifest into the disposable producer fixture and checks that every
fixed JSON document and the canonical SQLite snapshot are unchanged. It does
not invoke a retired migration, initialize over populated authority, export a
legacy root or replace the fixture's input data.

Local validation and independent review remain pending. The actual producer
scenario requires Linux and its existing sealed public runtime image gate;
macOS skips are not live qualification.

## Verification

The edited module imports and compiles. Its five methods complete locally:
two ownership/race methods pass and the three existing Linux producer methods
skip on macOS (0.023s, ResourceWarnings as errors). The producer backup/tamper
scenario is not claimed as executed.

An independent one-off verification executes the actual edited method's setup
prefix, stopping immediately before backup creation, against the real current
ProjectInferenceBroker fixture containing one canonical Project, Task and Run.
Fresh staging initialization produces current metadata; all fixed JSON bytes
and the full serialized logical SQLite snapshot remain exactly unchanged.
No sealed image, worker, account, provider or production activation is used.
Log: /private/tmp/mentat-current-producer-backup-prefix.log.
The original successful backup, trigger-preserving provenance forgery, blocked
second backup and exact no-new-archive assertions remain intact. No timeout,
platform skip, storage limit or production code changed.
