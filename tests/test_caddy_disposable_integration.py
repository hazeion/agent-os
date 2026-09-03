from __future__ import annotations

from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from deploy.caddy.disposable_integration import (
    DisposableIntegrationError,
    _caddyfile_path,
    _free_port,
    _start_backend,
    _stop_backend,
    assert_external_address_isolation,
    assert_loopback_listener_inventory,
    render_disposable_caddyfile,
    request_http,
)


class DisposableCaddyIntegrationTests(unittest.TestCase):
    def test_non_stream_capture_responses_close_before_backend_shutdown(self):
        backend = _start_backend(_free_port())
        try:
            status, headers, body = request_http(
                backend.server_port,
                "mentat.example.test",
                "/headers",
            )
        finally:
            _stop_backend(backend)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("connection"), "close")
        self.assertEqual(body, b'{"ok":true}')

    def test_fixture_binds_only_loopback_and_exercises_every_real_edge_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            certificate = root / "certificate.pem"
            key = root / "key.pem"
            certificate.write_text("certificate", encoding="utf-8")
            key.write_text("key", encoding="utf-8")
            rendered = render_disposable_caddyfile(
                host="mentat.example.test", http_port=18080, https_port=18443,
                admin_port=12019, upstream_port=18888, certificate=certificate, key=key,
            )
            maintenance = render_disposable_caddyfile(
                host="mentat.example.test", http_port=18080, https_port=18443,
                admin_port=12019, upstream_port=18888, certificate=certificate, key=key,
                maintenance=True,
            )
        self.assertIn("admin 127.0.0.1:12019", rendered)
        self.assertIn("http://:18080", rendered)
        self.assertNotIn("http://mentat.example.test:18080", rendered)
        self.assertIn("redir @canonical https://mentat.example.test:18443{uri} 308", rendered)
        self.assertNotIn(" permanent", rendered)
        self.assertIn("bind 127.0.0.1", rendered)
        self.assertIn("https://mentat.example.test:18443", rendered)
        self.assertIn("reverse_proxy 127.0.0.1:18888", rendered)
        self.assertIn("strict_sni_host on", rendered)
        self.assertIn("header_up -Forwarded", rendered)
        self.assertIn("header_up -X-Real-IP", rendered)
        for header in ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto"):
            self.assertNotIn(f"header_up -{header}", rendered)
            self.assertNotIn(f"header_up {header}", rendered)
        self.assertIn("@timeline path /api/runs/*/events", rendered)
        self.assertIn('Cache-Control "private, no-store, no-transform"', rendered)
        self.assertIn('X-Accel-Buffering "no"', rendered)
        self.assertNotIn("flush_interval", rendered)
        self.assertNotIn("0.0.0.0", rendered)
        self.assertNotIn("tls internal", rendered)
        self.assertIn('header Cache-Control "no-store"', maintenance)
        self.assertIn("respond 503", maintenance)
        self.assertNotIn("reverse_proxy", maintenance)

    def test_fixture_rejects_privileged_duplicate_and_unsafe_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            certificate = root / "certificate.pem"
            key = root / "key.pem"
            certificate.write_text("certificate", encoding="utf-8")
            key.write_text("key", encoding="utf-8")
            base = dict(host="mentat.example.test", http_port=18080, https_port=18443, admin_port=12019, upstream_port=18888, certificate=certificate, key=key)
            for changes in (
                {"http_port": 80},
                {"https_port": 18080},
                {"host": "*.example.test"},
                {"host": "127.0.0.1"},
                {"host": "MENTAT.example.test"},
                {"host": "mentat.local"},
                {"host": "mentat.example.test\nrespond 200"},
                {"host": "mentat.example.test#"},
            ):
                with self.subTest(changes=changes):
                    with self.assertRaises(DisposableIntegrationError):
                        render_disposable_caddyfile(**{**base, **changes})

    def test_fixture_quotes_safe_paths_and_rejects_control_characters(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "directory with spaces"
            root.mkdir()
            certificate = root / "certificate.pem"
            key = root / "key.pem"
            certificate.write_text("certificate", encoding="utf-8")
            key.write_text("key", encoding="utf-8")
            rendered = render_disposable_caddyfile(
                host="mentat.example.test",
                http_port=18080,
                https_port=18443,
                admin_port=12019,
                upstream_port=18888,
                certificate=certificate,
                key=key,
            )
            self.assertIn(
                f"tls {json.dumps(str(certificate))} {json.dumps(str(key))}",
                rendered,
            )
            unsafe = Path(Path.cwd().anchor) / "bad\ncertificate.pem"
            with patch("deploy.caddy.disposable_integration._regular_file"):
                with self.assertRaisesRegex(DisposableIntegrationError, "unsafe"):
                    _caddyfile_path(unsafe, "test certificate")

    def test_listener_gate_refuses_public_or_missing_ports(self):
        class Result:
            returncode = 0
            stdout = "LISTEN 0 4096 127.0.0.1:18080 0.0.0.0:*\nLISTEN 0 4096 127.0.0.1:18443 0.0.0.0:*\nLISTEN 0 4096 127.0.0.1:12019 0.0.0.0:*\n"
        with patch("deploy.caddy.disposable_integration.shutil.which", return_value="/usr/bin/ss"), patch("deploy.caddy.disposable_integration.subprocess.run", return_value=Result()):
            assert_loopback_listener_inventory((18080, 18443, 12019))
        Result.stdout = "LISTEN 0 4096 *:18443 *:*\n"
        with patch("deploy.caddy.disposable_integration.shutil.which", return_value="/usr/bin/ss"), patch("deploy.caddy.disposable_integration.subprocess.run", return_value=Result()):
            with self.assertRaises(DisposableIntegrationError):
                assert_loopback_listener_inventory((18080, 18443, 12019))

    def test_listener_gate_rejects_extra_caddy_tcp_or_udp_ports(self):
        class Result:
            returncode = 0

            def __init__(self, stdout: str):
                self.stdout = stdout

        expected = "".join(
            f'LISTEN 0 4096 127.0.0.1:{port} 0.0.0.0:* users:(("caddy",pid=42,fd=1))\n'
            for port in (18080, 18443, 12019)
        )
        with patch("deploy.caddy.disposable_integration.shutil.which", return_value="/usr/bin/ss"), patch(
            "deploy.caddy.disposable_integration.subprocess.run",
            side_effect=[Result(expected), Result("")],
        ):
            assert_loopback_listener_inventory((18080, 18443, 12019), caddy_pid=42)
        unexpected = expected + 'LISTEN 0 4096 127.0.0.1:19000 0.0.0.0:* users:(("caddy",pid=42,fd=2))\n'
        with patch("deploy.caddy.disposable_integration.shutil.which", return_value="/usr/bin/ss"), patch(
            "deploy.caddy.disposable_integration.subprocess.run",
            return_value=Result(unexpected),
        ):
            with self.assertRaisesRegex(DisposableIntegrationError, "unexpected TCP"):
                assert_loopback_listener_inventory((18080, 18443, 12019), caddy_pid=42)

    def test_external_address_gate_probes_every_caddy_port(self):
        class Result:
            returncode = 0
            stdout = '[{"addr_info":[{"family":"inet","local":"127.0.0.1"},{"family":"inet","local":"192.0.2.10"}]}]'

        with patch("deploy.caddy.disposable_integration.shutil.which", return_value="/usr/bin/ip") as which, patch(
            "deploy.caddy.disposable_integration.subprocess.run", return_value=Result()
        ) as run, patch(
            "deploy.caddy.disposable_integration.socket.create_connection",
            side_effect=OSError,
        ) as connect:
            assert_external_address_isolation((18080, 18443, 12019))
        which.assert_called_once_with("ip", path=os.defpath)
        self.assertEqual(
            set(run.call_args.kwargs["env"]),
            {"HOME", "LANG", "LC_ALL", "PATH", "XDG_CONFIG_HOME", "XDG_DATA_HOME"},
        )
        self.assertEqual(
            [call.args[0] for call in connect.call_args_list],
            [("192.0.2.10", 18080), ("192.0.2.10", 18443), ("192.0.2.10", 12019)],
        )
        with patch("deploy.caddy.disposable_integration.shutil.which", return_value="/usr/bin/ip"), patch(
            "deploy.caddy.disposable_integration.subprocess.run", return_value=Result()
        ), patch(
            "deploy.caddy.disposable_integration.socket.create_connection",
            return_value=Mock(),
        ):
            with self.assertRaisesRegex(DisposableIntegrationError, "external address"):
                assert_external_address_isolation((18080, 18443, 12019))


if __name__ == "__main__":
    unittest.main()
