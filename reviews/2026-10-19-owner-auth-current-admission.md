# Owner authentication on current storage admission

Contract recorded before implementation: preserve fail-closed current SQLite
admission and expose kernel refusal through the existing fixed OwnerAuthError
boundary. Do not weaken authentication, session capacity/lifetimes, receipt
matching, one-use Google transactions, atomic rollback or replay protection.
A rollback fixture must reach session insertion and fail transaction deletion
without modifying authoritative schema. Keep an independent real schema-drift
refusal case. Beta tests should follow approved current-only storage and pending
release QA rather than old upgrade or completed-integration claims.

This is isolated from the frozen13a run and starts at pure cleanup293e4ee.
No live credentials, provider calls, account consent or permission changes.

The only production change maps `MentatDatabaseError` from the authority's
connection opener to the existing fixed `OwnerAuthError("unavailable")`.
Authentication and transaction bodies, permissions, capacity, expiry and replay
rules remain unchanged. Unsupported current-schema drift still refuses before
session issuance.

The old delete-trigger rollback fixture conflicted with exact current schema
admission. Its replacement installs a connection-local SQLite authorizer after
normal admission, observes an actual open transaction with one inserted active
session, then denies deletion of the verified Google transaction. The test
requires complete session rollback, the exact retained transaction row and
unchanged schema; the same receipt subsequently succeeds exactly once. A
separate real added-trigger test requires the typed early refusal, unchanged
serialized database and exact receipt, then succeeds after removing the owned
fixture trigger. No schema validation is bypassed in production.

Two existing Beta contract methods now follow the approved manual application
replacement/current-backup policy and current integration QA status. The seven
pending release checks remain pending; these assertions do not claim release
readiness.

Selected validation: the rollback and drift methods plus all twelve Beta
contract methods passed (14 methods, 5.941s), with ResourceWarnings as errors.
Full Google session issuance, owner authentication, Google authentication and
Beta modules passed: 60 methods, 72.910s, no skips, ResourceWarnings as errors.
Reproduce with:

```sh
python -W error::ResourceWarning -m unittest tests.test_google_session_issuance tests.test_owner_auth tests.test_owner_auth_google tests.test_beta_contract -v
```

AST comparison confirms 37 of 38 OwnerAuthAuthority methods remain exactly
unchanged; only `_open` differs. `git diff --check` passes. This focused repair
does not establish full integration, native acceptance or release readiness.
