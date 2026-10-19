# Current-only backup and private unit

The owner explicitly requested fresh/current operation only. This slice accepts
backup format5 and the current schema46 SQLite unit exclusively. Formats1–4,
older restore receipt protocols, out-of-line Agent registries and historical
positive fixtures are retired, not migrated. Unknown/future inputs also fail.

Old-root refusal must occur through read-only inspection before data locks,
source hardening, chmod or publication. Refusal preserves the exact archive
and source/target tree. A genuinely absent/uninitialized Console may use a
current empty unit; existing historical files never become an empty fallback.

PrivateConsoleUnit has three fields: history_raw, database_raw and blobs.
Canonical Agents are embedded. Current integrity, retained input/output/blob
bounds, owner-auth invalidation, approval/review epoch rotation, exact preview/
confirmation, locking, unknown Run/Stop evidence and interrupted current restore
reconciliation remain intact. B supplies one current schema46 initialization
recipe plus structural receipts1–45; its caller records46. A owns repository
validators and cache tests. Root owns global CLI/docs removal.

Verification uses current roundtrip, corruption/graph/retention, owner-auth and
restore recovery tests, plus explicit old/future format/schema refusal proving
no archive/tree mutation. Historical success cases are removed rather than
repurposed into compatibility promises. Two independent reviews are required
before publication. No production provider or owner service is involved.

## Retired or ported historical methods

The following exact old method names are absent after this change. Current
Run/blob, provider, Project, owner-method and plan behavior is retained, including
renamed current equivalents and a current FK/SSE-trigger assertion. Explicit
old schema/format upgrade success contracts are intentionally retired.

`tests/test_private_console_state.py`:

- `test_already_migrated_summary_uses_current_canonical_counts`
- `test_bridge_recovery_does_not_create_destination_before_private_migration`
- `test_changed_legacy_source_invalidates_migration_confirmation`
- `test_malformed_v2_manifest_items_fail_closed`
- `test_pre_registry_v2_backup_restores_with_an_empty_registry`
- `test_previewed_private_migration_preserves_source_and_is_idempotent`
- `test_private_migration_creates_missing_root_and_rebuilds_partial_stage`
- `test_private_migration_never_promotes_extra_stage_entries`
- `test_private_migration_never_promotes_nested_stage_symlink`
- `test_private_migration_receipt_crash_rejects_changed_destination`
- `test_private_migration_receipt_crash_resumes_without_recopy`
- `test_private_migration_revalidates_inventory_after_rename`
- `test_released_schema_eight_format_four_backup_restores_and_upgrades`
- `test_released_schema_four_v2_and_v3_backups_restore_and_migrate`
- `test_released_schema_seven_v3_backup_restores_and_converges_agents`
- `test_released_schema_ten_format_four_backup_restores_and_upgrades`
- `test_released_schema_thirteen_format_four_backup_restores_and_upgrades`
- `test_released_schema_twelve_format_four_backup_restores_and_upgrades`
- `test_schema_nine_backup_restores_vercel_connection_and_agent_together`
- `test_schema_seven_backup_bounds_legacy_projection_without_dropping_canonical_runs`
- `test_schema_seven_backup_derives_runs_from_sqlite_and_rejects_event_corruption`
- `test_schema_seven_capture_ignores_malformed_stale_legacy_history`
- `test_schema_seven_private_migration_receipt_survives_digest_upgrade`
- `test_schema_six_backup_restores_and_migrates_to_current_schema`
- `test_startup_refuses_legacy_private_state_until_migrated`
- `test_upgrade_resumes_genuine_protocol_2_restore_receipts`
- `test_upgrade_resumes_genuine_protocol_3_schema_seven_restore`
- `test_v2_restore_is_blocked_while_recorded_server_is_active`
- `test_v2_restore_replaces_private_unit_and_v1_preserves_it`

`tests/test_data_backup_restore.py`:

- `test_default_released_private_units_round_trip_for_older_formats`

`tests/test_restore_sanitization_context.py`:

- `test_published_protocol3_owner_sanitization_with_real_clock_resumes_exactly`

`tests/test_retained_project_schema_backups.py`:

- `test_future_schema_remains_unsupported`
- `test_retained_project_schemas_filter_and_validate_complete_empty_units`
- `test_retained_project_schemas_preserve_nonempty_agent_registry`
- `test_retained_version_does_not_bypass_exact_schema_validation`

`tests/test_project_context.py`:

- `test_exact_schema26_upgrades_without_changing_existing_authority`
- `test_populated_schema26_run_authority_backup_restores_and_upgrades`
- `test_private_restore_preserves_context_and_compatible_export_omits_it`
- `test_schema26_backup_remains_supported`
- `test_schema26_drift_and_partial_migration_fail_atomically`

`tests/test_project_plans.py`:

- `test_schema32_exact_upgrade_and_drift_gate`

`tests/test_google_login_transactions.py`:

- `test_migration_failure_is_atomic`
- `test_schema25_snapshot_compatibility_and_exact_forward_migration`

`tests/test_schema25_owner_methods.py`:

- `test_changed_source_and_mid_rewrite_failure_leave_schema24_and_restore_fk_enforcement`
- `test_populated_migration_preserves_sessions_and_sse_foreign_key_and_trigger`
- `test_private_backup_restore_and_compatible_export_keep_identity_boundaries`
- `test_released_schema24_private_snapshot_still_validates_and_sanitizes`

## Verification checkpoint

Current empty-unit construction, canonical Run/blob capture and active Run
status/timestamps pass. Old/future source schemas, retired runtime files,
current schema drift, and old/future restore protocols pass refusal checks;
source modes/mtime/bytes and inflight evidence stay unchanged. Current archive
roundtrip plus old/future formats pass. An initial broader data-backup run
passed its 34 selected invocations, including an imported-helper discovery
duplicate that has since been removed; that is not claimed as 34 unique tests.
Four existing owner-auth/epoch restore methods pass. A new refusal test's first
assertion used the wrong public partial status; it now requires the existing
`partial_failure`, and its corrected run passes without production changes.

The initial current plan-drift port expects strict current core admission and
fails against the old base core; it must run against B's actual current-only
core before qualification. A's repository/cache changes and root's fresh-only
CLI/document initialization must compose with this branch. This checkpoint is
not independently shippable and does not claim final whole-suite acceptance.
All historical provider/owner feature tests outside explicitly retired
migration contracts remain. No test deadline or storage limit was widened.

Outside callers retired elsewhere: task_repository standalone/schema5 export
helpers and cache constructors (A); agent_registry_migration and global CLI/
private migration modules (root); global forward fixtures (B/root). The removed
MAX_REGISTRY_DATABASE_BYTES reference in test_run_identities needs root cleanup.
Shared pure document I/O currently imports data_migration._publish_raw_missing;
root will move it to data_documents. Current restore protocol4 and its exact
inflight state, including unknown/partial outcomes, remain authoritative.
