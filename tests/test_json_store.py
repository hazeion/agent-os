from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import json_store


class JsonStoreTests(unittest.TestCase):
    def test_mode_is_established_before_atomic_replace_commit(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tasks.json"
            path.write_text("[]\n", encoding="utf-8")
            if os.name == "posix":
                path.chmod(0o600)
            events: list[tuple[str, str]] = []
            real_chmod = Path.chmod
            real_replace = Path.replace

            def record_chmod(selected, *args, **kwargs):
                events.append(("chmod", selected.name))
                return real_chmod(selected, *args, **kwargs)

            def record_replace(selected, target):
                events.append(("replace", selected.name))
                return real_replace(selected, target)

            with patch.object(Path, "chmod", new=record_chmod), patch.object(
                Path,
                "replace",
                new=record_replace,
            ):
                json_store.write_json_atomic(path, [{"id": "committed-once"}])

            replace_index = next(
                index for index, event in enumerate(events) if event[0] == "replace"
            )
            self.assertFalse(any(event[0] == "chmod" for event in events[replace_index + 1 :]))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [{"id": "committed-once"}])
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
