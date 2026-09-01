from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from PIL import Image

from conversation_repository import ConversationRepositoryConflict
from link_preview_cache import LinkPreviewCache, LinkPreviewPreferenceStore
from link_preview_service import LinkPreviewService, LinkPreviewServiceError, MAXIMUM_EPHEMERAL_ENTRIES, _freshness
from link_preview_workers import LinkPreviewWorkerError


@dataclass
class Message:
    id: str = "msg_preview"
    conversation_id: str = "conv_preview"
    revision: int = 1
    role: str = "user"
    state: str = "accepted"
    content: dict | None = None

    def __post_init__(self):
        if self.content is None:
            self.content = {"schema_version": 1, "parts": [{"type": "text", "text": "Read https://python.org/docs"}]}


class Repository:
    def __init__(self, message: Message | None):
        self.message = message

    def read_message(self, message_id: str):
        if self.message is None or self.message.id != message_id:
            raise ConversationRepositoryConflict("conversation.message_not_found")
        return self.message


class FakePool:
    def __init__(
        self,
        results=None,
        *,
        barrier: threading.Event | None = None,
        started: threading.Event | None = None,
    ):
        self.results = list(results or [])
        self.barrier = barrier
        self.started = started
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def execute(self, *, kind: str, normalized_url: str):
        self.calls.append((kind, normalized_url))
        if self.started is not None:
            self.started.set()
        if self.barrier is not None:
            self.barrier.wait(timeout=2)
        if not self.results:
            raise LinkPreviewWorkerError("link_preview.unavailable")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True
        if self.barrier is not None:
            self.barrier.set()


def page_result(*, cache_control=None, display_host="python.org", final_url="https://python.org/docs", image_candidate=None):
    return {
        "cache_control": list(cache_control or []),
        "description": "Safe description",
        "display_host": display_host,
        "final_url": final_url,
        "image_alt": "Preview",
        "image_candidate": image_candidate,
        "site_name": "Python",
        "status": "ready",
        "title": "Safe title",
        "vary": [],
    }


def valid_webp() -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 8), (20, 80, 40)).save(output, "WEBP", quality=80)
    return output.getvalue()


