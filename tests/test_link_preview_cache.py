from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from io import BytesIO

from PIL import Image

from link_preview_cache import (
    BLOCKED_SECONDS,
    LinkPreviewCache,
    LinkPreviewCacheError,
    LinkPreviewPreferenceConflict,
    LinkPreviewPreferenceStore,
    MAXIMUM_READY_SECONDS,
    UNAVAILABLE_SECONDS,
    _owned_file,
)


def valid_webp() -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 8), (20, 80, 40)).save(output, "WEBP", quality=80)
    return output.getvalue()


class LinkPreviewCacheTests(unittest.TestCase):
    def root(self, temporary: str) -> Path:
        root = Path(temporary)
        for name in ("cache", "config"):
            (root / name).mkdir(mode=0o700)
        return root

    def test_windows_zero_link_count_is_regular_but_hardlinks_still_fail(self):
        regular = SimpleNamespace(st_mode=stat.S_IFREG | 0o666, st_nlink=0, st_size=32)
        hardlinked = SimpleNamespace(st_mode=stat.S_IFREG | 0o666, st_nlink=2, st_size=32)
        with mock.patch("link_preview_cache.os.name", "nt"), mock.patch("link_preview_cache.os.lstat", return_value=regular):
            self.assertIs(_owned_file(Path("cache-secret"), maximum_bytes=32), regular)
        with mock.patch("link_preview_cache.os.name", "nt"), mock.patch("link_preview_cache.os.lstat", return_value=hardlinked):
            with self.assertRaises(LinkPreviewCacheError):
                _owned_file(Path("cache-secret"), maximum_bytes=32)

    def test_preference_defaults_enabled_and_updates_by_exact_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            store = LinkPreviewPreferenceStore(root)
            self.assertEqual(store.read().public_projection(), {"enabled": True, "revision": 1})
            disabled = store.update(enabled=False, expected_revision=1)
            self.assertEqual(disabled.public_projection(), {"enabled": False, "revision": 2})
            with self.assertRaises(LinkPreviewPreferenceConflict):
                store.update(enabled=True, expected_revision=1)
            unchanged = store.update(enabled=False, expected_revision=2)
            self.assertEqual(unchanged, disabled)
            path = root / "config" / "link-previews-v1.json"
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            else:
                self.assertTrue(path.is_file())

    def test_preference_rejects_extra_fields_broad_permissions_and_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            path = root / "config" / "link-previews-v1.json"
            path.write_text('{"schema_version":1,"enabled":true,"revision":1,"url":"https://secret.example/"}', encoding="utf-8")
            path.chmod(0o600)
            with self.assertRaises(LinkPreviewCacheError):
                LinkPreviewPreferenceStore(root).read()
            path.write_text('{"schema_version":1,"enabled":true,"revision":1}', encoding="utf-8")
            path.chmod(0o644)
            if os.name == "posix":
                with self.assertRaises(OSError):
                    LinkPreviewPreferenceStore(root).read()
            else:
                self.assertTrue(LinkPreviewPreferenceStore(root).read().enabled)
            path.unlink()
            target = root / "outside.json"
            target.write_text('{"schema_version":1,"enabled":true,"revision":1}', encoding="utf-8")
            target.chmod(0o600)
            path.symlink_to(target)
            with self.assertRaises(OSError):
                LinkPreviewPreferenceStore(root).read()

    def test_cache_persists_only_hmac_identity_and_safe_projection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            now = [1_000.0]
            cache = LinkPreviewCache(root, clock=lambda: now[0])
            raw = "https://public.example/private-path?ordinary=value"
            result = cache.store(
                raw,
                final_normalized_url="https://cdn.example/final",
                status="ready",
                ttl_seconds=60,
                title="Safe title",
                description="Safe description",
                site_name="Example",
                display_host="public.example",
                image_alt="Preview",
                image_webp=valid_webp(),
                image_normalized_url="https://images.example/source.png",
                image_final_normalized_url="https://images.example/final.png",
            )
            self.assertEqual(result["status"], "ready")
            self.assertRegex(str(result["image_id"]), r"^[0-9a-f]{32}$")
            self.assertNotIn("url", result)
            self.assertEqual(cache.lookup(raw), result)
            database = root / "cache" / "link-previews-v1" / "metadata.sqlite3"
            self.assertNotIn(raw.encode("utf-8"), database.read_bytes())
            connection = sqlite3.connect(database)
            try:
                columns = [row[1] for row in connection.execute("PRAGMA table_info(previews)")]
            finally:
                connection.close()
            self.assertFalse(any("url" in column for column in columns))
            image, max_age = cache.image(str(result["image_id"])) or (b"", -1)
            self.assertEqual(image, valid_webp())
            self.assertEqual(max_age, 60)

    def test_expiry_negative_ttls_and_clear_are_independent_from_preference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            now = [5_000.0]
            preference = LinkPreviewPreferenceStore(root)
            preference.update(enabled=False, expected_revision=1)
            cache = LinkPreviewCache(root, clock=lambda: now[0])
            unavailable_url = "https://unavailable.example/"
            blocked_url = "https://blocked.example/"
            cache.store(unavailable_url, final_normalized_url=unavailable_url, status="unavailable", ttl_seconds=UNAVAILABLE_SECONDS)
            cache.store(blocked_url, final_normalized_url=blocked_url, status="blocked", ttl_seconds=BLOCKED_SECONDS)
            with self.assertRaises(LinkPreviewCacheError):
                cache.store(unavailable_url, final_normalized_url=unavailable_url, status="unavailable", ttl_seconds=UNAVAILABLE_SECONDS + 1)
            with self.assertRaises(LinkPreviewCacheError):
                cache.store("https://ready.example/", final_normalized_url="https://ready.example/", status="ready", ttl_seconds=MAXIMUM_READY_SECONDS + 1, title="x", display_host="ready.example")
            now[0] += UNAVAILABLE_SECONDS + 1
            self.assertIsNone(cache.lookup(unavailable_url))
            self.assertEqual(cache.lookup(blocked_url), {"status": "blocked"})
            secret = (root / "cache" / "link-previews-v1" / "secret").read_bytes()
            cache.clear()
            self.assertIsNone(cache.lookup(blocked_url))
            self.assertEqual((root / "cache" / "link-previews-v1" / "secret").read_bytes(), secret)
            self.assertEqual(preference.read().public_projection(), {"enabled": False, "revision": 2})

    def test_lru_eviction_and_secret_change_discard_derived_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            now = [1.0]
            with mock.patch("link_preview_cache.MAXIMUM_METADATA_ENTRIES", 2):
                cache = LinkPreviewCache(root, clock=lambda: now[0])
                urls = [f"https://example.com/{index}" for index in range(3)]
                for index, url in enumerate(urls):
                    now[0] += 1
                    cache.store(url, final_normalized_url=url, status="ready", ttl_seconds=60, title=f"Title {index}", display_host="example.com")
                self.assertIsNone(cache.lookup(urls[0]))
                self.assertIsNotNone(cache.lookup(urls[1]))
                self.assertIsNotNone(cache.lookup(urls[2]))
            secret_path = root / "cache" / "link-previews-v1" / "secret"
            secret_path.write_bytes(os.urandom(32))
            secret_path.chmod(0o600)
            replacement = LinkPreviewCache(root, clock=lambda: now[0])
            self.assertIsNone(replacement.lookup(urls[2]))

    def test_image_transform_version_mismatch_discards_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            url = "https://python.org/"
            cache = LinkPreviewCache(root)
            cache.store(url, final_normalized_url=url, status="ready", ttl_seconds=60, title="Python", display_host="python.org")
            with mock.patch("link_preview_cache.IMAGE_TRANSFORM_VERSION", "image-transform-v2"):
                replacement = LinkPreviewCache(root)
                self.assertIsNone(replacement.lookup(url))

    def test_image_byte_lru_evicts_whole_metadata_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            now = [10.0]
            image = valid_webp()
            with mock.patch("link_preview_cache.MAXIMUM_IMAGE_BYTES", len(image) * 2 - 1):
                cache = LinkPreviewCache(root, clock=lambda: now[0])
                first = "https://python.org/first"
                second = "https://python.org/second"
                cache.store(first, final_normalized_url=first, status="ready", ttl_seconds=60, title="First", display_host="python.org", image_webp=image, image_normalized_url="https://images.python.org/first", image_final_normalized_url="https://images.python.org/first")
                now[0] += 1
                cache.store(second, final_normalized_url=second, status="ready", ttl_seconds=60, title="Second", display_host="python.org", image_webp=image, image_normalized_url="https://images.python.org/second", image_final_normalized_url="https://images.python.org/second")
                self.assertIsNone(cache.lookup(first))
                self.assertIsNotNone(cache.lookup(second))

    def test_cache_rejects_unsafe_storage_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            cache_root = root / "cache" / "link-previews-v1"
            cache_root.mkdir(mode=0o755)
            with self.assertRaises(LinkPreviewCacheError):
                LinkPreviewCache(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            cache = LinkPreviewCache(root)
            with self.assertRaises(LinkPreviewCacheError):
                cache.store("https://example.com/", final_normalized_url="https://example.com/", status="ready", ttl_seconds=60, title="Only title", display_host=None)
            with self.assertRaises(LinkPreviewCacheError):
                cache.store("https://example.com/", final_normalized_url="https://example.com/", status="blocked", ttl_seconds=60, title="leak")
            with self.assertRaises(LinkPreviewCacheError):
                cache.store("https://example.com/", final_normalized_url="https://example.com/", status="ready", ttl_seconds=60, title="Unsafe", display_host="example.com", image_webp=b"<svg/>", image_normalized_url="https://images.example/x", image_final_normalized_url="https://images.example/x")
            self.assertIsNone(cache.image("https://example.com/image.webp"))

    def test_corrupt_disposable_database_is_discarded_without_changing_preference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            preference = LinkPreviewPreferenceStore(root)
            preference.update(enabled=False, expected_revision=1)
            LinkPreviewCache(root)
            database = root / "cache" / "link-previews-v1" / "metadata.sqlite3"
            database.write_bytes(b"not-sqlite")
            database.chmod(0o600)
            cache = LinkPreviewCache(root)
            self.assertIsNone(cache.lookup("https://python.org/"))
            self.assertEqual(preference.read().public_projection(), {"enabled": False, "revision": 2})

    def test_semantically_corrupt_rows_fail_before_projection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            url = "https://python.org/"
            cache = LinkPreviewCache(root)
            cache.store(url, final_normalized_url=url, status="ready", ttl_seconds=60, title="Safe", display_host="python.org")
            database = root / "cache" / "link-previews-v1" / "metadata.sqlite3"
            connection = sqlite3.connect(database)
            try:
                connection.execute("UPDATE previews SET title = ?", ("raw\u202e-canary",))
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(LinkPreviewCacheError) as raised:
                cache.lookup(url)
            self.assertNotIn("canary", str(raised.exception))

    def test_startup_reconciles_missing_secret_orphan_images_and_crash_temps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            cache = LinkPreviewCache(root)
            preview = cache.store(
                "https://python.org/",
                final_normalized_url="https://python.org/",
                status="ready",
                ttl_seconds=60,
                title="Python",
                display_host="python.org",
                image_webp=valid_webp(),
                image_normalized_url="https://images.python.org/source",
                image_final_normalized_url="https://images.python.org/final",
            )
            cache_root = root / "cache" / "link-previews-v1"
            images = cache_root / "images"
            crash_temp = images / f".{str(preview['image_id'])}.{'a' * 16}.tmp"
            crash_temp.write_bytes(b"partial")
            crash_temp.chmod(0o600)
            orphan = images / f"{'b' * 32}.webp"
            orphan.write_bytes(b"orphan")
            orphan.chmod(0o600)
            LinkPreviewCache(root)
            self.assertFalse(crash_temp.exists())
            self.assertFalse(orphan.exists())
            (cache_root / "secret").unlink()
            (cache_root / "metadata.sqlite3").unlink()
            self.assertTrue(any(images.iterdir()))
            LinkPreviewCache(root)
            self.assertEqual(list(images.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
