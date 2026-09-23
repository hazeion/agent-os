from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import data_backup_restore as restore
import mentat_db
import private_console_unit as private_unit
import project_context
import project_context_access as access
from agent_registry import AgentRegistry
from owner_auth import OwnerAuthAuthority, OwnerAuthError
from project_repository import ensure_project_sqlite_authority
from task_repository import ensure_task_sqlite_authority
from tests import test_private_console_state as private_tests
from tests import test_owner_auth as auth_tests
from tests.test_project_repository import project


class RestoreSanitizationContextTests(unittest.TestCase):
    def source(self, base, *, granted=True, authenticated=True):
        helper = private_tests.PrivateConsoleStateTests()
        source = helper.make_current(base, 'source', 'source')
        (source / 'tasks.json').write_text('[]')
        (source / 'projects.json').write_text(json.dumps([project()]))
        ensure_task_sqlite_authority(source, required_source_mode=None)
        ensure_project_sqlite_authority(source, required_source_mode=None)
        AgentRegistry(source, supported_runtime_types=('codex',)).create_agent(
            agent_id='agent_restore', name='Restore Agent', runtime_config_id='restore_config',
            runtime_type='codex', runtime_agent_ref='default', capabilities=('run.start',))
        context = project_context.publish_project_context(source, 'project_mentat', expected_project_revision=1,
            expected_revision=0, brief='Preserve the garage brief', attachment_ids=[])
        preview = access.preview_context_grant(source, 'project_mentat', context['id'], 'agent_restore')
        if granted:
            access.confirm_context_grant(source, 'project_mentat', context['id'], 'agent_restore', confirmation_id=preview['confirmation_id'])
        session = None
        if authenticated:
            authority = OwnerAuthAuthority(source, _registration_verifier=auth_tests.OwnerAuthAuthorityTests._fixture_registration)
            bootstrap = authority.open_bootstrap('https://mentat.example')
            ceremony = authority.start_bootstrap_registration(bootstrap.code, 'primary')
            session = authority.finish_registration(ceremony.ceremony_id, auth_tests.OwnerAuthAuthorityTests.registration())
        backup = restore.create_durable_backup(source)
        self.assertEqual(backup.status, 'created', backup.public_summary())
        return source, source / 'backups' / backup.backup_name, context, preview, session

    def epoch(self, target):
        with closing(sqlite3.connect(mentat_db.database_path(target))) as connection:
            return connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state').fetchone()[0]

    def test_interruptions_reuse_exact_sanitization_and_new_attempt_rotates_it(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source, archive, _, _, session = self.source(base)
            helper = private_tests.PrivateConsoleStateTests()
            for phase in ('published', 'old_removed', 'receipt_removal'):
                with self.subTest(phase=phase):
                    target = helper.make_current(base, 'target-'+phase, 'target')
                    mentat_db.connect(target).close()
                    preview = restore.preview_durable_restore(target, archive)
                    self.assertEqual(preview.status, 'ready', preview.public_summary())
                    if phase == 'published':
                        original = restore._restore_private_console_under_lock
                        def interrupt(*args, **kwargs):
                            original(*args, **kwargs)
                            raise OSError('injected after publication')
                        patched = patch.object(restore, '_restore_private_console_under_lock', side_effect=interrupt)
                    elif phase == 'old_removed':
                        original = restore.remove_private_console_tree
                        def interrupt(root, path):
                            original(root, path)
                            if path.name.endswith('-old'):
                                raise OSError('injected after old tree removal')
                        patched = patch.object(restore, 'remove_private_console_tree', side_effect=interrupt)
                    else:
                        original = restore._unlink_relative
                        def interrupt(path, parent):
                            if path.name == restore.RESTORE_STATE_NAME:
                                raise OSError('injected before receipt removal')
                            return original(path, parent)
                        patched = patch.object(restore, '_unlink_relative', side_effect=interrupt)
                    with patched:
                        partial = restore.restore_durable_backup(target, archive, confirmation_token=preview.confirmation_token)
                    self.assertEqual(partial.status, 'partial_failure', partial.public_summary())
                    state_path = target / 'config' / restore.RESTORE_STATE_NAME
                    state_bytes = state_path.read_bytes()
                    self.assertEqual(json.loads(state_bytes)['protocol_version'], 4)
                    epoch = self.epoch(target)
                    first = restore.preview_durable_restore(target, archive)
                    second = restore.preview_durable_restore(target, archive)
                    self.assertEqual(first.status, 'resume_required', first.public_summary())
                    self.assertEqual(second.status, 'resume_required', second.public_summary())
                    self.assertEqual(first.confirmation_token, second.confirmation_token)
                    self.assertEqual(state_path.read_bytes(), state_bytes)
                    resumed = restore.restore_durable_backup(target, archive, confirmation_token=second.confirmation_token)
                    self.assertEqual(resumed.status, 'resumed', resumed.public_summary())
                    self.assertEqual(self.epoch(target), epoch)
                    with closing(mentat_db.connect(target)) as connection:
                        self.assertEqual(tuple(connection.execute('SELECT state,reason,revision FROM mentat_project_context_grants').fetchone()), ('revoked','restored',2))
                    with self.assertRaises(OwnerAuthError):
                        OwnerAuthAuthority(target).authenticate_session(session.cookie_value)
                    again = restore.preview_durable_restore(target, archive)
                    self.assertEqual(again.status, 'ready', again.public_summary())
                    completed = restore.restore_durable_backup(target, archive, confirmation_token=again.confirmation_token)
                    self.assertEqual(completed.status, 'restored', completed.public_summary())
                    self.assertNotEqual(self.epoch(target), epoch)

    def test_real_archive_restore_invalidates_unsubmitted_grant_preview(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            _, archive, context, approval, _ = self.source(base, granted=False, authenticated=False)
            target = private_tests.PrivateConsoleStateTests().make_current(base, 'target', 'target')
            preview = restore.preview_durable_restore(target, archive)
            result = restore.restore_durable_backup(target, archive, confirmation_token=preview.confirmation_token)
            self.assertEqual(result.status, 'restored', result.public_summary())
            with self.assertRaisesRegex(access.ProjectContextAccessError, 'stale'):
                access.confirm_context_grant(target, 'project_mentat', context['id'], 'agent_restore', confirmation_id=approval['confirmation_id'])

    def test_changed_published_tree_or_receipt_seed_cannot_resume(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            _, archive, _, _, _ = self.source(base, granted=False, authenticated=False)
            for changed in ('tree', 'seed'):
                with self.subTest(changed=changed):
                    target = private_tests.PrivateConsoleStateTests().make_current(base, 'target-'+changed, 'target')
                    preview = restore.preview_durable_restore(target, archive)
                    original = restore._restore_private_console_under_lock
                    def interrupt(*args, **kwargs):
                        original(*args, **kwargs)
                        raise OSError('injected after publication')
                    with patch.object(restore, '_restore_private_console_under_lock', side_effect=interrupt):
                        result = restore.restore_durable_backup(target, archive, confirmation_token=preview.confirmation_token)
                    self.assertEqual(result.status, 'partial_failure')
                    if changed == 'tree':
                        with closing(sqlite3.connect(mentat_db.database_path(target))) as connection:
                            connection.execute('UPDATE mentat_project_context_access_state SET approval_epoch=randomblob(32)')
                            connection.commit()
                    else:
                        state_path = target / 'config' / restore.RESTORE_STATE_NAME
                        state = json.loads(state_path.read_text())
                        state['sanitization']['seed'] = 'f' * 64
                        state_path.write_bytes(restore._canonical_json(state))
                    rejected = restore.preview_durable_restore(target, archive)
                    self.assertEqual(rejected.status, 'unsafe', rejected.public_summary())

    def test_sanitization_context_rejects_hostile_timestamp_without_overflow(self):
        for value in (True, -1, 0, float('nan'), float('inf'), 10**1000, 'today'):
            self.assertFalse(restore._valid_sanitization_timestamp(value))

    def test_published_protocol3_owner_sanitization_with_real_clock_resumes_exactly(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            helper = private_tests.PrivateConsoleStateTests()
            old_migrations = tuple(item for item in mentat_db.MIGRATIONS if item[0] <= 27)
            with patch.object(mentat_db, 'MIGRATIONS', old_migrations), patch.object(mentat_db, 'SCHEMA_VERSION', 27):
                source = helper.make_current(base, 'legacy-source', 'source')
                authority = OwnerAuthAuthority(source, _registration_verifier=auth_tests.OwnerAuthAuthorityTests._fixture_registration)
                grant = authority.open_bootstrap('https://mentat.example')
                ceremony = authority.start_bootstrap_registration(grant.code, 'primary')
                authority.finish_registration(ceremony.ceremony_id, auth_tests.OwnerAuthAuthorityTests.registration())
                backup = restore.create_durable_backup(source)
                self.assertEqual(backup.status, 'created')
                archive = source / 'backups' / backup.backup_name
                target = helper.make_current(base, 'legacy-target', 'target')
                mentat_db.connect(target).close()
                prior_timestamp = time.time()
                original = restore._restore_private_console_under_lock
                def interrupt(*args, **kwargs):
                    original(*args, **kwargs)
                    raise OSError('published protocol3 interruption')
                def published_sanitizer(source_unit, _state, **_kwargs):
                    return private_unit.sanitize_owner_auth_restore_unit(source_unit, now=prior_timestamp)
                with patch.object(restore, 'RESTORE_PROTOCOL_VERSION', 3):
                    preview = restore.preview_durable_restore(target, archive)
                    with patch.object(restore, '_sanitized_restore_source', side_effect=published_sanitizer), patch.object(restore, '_restore_private_console_under_lock', side_effect=interrupt):
                        partial = restore.restore_durable_backup(target, archive, confirmation_token=preview.confirmation_token)
                self.assertEqual(partial.status, 'partial_failure', partial.public_summary())
            state = json.loads((target / 'config' / restore.RESTORE_STATE_NAME).read_text())
            self.assertEqual(state['protocol_version'], 3)
            self.assertNotIn('sanitization', state)
            published = private_unit.capture_private_console_unit(target)
            source_unit = restore._read_backup_file(archive)[2]
            witness = private_unit.matching_legacy_owner_restore_unit(source_unit, published)
            self.assertIsNotNone(witness)
            # Unrelated valid metadata changes must not pass merely because the
            # session flags and all sanitization timestamps look correct.
            mutated_path = base / 'mutated.sqlite3'
            mutated_path.write_bytes(published.database_raw)
            with closing(sqlite3.connect(mutated_path)) as connection:
                connection.execute('UPDATE mentat_owner_auth_credentials SET sign_count=sign_count+1')
                connection.commit()
            mutated = private_unit.PrivateConsoleUnit(published.history_raw, mutated_path.read_bytes(), published.registry_database_raw, published.blobs)
            self.assertIsNone(private_unit.matching_legacy_owner_restore_unit(source_unit, mutated))
            for _ in range(2):
                resume = restore.preview_durable_restore(target, archive)
                self.assertEqual(resume.status, 'resume_required', resume.public_summary())
            completed = restore.restore_durable_backup(target, archive, confirmation_token=resume.confirmation_token)
            self.assertEqual(completed.status, 'resumed', completed.public_summary())
            with closing(sqlite3.connect(mentat_db.database_path(target))) as connection:
                self.assertEqual(connection.execute('SELECT revoked_at FROM mentat_owner_auth_sessions').fetchone()[0], prior_timestamp)
