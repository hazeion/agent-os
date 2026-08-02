from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts.verify_macos_architecture import (
    ArchitectureError,
    inspect_macho_architectures,
    verify_bundle,
)


class MacOSArchitectureTests(unittest.TestCase):
    def make_bundle(self, root: Path) -> tuple[Path, Path, Path, Path]:
        bundle = root / "Mentat.app"
        main = bundle / "Contents" / "MacOS" / "Mentat"
        library = bundle / "Contents" / "Frameworks" / "library.dylib"
        text = bundle / "Contents" / "Resources" / "public" / "index.html"
        main.parent.mkdir(parents=True)
        library.parent.mkdir(parents=True)
        text.parent.mkdir(parents=True)
        main.write_bytes(b"main")
        library.write_bytes(b"library")
        text.write_text("public")
        return bundle, main, library, text

    def test_accepts_exact_thin_arm_and_intel_bundles(self):
        for architecture in ("arm64", "x86_64"):
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory() as temporary:
                bundle, main, library, _text = self.make_bundle(Path(temporary))
                count = verify_bundle(
                    bundle,
                    architecture,
                    runner_architecture=architecture,
                    inspector=lambda path: (
                        {architecture}
                        if path.name in {main.name, library.name}
                        else None
                    ),
                )
                self.assertEqual(count, 2)

    def test_rejects_runner_mismatch_before_inspecting_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, _main, _library, _text = self.make_bundle(Path(temporary))
            inspector = mock.Mock()
            with self.assertRaisesRegex(ArchitectureError, "runner architecture mismatch"):
                verify_bundle(
                    bundle,
                    "arm64",
                    runner_architecture="x86_64",
                    inspector=inspector,
                )
            inspector.assert_not_called()

    def test_rejects_mixed_universal_and_wrong_architecture_files(self):
        mutations = ({"arm64", "x86_64"}, {"x86_64"})
        for observed in mutations:
            with self.subTest(observed=observed), tempfile.TemporaryDirectory() as temporary:
                bundle, main, library, _text = self.make_bundle(Path(temporary))
                with self.assertRaisesRegex(ArchitectureError, "library.dylib"):
                    verify_bundle(
                        bundle,
                        "arm64",
                        runner_architecture="arm64",
                        inspector=lambda path: (
                            {"arm64"} if path.name == main.name else observed
                        ),
                    )

    def test_rejects_missing_or_non_macho_main_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, main, library, _text = self.make_bundle(Path(temporary))
            main.unlink()
            with self.assertRaisesRegex(ArchitectureError, "executable is missing"):
                verify_bundle(bundle, "arm64", runner_architecture="arm64")

        with tempfile.TemporaryDirectory() as temporary:
            bundle, main, library, _text = self.make_bundle(Path(temporary))
            with self.assertRaisesRegex(ArchitectureError, "not a Mach-O"):
                verify_bundle(
                    bundle,
                    "arm64",
                    runner_architecture="arm64",
                    inspector=lambda path: (
                        None if path.name == main.name else {"arm64"}
                    ),
                )

    def test_rejects_unknown_architecture_and_escaping_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, _main, _library, _text = self.make_bundle(root)
            with self.assertRaisesRegex(ArchitectureError, "unsupported"):
                verify_bundle(bundle, "universal2", runner_architecture="arm64")
            outside = root / "outside.dylib"
            outside.write_bytes(b"outside")
            (bundle / "Contents" / "Frameworks" / "escape.dylib").symlink_to(outside)
            with self.assertRaisesRegex(ArchitectureError, "escapes Contents"):
                verify_bundle(
                    bundle,
                    "arm64",
                    runner_architecture="arm64",
                    inspector=lambda _path: {"arm64"},
                )

    def test_tool_failure_is_fail_closed(self):
        path = Path("binary")
        with mock.patch(
            "scripts.verify_macos_architecture.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["file"]),
        ):
            with self.assertRaisesRegex(ArchitectureError, "inspection failed"):
                inspect_macho_architectures(path)


if __name__ == "__main__":
    unittest.main()
