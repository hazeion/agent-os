# Owner authentication methods and session generations

Scope: [Owner-session migration](https://github.com/hazeion/agent-os/issues/250).
Approved as part of Google owner access. Baseline `6ec381a`; publication follows
tests and two independent reviews. No remote activation or enrollment is implied.

Schema 25 adds method/generation metadata, bounded singleton Google settings
and principal evidence, and real method-specific session identity. Preserve all
schema24 passkey rows and SSE references through a create/copy/drop/rename
rewrite under the existing exact-source transaction and FK-restoration gate.
Never rename the old parent table first or fabricate passkey credentials.

Google session authentication requires an exact current principal/configuration,
owner generation and method; passkey ceremonies cannot operate in Google mode.
Schema migration creates no Google configuration, principal or session. Verified
CLI conversion and durable callback consumption remain subsequent work.

Backup validation supports both schema24 and25. Restore revokes all sessions and
marks Google configuration for host reconciliation, while retaining identity.
Compatible schema5 export retains its explicit table allowlist and omits this
authority. Test forward migration, rollback, malformed source, method confusion,
passkey parity, restore and export before publication.

Two independent reviewers found and rechecked two implementation concerns:

- Fresh but stale-generation passkey sessions could reach security mutations.
  Every authorizing session is now checked against current method/generation
  inside the mutation transaction, including after external ceremony verification.
- Restoring or bulk-revoking a full terminal history could exceed its retention
  bound. Both paths now retain at most 128 terminal sessions.

A real historical schema-24 snapshot exposed repository version guards that
had accepted 24 only through the current-version alias. Each affected guard now
explicitly retains 24 while still rejecting unknown schemas. Both reviewers
rechecked the final compatibility and retention changes with no further findings.

Verification so far: 181 focused authentication, migration, attachment, provider,
Task and Run checks passed (eight skips); the final 14 schema-25 regressions
passed. Those cover populated migration, transactional rollback, SSE references,
historical snapshot validation, method confusion, stale generations and external
verification races, backup/restore and compatible export, and retention bounds.
The initial broader run observed the historical-24 guard bug while its fix was
being made. A fresh final run passed all 83 private-state and backup/restore
checks (three skips); all 40 owner-authentication/schema-25 checks also passed
against the final code. Wheel and source distribution built and passed exact
inventory verification; installed-wheel imports verified schema 25. The Windows
path-normalized tracked-secret diagnostic found no new candidates. Ordinary
Linux CI remains required.

Status: independent code review clean and local verification complete; ready for
PR publication, with CI and merge still required.
