from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import server
from link_preview_service import LinkPreviewServiceError


class LinkPreviewServerTests(unittest.TestCase):
    def test_message_actions_forward_only_exact_canonical_identity(self):
        service = Mock()
        service.read.return_value = {"schema_version": 1, "previews": []}
        service.enqueue.return_value = {"schema_version": 1, "previews": []}
        with patch.object(server, "_link_preview_service", return_value=service):
            payload, status = server.mentat_link_previews_payload("conv_preview", "msg_preview", 2)
            self.assertEqual((payload, status), ({"schema_version": 1, "previews": []}, 200))
            payload, status = server.mentat_link_previews_payload("conv_preview", "msg_preview", 2, action="retry")
            self.assertEqual(status, 202)
        service.read.assert_called_once_with(conversation_id="conv_preview", message_id="msg_preview", message_revision=2)
        service.enqueue.assert_called_once_with(conversation_id="conv_preview", message_id="msg_preview", message_revision=2, retry=True)
        with patch.object(server, "_link_preview_service", return_value=service):
            with self.assertRaises(LinkPreviewServiceError):
                server.mentat_link_previews_payload("conv_preview", "msg_preview", 2, action="url")

    def test_preference_clear_and_image_are_fixed(self):
        service = Mock()
        service.preference.return_value = SimpleNamespace(public_projection=lambda: {"enabled": True, "revision": 1})
        service.update_preference.return_value = SimpleNamespace(public_projection=lambda: {"enabled": False, "revision": 2})
        service.image.return_value = (b"webp", 30)
        with patch.object(server, "_link_preview_service", return_value=service):
            self.assertEqual(server.mentat_link_preview_preference_payload(), {"schema_version": 1, "enabled": True, "revision": 1})
            self.assertEqual(server.update_mentat_link_preview_preference({"enabled": False, "expected_revision": 1})[1], 200)
            self.assertEqual(server.clear_mentat_link_preview_cache({}), ({"schema_version": 1, "cleared": True}, 200))
            self.assertEqual(server.mentat_link_preview_image("a" * 32), (b"webp", 30))
            for invalid in ({}, {"enabled": False, "expected_revision": True}, {"enabled": "false", "expected_revision": 1}):
                with self.assertRaises(LinkPreviewServiceError):
                    server.update_mentat_link_preview_preference(invalid)
            with self.assertRaises(LinkPreviewServiceError):
                server.clear_mentat_link_preview_cache({"url": "https://python.org"})

    def test_shutdown_closes_preview_workers_and_clears_singleton(self):
        service = Mock()
        with patch.object(server, "LINK_PREVIEW_SERVICE", service), patch.object(server, "LINK_PREVIEW_SERVICE_ROOT", server.Path("/private/cache")), patch.object(server, "stop_agent_console_processes"), patch.object(server.CODEX_RUNTIME, "close"):
            server.shutdown_agent_runtimes()
            self.assertIsNone(server.LINK_PREVIEW_SERVICE)
            self.assertIsNone(server.LINK_PREVIEW_SERVICE_ROOT)
        service.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
