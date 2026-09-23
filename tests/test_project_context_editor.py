from contextlib import closing
import json
import time
import unittest
from unittest.mock import patch

import agent_console_attachments as files
import mentat_db
import private_console_unit as backups
import project_context as context
import project_context_access as access
import project_context_editor as editor
from project_repository import mutate_authoritative_projects
from tests import test_project_context as context_tests
from tests import test_project_context_access as access_tests
from tests.test_project_repository import project


class ProjectContextEditorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = context_tests.ProjectContextTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def stage(self, content=b'Garage floorplan'):
        return editor.stage_project_file(self.root, 'project_mentat', expected_project_revision=1, original_name='floorplan.md', content=content)

    def publish(self, identifiers, staged, *, expected=0):
        return context.publish_project_context(self.root, 'project_mentat', expected_project_revision=1,
            expected_revision=expected, brief='Garage goals', attachment_ids=identifiers, expected_staged_ids=staged)

    def test_staging_publication_is_exact_and_consumes_only_selected_files(self):
        first, second = self.stage(), self.stage(b'Additional notes')
        with self.assertRaisesRegex(context.ProjectContextError, 'staging_changed'):
            self.publish([first['id']], [first['id']])
        published = self.publish([first['id']], [first['id'], second['id']])
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual([row[0] for row in connection.execute('SELECT attachment_id FROM mentat_project_context_staged')], [second['id']])
        self.assertEqual(editor.read_project_file(self.root, context_id=published['id'], attachment_id=first['id'])[1], b'Garage floorplan')
        with self.assertRaises(editor.ProjectContextEditorError):
            editor.read_project_file(self.root, context_id=published['id'], attachment_id=second['id'])

    def test_other_project_or_unbound_upload_cannot_be_read_or_published(self):
        mutate_authoritative_projects(self.root, lambda rows: ([*rows, project('Other','project_other')], None))
        staged = self.stage()
        unbound = self.fixture.upload(b'Not staged for this Project')
        with self.assertRaises(editor.ProjectContextEditorError):
            editor.read_project_file(self.root, project_id='project_other', attachment_id=staged['id'])
        with self.assertRaisesRegex(context.ProjectContextError, 'file_scope'):
            self.publish([unbound], [staged['id']])

    def test_deletion_disposes_staging_and_id_reuse_cannot_adopt_it(self):
        from planning_deletion import PlanningDeletionError
        service = self.fixture.deletion_service()
        before = service.preview('project','project_mentat')
        upload = self.stage()
        with self.assertRaises(PlanningDeletionError):
            service.finalize(before)
        plan = service.preview('project','project_mentat')
        self.assertEqual(plan.counts.artifacts, 1)
        service.finalize(plan)
        mutate_authoritative_projects(self.root, lambda rows: ([*rows, project()], None))
        with self.assertRaisesRegex(context.ProjectContextError, 'file_scope'):
            self.publish([upload['id']], [])

    def test_discard_and_quota_failure_leave_no_publishable_stage(self):
        upload = self.stage()
        editor.discard_project_file(self.root, 'project_mentat', upload['id'], expected_project_revision=1)
        with self.assertRaises(editor.ProjectContextEditorError):
            editor.read_project_file(self.root, project_id='project_mentat', attachment_id=upload['id'])
        with patch.object(editor, 'MAX_STAGED_FILES', 0):
            with self.assertRaisesRegex(editor.ProjectContextEditorError, 'capacity'):
                self.stage(b'Over quota')
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_context_staged').fetchone()[0], 0)

    def test_backup_discards_stages_without_affecting_live_draft(self):
        upload = self.stage()
        unit = backups.capture_private_console_unit(self.root)
        backups.validate_private_console_unit(unit)
        self.assertEqual(unit.blobs, ())
        self.assertEqual(editor.read_project_file(self.root, project_id='project_mentat', attachment_id=upload['id'])[1], b'Garage floorplan')

    def test_staging_budget_deduplicates_bytes_and_expiry_never_publishes_partial_input(self):
        first = self.stage(b'same')
        with patch.object(files, 'MAX_RETAINED_BLOB_BYTES', 4):
            second = self.stage(b'same')
            with self.assertRaisesRegex(editor.ProjectContextEditorError, 'capacity'):
                self.stage(b'next')
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('UPDATE attachments SET expires_at=? WHERE id=?', (time.time()-1, first['id']))
        with self.assertRaises(editor.ProjectContextEditorError):
            editor.read_project_file(self.root, project_id='project_mentat', attachment_id=first['id'])
        with self.assertRaisesRegex(context.ProjectContextError, 'file_unavailable'):
            self.publish([first['id'],second['id']], [first['id'],second['id']])
        self.assertIsNone(context.read_project_context(self.root, 'project_mentat'))

    def test_editor_projection_keeps_retired_history_separate_and_exposes_no_private_binding(self):
        upload = self.stage()
        version = self.publish([upload['id']], [upload['id']])
        view = editor.read_project_editor(self.root, 'project_mentat')
        self.assertEqual(view['current']['id'], version['id'])
        self.assertEqual(view['current']['prune_blocked'], 'current_version')
        self.assertTrue(view['current']['files'][0]['available'])
        for private in ('scope_id','files_digest','approval_epoch','storage_key','sha256','runtime_agent_ref'):
            self.assertNotIn(private, json.dumps(view))
        service = self.fixture.deletion_service()
        service.finalize(service.preview('project','project_mentat'))
        mutate_authoritative_projects(self.root, lambda rows: ([*rows, project()], None))
        self.assertIsNone(editor.read_project_editor(self.root, 'project_mentat')['current'])
        self.assertEqual(editor.read_retired_context_history(self.root)[0]['id'], version['id'])
        self.assertTrue(editor.read_context_version(self.root, version['id'])['retired'])

    def test_pruning_requires_exact_preview_and_preserves_shared_run_file(self):
        upload = self.stage()
        first = self.publish([upload['id']], [upload['id']])
        with self.assertRaisesRegex(editor.ProjectContextEditorError, 'current_version'):
            editor.preview_context_prune(self.root, first['id'])
        self.publish([], [], expected=1)
        preview = editor.preview_context_prune(self.root, first['id'])
        files.bind_run_attachment(self.root, upload['id'], 'run_retained')
        with self.assertRaisesRegex(editor.ProjectContextEditorError, 'stale'):
            editor.confirm_context_prune(self.root, first['id'], confirmation_id=preview['confirmation_id'])
        preview = editor.preview_context_prune(self.root, first['id'])
        editor.confirm_context_prune(self.root, first['id'], confirmation_id=preview['confirmation_id'])
        self.assertEqual(files.get_attachment(self.root, upload['id'])['state'], 'attached')

    def test_pruning_last_retired_version_releases_scope_and_lost_file(self):
        upload = self.stage()
        version = self.publish([upload['id']], [upload['id']])
        service = self.fixture.deletion_service()
        service.finalize(service.preview('project','project_mentat'))
        files.resolve_blob_path(self.root, upload['id']).unlink()
        files.reconcile_startup(self.root)
        preview = editor.preview_context_prune(self.root, version['id'])
        editor.confirm_context_prune(self.root, version['id'], confirmation_id=preview['confirmation_id'])
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_context_scopes').fetchone()[0], 0)
        backups.validate_private_console_unit(backups.capture_private_console_unit(self.root))


class ProjectContextGrantPruningTests(unittest.TestCase):
    def test_granted_version_is_pinned_and_revoked_tombstone_survives_pruning(self):
        fixture = access_tests.ProjectContextGrantTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        grant = fixture.grant()
        fixture.fixture.publish(expected=1, brief='New brief')
        with self.assertRaisesRegex(editor.ProjectContextEditorError, 'granted_version'):
            editor.preview_context_prune(fixture.root, fixture.version['id'])
        access.revoke_context_grant(fixture.root, 'project_mentat', fixture.version['id'], 'agent_context', expected_revision=grant['revision'])
        preview = editor.preview_context_prune(fixture.root, fixture.version['id'])
        editor.confirm_context_prune(fixture.root, fixture.version['id'], confirmation_id=preview['confirmation_id'])
        self.assertEqual(fixture.row(), ('revoked','context_pruned',3,None))
