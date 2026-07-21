from __future__ import annotations

from email.message import Message
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import server


class RequestBoundaryTests(unittest.TestCase):
    server_port = 8890

    def handler(self, *, headers=None, client="127.0.0.1"):
        instance = object.__new__(server.Handler)
        instance.client_address = (client, 54123)
        instance.server = SimpleNamespace(server_port=self.server_port)
        message = Message()
        for name, value in (headers or {}).items():
            message[name] = value
        instance.headers = message
        return instance

    def local_headers(self, **overrides) -> dict[str, str]:
        headers = {
            "Host": f"127.0.0.1:{self.server_port}",
            "Origin": f"http://127.0.0.1:{self.server_port}",
            "Sec-Fetch-Site": "same-origin",
        }
        headers.update(overrides)
        return headers

    def test_api_rejects_nonlocal_host_and_cross_site_origin(self):
        nonlocal_host = self.handler(headers={"Host": "attacker.example"})
        foreign_origin = self.handler(
            headers=self.local_headers(Origin="https://attacker.example")
        )
        cross_site = self.handler(
            headers=self.local_headers(**{"Sec-Fetch-Site": "cross-site"})
        )

        self.assertFalse(nonlocal_host.local_api_request_is_allowed())
        self.assertFalse(foreign_origin.local_api_request_is_allowed())
        self.assertFalse(cross_site.local_api_request_is_allowed())

    def test_api_rejects_a_different_loopback_origin_port(self):
        instance = self.handler(
            headers=self.local_headers(Origin="http://127.0.0.1:65534")
        )
        self.assertFalse(instance.local_api_request_is_allowed())

    def test_api_accepts_only_matching_local_host_and_origin(self):
        instance = self.handler(headers=self.local_headers())
        self.assertTrue(instance.local_api_request_is_allowed())

    def test_json_post_requires_json_content_type_before_route_dispatch(self):
        body = json.dumps({"title": "Must not be created"}).encode("utf-8")
        instance = self.handler(
            headers=self.local_headers(
                **{
                    "Content-Type": "text/plain",
                    "Content-Length": str(len(body)),
                }
            )
        )
        instance.path = "/api/tasks"
        instance.rfile = BytesIO(body)
        instance.send_json = Mock()
        with patch.object(server, "handle_post_route") as dispatch:
            instance.do_POST()

        dispatch.assert_not_called()
        args, kwargs = instance.send_json.call_args
        self.assertEqual(kwargs["status"], 415)
        self.assertIn("Content-Type: application/json", args[0]["error"])

    def test_attachment_upload_accepts_raw_body_before_json_boundary(self):
        body = b"notes for the agent\n"
        instance = self.handler(
            headers=self.local_headers(
                **{
                    "Content-Type": "text/plain",
                    "Content-Length": str(len(body)),
                    "X-Mentat-Filename": "notes%20for%20agent.txt",
                }
            )
        )
        instance.path = "/api/agent-console/attachments"
        instance.rfile = BytesIO(body)
        instance.send_json = Mock()
        with patch.object(
            server,
            "create_agent_console_attachment",
            return_value=({"attachment": {"id": "attachment_safe"}}, 201),
        ) as create, patch.object(server, "handle_post_route") as dispatch:
            instance.do_POST()

        dispatch.assert_not_called()
        create.assert_called_once_with(
            original_name="notes for agent.txt",
            content_type="text/plain",
            content=body,
        )
        self.assertEqual(instance.send_json.call_args.kwargs["status"], 201)

    def test_diagnostics_post_uses_local_boundary_before_generating_bundle(self):
        instance = self.handler(headers=self.local_headers())
        instance.path = "/api/diagnostics/bundle"
        instance.send_diagnostics_bundle = Mock()
        instance.send_json = Mock()
        with patch.object(
            server,
            "diagnostics_health_snapshot",
            return_value={"overall": "healthy", "subsystems": []},
        ) as snapshot, patch.object(server, "health") as live_health, patch.object(
            server, "build_diagnostics_bundle", return_value=b"safe-zip"
        ) as build:
            instance.do_POST()

        snapshot.assert_called_once_with()
        live_health.assert_not_called()
        build.assert_called_once()
        instance.send_diagnostics_bundle.assert_called_once_with(b"safe-zip")
        instance.send_json.assert_not_called()

        rejected = self.handler(headers=self.local_headers(Origin="https://attacker.example"))
        rejected.path = "/api/diagnostics/bundle"
        rejected.send_diagnostics_bundle = Mock()
        rejected.send_json = Mock()
        with patch.object(server, "build_diagnostics_bundle") as rejected_build:
            rejected.do_POST()
        rejected_build.assert_not_called()
        self.assertEqual(rejected.send_json.call_args.kwargs["status"], 403)

    def test_diagnostics_response_is_a_nonsniffable_private_download(self):
        instance = self.handler(headers=self.local_headers())
        instance.wfile = BytesIO()
        instance.send_response = Mock()
        captured = {}
        instance.send_header = lambda name, value: captured.__setitem__(name, value)
        instance.end_headers = Mock()

        instance.send_diagnostics_bundle(b"safe-zip")

        self.assertEqual(instance.wfile.getvalue(), b"safe-zip")
        self.assertEqual(captured["Content-Type"], "application/zip")
        self.assertEqual(captured["Content-Disposition"], "attachment; filename=mentat-diagnostics.zip")
        self.assertEqual(captured["Cache-Control"], "private, no-store")
        self.assertEqual(captured["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertEqual(captured["X-Content-Type-Options"], "nosniff")

    def test_health_cache_keeps_only_the_redacted_fixed_snapshot(self):
        raw = {
            "status": "error",
            "summary": "private conversation /Users/operator sk-secret",
            "subsystems": [
                {"key": "cron", "status": "error", "summary": "private cron details"},
                {"key": "remote_hermes", "status": "healthy", "endpoint": "https://private.example"},
            ],
        }
        with patch.object(server, "current_health_payload", return_value=raw):
            self.assertIs(server.health(), raw)

        self.assertEqual(
            server.diagnostics_health_snapshot(),
            {
                "overall": "error",
                "subsystems": [
                    {"key": "cron", "status": "error"},
                    {"key": "remote_hermes", "status": "healthy"},
                ],
            },
        )

    def test_attachment_content_is_streamed_with_safe_headers(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "blob"
            path.write_bytes(b"hello")
            instance = self.handler(headers=self.local_headers())
            instance.wfile = BytesIO()
            instance.send_response = Mock()
            captured = {}
            instance.send_header = lambda name, value: captured.__setitem__(name, value)
            instance.end_headers = Mock()

            instance.send_attachment_file(
                {
                    "name": "example.html",
                    "kind": "text",
                    "mime_type": "text/html",
                    "byte_size": 5,
                },
                path,
            )

        self.assertEqual(instance.wfile.getvalue(), b"hello")
        self.assertEqual(captured["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(captured["X-Content-Type-Options"], "nosniff")
        self.assertEqual(captured["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertIn("sandbox", captured["Content-Security-Policy"])

    def test_json_response_includes_clickjacking_and_content_headers(self):
        instance = self.handler(headers=self.local_headers())
        instance.wfile = BytesIO()
        instance.send_response = Mock()
        captured = {}
        instance.send_header = lambda name, value: captured.__setitem__(name, value)
        instance.end_headers = Mock()

        instance.send_json({"ok": True})

        instance.send_response.assert_called_once_with(200)
        self.assertEqual(captured.get("X-Frame-Options"), "DENY")
        self.assertEqual(captured.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("frame-ancestors 'none'", captured.get("Content-Security-Policy", ""))
        self.assertEqual(captured.get("Referrer-Policy"), "no-referrer")

    def test_disconnected_json_client_does_not_trigger_a_second_get_response(self):
        for disconnect_error in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            with self.subTest(disconnect_error=disconnect_error.__name__):
                writer = Mock()
                writer.write.side_effect = disconnect_error("client disconnected")
                instance = self.handler(headers=self.local_headers())
                instance.path = "/api/overview"
                instance.wfile = writer
                instance.send_response = Mock()
                instance.send_header = Mock()
                instance.end_headers = Mock()
                instance.log_internal_error = Mock()

                with patch.dict(server.API_ROUTES, {"/api/overview": lambda: {"ok": True}}):
                    instance.do_GET()

                instance.send_response.assert_called_once_with(200)
                writer.write.assert_called_once()
                instance.log_internal_error.assert_not_called()
                self.assertTrue(instance.close_connection)

    def test_json_transmission_failure_never_reaches_route_retry(self):
        writer = Mock()
        failure = TimeoutError("response write timed out")
        writer.write.side_effect = failure
        instance = self.handler(headers=self.local_headers())
        instance.path = "/api/overview"
        instance.wfile = writer
        instance.send_response = Mock()
        instance.send_header = Mock()
        instance.end_headers = Mock()
        instance.log_internal_error = Mock()

        with patch.dict(server.API_ROUTES, {"/api/overview": lambda: {"ok": True}}):
            instance.do_GET()

        instance.send_response.assert_called_once_with(200)
        writer.write.assert_called_once()
        instance.log_internal_error.assert_called_once_with("JSON response transmission", failure)
        self.assertTrue(instance.close_connection)

    def test_disconnected_static_client_does_not_trigger_error_response(self):
        for disconnect_error in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            with self.subTest(disconnect_error=disconnect_error.__name__), TemporaryDirectory() as tmpdir:
                public = Path(tmpdir)
                (public / "index.html").write_text("<!doctype html><title>Mentat</title>", encoding="utf-8")
                writer = Mock()
                writer.write.side_effect = disconnect_error("client disconnected")
                instance = self.handler(headers=self.local_headers())
                instance.path = "/"
                instance.wfile = writer
                instance.send_response = Mock()
                instance.send_header = Mock()
                instance.end_headers = Mock()
                instance.send_error = Mock()
                instance.log_internal_error = Mock()

                with patch.object(server, "PUBLIC_DIR", public):
                    instance.do_GET()

                instance.send_response.assert_called_once_with(200)
                writer.write.assert_called_once()
                instance.send_error.assert_not_called()
                instance.log_internal_error.assert_not_called()
                self.assertTrue(instance.close_connection)

    def test_static_preparation_failure_sends_one_500_response(self):
        with TemporaryDirectory() as tmpdir:
            public = Path(tmpdir)
            (public / "index.html").write_text("<!doctype html><title>Mentat</title>", encoding="utf-8")
            instance = self.handler(headers=self.local_headers())
            instance.path = "/"
            instance.send_response = Mock()
            instance.send_error = Mock()
            instance.log_internal_error = Mock()

            failure = OSError("asset read failed")
            with patch.object(server, "PUBLIC_DIR", public), patch.object(
                Path, "read_bytes", side_effect=failure
            ):
                instance.do_GET()

        instance.send_response.assert_not_called()
        instance.send_error.assert_called_once_with(500, "Static asset could not be loaded")
        instance.log_internal_error.assert_called_once_with("static asset preparation", failure)

    def test_static_transmission_failure_never_attempts_error_response(self):
        with TemporaryDirectory() as tmpdir:
            public = Path(tmpdir)
            (public / "index.html").write_text("<!doctype html><title>Mentat</title>", encoding="utf-8")
            writer = Mock()
            failure = RuntimeError("response stream failed")
            writer.write.side_effect = failure
            instance = self.handler(headers=self.local_headers())
            instance.path = "/"
            instance.wfile = writer
            instance.send_response = Mock()
            instance.send_header = Mock()
            instance.end_headers = Mock()
            instance.send_error = Mock()
            instance.log_internal_error = Mock()

            with patch.object(server, "PUBLIC_DIR", public):
                instance.do_GET()

        instance.send_response.assert_called_once_with(200)
        instance.send_error.assert_not_called()
        instance.log_internal_error.assert_called_once_with("static asset transmission", failure)
        self.assertTrue(instance.close_connection)

    def test_unexpected_api_failure_is_logged_but_client_response_stays_generic(self):
        instance = self.handler(headers=self.local_headers())
        instance.path = "/api/overview"
        instance.send_json = Mock()
        instance.log_internal_error = Mock()
        failure = RuntimeError("provider token sk-secret-value")

        with patch.dict(server.API_ROUTES, {"/api/overview": Mock(side_effect=failure)}):
            instance.do_GET()

        instance.log_internal_error.assert_called_once_with(
            "dashboard route /api/overview", failure
        )
        payload = instance.send_json.call_args.args[0]
        self.assertEqual(instance.send_json.call_args.kwargs["status"], 500)
        self.assertNotIn("sk-secret-value", json.dumps(payload))

    def test_internal_error_log_omits_exception_message(self):
        instance = self.handler(headers=self.local_headers())
        instance.log_error = Mock()

        try:
            raise RuntimeError("provider token sk-secret-value")
        except RuntimeError as failure:
            instance.log_internal_error("provider refresh", failure)

        instance.log_error.assert_called_once()
        rendered = " ".join(str(value) for value in instance.log_error.call_args.args)
        self.assertIn("RuntimeError", rendered)
        self.assertNotIn("sk-secret-value", rendered)


if __name__ == "__main__":
    unittest.main()
