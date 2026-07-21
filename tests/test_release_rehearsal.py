import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.release_rehearsal import (
    build_bundle,
    expected_artifacts,
    validate_release_tag,
    validate_source_sha,
)


ROOT = Path(__file__).resolve().parents[1]


class ReleaseRehearsalTests(unittest.TestCase):
    def make_artifacts(self, root: Path) -> None:
        for index, name in enumerate(expected_artifacts(), start=1):
            (root / name).write_bytes(f"artifact-{index}".encode())

    def test_current_beta_and_positive_numbered_rc_tags_are_valid(self):
        for tag in ("v0.1.0-beta.1", "v0.1.0-beta.1-rc.1", "v0.1.0-beta.1-rc.12"):
            self.assertEqual(validate_release_tag(tag), tag)
        for tag in (
            "v0.1.0-beta.2",
            "v0.1.0-beta.1-rc.0",
            "v0.1.0-beta.1-rc.01",
            "v0.1.0-beta.1-rc.1-extra",
            "0.1.0-beta.1-rc.1",
        ):
            with self.assertRaises(ValueError, msg=tag):
                validate_release_tag(tag)

    def test_source_sha_is_exact_lowercase_hex(self):
        self.assertEqual(validate_source_sha("a" * 40), "a" * 40)
        for value in ("a" * 39, "A" * 40, "g" * 40, "a" * 41):
            with self.assertRaises(ValueError):
                validate_source_sha(value)

    def test_workflow_script_entry_point_loads_from_outside_the_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "release_rehearsal.py"),
                    "validate-tag",
                    "v0.1.0-beta.1-rc.1",
                ],
                cwd=temporary,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bundle_is_deterministic_and_contains_no_local_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = root / "private-machine-artifacts"
            first = root / "first"
            second = root / "second"
            artifacts.mkdir()
            self.make_artifacts(artifacts)
            build_bundle(artifacts, first, "v0.1.0-beta.1-rc.1", "a" * 40)
            build_bundle(artifacts, second, "v0.1.0-beta.1-rc.1", "a" * 40)

            self.assertEqual(
                {path.name: path.read_bytes() for path in first.iterdir()},
                {path.name: path.read_bytes() for path in second.iterdir()},
            )
            self.assertEqual(
                {path.name for path in first.iterdir()},
                {"SHA256SUMS", "release-manifest.json", "RELEASE_NOTES.md"},
            )
            combined = b"".join(path.read_bytes() for path in first.iterdir())
            self.assertNotIn(str(root).encode(), combined)
            manifest = json.loads((first / "release-manifest.json").read_text())
            self.assertEqual(len(manifest["artifacts"]), 4)
            self.assertEqual(manifest["source_sha"], "a" * 40)
            self.assertNotIn("created", manifest)
            notes = (first / "RELEASE_NOTES.md").read_text()
            self.assertIn("/Applications/Mentat.app/Contents/MacOS/Mentat backup", notes)
            self.assertIn("$env:LOCALAPPDATA\\Programs\\Mentat\\mentat.exe", notes)
            self.assertIn("--confirm TOKEN_FROM_PREVIEW", notes)

    def test_inventory_rejects_missing_extra_empty_and_symlink_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            self.make_artifacts(artifacts)
            missing = next(iter(expected_artifacts()))
            (artifacts / missing).unlink()
            with self.assertRaisesRegex(ValueError, "inventory mismatch"):
                build_bundle(artifacts, root / "missing-output", "v0.1.0-beta.1", "a" * 40)
            (artifacts / missing).write_bytes(b"restored")
            (artifacts / "extra.txt").write_text("extra")
            with self.assertRaisesRegex(ValueError, "inventory mismatch"):
                build_bundle(artifacts, root / "extra-output", "v0.1.0-beta.1", "a" * 40)
            (artifacts / "extra.txt").unlink()
            (artifacts / missing).write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "size"):
                build_bundle(artifacts, root / "empty-output", "v0.1.0-beta.1", "a" * 40)
            (artifacts / missing).unlink()
            (artifacts / missing).symlink_to(next(path for path in artifacts.iterdir()))
            with self.assertRaisesRegex(ValueError, "regular file"):
                build_bundle(artifacts, root / "link-output", "v0.1.0-beta.1", "a" * 40)

    def test_output_must_be_empty_and_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            self.make_artifacts(artifacts)
            output = root / "output"
            output.mkdir()
            (output / "old.txt").write_text("old")
            with self.assertRaisesRegex(ValueError, "must be empty"):
                build_bundle(artifacts, output, "v0.1.0-beta.1", "a" * 40)
            with self.assertRaisesRegex(ValueError, "must not overlap"):
                build_bundle(artifacts, artifacts / "nested", "v0.1.0-beta.1", "a" * 40)

    def test_public_rehearsal_covers_every_required_drill_and_history_rule(self):
        guide = (ROOT / "RELEASE_REHEARSAL.md").read_text(encoding="utf-8")
        normalized = " ".join(guide.split())
        for phrase in (
            "Clean install",
            "Upgrade from the recorded previous release",
            "Backup before upgrade",
            "Restore that backup into a clean install",
            "Roll back to the previous release",
            "Uninstall, reinstall",
            "another person installed the exact files",
            "Never delete or move a release tag",
            "no P0 or P1 issue remains",
            "release-tag rule blocks tag updates and deletion",
            "/Applications/Mentat.app/Contents/MacOS/Mentat",
            "$env:LOCALAPPDATA\\Mentat\\backups\\BACKUP_NAME",
            "--confirm TOKEN_FROM_PREVIEW",
            "mentat-release-recovery-bundle",
            "Never rebuild or replace an asset",
            "Apple Silicon + Rosetta",
            "--data-dir RESTORE_DIR",
            "Require a `restored` result",
            "Install the recorded previous package—not the candidate",
            "backup --data-dir UPGRADE_DIR",
            "mentat_local-0.1.0b1-py3-none-any.whl",
            "mentat_local-0.1.0b1.tar.gz",
            "Next, prove uninstall/reinstall preservation",
            "confirm the fixture files still exist in `UPGRADE_DIR`",
            "reinstall the exact candidate",
            "Then stop the candidate with `--data-dir UPGRADE_DIR`",
            "Compare the restored fixture through Mentat",
            "This guide is the artifact-install authority",
        ):
            self.assertIn(phrase, normalized)
        self.assertLess(
            normalized.index("Backup before upgrade"),
            normalized.index("Upgrade from the recorded previous release"),
        )
        self.assertLess(
            normalized.index("Next, prove uninstall/reinstall preservation"),
            normalized.index("Finally, prove rollback"),
        )


if __name__ == "__main__":
    unittest.main()
