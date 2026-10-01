from contextlib import closing
import sqlite3
import hashlib
import unittest
from unittest.mock import patch

from agent_registry import AgentRegistry
import mentat_db
import private_console_unit as backups
from private_state import private_state_lock
import project_context as context
import project_context_access as access
from tests import test_project_context as context_tests
from project_repository import mutate_authoritative_projects
from tests.test_project_repository import project


class ProjectContextGrantTests(unittest.TestCase):
    def setUp(self):
        self.fixture = context_tests.ProjectContextTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.registry = AgentRegistry(self.root, supported_runtime_types=('codex',))
        self.registry.create_agent(agent_id='agent_context', name='Research Agent', runtime_config_id='context_config',
            runtime_type='codex', runtime_agent_ref='default', capabilities=('run.start',))
        self.version = self.fixture.publish(self.fixture.upload())

    def preview(self):
        return access.preview_context_grant(self.root, 'project_mentat', self.version['id'], 'agent_context')

    def grant(self, preview=None):
        preview = self.preview() if preview is None else preview
        return access.confirm_context_grant(self.root, 'project_mentat', self.version['id'], 'agent_context', confirmation_id=preview['confirmation_id'])

    def row(self):
        with closing(mentat_db.connect(self.root)) as connection:
            row = connection.execute('SELECT state,reason,revision,context_id FROM mentat_project_context_grants').fetchone()
            return tuple(row) if row else None

    def test_no_implicit_grant_and_confirmation_creates_no_run(self):
        self.assertIsNone(self.row())
        preview = self.preview()
        self.assertEqual(preview['brief'], self.version['brief'])
        self.assertEqual(preview['files'][0]['id'], self.version['attachment_ids'][0])
        self.assertNotIn('agent_incarnation', preview)
        self.assertNotIn('runtime_agent_ref', str(preview))
        granted = self.grant(preview)
        self.assertEqual((granted['state'], granted['revision']), ('active', 1))
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_runs').fetchone()[0], 0)
        with self.assertRaisesRegex(access.ProjectContextAccessError, 'stale'):
            self.grant(preview)

    def test_new_brief_invalidates_preview_but_does_not_expand_existing_grant(self):
        before = self.preview()
        self.fixture.publish(expected=1, brief='New private constraints')
        with self.assertRaisesRegex(access.ProjectContextAccessError, 'stale'):
            self.grant(before)
        self.grant()
        self.assertEqual(self.row()[3], self.version['id'])
        self.fixture.publish(expected=2, brief='Further constraints')
        self.assertEqual(self.row()[3], self.version['id'])

    def test_revoke_requires_exact_revision_and_context(self):
        grant = self.grant()
        for revision, context_id in ((2, self.version['id']), (1, 'project_context_'+'a'*32)):
            with self.assertRaisesRegex(access.ProjectContextAccessError, 'stale'):
                access.revoke_context_grant(self.root, 'project_mentat', context_id, 'agent_context', expected_revision=revision)
        result = access.revoke_context_grant(self.root, 'project_mentat', self.version['id'], 'agent_context', expected_revision=grant['revision'])
        self.assertEqual((result['state'], result['revision']), ('revoked', 2))
        self.assertEqual(self.row()[1], 'owner')

    def test_missing_history_file_does_not_block_revocation_or_explicit_replacement(self):
        import agent_console_attachments as files
        grant = self.grant()
        file_id = self.version['attachment_ids'][0]
        files.resolve_blob_path(self.root, file_id).unlink()
        files.reconcile_startup(self.root)
        revoked = access.revoke_context_grant(self.root, 'project_mentat', self.version['id'], 'agent_context', expected_revision=grant['revision'])
        self.assertEqual(revoked['state'], 'revoked')
        with self.assertRaises(access.ProjectContextAccessError):
            self.preview()
        self.version = self.fixture.publish(self.fixture.upload(b'Replacement floorplan'), expected=1)
        self.assertEqual(self.grant()['state'], 'active')
        # Backup still refuses the missing retained historical bytes: metadata
        # maintenance is not permission to silently omit backup content.
        with self.assertRaises(backups.PrivateConsoleUnitError):
            backups.capture_private_console_unit(self.root)

    def test_project_retirement_revokes_grant_atomically(self):
        self.grant()
        service = self.fixture.deletion_service()
        service.finalize(service.preview('project','project_mentat'))
        self.assertEqual(self.row()[:3], ('revoked','project_deleted',2))

    def test_new_grant_invalidates_a_pending_project_deletion(self):
        from planning_deletion import PlanningDeletionError
        service = self.fixture.deletion_service()
        plan = service.preview('project', 'project_mentat')
        self.grant()
        with self.assertRaises(PlanningDeletionError):
            service.finalize(plan)
        self.assertEqual(self.row()[0], 'active')

    def test_agent_deletion_and_id_reuse_never_restore_old_access(self):
        from project_context_editor import read_project_editor
        self.grant()
        self.assertEqual(read_project_editor(self.root, 'project_mentat')['grants'], [{
            'agent_id': 'agent_context', 'context_id': self.version['id'], 'revision': 1, 'state': 'active', 'reason': None,
        }])
        with closing(mentat_db.connect(self.root)) as connection:
            old = connection.execute("SELECT context_incarnation FROM mentat_agents WHERE id='agent_context'").fetchone()[0]
            connection.execute("DELETE FROM mentat_agents WHERE id='agent_context'")
            connection.execute("DELETE FROM agent_runtime_configs WHERE id='context_config'")
        self.assertEqual(self.row()[:3], ('revoked','agent_deleted',2))
        self.assertEqual(read_project_editor(self.root, 'project_mentat')['grants'], [])
        self.registry.create_agent(agent_id='agent_context',name='Replacement',runtime_config_id='replacement_config',runtime_type='codex',runtime_agent_ref='default',capabilities=('run.start',))
        with closing(mentat_db.connect(self.root)) as connection:
            new = connection.execute("SELECT context_incarnation FROM mentat_agents WHERE id='agent_context'").fetchone()[0]
        self.assertNotEqual(new, old)
        self.assertEqual(read_project_editor(self.root, 'project_mentat')['grants'], [])
        self.assertEqual(self.row()[0], 'revoked')
        self.assertEqual(self.grant()['revision'], 3)
        self.assertEqual(read_project_editor(self.root, 'project_mentat')['grants'][0]['revision'], 3)

    def test_restore_revokes_context_access_even_without_owner_login_configuration(self):
        self.grant()
        with private_state_lock(self.root):
            unit = backups.capture_private_console_unit(self.root)
        restored = backups.sanitize_owner_auth_restore_unit(unit)
        snapshot = self.root / 'restored-inspect.sqlite3'
        snapshot.write_bytes(restored.database_raw)
        with closing(sqlite3.connect(snapshot)) as connection:
            self.assertEqual(connection.execute('SELECT state,reason,revision FROM mentat_project_context_grants').fetchone(), ('revoked','restored',2))
        self.assertEqual(self.row()[0], 'active')

    def test_restore_invalidates_unsubmitted_preview_and_each_restore_has_fresh_epoch(self):
        before = self.preview()
        with private_state_lock(self.root):
            unit = backups.capture_private_console_unit(self.root)
        epochs = []
        for index in range(2):
            restored = backups.sanitize_owner_auth_restore_unit(unit)
            target = self.root / f'restore-{index}'
            (target / 'private').mkdir(parents=True, mode=0o700)
            backups.materialize_private_console_unit(target, restored, target / 'private' / 'console')
            with self.assertRaisesRegex(access.ProjectContextAccessError, 'stale'):
                access.confirm_context_grant(target, 'project_mentat', self.version['id'], 'agent_context', confirmation_id=before['confirmation_id'])
            with closing(mentat_db.connect(target)) as connection:
                epochs.append(connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state').fetchone()[0])
        self.assertNotEqual(epochs[0], epochs[1])
        self.assertEqual(self.grant(before)['state'], 'active')

    def test_admitted_metadata_at_capacity_remains_restorable_after_revocation(self):
        self.grant()
        encoded_sizes = []
        encode = context._encoded
        def observed(value):
            raw = encode(value)
            encoded_sizes.append(len(raw))
            return raw
        with closing(mentat_db.connect(self.root)) as connection, patch.object(context, '_encoded', side_effect=observed):
            context.validate_project_context_connection(connection)
        with patch.object(context, 'MAX_METADATA_BYTES', max(encoded_sizes)):
            with private_state_lock(self.root):
                unit = backups.capture_private_console_unit(self.root)
            restored = backups.sanitize_owner_auth_restore_unit(unit)
            backups.validate_private_console_unit(restored)

    def test_full_context_budget_reserves_future_agent_creation(self):
        sizes = []
        encode = context._encoded
        def observed(value):
            result = encode(value)
            sizes.append(len(result))
            return result
        with closing(mentat_db.connect(self.root)) as connection, patch.object(context, '_encoded', side_effect=observed):
            context.validate_project_context_connection(connection)
        with patch.object(context, 'MAX_METADATA_BYTES', max(sizes)):
            registry = AgentRegistry(self.root, supported_runtime_types=('hermes','codex'))
            for index in range(127):
                identifier = f'agent_{index}_' + 'x' * (128 - len(f'agent_{index}_'))
                registry.create_agent(agent_id=identifier, name=f'Agent {index}', runtime_config_id=f'config_{index}', runtime_type='hermes', runtime_agent_ref=f'profile_{index}', capabilities=('run.start',))
            with closing(mentat_db.connect(self.root)) as connection:
                context.validate_project_context_connection(connection)
            with private_state_lock(self.root):
                unit = backups.capture_private_console_unit(self.root)
            backups.validate_private_console_unit(unit)


class ProjectContextAccessMigrationTests(unittest.TestCase):
    def test_virtual_empty_snapshot_identity_is_stable(self):
        first = backups.empty_private_console_unit()
        second = backups.empty_private_console_unit()
        self.assertEqual(backups.private_console_unit_digest(first), backups.private_console_unit_digest(second))

    def test_full_schema27_context_budget_migrates_and_remains_retirable_and_restorable(self):
        fixture = context_tests.ProjectContextTests()
        old_migrations = tuple(item for item in mentat_db.MIGRATIONS if item[0] <= 27)
        with patch.object(mentat_db, 'MIGRATIONS', old_migrations), patch.object(mentat_db, 'SCHEMA_VERSION', 27):
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            root = fixture.root
            extra = [project(f'Capacity {index}', f'project_capacity_{index}') for index in range(1,8)]
            mutate_authoritative_projects(root, lambda rows: ([*rows, *extra], None))
            registry = AgentRegistry(root, supported_runtime_types=('hermes',))
            for index in range(128):
                registry.create_agent(agent_id='agent_'+f'{index:0122d}',name=f'Agent {index}',runtime_config_id=f'config_{index}',runtime_type='hermes',runtime_agent_ref=f'profile_{index}',capabilities=('run.start',))
            projects = ['project_mentat', *[item['id'] for item in extra]]
            scopes = [[f'project_scope_{index:032x}', project_id, 32, 1.0, None] for index, project_id in enumerate(projects)]
            empty_digest = hashlib.sha256(b'[]').hexdigest()
            versions = [[f'project_context_{index:032x}', scopes[index//32][0], index%32+1, '', empty_digest, 1.0] for index in range(256)]
            remaining = context.LEGACY_MAX_METADATA_BYTES - len(context._encoded([scopes,versions,[]]))
            self.assertLessEqual(remaining, 256 * context.MAX_BRIEF_BYTES)
            for row in versions:
                count = min(remaining, context.MAX_BRIEF_BYTES)
                row[3] = 'x' * count
                remaining -= count
            self.assertEqual(remaining, 0)
            self.assertEqual(len(context._encoded([scopes,versions,[]])), context.LEGACY_MAX_METADATA_BYTES)
            with closing(mentat_db.connect(root)) as connection:
                connection.executemany('INSERT INTO mentat_project_context_scopes VALUES(?,?,?,?,?)', scopes)
                connection.executemany('INSERT INTO mentat_project_context_versions VALUES(?,?,?,?,?,?)', versions)
                context.validate_project_context_connection(connection)
            with private_state_lock(root):
                historical = backups.capture_private_console_unit(root)
        backups.validate_private_console_unit(historical)
        with closing(mentat_db.connect(root)) as connection:
            self.assertEqual(mentat_db.schema_signature_state(connection, 33), 'expected')
            context.validate_project_context_connection(connection)
        service = fixture.deletion_service()
        service.finalize(service.preview('project','project_mentat'))
        with private_state_lock(root):
            unit = backups.capture_private_console_unit(root)
        backups.validate_private_console_unit(backups.sanitize_owner_auth_restore_unit(unit))


if __name__ == '__main__':
    unittest.main()
