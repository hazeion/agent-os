import json
import unittest
from unittest.mock import patch

import task_inputs_http as api
from project_repository import mutate_authoritative_projects
from tests import test_task_inputs as inputs_tests
from tests import test_owner_bridge_admission as admission_tests


class TaskInputCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = inputs_tests.TaskInputStorageTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_exact_owner_read_and_publication_have_no_runtime_reference(self):
        root = self.fixture.root
        published, status = api.dispatch_task_inputs(root, 'publish', self.fixture.payload)
        self.assertEqual(status, 200)
        identifier = published['data']['input_id']
        read, status = api.dispatch_task_inputs(root, 'task', {'task_id':'task_research'})
        self.assertEqual(status, 200)
        self.assertEqual(read['data']['version']['id'], identifier)
        version, status = api.dispatch_task_inputs(root, 'version', {'task_id':'task_research','input_id':identifier})
        self.assertEqual((status, version['data']['version']['id']), (200, identifier))
        for private in ('binding_digest','input_incarnation','runtime_agent_ref','project_scope_id'):
            self.assertNotIn(private, json.dumps(read))

    def test_unknown_or_widened_body_never_reaches_storage(self):
        with patch.object(api, 'publish_task_inputs') as write:
            for operation, body in (('shell', {}), ('task', {'task_id':'task_research','path':'private'}),
                                    ('publish', {**self.fixture.payload,'runtime_agent_ref':'default'}),
                                    ('version', {'task_id':'task_research','input_id':'../../private'})):
                _, status = api.dispatch_task_inputs(self.fixture.root, operation, body)
                self.assertEqual(status, 400)
            write.assert_not_called()

    def test_retired_history_prunes_only_after_exact_owner_confirmation(self):
        from task_inputs import publish_task_inputs
        from task_repository import mutate_authoritative_tasks
        root = self.fixture.root
        published = publish_task_inputs(root, self.fixture.payload)
        mutate_authoritative_tasks(root, lambda rows: ([], None))
        history, status = api.dispatch_task_inputs(root, 'retired-history', {})
        self.assertEqual((status, history['data']['versions'][0]['id']), (200, published['input_id']))
        detail, status = api.dispatch_task_inputs(root, 'retired-version', {'input_id':published['input_id']})
        self.assertEqual((status, detail['data']['files'][0]['id']), (200, self.fixture.attachment))
        preview, status = api.dispatch_task_inputs(root, 'prune-preview', {'input_id':published['input_id']})
        self.assertEqual(status, 200)
        rejected, status = api.dispatch_task_inputs(root, 'prune-confirm', {'input_id':published['input_id'], 'confirmation_id':preview['data']['confirmation_id'], 'confirmed':False})
        self.assertEqual((status, rejected['status']), (400,'invalid'))
        done, status = api.dispatch_task_inputs(root, 'prune-confirm', {'input_id':published['input_id'], 'confirmation_id':preview['data']['confirmation_id'], 'confirmed':True})
        self.assertEqual((status,done['data']), (200,{'pruned':True}))
        replay, status = api.dispatch_task_inputs(root, 'prune-confirm', {'input_id':published['input_id'], 'confirmation_id':preview['data']['confirmation_id'], 'confirmed':True})
        self.assertEqual((status,replay['status']), (409,'version_unavailable'))

    def test_paused_project_returns_bounded_error_through_real_owner_bridge(self):
        from tests import test_owner_bridge_admission as admission
        import server
        owner_fixture = admission.OwnerBridgeAdmissionTests(); owner_fixture.setUp()
        self.addCleanup(owner_fixture.doCleanups)
        mutate_authoritative_projects(self.fixture.root, lambda rows: ([{**rows[0], 'status':'paused'}], None))
        headers = {'Content-Type':'application/json', 'X-Mentat-Owner-Session':owner_fixture.owner.cookie,
                   'X-Mentat-Owner-Csrf':owner_fixture.owner.csrf}
        with patch.object(server, 'DATA_DIR', self.fixture.root):
            status, payload, _ = owner_fixture.bridge.request(method='POST', path='/bridge/v1/task-inputs/publish',
                headers=headers, body=json.dumps(self.fixture.payload).encode())
        self.assertEqual((status, payload), (409, {'schema_version':1,'status':'project_unavailable'}))


class TaskInputBridgeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = admission_tests.OwnerBridgeAdmissionTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_owner_session_and_csrf_precede_private_dispatch(self):
        bridge, owner = self.fixture.bridge, self.fixture.owner
        with patch.object(api, 'dispatch_task_inputs', return_value=({'schema_version':1,'status':'ready'},200)) as dispatch:
            status, _, _ = bridge.request(path='/bridge/v1/task-inputs/task?task_id=task_research')
            self.assertEqual(status, 401); dispatch.assert_not_called()
            headers = {'X-Mentat-Owner-Session':owner.cookie}
            status, _, _ = bridge.request(path='/bridge/v1/task-inputs/task?task_id=task_research',headers=headers)
            self.assertEqual(status, 200)
            dispatch.assert_called_once(); dispatch.reset_mock()
            body = json.dumps({'task_id':'task_research'}).encode()
            status, _, _ = bridge.request(method='POST',path='/bridge/v1/task-inputs/publish',headers={**headers,'Content-Type':'application/json'},body=body)
            self.assertEqual(status, 401); dispatch.assert_not_called()
            status, _, _ = bridge.request(method='POST',path='/bridge/v1/task-inputs/publish',headers={**headers,'Content-Type':'application/json','X-Mentat-Owner-Csrf':owner.csrf},body=body)
            self.assertEqual(status, 200); dispatch.assert_called_once()
            dispatch.reset_mock()
            status, _, _ = bridge.request(path='/bridge/v1/task-inputs/task?task_id=task_research&task_id=task_other',headers=headers)
            self.assertEqual(status, 404); dispatch.assert_not_called()
            status, _, _ = bridge.request(path='/bridge/v1/task-inputs/retired-history', headers=headers)
            self.assertEqual(status, 200); dispatch.assert_called_once()
            dispatch.reset_mock()
            status, _, _ = bridge.request(method='POST', path='/bridge/v1/task-inputs/prune-confirm',
                headers={**headers,'Content-Type':'application/json'}, body=b'{}')
            self.assertEqual(status, 401); dispatch.assert_not_called()
            status, _, _ = bridge.request(method='POST', path='/bridge/v1/task-inputs/prune-confirm',
                headers={**headers,'Content-Type':'application/json','X-Mentat-Owner-Csrf':owner.csrf}, body=b'{}')
            self.assertEqual(status, 200); dispatch.assert_called_once()
