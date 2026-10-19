import http.client
import shutil
import unittest
from unittest.mock import patch

from mentat import local_bridge
from tests import test_owner_website_browser as website


@unittest.skipUnless(shutil.which('node') and (website.STANDALONE / 'server.js').is_file(), 'Built Node website required')
class OwnerWebsiteHttpTests(unittest.TestCase):
    def test_open_stream_stops_disclosure_after_revocation_without_touching_idle_expiry(self):
        harness = website.OwnerWebsiteBrowserTests()
        fixture, bridge, port, _environment, cookie, csrf = harness.start_site()
        self.addCleanup(harness.doCleanups)
        authority = bridge.owner_gateway.authority
        initial = authority.authenticate_session(cookie, touch=False)['idle_expires_at']
        event = {'id': 'event_fixture', 'run_id': 'run_fixture', 'sequence': 1, 'type': 'run.started', 'occurred_at': '2026-09-22T00:00:00Z', 'summary': 'Owner-only stream event', 'message': None, 'metrics': {}, 'presentation': None}
        payload = {'schema_version': 1, 'service': 'mentat-local-bridge', 'runtime': 'python', 'status': 'ready', 'run_id': 'run_fixture', 'after': 0, 'next_cursor': 1, 'cursor_reset_required': False, 'events': [event]}
        refreshed = {'schema_version': 1, 'service': 'mentat-local-bridge', 'runtime': 'python', 'status': 'ready', 'run_id': 'run_fixture', 'disposition': 'idle'}
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=12)
        try:
            with patch.object(local_bridge, 'bridge_refresh_run_payload', return_value=(refreshed, 200)), patch.object(local_bridge, 'bridge_run_events_payload', return_value=(payload, 200)) as read:
                connection.request('GET', '/api/runs/run_fixture/events', headers={'Host': 'mentat.example', 'X-Forwarded-Host': 'mentat.example', 'X-Forwarded-Proto': 'https', 'Cookie': '__Host-mentat=' + cookie})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                first = b''
                while b'Owner-only stream event' not in first:
                    line = response.readline()
                    self.assertTrue(line, first)
                    first += line
                self.assertEqual(authority.authenticate_session(cookie, touch=False)['idle_expires_at'], initial)
                authority.sign_out(cookie, csrf)
                remainder = response.read()
                self.assertIn(b'owner-auth-required', remainder)
                self.assertNotIn(b'Owner-only stream event', remainder)
                self.assertEqual(read.call_count, 1)
        finally:
            connection.close()
        database = authority._open()
        try:
            self.assertEqual(database.execute('SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations').fetchone()[0], 0)
        finally:
            database.close()


if __name__ == '__main__': unittest.main()
