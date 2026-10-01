from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

import agent_console_attachments as files
import mentat_db
import private_console_unit as backups
from private_state import private_state_lock
import project_context as context
from project_repository import ensure_project_sqlite_authority, mutate_authoritative_projects, ProjectRepositoryConflict
from task_repository import ensure_task_sqlite_authority
from task_repository import _schema5_private_unit
from tests.test_project_repository import project


class ProjectContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'tasks.json').write_text('[]')
        (self.root / 'projects.json').write_text(json.dumps([project()]))
        ensure_task_sqlite_authority(self.root, required_source_mode=None)
        ensure_project_sqlite_authority(self.root, required_source_mode=None)

    def upload(self, content=b'Floorplan with supplied dimensions'):
        return files.create_attachment(self.root, original_name='floorplan.md', content=content)['id']

    def publish(self, *ids, expected=0, brief='Keep room for two bicycles'):
        return context.publish_project_context(self.root, 'project_mentat', expected_project_revision=1,
            expected_revision=expected, brief=brief, attachment_ids=list(ids))

    def test_project_only_file_survives_release_gc_and_restart(self):
        attachment = self.upload()
        published = self.publish(attachment)
        with self.assertRaises(files.AttachmentUnavailable):
            files.release_attachment(self.root, attachment, grace_seconds=0)
        files.garbage_collect(self.root, now=time.time()+10000, orphan_grace=0)
        files.reconcile_startup(self.root, retained_run_ids=(), now=time.time()+10001)
        self.assertEqual(context.read_project_context(self.root, 'project_mentat'), published)
        self.assertEqual(files.read_attachment_bytes(self.root, attachment)[1], b'Floorplan with supplied dimensions')
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM run_attachments').fetchone()[0], 0)

    def test_shared_file_survives_run_unbinding_and_old_version_remains(self):
        attachment = self.upload()
        first = self.publish(attachment)
        files.bind_run_attachment(self.root, attachment, 'run_context')
        second = self.publish(expected=1, brief='Revised brief')
        files.unbind_run_attachments(self.root, 'run_context', grace_seconds=0)
        files.garbage_collect(self.root, now=time.time()+10000, orphan_grace=0)
        self.assertEqual(context.read_project_context(self.root, 'project_mentat', revision=1), first)
        self.assertEqual(context.read_project_context(self.root, 'project_mentat'), second)
        self.assertEqual(files.get_attachment(self.root, attachment)['state'], 'attached')

    def test_stale_publication_leaves_files_staged_and_old_revision_unchanged(self):
        first = self.publish()
        attachment = self.upload()
        with self.assertRaisesRegex(context.ProjectContextError, 'revision_conflict'):
            self.publish(attachment)
        self.assertEqual(context.read_project_context(self.root, 'project_mentat'), first)
        self.assertEqual(files.get_attachment(self.root, attachment)['state'], 'staged')

    def test_publication_rejects_tampered_or_expired_input_without_partial_retention(self):
        good = self.upload(b'good')
        bad = self.upload(b'bad')
        files.resolve_blob_path(self.root, bad).write_bytes(b'changed')
        with self.assertRaisesRegex(context.ProjectContextError, 'file_unavailable'):
            self.publish(good, bad)
        self.assertIsNone(context.read_project_context(self.root, 'project_mentat'))
        self.assertEqual(files.get_attachment(self.root, good)['state'], 'staged')
        expired = files.create_attachment(self.root, original_name='expired.md', content=b'expired', now=time.time()-10000)['id']
        with self.assertRaisesRegex(context.ProjectContextError, 'file_unavailable'):
            self.publish(expired)

    def test_concurrent_exact_revision_has_one_winner(self):
        gate = threading.Barrier(2)
        outcomes = []
        def publish(brief):
            gate.wait(timeout=5)
            try:
                outcomes.append(self.publish(brief=brief)['brief'])
            except context.ProjectContextError as exc:
                outcomes.append(str(exc))
        threads = [threading.Thread(target=publish, args=(brief,)) for brief in ('first', 'second')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes.count('project_context.revision_conflict'), 1)
        self.assertEqual(context.read_project_context(self.root, 'project_mentat')['revision'], 1)

    def test_capacity_and_utf8_limits_roll_back_every_row(self):
        with self.assertRaisesRegex(context.ProjectContextError, 'brief_invalid'):
            self.publish(brief='é' * 8193)
        self.publish(brief='é' * 8192)
        attachment = self.upload()
        with patch.object(context, 'PLAN_MAX_METADATA_BYTES', 100):
            with self.assertRaisesRegex(context.ProjectContextError, 'capacity'):
                self.publish(attachment, expected=1)
        self.assertEqual(files.get_attachment(self.root, attachment)['state'], 'staged')
        self.assertEqual(context.read_project_context(self.root, 'project_mentat')['revision'], 1)

    def test_concurrent_projects_cannot_exceed_shared_blob_quota(self):
        mutate_authoritative_projects(self.root, lambda items: ([*items, project('Other', 'project_other')], None))
        identifiers = (self.upload(b'first input'), self.upload(b'second input'))
        gate = threading.Barrier(2)
        outcomes = []
        def publish(project_id, attachment_id):
            gate.wait(timeout=5)
            try:
                context.publish_project_context(self.root, project_id, expected_project_revision=1,
                    expected_revision=0, brief='Scoped work', attachment_ids=[attachment_id])
                outcomes.append('published')
            except context.ProjectContextError as exc:
                outcomes.append(str(exc))
        threads = [threading.Thread(target=publish, args=pair) for pair in zip(('project_mentat', 'project_other'), identifiers)]
        with patch.object(context, 'MAX_RETAINED_BLOBS', 1):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
                self.assertFalse(thread.is_alive())
        self.assertCountEqual(outcomes, ['published', 'project_context.blob_capacity'])
        self.assertCountEqual([files.get_attachment(self.root, item)['state'] for item in identifiers], ['attached', 'staged'])

    def test_context_and_run_bind_share_unique_blob_capacity(self):
        attachment = self.upload(b'one')
        self.publish(attachment)
        same_bytes = self.upload(b'one')
        other = self.upload(b'two')
        with patch.object(files, 'MAX_RETAINED_BLOBS', 1):
            files.bind_run_attachment(self.root, same_bytes, 'run_shared')
            with self.assertRaises(files.AttachmentUnavailable):
                files.bind_run_attachment(self.root, other, 'run_new')
        with patch.object(context, 'MAX_RETAINED_BLOBS', 1):
            with self.assertRaisesRegex(context.ProjectContextError, 'blob_capacity'):
                self.publish(other, expected=1)
        self.assertEqual(files.get_attachment(self.root, other)['state'], 'staged')

    def test_whole_collection_rename_preserves_context_and_delete_stays_rejected(self):
        first = self.publish(self.upload())
        def rename(items):
            return [{**item, 'name': 'Garage'} for item in items], None
        mutate_authoritative_projects(self.root, rename)
        self.assertEqual(context.read_project_context(self.root, 'project_mentat'), first)
        with self.assertRaises(ProjectRepositoryConflict):
            mutate_authoritative_projects(self.root, lambda items: ([], None))
        self.assertEqual(context.read_project_context(self.root, 'project_mentat'), first)
        with self.assertRaisesRegex(context.ProjectContextError, 'project_changed'):
            self.publish(expected=1)

    def test_backup_retains_project_only_bytes_and_validates_exact_graph(self):
        published = self.publish(self.upload())
        with private_state_lock(self.root):
            unit = backups.capture_private_console_unit(self.root)
        backups.validate_private_console_unit(unit)
        self.assertEqual(len(unit.blobs), 1)
        self.assertEqual(unit.blobs[0].raw, b'Floorplan with supplied dimensions')
        snapshot = self.root / 'snapshot.sqlite3'
        snapshot.write_bytes(unit.database_raw)
        with closing(sqlite3.connect(snapshot)) as connection:
            self.assertEqual(connection.execute('SELECT brief FROM mentat_project_context_versions').fetchone()[0], published['brief'])
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM run_attachments').fetchone()[0], 0)
        with self.assertRaises(backups.PrivateConsoleUnitError):
            backups.validate_private_console_unit(replace(unit, blobs=()))

    def test_database_enforces_immutable_versions(self):
        published = self.publish()
        with closing(mentat_db.connect(self.root)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('UPDATE mentat_project_context_versions SET brief=? WHERE id=?', ('changed', published['id']))

    def deletion_service(self):
        from tests.sqlite_authority_support import ensure_run_sqlite_authority
        from private_state import history_path
        from planning_deletion import PlanningDeletionService
        ensure_run_sqlite_authority(self.root, history_path(self.root))
        return PlanningDeletionService(self.root)

    def test_confirmed_project_deletion_retires_context_and_id_reuse_is_new_scope(self):
        from planning_deletion import PlanningDeletionError
        original = self.publish(self.upload())
        service = self.deletion_service()
        plan = service.preview('project', 'project_mentat')
        self.assertEqual(plan.retained_context_versions, 1)
        service.finalize(plan)
        retired = context.read_retired_project_context(self.root, original['id'])
        self.assertTrue(retired['retired'])
        self.assertEqual(retired['brief'], original['brief'])
        files.reconcile_startup(self.root, retained_run_ids=(), now=time.time()+10000)
        self.assertEqual(files.read_attachment_bytes(self.root, original['attachment_ids'][0])[1], b'Floorplan with supplied dimensions')
        with private_state_lock(self.root):
            unit = backups.capture_private_console_unit(self.root)
        target = self.root / 'retired-restore'
        (target / 'private').mkdir(parents=True, mode=0o700)
        backups.materialize_private_console_unit(target, unit, target / 'private' / 'console')
        self.assertEqual(context.read_retired_project_context(target, original['id']), retired)
        mutate_authoritative_projects(self.root, lambda items: ([*items, project()], None))
        self.assertIsNone(context.read_project_context(self.root, 'project_mentat'))
        replacement = self.publish(brief='New Project with reused ID')
        self.assertNotEqual(replacement['id'], original['id'])
        self.assertEqual(context.read_retired_project_context(self.root, original['id']), retired)
        with self.assertRaises(PlanningDeletionError):
            service.completed_receipt('project', 'project_mentat', plan.confirmation_id)
        with self.assertRaises(PlanningDeletionError):
            service.finalize(plan)

    def test_context_change_invalidates_deletion_preview_and_late_failure_rolls_back_retirement(self):
        from planning_deletion import PlanningDeletionError
        self.publish()
        service = self.deletion_service()
        old = service.preview('project', 'project_mentat')
        latest = self.publish(expected=1, brief='New approved brief')
        with self.assertRaises(PlanningDeletionError):
            service.finalize(old)
        current = service.preview('project', 'project_mentat')
        erase = service._erase
        def fail_after_erase(connection, plan):
            erase(connection, plan)
            raise sqlite3.OperationalError('injected after retirement and deletion')
        with patch.object(service, '_erase', side_effect=fail_after_erase):
            with self.assertRaises(PlanningDeletionError):
                service.finalize(current)
        self.assertEqual(context.read_project_context(self.root, 'project_mentat'), latest)
        with self.assertRaises(context.ProjectContextError):
            context.read_retired_project_context(self.root, latest['id'])

    def test_task_deletion_does_not_orphan_shared_project_file(self):
        from tests.test_planning_deletion import PlanningDeletionTests
        from planning_deletion import PlanningDeletionService, PlanningDeletionError
        task_root = self.root / 'task-root'
        task_root.mkdir()
        root, _, _ = PlanningDeletionTests().executed_root(str(task_root), retry_count=0)
        attachment = files.create_attachment(root, original_name='shared.md', content=b'Keep for Project')['id']
        with closing(mentat_db.connect(root)) as connection:
            run_id = connection.execute("SELECT id FROM mentat_runs WHERE task_id='task_run'").fetchone()[0]
        files.bind_run_attachment(root, attachment, run_id)
        service = PlanningDeletionService(root)
        stale = service.preview('task', 'task_run')
        published = context.publish_project_context(root, 'project_one', expected_project_revision=1,
            expected_revision=0, brief='Shared goals', attachment_ids=[attachment])
        with self.assertRaises(PlanningDeletionError):
            service.finalize(stale)
        plan = service.preview('task', 'task_run')
        self.assertEqual(plan.retained_context_versions, 1)
        service.finalize(plan)
        files.garbage_collect(root, now=time.time()+10000, orphan_grace=0)
        self.assertEqual(context.read_project_context(root, 'project_one'), published)
        self.assertEqual(files.get_attachment(root, attachment)['state'], 'attached')

    def test_deletion_bridge_projects_retention_count_without_context_content(self):
        import server
        from mentat.local_bridge import bridge_planning_deletion_preview_payload
        self.publish(self.upload(), brief='Private garage requirements')
        self.deletion_service()
        with patch.object(server, 'DATA_DIR', self.root), patch.object(server, 'CONFIGURED_DATA_DIR', self.root):
            payload, status = bridge_planning_deletion_preview_payload({'target_kind': 'project', 'target_id': 'project_mentat'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['retained_context_versions'], 1)
        self.assertNotIn('Private garage requirements', json.dumps(payload))
        self.assertNotIn('attachment_', json.dumps(payload))

    def test_private_restore_preserves_context_and_compatible_export_omits_it(self):
        original = self.publish(self.upload())
        with private_state_lock(self.root):
            unit = backups.capture_private_console_unit(self.root)
        sanitized = backups.sanitize_owner_auth_restore_unit(unit)
        target = self.root / 'restored'
        (target / 'private').mkdir(parents=True, mode=0o700)
        backups.materialize_private_console_unit(target, sanitized, target / 'private' / 'console')
        self.assertEqual(context.read_project_context(target, 'project_mentat'), original)
        self.assertEqual(files.read_attachment_bytes(target, original['attachment_ids'][0])[1], b'Floorplan with supplied dimensions')
        compatible = _schema5_private_unit(unit)
        self.assertEqual(compatible.blobs, ())
        with closing(sqlite3.connect(':memory:')) as connection:
            connection.deserialize(compatible.database_raw)
            self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 5)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='mentat_project_context_versions'").fetchone())
        self.assertEqual(context.read_project_context(self.root, 'project_mentat'), original)

    def test_durable_backup_archive_restore_retains_project_files(self):
        import data_backup_restore
        from tests.test_private_console_state import PrivateConsoleStateTests
        helper = PrivateConsoleStateTests()
        source = helper.make_current(self.root, 'archive-source', 'source')
        (source / 'tasks.json').write_text('[]')
        (source / 'projects.json').write_text(json.dumps([project()]))
        ensure_task_sqlite_authority(source, required_source_mode=None)
        ensure_project_sqlite_authority(source, required_source_mode=None)
        attachment = files.create_attachment(source, original_name='plan.md', content=b'owner floorplan')['id']
        expected = context.publish_project_context(source, 'project_mentat', expected_project_revision=1,
            expected_revision=0, brief='Garage brief', attachment_ids=[attachment])
        result = data_backup_restore.create_durable_backup(source)
        self.assertEqual(result.status, 'created', result.public_summary())
        archive = source / 'backups' / result.backup_name
        target = helper.make_current(self.root, 'archive-target', 'target')
        preview = data_backup_restore.preview_durable_restore(target, archive)
        self.assertEqual(preview.status, 'ready', preview.public_summary())
        restored = data_backup_restore.restore_durable_backup(target, archive, confirmation_token=preview.confirmation_token)
        self.assertEqual(restored.status, 'restored', restored.public_summary())
        self.assertEqual(context.read_project_context(target, 'project_mentat'), expected)
        self.assertEqual(files.read_attachment_bytes(target, attachment)[1], b'owner floorplan')

    def test_partial_reference_removal_is_not_a_valid_version(self):
        published = self.publish(self.upload())
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('DELETE FROM mentat_project_context_files WHERE context_id=?', (published['id'],))
            with self.assertRaisesRegex(context.ProjectContextError, 'invalid'):
                context.validate_project_context_connection(connection)

    def test_schema_rejects_null_and_blob_ids_and_validator_rejects_corrupt_identity(self):
        with closing(mentat_db.connect(self.root)) as connection:
            for identifier in (None, b'x' * 46):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute('INSERT INTO mentat_project_context_scopes(id,project_id,revision,created_at) VALUES(?,?,1,1)', (identifier, 'project_mentat'))
            # Damaged input is a bounded context error even without SQL checks.
            connection.execute('PRAGMA ignore_check_constraints=ON')
            connection.execute('INSERT INTO mentat_project_context_scopes(id,project_id,revision,created_at) VALUES(?,?,1,1)', ('bad', 'project_mentat'))
            with self.assertRaises(context.ProjectContextError):
                context.validate_project_context_connection(connection)


class ProjectContextMigrationTests(unittest.TestCase):
    def schema26(self):
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        for version, script in mentat_db.MIGRATIONS:
            if version > 26:
                break
            connection.executescript(script)
            connection.execute('INSERT INTO schema_migrations VALUES(?,0)', (version,))
            connection.commit()
        connection.execute('PRAGMA foreign_keys=ON')
        return connection

    def test_exact_schema26_upgrades_without_changing_existing_authority(self):
        connection = self.schema26()
        before = tuple(connection.execute('SELECT * FROM mentat_owner_auth_state').fetchone())
        mentat_db.migrate(connection)
        self.assertEqual(mentat_db.schema_signature_state(connection, 34), 'expected')
        self.assertEqual(tuple(connection.execute('SELECT * FROM mentat_owner_auth_state').fetchone()), before)
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_context_scopes').fetchone()[0], 0)
        self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_schema26_drift_and_partial_migration_fail_atomically(self):
        connection = self.schema26()
        connection.execute('CREATE TABLE unexpected(value TEXT)')
        connection.commit()
        with self.assertRaises(mentat_db.MentatDatabaseError):
            mentat_db.migrate(connection)
        self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 26)
        connection.execute('DROP TABLE unexpected')
        broken = tuple((version, script + '\nINVALID SQL;' if version == 27 else script) for version, script in mentat_db.MIGRATIONS)
        with patch.object(mentat_db, 'MIGRATIONS', broken):
            with self.assertRaises(sqlite3.OperationalError):
                mentat_db.migrate(connection)
        self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 26)
        self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='mentat_project_context_scopes'").fetchone())

    def test_schema26_backup_remains_supported(self):
        connection = self.schema26()
        connection.execute(
            "INSERT INTO mentat_agent_registry_state(singleton,authority,migration_contract,source_kind,source_sha256,source_agent_count,cutover_at) "
            "VALUES(1,'sqlite',?,'fresh',?,0,1)",
            (mentat_db.AGENT_REGISTRY_AUTHORITY_CONTRACT, mentat_db.EMPTY_AGENT_REGISTRY_SOURCE_SHA256),
        )
        connection.commit()
        unit = backups.PrivateConsoleUnit(json.dumps({'schema_version': 3, 'runs': []}).encode(), connection.serialize(), None, ())
        backups.validate_private_console_unit(unit)
        backups.validate_private_console_unit(backups.sanitize_owner_auth_restore_unit(unit))

    def test_populated_schema26_run_authority_backup_restores_and_upgrades(self):
        from agent_run_history import save_run_summaries
        from private_state import history_path
        from tests.sqlite_authority_support import ensure_run_sqlite_authority
        from tests.test_run_repository import run_fixture
        from run_repository import RunRepository
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_migrations = tuple(item for item in mentat_db.MIGRATIONS if item[0] <= 26)
            with patch.object(mentat_db, 'MIGRATIONS', old_migrations), patch.object(mentat_db, 'SCHEMA_VERSION', 26):
                save_run_summaries(history_path(root), [run_fixture('run_historical', bound=False)], data_root=root)
                ensure_run_sqlite_authority(root, history_path(root))
                with private_state_lock(root):
                    unit = backups.capture_private_console_unit(root)
            backups.validate_private_console_unit(unit)
            sanitized = backups.sanitize_owner_auth_restore_unit(unit)
            target = root / 'restored'
            (target / 'private').mkdir(parents=True, mode=0o700)
            backups.materialize_private_console_unit(target, sanitized, target / 'private' / 'console')
            with closing(mentat_db.connect(target)) as connection:
                repository = RunRepository(connection)
                self.assertIsNotNone(repository.authority_receipt(required=True))
                self.assertEqual(connection.execute('SELECT id FROM mentat_runs').fetchone()[0], 'run_historical')
                self.assertEqual(mentat_db.schema_signature_state(connection, 34), 'expected')


if __name__ == '__main__':
    unittest.main()
