import base64
import json
import unittest
from unittest.mock import patch

import project_context_http as api
from tests import test_project_context as context_tests
from tests import test_owner_bridge_admission as admission_tests


class ProjectContextCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = context_tests.ProjectContextTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def test_upload_publish_read_uses_only_project_owned_stage(self):
        uploaded, status = api.dispatch_project_context(self.root, 'upload', {'project_id':'project_mentat','expected_project_revision':1,
            'name':'garage.md','content_type':'text/markdown','content_base64':base64.b64encode(b'Garage goals').decode()})
        self.assertEqual(status, 200)
        identifier = uploaded['data']['file']['id']
        body = {'project_id':'project_mentat','expected_project_revision':1,'expected_revision':0,'brief':'Garage organization',
                'attachment_ids':[identifier],'expected_staged_ids':[identifier]}
        rejected, status = api.dispatch_project_context(self.root, 'publish', {**body,'expected_staged_ids':None})
        self.assertEqual((status,rejected['status']), (400,'invalid'))
        published, status = api.dispatch_project_context(self.root, 'publish', body)
        self.assertEqual(status, 200)
        file, status = api.dispatch_project_context(self.root, 'file', {'context_id':published['data']['context_id'],'attachment_id':identifier})
        self.assertEqual(status, 200)
        self.assertEqual(base64.b64decode(file['data']['content_base64']), b'Garage goals')
        for secret in ('storage_key','sha256','scope_id','approval_epoch','runtime_agent_ref'):
            self.assertNotIn(secret, json.dumps(file))

    def test_unknown_capability_or_widened_body_never_reaches_storage(self):
        with patch.object(api.editor, 'read_project_editor') as read:
            for operation, body in (('shell',{}),('project',{'project_id':'project_mentat','path':'private/file'}),('project',{'project_id':'../private'})):
                _, status = api.dispatch_project_context(self.root, operation, body)
                self.assertEqual(status, 400)
            read.assert_not_called()


class ProjectContextBridgeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = admission_tests.OwnerBridgeAdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_fixed_reads_require_owner_and_fixed_writes_require_csrf(self):
        bridge, owner = self.fixture.bridge, self.fixture.owner
        with patch.object(api, 'dispatch_project_context', return_value=({'safe':True},200)) as dispatch:
            status, _, _ = bridge.request(path='/bridge/v1/project-context/history')
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            headers = {'X-Mentat-Owner-Session':owner.cookie}
            status, _, _ = bridge.request(path='/bridge/v1/project-context/history',headers=headers)
            self.assertEqual(status, 200)
            self.assertEqual(dispatch.call_args.args[1:], ('history',{}))
            dispatch.reset_mock()
            status, _, _ = bridge.request(method='POST',path='/bridge/v1/project-context/publish',headers={**headers,'Content-Type':'application/json'},body=b'{}')
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            status, _, _ = bridge.request(method='POST',path='/bridge/v1/project-context/publish',headers={**headers,'Content-Type':'application/json','X-Mentat-Owner-Csrf':owner.csrf},body=b'{}')
            self.assertEqual(status, 200)
            self.assertEqual(dispatch.call_args.args[1:], ('publish',{}))
            dispatch.reset_mock()
            for path in ('/bridge/v1/project-context/project?project_id=one&project_id=two','/bridge/v1/project-context/publish','/bridge/v1/project-context/arbitrary'):
                status, _, _ = bridge.request(path=path,headers=headers)
                self.assertEqual(status, 404)
            dispatch.assert_not_called()
