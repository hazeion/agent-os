import json
import secrets
import unittest
from unittest.mock import patch

from mentat import local_bridge
from tests import test_owner_gateway as owner_fixture
from tests import test_mentat_local_bridge as bridge_fixture


class OwnerBridgeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.owner = owner_fixture.OwnerGatewayTests()
        self.owner.setUp()
        self.addCleanup(self.owner.doCleanups)
        self.bridge = bridge_fixture.LocalBridgeTests()
        self.bridge.setUp()
        self.addCleanup(self.bridge.tearDown)
        self.bridge.server.owner_gateway = self.owner.gateway

    def test_private_token_alone_and_forged_sessions_cannot_read_application_data(self):
        with patch.object(local_bridge, 'bridge_tasks_payload', return_value=({'private': 'fixture'}, 200)) as read:
            for headers in ({}, {'X-Mentat-Owner-Session': secrets.token_urlsafe(32)}):
                status, body, _ = self.bridge.request(path='/bridge/v1/tasks', headers=headers)
                self.assertEqual(status, 401)
                self.assertNotIn('private', body)
            read.assert_not_called()
            status, body, _ = self.bridge.request(path='/bridge/v1/tasks', headers={'X-Mentat-Owner-Session': self.owner.cookie})
            self.assertEqual((status, body), (200, {'private': 'fixture'}))
            read.assert_called_once()

    def test_mutation_needs_exact_csrf_and_stream_lease_cannot_substitute(self):
        lease = self.owner.gateway.dispatch('sse-reserve', {'cookie': self.owner.cookie})['lease']
        base = {'Content-Type': 'application/json', 'X-Mentat-Owner-Session': self.owner.cookie}
        with patch.object(local_bridge, 'bridge_agent_setup', return_value=({'ok': True}, 200)) as mutate:
            for extra in ({}, {'X-Mentat-Owner-Csrf': secrets.token_urlsafe(32)}, {'X-Mentat-Owner-Lease': lease}):
                status, _, _ = self.bridge.request(method='POST', path='/bridge/v1/agent-setup/check', body=b'{}', headers={**base, **extra})
                self.assertEqual(status, 401)
            mutate.assert_not_called()
            status, _, _ = self.bridge.request(method='POST', path='/bridge/v1/agent-setup/check', body=b'{}', headers={**base, 'X-Mentat-Owner-Csrf': self.owner.csrf})
            self.assertEqual(status, 200)
            mutate.assert_called_once()

    def test_fixed_owner_capabilities_do_not_expose_setup_or_raw_rows(self):
        status, body, _ = self.bridge.request(method='POST', path='/bridge/v1/owner/session', body=json.dumps({'cookie': self.owner.cookie}).encode(), headers={'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {'ok', 'absolute_expires_at'})
        for name in ('enroll', 'configure', 'recover', 'confirm'):
            status, _, _ = self.bridge.request(method='POST', path='/bridge/v1/owner/' + name, body=b'{}', headers={'Content-Type': 'application/json'})
            self.assertEqual(status, 404)


if __name__ == '__main__': unittest.main()
