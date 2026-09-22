"""The setup profile is inert until its complete lifecycle is qualified."""

import unittest

from deploy.caddy.profile import DeploymentProfileError
from deploy.caddy.setup_profile import render_setup_caddyfile


class CaddySetupProfileTests(unittest.TestCase):
    def test_untrusted_hosts_cannot_change_ingress_configuration(self):
        for host in ('localhost', '127.0.0.1', '*.example.test', 'example.test:8443',
                     'Example.test', 'example.test\nreverse_proxy attacker.test',
                     'https://example.test', 'example.test/path', 'example.local'):
            with self.subTest(host=host), self.assertRaises(DeploymentProfileError):
                render_setup_caddyfile(host)

    def test_setup_ingress_has_no_general_proxy_or_cleartext_callback_redirect(self):
        rendered = render_setup_caddyfile('mentat.example.test')
        self.assertEqual(rendered.count('reverse_proxy 127.0.0.1:8888'), 2)
        self.assertNotIn('redir ', rendered)
        self.assertNotIn('path /*', rendered)
        self.assertNotIn('/api/', rendered)
        self.assertIn('handle {\n        respond 404', rendered)
        self.assertIn('output discard', rendered)
        self.assertIn('Referrer-Policy "no-referrer"', rendered)
        self.assertIn('Cache-Control "no-store"', rendered)


if __name__ == '__main__':
    unittest.main()
