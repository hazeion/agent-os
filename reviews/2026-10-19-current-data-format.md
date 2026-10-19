# Current durable JSON format only

The user retired older data upgrades and backup paths. This branch removes the legacy JSON schema migration preview, confirmation, archive creation and explicit recovery-deletion capabilities. It preserves current format1 validation, prior-origin records inside an already-current manifest, and genuinely fresh initialization with its reservation/crash-recovery contract. The branch starts from the reviewed composed current kernel/repository/private-unit/root startup checkpoint `de8e585eec0755744a6245df713019cba7dc852c`.

## Production changes

`preview_schema_migration`, `migrate_data_schema`, their preview/result/token/recovery data structures, ZIP creators and migration-specific deletion/confirmation helpers are removed. The module does not import `data_migration`. Its only ZIP operation is bounded read-only validation of the exact existing prior-origin archive inventory and semantics.

Forty source definitions remain AST-identical to the original checkpoint before the final wrapper preflight. The fixed fresh manifest has byte-for-byte the same canonical JSON as the original `origin="fresh_seed"` constructor, verified independently against the original pure function. The remaining changed contracts are explicit:

- Fresh preparation accepts an existing inventory only when its pinned manifest is current, or when the existing fresh reservation authorizes the exact recovery sequence. An unversioned existing inventory cannot receive an upgrade through the fresh entrypoint.
- Completion without a reservation accepts only an already-current manifest. It no longer treats an unversioned inventory as successful completion.
- The standalone fresh completion wrapper refuses an unreserved unsupported inventory during read-only preflight, before creating a lock.

The read-only status APIs and fresh initializer signatures remain available to startup and current backup/restore. Their `legacy` status value remains only a missing-manifest classifier used by root's fresh/development admission, not approval to upgrade an existing operator root. Root startup separately refuses such existing roots before layout mutation. No document format or SQLite version is bumped.

The read-only prior-origin format1 validator remains deliberately intact. A current manifest may retain its exact fixed historical origin/step/archive metadata without exposing an upgrade, backup-creation or recovery-write capability. Malformed, missing, linked, broad-mode, encrypted or semantically forged prior-origin evidence still refuses current status. Future versions take priority over recovery artifacts.

## Fixture retirement and current coverage

The21 removed methods exercise retired migration creation, preview/confirmation, explicit old recovery, old publication failure and migration-specific ABA/serialization paths. Current equivalents remain for root pinning, final source/readback verification, fresh rollback/recovery, shared JSON lock ordering, file shape/size, FIFO refusal, unsafe redirects and unchanged rejected storage. The startup half of the mixed migration/startup substitution method is retained.

Current product fixtures use the real fresh initializer. Prior-origin archive tamper tests construct only disposable static current-format evidence in the test module; they invoke no retired production migration helper or writer. A positive test requires read-only prior-origin validation to leave the entire fixture unchanged. Another test requires fresh completion to refuse an unreserved inventory without changing it.

Fixture ports preserve current startup boundaries. The empty JSON required-directory repair matrix runs before subsequent SQLite initialization populates private storage. Other current directories retain permission-hardening assertions; an unsafe existing SQLite private directory instead has an explicit unchanged refusal check. Repeated startup retains exact file bytes, file timestamps and hierarchy/permissions. It does not mistake the private directory timestamp change caused by normal SQLite WAL/SHM turnover for a durable document rewrite. Redirect tests remove their owned fixture's initialization lock before the attack, preserving the original assertion that a rejected redirected write must not create one outside the approved root.

Current bounded startup error labels replace obsolete migration-era labels while the exact invalid/newer/current status, source bytes, rejection and ownership assertions remain. Existing wait/join limits and platform skips are unchanged. No runtime/provider permission, credential path, process launch, timeout or production gate is changed.

## Verification

The initial fixture port was not a pass. Removed helper references and fixture assumptions about new SQLite initialization were corrected without loosening validation. The36-method current suite then passed in66.796seconds with ResourceWarnings treated as errors; one existing native-Windows reparse test was skipped on macOS. The final suite additionally includes explicit valid prior-origin read-only validation and unreserved fresh refusal. Its result is recorded below after completion.

No hosted checks, Windows execution, Linux qualification or production readiness is claimed. Root and an independent peer must review this change before the combined current-only cleanup PR is published.

Final complete owned-suite result:38 methods,37 passed and one existing native-Windows reparse skip, in81.490seconds with ResourceWarnings as errors on the real composed checkpoint. Raw log: `/private/tmp/mentat-current-data-format-final.log`. Both added explicit read-only/fresh-refusal regressions pass. `py_compile` and `git diff --check` also pass.
