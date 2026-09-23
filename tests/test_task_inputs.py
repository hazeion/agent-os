from dataclasses import FrozenInstanceError
from contextlib import closing
import sqlite3
from threading import Barrier, Thread
import unittest
from unittest.mock import patch

import mentat_db
import project_context
import project_context_access
import project_context_editor
import private_console_unit
from agent_registry import AgentRegistry
from task_repository import mutate_authoritative_tasks, TaskRepository
from tests import test_project_context as context_tests
from tests.test_task_repository import task

from task_inputs import normalize_input_selection, validate_selected_files, TaskInputError
from task_inputs import publish_task_inputs, read_task_input_editor, read_retired_task_input_history, read_retired_task_input, preview_task_input_prune, confirm_task_input_prune


def selection_payload(count=1):
    return {'project_id': 'project_garage', 'task_id': 'task_research', 'agent_id': 'agent_research',
            'expected_task_revision': 1, 'expected_input_revision': 0,
            'expected_task_token': 'f'*64,
            'context_id': 'project_context_' + 'a'*32, 'expected_grant_revision': 1,
            'instructions': 'Keep bicycle access clear.',
            'attachment_ids': ['attachment_' + f'{index:032x}' for index in range(count)]}


class TaskInputContractTests(unittest.TestCase):
    def test_selection_is_immutable_and_does_not_alias_the_request(self):
        payload = selection_payload()
        value = normalize_input_selection(payload)
        payload['attachment_ids'].clear()
        self.assertEqual(len(value.attachment_ids), 1)
        with self.assertRaises(FrozenInstanceError):
            value.instructions = 'Changed'

    def test_widened_authority_missing_fields_and_unsafe_revisions_are_rejected(self):
        baseline = selection_payload()
        invalid = [{**baseline, 'runtime_agent_ref': 'default'},
                   {**baseline, 'expected_grant_revision': True},
                   {**baseline, 'expected_task_revision': 0},
                   {**baseline, 'expected_input_revision': 2**53},
                   {**baseline, 'context_id': '/private/file'},
                   {**baseline, 'attachment_ids': baseline['attachment_ids']*2},
                   {**baseline, 'attachment_ids': None}, selection_payload(9)]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(TaskInputError):
                    normalize_input_selection(value)

    def test_instruction_limit_is_utf8_and_never_truncates(self):
        value = selection_payload(0)
        value['instructions'] = '\U0001f6b2' * 4096
        self.assertEqual(normalize_input_selection(value).instructions, value['instructions'])
        for instructions in (value['instructions']+'x', 'invalid\0text', '\ud800'):
            with self.assertRaises(TaskInputError):
                normalize_input_selection({**value, 'instructions': instructions})

    def test_complete_order_and_adapter_limits_are_required(self):
        selection = normalize_input_selection(selection_payload(8))
        metadata = [{'id': identifier, 'state': 'attached', 'kind': 'text', 'byte_size': 20, 'mime_type': 'text/plain'} for identifier in selection.attachment_ids]
        validate_selected_files(selection, metadata)
        for values in (metadata[:-1], list(reversed(metadata)), [*metadata[:-1], {**metadata[-1], 'state': 'missing'}]):
            with self.assertRaises(TaskInputError):
                validate_selected_files(selection, values)
        with self.assertRaises(TaskInputError):
            validate_selected_files(selection, metadata, adapter_file_limit=5)
        with self.assertRaises(TaskInputError):
            validate_selected_files(selection, metadata, adapter_file_limit=True)
        self.assertEqual(len(selection.attachment_ids), 8)

    def test_one_image_ceiling_and_verified_size_shape(self):
        selection = normalize_input_selection(selection_payload(2))
        metadata = [{'id': identifier, 'state': 'attached', 'kind': 'image', 'byte_size': 20, 'mime_type': 'image/png'} for identifier in selection.attachment_ids]
        with self.assertRaisesRegex(TaskInputError, 'image_limit'):
            validate_selected_files(selection, metadata)
        metadata[1].update(kind='text', mime_type='text/plain')
        validate_selected_files(selection, metadata)
        with self.assertRaisesRegex(TaskInputError, 'image_limit'):
            validate_selected_files(selection, metadata, adapter_image_limit=0)
        metadata[0]['byte_size'] = True
        with self.assertRaises(TaskInputError):
            validate_selected_files(selection, metadata)

        metadata[0].update(byte_size=20, kind=[])
        with self.assertRaises(TaskInputError):
            validate_selected_files(selection, metadata)
        metadata[0].update(kind='image', mime_type=[])
        with self.assertRaises(TaskInputError):
            validate_selected_files(selection, metadata)


class TaskInputStorageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = context_tests.ProjectContextTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups); self.root = self.fixture.root
        AgentRegistry(self.root, supported_runtime_types=('codex',)).create_agent(agent_id='agent_research', name='Research', runtime_config_id='config_research', runtime_type='codex', runtime_agent_ref='default', capabilities=('run.start',))
        mutate_authoritative_tasks(self.root, lambda rows: ([*rows, {**task('task_research'), 'project_id': 'project_mentat', 'assigned_agent_id': 'agent_research'}], None))
        self.attachment = self.fixture.upload()
        self.context = self.fixture.publish(self.attachment)
        preview = project_context_access.preview_context_grant(self.root, 'project_mentat', self.context['id'], 'agent_research')
        project_context_access.confirm_context_grant(self.root, 'project_mentat', self.context['id'], 'agent_research', confirmation_id=preview['confirmation_id'])
        self.payload = {**selection_payload(), 'project_id': 'project_mentat', 'context_id': self.context['id'], 'attachment_ids': [self.attachment]}
        self.payload['expected_task_token'] = read_task_input_editor(self.root, 'task_research')['expected_task_token']

    def test_publication_is_retained_immutable_and_creates_no_run(self):
        result = publish_task_inputs(self.root, self.payload)
        self.assertEqual(result['revision'], 1)
        owner_view = read_task_input_editor(self.root, 'task_research')
        self.assertEqual(owner_view['version']['id'], result['input_id'])
        self.assertEqual(owner_view['eligible_contexts'][0]['context']['id'], self.context['id'])
        self.assertEqual(owner_view['eligible_contexts'][0]['grant_revision'], 1)
        self.assertEqual(owner_view['version']['files'][0]['id'], self.attachment)
        self.assertNotIn('binding_digest', str(owner_view))
        self.assertNotIn('input_incarnation', str(owner_view))
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_runs').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_task_input_versions').fetchone()[0], 1)
            with self.assertRaisesRegex(Exception, 'immutable'):
                connection.execute("UPDATE mentat_task_input_versions SET instructions='changed'")
            self.assertNotIn('input_incarnation', TaskRepository(connection).get('task_research').document)
        with self.assertRaisesRegex(TaskInputError, 'revision_conflict'):
            publish_task_inputs(self.root, self.payload)
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)

    def test_task_edit_keeps_identity_and_deletion_recreation_retires_input_scope(self):
        original_version = publish_task_inputs(self.root, self.payload)
        with closing(mentat_db.connect(self.root)) as connection:
            original = connection.execute('SELECT input_incarnation FROM mentat_tasks').fetchone()[0]
        mutate_authoritative_tasks(self.root, lambda rows: ([{**rows[0], 'title': 'Edited title'}], None))
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT input_incarnation FROM mentat_tasks').fetchone()[0], original)
            self.assertIsNone(connection.execute('SELECT retired_at FROM mentat_task_input_scopes').fetchone()[0])
        mutate_authoritative_tasks(self.root, lambda rows: ([], None))
        mutate_authoritative_tasks(self.root, lambda rows: ([{**task('task_research'), 'project_id': 'project_mentat', 'assigned_agent_id': 'agent_research'}], None))
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertNotEqual(connection.execute('SELECT input_incarnation FROM mentat_tasks').fetchone()[0], original)
            self.assertIsNotNone(connection.execute('SELECT retired_at FROM mentat_task_input_scopes').fetchone()[0])
            project_context.validate_project_context_connection(connection)
        with self.assertRaisesRegex(TaskInputError, 'task_changed'):
            publish_task_inputs(self.root, self.payload)
        replacement_payload = {**self.payload, 'expected_task_token': read_task_input_editor(self.root, 'task_research')['expected_task_token']}
        replacement = publish_task_inputs(self.root, replacement_payload)
        self.assertEqual(replacement['revision'], 1)
        with self.assertRaisesRegex(TaskInputError, 'version_unavailable'):
            read_task_input_editor(self.root, 'task_research', version_id=original_version['input_id'])
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_task_input_scopes').fetchone()[0], 2)

    def test_changed_grant_assignment_and_unselected_context_files_fail_whole(self):
        for changes in ({'agent_id': 'agent_other'}, {'expected_grant_revision': 2}, {'expected_task_revision': 2}, {'attachment_ids': [self.fixture.upload(b'Unselected')]}):
            with self.assertRaises(TaskInputError):
                publish_task_inputs(self.root, {**self.payload, **changes})
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_task_input_versions').fetchone()[0], 0)

    def test_input_history_pins_context_after_grant_revocation(self):
        publish_task_inputs(self.root, self.payload)
        self.fixture.publish(expected=1, brief='New version')
        project_context_access.revoke_context_grant(self.root, 'project_mentat', self.context['id'], 'agent_research', expected_revision=1)
        with self.assertRaisesRegex(project_context_editor.ProjectContextEditorError, 'task_input'):
            project_context_editor.preview_context_prune(self.root, self.context['id'])
        self.assertEqual(project_context_editor.read_context_version(self.root, self.context['id'])['prune_blocked'], 'task_input')
        private_console_unit.validate_private_console_unit(private_console_unit.capture_private_console_unit(self.root))

    def test_reassignment_requires_new_grant_and_keeps_previous_version_separate(self):
        original = publish_task_inputs(self.root, self.payload)
        AgentRegistry(self.root, supported_runtime_types=('codex', 'hermes')).create_agent(agent_id='agent_layout', name='Layout', runtime_config_id='config_layout', runtime_type='hermes', runtime_agent_ref='profile_layout', capabilities=('run.start',))
        mutate_authoritative_tasks(self.root, lambda rows: ([{**rows[0], 'assigned_agent_id': 'agent_layout'}], None))
        with self.assertRaises(TaskInputError):
            publish_task_inputs(self.root, {**self.payload, 'agent_id': 'agent_layout', 'expected_task_revision': 2, 'expected_input_revision': 1})
        preview = project_context_access.preview_context_grant(self.root, 'project_mentat', self.context['id'], 'agent_layout')
        project_context_access.confirm_context_grant(self.root, 'project_mentat', self.context['id'], 'agent_layout', confirmation_id=preview['confirmation_id'])
        revised = publish_task_inputs(self.root, {**self.payload, 'agent_id': 'agent_layout', 'expected_task_revision': 2, 'expected_input_revision': 1,
            'expected_task_token': read_task_input_editor(self.root, 'task_research')['expected_task_token']})
        self.assertNotEqual(original['input_id'], revised['input_id'])
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual([tuple(row) for row in connection.execute('SELECT revision,agent_id FROM mentat_task_input_versions ORDER BY revision')], [(1,'agent_research'),(2,'agent_layout')])
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_runs').fetchone()[0], 0)

    def test_capacity_failure_rolls_back_head_and_version(self):
        with patch('task_inputs.MAX_INPUT_VERSIONS', 0), self.assertRaises(project_context.ProjectContextError):
            publish_task_inputs(self.root, self.payload)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_task_input_scopes').fetchone()[0], 0)

    def test_retained_file_metadata_must_keep_supported_type_and_size(self):
        publish_task_inputs(self.root, self.payload)
        with closing(mentat_db.connect(self.root)) as connection:
            original = tuple(connection.execute('SELECT kind,mime_type,byte_size FROM attachments WHERE id=?', (self.attachment,)).fetchone())
            for updates in ({'kind':'image','mime_type':'image/svg+xml'}, {'kind':'text','mime_type':'application/x-unsafe'}, {'kind':'text','mime_type':'text/plain','byte_size':3*1024*1024}):
                for field, value in updates.items():
                    connection.execute(f'UPDATE attachments SET {field}=? WHERE id=?', (value, self.attachment))
                with self.assertRaises(project_context.ProjectContextError):
                    project_context.validate_project_context_connection(connection)
                connection.execute('UPDATE attachments SET kind=?,mime_type=?,byte_size=? WHERE id=?', (*original, self.attachment))
            project_context.validate_project_context_connection(connection)

    def test_scope_and_version_identity_columns_reject_null(self):
        publish_task_inputs(self.root, self.payload)
        with closing(mentat_db.connect(self.root)) as connection:
            original = tuple(connection.execute('SELECT task_id,task_incarnation,project_scope_id,revision,created_at FROM mentat_task_input_scopes').fetchone())
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('INSERT INTO mentat_task_input_scopes VALUES(NULL,?,?,?,?,?,NULL)', original)
            version = tuple(connection.execute('SELECT scope_id,revision,task_revision,agent_id,agent_incarnation,context_id,grant_revision,binding_digest,instructions,files_digest,created_at FROM mentat_task_input_versions').fetchone())
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('INSERT INTO mentat_task_input_versions VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?)', version)

    def test_restore_revokes_grant_but_keeps_immutable_input_evidence(self):
        published = publish_task_inputs(self.root, self.payload)
        source = private_console_unit.capture_private_console_unit(self.root)
        restored = private_console_unit.sanitize_owner_auth_restore_unit(source)
        private_console_unit.validate_private_console_unit(restored)
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'restored.sqlite3'
            path.write_bytes(restored.database_raw)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute('SELECT id FROM mentat_task_input_versions').fetchone()[0], published['input_id'])
                self.assertEqual(connection.execute('SELECT state FROM mentat_project_context_grants').fetchone()[0], 'revoked')

    def test_concurrent_exact_publication_has_one_winner(self):
        barrier = Barrier(2)
        outcomes = []
        def submit():
            barrier.wait(timeout=5)
            try:
                outcomes.append(('saved', publish_task_inputs(self.root, self.payload)['revision']))
            except TaskInputError as exc:
                outcomes.append(('rejected', str(exc)))
        threads = [Thread(target=submit) for _ in range(2)]
        for worker in threads: worker.start()
        for worker in threads: worker.join(timeout=10)
        self.assertTrue(all(not worker.is_alive() for worker in threads))
        self.assertEqual(sum(status == 'saved' for status, _ in outcomes), 1)
        self.assertEqual(sum(status == 'rejected' for status, _ in outcomes), 1)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_task_input_versions').fetchone()[0], 1)

    def test_deletion_preview_binds_new_input_and_retains_history(self):
        from planning_deletion import PlanningDeletionError
        service = self.fixture.deletion_service()
        before = service.preview('task', 'task_research')
        published = publish_task_inputs(self.root, self.payload)
        with self.assertRaises(PlanningDeletionError):
            service.finalize(before)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertIsNotNone(TaskRepository(connection).get('task_research'))
        reviewed = service.preview('task', 'task_research')
        self.assertEqual(reviewed.retained_input_versions, 1)
        service.finalize(reviewed)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT id FROM mentat_task_input_versions').fetchone()[0], published['input_id'])
            self.assertIsNotNone(connection.execute('SELECT retired_at FROM mentat_task_input_scopes').fetchone()[0])
        private_console_unit.validate_private_console_unit(private_console_unit.capture_private_console_unit(self.root))

    def test_durable_backup_restores_retained_input_and_revokes_grant(self):
        import data_backup_restore
        import agent_console_attachments as files
        from project_repository import ensure_project_sqlite_authority
        from task_repository import ensure_task_sqlite_authority
        from tests.test_private_console_state import PrivateConsoleStateTests
        from tests.test_project_repository import project
        helper = PrivateConsoleStateTests()
        source = helper.make_current(self.root, 'input-archive-source', 'source')
        (source / 'tasks.json').write_text('[]')
        (source / 'projects.json').write_text(__import__('json').dumps([project()]))
        ensure_task_sqlite_authority(source, required_source_mode=None)
        ensure_project_sqlite_authority(source, required_source_mode=None)
        AgentRegistry(source, supported_runtime_types=('codex',)).create_agent(agent_id='agent_research', name='Research', runtime_config_id='config_research', runtime_type='codex', runtime_agent_ref='default', capabilities=('run.start',))
        mutate_authoritative_tasks(source, lambda rows: ([*rows, {**task('task_research'), 'project_id': 'project_mentat', 'assigned_agent_id': 'agent_research'}], None))
        attachment = files.create_attachment(source, original_name='dimensions.md', content=b'6 by 5 metres')['id']
        context = project_context.publish_project_context(source, 'project_mentat', expected_project_revision=1, expected_revision=0, brief='Garage goals', attachment_ids=[attachment])
        preview = project_context_access.preview_context_grant(source, 'project_mentat', context['id'], 'agent_research')
        project_context_access.confirm_context_grant(source, 'project_mentat', context['id'], 'agent_research', confirmation_id=preview['confirmation_id'])
        published = publish_task_inputs(source, {**self.payload, 'context_id': context['id'], 'attachment_ids': [attachment],
            'expected_task_token': read_task_input_editor(source, 'task_research')['expected_task_token']})
        archive_result = data_backup_restore.create_durable_backup(source)
        self.assertEqual(archive_result.status, 'created', archive_result.public_summary())
        target = helper.make_current(self.root, 'input-archive-target', 'target')
        archive = source / 'backups' / archive_result.backup_name
        restore_preview = data_backup_restore.preview_durable_restore(target, archive)
        self.assertEqual(restore_preview.status, 'ready', restore_preview.public_summary())
        restored = data_backup_restore.restore_durable_backup(target, archive, confirmation_token=restore_preview.confirmation_token)
        self.assertEqual(restored.status, 'restored', restored.public_summary())
        with closing(mentat_db.connect(target)) as connection:
            self.assertEqual(connection.execute('SELECT id FROM mentat_task_input_versions').fetchone()[0], published['input_id'])
            self.assertEqual(connection.execute('SELECT state FROM mentat_project_context_grants').fetchone()[0], 'revoked')
        self.assertEqual(files.read_attachment_bytes(target, attachment)[1], b'6 by 5 metres')

    def test_current_input_is_protected_and_old_version_needs_exact_prune_preview(self):
        first = publish_task_inputs(self.root, self.payload)
        with self.assertRaisesRegex(TaskInputError, 'current_version'):
            preview_task_input_prune(self.root, first['input_id'])
        second = publish_task_inputs(self.root, {**self.payload, 'expected_input_revision': 1, 'instructions': 'Updated garage notes'})
        before = preview_task_input_prune(self.root, first['input_id'])
        mutate_authoritative_tasks(self.root, lambda rows: ([{**rows[0], 'title': 'Revised task title'}], None))
        with self.assertRaisesRegex(TaskInputError, 'stale'):
            confirm_task_input_prune(self.root, first['input_id'], confirmation_id=before['confirmation_id'])
        exact = preview_task_input_prune(self.root, first['input_id'])
        confirm_task_input_prune(self.root, first['input_id'], confirmation_id=exact['confirmation_id'])
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT id FROM mentat_task_input_versions').fetchone()[0], second['input_id'])
            project_context.validate_project_context_connection(connection)

    def test_retired_history_can_be_read_and_pruned_without_adopting_reused_task_id(self):
        first = publish_task_inputs(self.root, self.payload)
        mutate_authoritative_tasks(self.root, lambda rows: ([], None))
        mutate_authoritative_tasks(self.root, lambda rows: ([{**task('task_research'), 'project_id': 'project_mentat', 'assigned_agent_id': 'agent_research'}], None))
        history = read_retired_task_input_history(self.root)
        self.assertEqual(history[0]['id'], first['input_id'])
        self.assertEqual(read_retired_task_input(self.root, first['input_id'])['files'][0]['id'], self.attachment)
        preview = preview_task_input_prune(self.root, first['input_id'])
        confirm_task_input_prune(self.root, first['input_id'], confirmation_id=preview['confirmation_id'])
        self.assertEqual(read_retired_task_input_history(self.root), [])
        with self.assertRaisesRegex(TaskInputError, 'version_unavailable'):
            read_retired_task_input(self.root, first['input_id'])
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_task_input_scopes').fetchone()[0], 0)
            project_context.validate_project_context_connection(connection)