class LinkPreviewServiceTests(unittest.TestCase):
    def test_cache_freshness_policy_is_exact_and_conservative(self):
        self.assertEqual(_freshness([], []), 24 * 60 * 60)
        self.assertEqual(_freshness(["max-age=1"], []), 1)
        self.assertEqual(_freshness(["max-age=999999"], []), 24 * 60 * 60)
        self.assertEqual(_freshness(["max-age=0"], []), 0)
        for cache_control, vary in (
            (["no-store"], []), (["no-cache"], []), (["max-age=-1"], []),
            (["max-age=1, max-age=2"], []), (["max-age=abc"], []),
            ([], ["*"]), ([], ["Accept-Encoding, *"]),
        ):
            with self.subTest(cache_control=cache_control, vary=vary):
                self.assertIsNone(_freshness(cache_control, vary))

    def test_parent_rejects_non_webp_worker_image_bytes(self):
        for body in (
            b"<html><script>alert(1)</script></html>",
            b"<svg xmlns='http://www.w3.org/2000/svg'/>",
            b"random-bytes",
            b"RIFF\x10\x00\x00\x00WEBPbroken",
            valid_webp()[:20],
        ):
            with self.subTest(body=body[:12]):
                self.assertEqual(LinkPreviewService._image_result({"body": base64.b64encode(body).decode(), "final_url": "https://images.python.org/image", "status": "ready"}), (None, None))

    def roots(self, temporary: str):
        root = Path(temporary)
        for name in ("cache", "config"):
            (root / name).mkdir(mode=0o700)
        return root, LinkPreviewCache(root), LinkPreviewPreferenceStore(root)

    def wait_for(self, service: LinkPreviewService, status: str, *, message: Message):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            payload = service.read(conversation_id=message.conversation_id, message_id=message.id, message_revision=message.revision)
            if payload["previews"] and payload["previews"][0]["status"] == status:
                return payload
            time.sleep(0.01)
        self.fail(f"preview never reached {status}")

    def test_exact_message_binding_rejects_missing_stale_assistant_and_cancelled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, cache, preferences = self.roots(temporary)
            message = Message()
            repository = Repository(message)
            service = LinkPreviewService(repository, cache, preferences, worker_factory=lambda: FakePool())
            try:
                for conversation_id, message_id, revision in (
                    ("bad", message.id, 1),
                    (message.conversation_id, "bad", 1),
                    (message.conversation_id, message.id, 2),
                    ("conv_other", message.id, 1),
                ):
                    with self.subTest(conversation_id=conversation_id, message_id=message_id, revision=revision):
                        with self.assertRaises(LinkPreviewServiceError):
                            service.read(conversation_id=conversation_id, message_id=message_id, message_revision=revision)
                for role, state in (("assistant", "accepted"), ("user", "cancelled")):
                    message.role, message.state = role, state
                    with self.assertRaises(LinkPreviewServiceError):
                        service.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                repository.message = None
                with self.assertRaises(LinkPreviewServiceError) as raised:
                    service.read(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                self.assertEqual(raised.exception.code, "link_preview.not_found")
            finally:
                service.close()

    def test_async_ready_card_and_image_are_cached_without_urls_in_projection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, cache, preferences = self.roots(temporary)
            message = Message(content={"schema_version": 1, "parts": [{"type": "text", "text": "Read https://python.org/docs"}]})
            pool = FakePool([
                page_result(image_candidate="https://images.python.org/card.png"),
                {"body": base64.b64encode(valid_webp()).decode(), "final_url": "https://images.python.org/card.png", "status": "ready"},
            ])
            service = LinkPreviewService(Repository(message), cache, preferences, worker_factory=lambda: pool)
            try:
                service.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                deadline = time.monotonic() + 2
                payload = None
                while time.monotonic() < deadline:
                    payload = service.read(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                    if len(payload["previews"]) == 1 and payload["previews"][0]["status"] == "ready":
                        break
                    time.sleep(0.01)
                self.assertIsNotNone(payload)
                self.assertEqual(len(payload["previews"]), 1)
                self.assertEqual([item["candidate_ordinal"] for item in payload["previews"]], [1])
                self.assertNotIn("url", repr(payload))
                image_id = payload["previews"][0]["image_id"]
                self.assertEqual(service.image(image_id)[0], valid_webp())
                self.assertEqual(len([call for call in pool.calls if call[0] == "page"]), 1)
            finally:
                service.close()

    def test_candidate_extraction_deduplicates_fragments_and_caps_three_urls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, cache, preferences = self.roots(temporary)
            message = Message(content={"schema_version": 1, "parts": [{"type": "text", "text": " ".join((
                "https://python.org/docs#one", "https://python.org/docs#two",
                "https://www.python.org/", "https://pypi.org/", "https://packaging.python.org/",
            ))}]})
            pool = FakePool([
                page_result(),
                page_result(display_host="www.python.org", final_url="https://www.python.org/"),
            ])
            service = LinkPreviewService(Repository(message), cache, preferences, worker_factory=lambda: pool)
            try:
                service.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                deadline = time.monotonic() + 2
                payload = None
                while time.monotonic() < deadline:
                    payload = service.read(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                    if len(payload["previews"]) == 2 and all(item["status"] == "ready" for item in payload["previews"]):
                        break
                    time.sleep(0.01)
                self.assertEqual([item["candidate_ordinal"] for item in payload["previews"]], [1, 3])
                self.assertEqual(len(pool.calls), 2)
            finally:
                service.close()

    def test_no_store_is_process_local_and_cache_miss_does_not_auto_fetch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, cache, preferences = self.roots(temporary)
            message = Message()
            pool = FakePool([page_result(cache_control=["no-store"])])
            service = LinkPreviewService(Repository(message), cache, preferences, worker_factory=lambda: pool)
            try:
                service.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                ready = self.wait_for(service, "ready", message=message)
                self.assertEqual(ready["previews"][0]["title"], "Safe title")
            finally:
                service.close()
            replacement_pool = FakePool()
            replacement = LinkPreviewService(Repository(message), cache, preferences, worker_factory=lambda: replacement_pool)
            try:
                read = replacement.read(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                self.assertEqual(read["previews"], [{"candidate_ordinal": 1, "status": "unavailable"}])
                self.assertEqual(replacement_pool.calls, [])
            finally:
                replacement.close()

    def test_ephemeral_state_is_lru_bounded_and_persisted_results_are_not_duplicated(self):
        with tempfile.TemporaryDirectory() as temporary:
            _root, cache, preferences = self.roots(temporary)
            message = Message()
            service = LinkPreviewService(Repository(message), cache, preferences, worker_factory=lambda: FakePool([page_result()]))
            try:
                with service._lock:
                    for index in range(MAXIMUM_EPHEMERAL_ENTRIES + 7):
                        service._remember_ephemeral_locked((f"msg_{index}", 1, 1), {"candidate_ordinal": 1, "status": "unavailable"})
                    self.assertEqual(len(service._ephemeral), MAXIMUM_EPHEMERAL_ENTRIES)
                    self.assertNotIn(("msg_0", 1, 1), service._ephemeral)
                service.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1, retry=True)
                self.wait_for(service, "ready", message=message)
                with service._lock:
                    self.assertNotIn((message.id, 1, 1), service._ephemeral)
            finally:
                service.close()

    def test_failures_are_bounded_negative_cached_and_explicit_retry_rechecks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, cache, preferences = self.roots(temporary)
            message = Message()
            pool = FakePool([LinkPreviewWorkerError("link_preview.blocked"), page_result()])
            service = LinkPreviewService(Repository(message), cache, preferences, worker_factory=lambda: pool)
            try:
                service.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                self.wait_for(service, "blocked", message=message)
                service.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                self.assertEqual(len(pool.calls), 1)
                service.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1, retry=True)
                self.wait_for(service, "ready", message=message)
                self.assertEqual(len(pool.calls), 2)
            finally:
                service.close()

    def test_disabled_offline_and_midflight_revision_change_never_publish(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, cache, preferences = self.roots(temporary)
            message = Message()
            offline_pool = FakePool()
            offline = LinkPreviewService(Repository(message), cache, preferences, worker_factory=lambda: offline_pool, offline=lambda: True)
            try:
                payload = offline.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                self.assertEqual(payload["previews"], [{"candidate_ordinal": 1, "status": "unavailable"}])
                self.assertEqual(offline_pool.calls, [])
            finally:
                offline.close()

            barrier = threading.Event()
            started = threading.Event()
            pool = FakePool([page_result()], barrier=barrier, started=started)
            service = LinkPreviewService(Repository(message), cache, preferences, worker_factory=lambda: pool)
            try:
                service.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1, retry=True)
                self.assertTrue(started.wait(timeout=2))
                future = service._pending[(message.id, 1, 1)]
                self.assertIsNotNone(future)
                message.revision = 2
                barrier.set()
                future.result(timeout=2)
                message.revision = 1
                self.assertEqual(service.read(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)["previews"], [{"candidate_ordinal": 1, "status": "unavailable"}])
                disabled = service.update_preference(enabled=False, expected_revision=1)
                self.assertFalse(disabled.enabled)
                payload = service.read(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                self.assertEqual(payload["previews"], [{"candidate_ordinal": 1, "status": "disabled"}])
                self.assertTrue(pool.closed)
            finally:
                service.close()

    def test_disabled_projection_distinguishes_policy_approved_links_from_blocked_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            _root, cache, preferences = self.roots(temporary)
            message = Message(content={"schema_version": 1, "parts": [{"type": "text", "text": "https://python.org/docs https://127.0.0.1/private"}]})
            service = LinkPreviewService(Repository(message), cache, preferences, worker_factory=FakePool)
            try:
                service.update_preference(enabled=False, expected_revision=1)
                payload = service.read(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                self.assertEqual(payload["previews"], [
                    {"candidate_ordinal": 1, "status": "disabled"},
                    {"candidate_ordinal": 2, "status": "blocked"},
                ])
            finally:
                service.close()

    def test_worker_payload_extra_fields_and_spoofed_host_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, cache, preferences = self.roots(temporary)
            message = Message()
            bad = page_result()
            bad["raw_html"] = "<secret>"
            pool = FakePool([bad])
            service = LinkPreviewService(Repository(message), cache, preferences, worker_factory=lambda: pool)
            try:
                service.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)
                result = self.wait_for(service, "unavailable", message=message)
                self.assertNotIn("raw_html", repr(result))
            finally:
                service.close()

    def test_cache_clear_generation_suppresses_late_inflight_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, cache, preferences = self.roots(temporary)
            message = Message()
            barrier = threading.Event()
            pool = FakePool([page_result()], barrier=barrier)
            service = LinkPreviewService(Repository(message), cache, preferences, worker_factory=lambda: pool)
            try:
                service.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1, retry=True)
                service.clear_cache()
                barrier.set()
                time.sleep(0.05)
                self.assertEqual(service.read(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)["previews"], [{"candidate_ordinal": 1, "status": "unavailable"}])
                self.assertIsNone(cache.lookup("https://python.org/docs"))
            finally:
                service.close()

    def test_cache_clear_linearizes_after_a_final_store_and_removes_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            _root, cache, preferences = self.roots(temporary)
            message = Message()
            pool_gate = threading.Event()
            pool = FakePool([page_result()], barrier=pool_gate)
            service = LinkPreviewService(Repository(message), cache, preferences, worker_factory=lambda: pool)
            store_entered = threading.Event()
            release_store = threading.Event()
            clear_requested = threading.Event()
            original_store = cache.store

            def delayed_store(*args, **kwargs):
                store_entered.set()
                release_store.wait()
                return original_store(*args, **kwargs)

            def clear_cache():
                clear_requested.set()
                service.clear_cache()

            try:
                with mock.patch.object(cache, "store", side_effect=delayed_store):
                    service.enqueue(conversation_id=message.conversation_id, message_id=message.id, message_revision=1, retry=True)
                    pool_gate.set()
                    self.assertTrue(store_entered.wait(timeout=2))
                    clear = threading.Thread(target=clear_cache)
                    clear.start()
                    self.assertTrue(clear_requested.wait(timeout=2))
                    self.assertTrue(clear.is_alive())
                    release_store.set()
                    clear.join(timeout=2)
                    self.assertFalse(clear.is_alive())
                self.assertIsNone(cache.lookup("https://python.org/docs"))
                self.assertEqual(service.read(conversation_id=message.conversation_id, message_id=message.id, message_revision=1)["previews"], [{"candidate_ordinal": 1, "status": "unavailable"}])
            finally:
                pool_gate.set()
                release_store.set()
                service.close()


if __name__ == "__main__":
    unittest.main()
