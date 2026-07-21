import io
import json
import os
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import health_checks
import runtime_config
import server
from data_layout import SEED_FILE_NAMES
from mentat import __version__
from mentat import cli
from mentat.version import DISPLAY_VERSION


ROOT = Path(__file__).resolve().parents[1]


class PackagingContractTests(unittest.TestCase):
    def test_pyproject_uses_single_version_source_and_pinned_dependencies(self):
        document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(document["project"]["dynamic"], ["version"])
        self.assertEqual(
            document["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "mentat.version.__version__",
        )
        self.assertEqual(document["project"]["requires-python"], ">=3.11,<3.14")
        self.assertTrue(all("==" in item for item in document["project"]["dependencies"]))
        self.assertEqual(document["project"]["scripts"]["mentat"], "mentat.cli:main")

    def test_source_manifest_allowlists_public_seed_files(self):
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertNotIn("recursive-include data", manifest)
        self.assertNotIn("recursive-include public", manifest)
        self.assertIn("prune data/private", manifest)
        self.assertIn("prune data/runtime", manifest)
        self.assertIn("include scripts/build_native.py", manifest)
        self.assertIn("include requirements-native.lock", manifest)
        for name in SEED_FILE_NAMES:
            self.assertIn(f"include data/{name}", manifest)
        for name in ("app.js", "core.js", "index.html", "mentat-logo.png", "styles.css"):
            self.assertIn(f"include public/{name}", manifest)

    def test_native_definitions_read_or_receive_the_single_version_source(self):
        spec = (ROOT / "packaging" / "mentat.spec").read_text(encoding="utf-8")
        windows = (ROOT / "packaging" / "windows" / "Mentat.iss").read_text(
            encoding="utf-8"
        )
        builder = (ROOT / "scripts" / "build_native.py").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements-native.txt").read_text(encoding="utf-8")
        lock = (ROOT / "requirements-native.lock").read_text(encoding="utf-8")
        self.assertIn('runpy.run_path(str(ROOT / "mentat" / "version.py"))', spec)
        self.assertIn('name="mentat"', spec)
        self.assertIn("console=True", spec)
        self.assertIn('"Mentat Launcher" if sys.platform.startswith("win")', spec)
        self.assertIn("MyAppVersion must be supplied", windows)
        self.assertNotIn("0.1.0-beta.1", windows)
        self.assertIn("from mentat.version import DISPLAY_VERSION, __version__", builder)
        self.assertIn('component["BundleIsRelocatable"] = False', builder)
        self.assertIn('"--component-plist"', builder)
        self.assertIn("-r requirements.txt", requirements)
        self.assertIn("pyinstaller==6.21.0", requirements)
        self.assertIn("pyinstaller==6.21.0", lock)
        self.assertIn("colorama==0.4.6", lock)
        self.assertIn("pefile==2024.8.26", lock)
        self.assertIn("pywin32-ctypes==0.2.3", lock)
        self.assertIn("--hash=sha256:", lock)

    def test_native_entry_honors_explicit_cli_arguments(self):
        entry = (ROOT / "packaging" / "mentat_native.py").read_text(encoding="utf-8")
        self.assertIn("arguments = sys.argv[1:]", entry)
        self.assertIn('main(arguments if arguments else ["start", "--open-browser"])', entry)

    def test_native_ci_builds_unsigned_artifacts_without_signing_secrets(self):
        workflow = (
            ROOT / ".github" / "workflows" / "native-artifacts.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("macos-15-intel", workflow)
        self.assertIn("windows-2025", workflow)
        self.assertIn('python-version: "3.13.14"', workflow)
        self.assertIn("Expected Inno Setup 6.7.1", workflow)
        self.assertIn("choco list --local-only --exact innosetup --limit-output", workflow)
        self.assertNotIn("VersionInfo.ProductVersion", workflow)
        self.assertGreaterEqual(workflow.count("-Wait -PassThru"), 3)
        self.assertIn('item.__setitem__("BundleIsRelocatable", False)', workflow)
        self.assertIn('pkgbuild --root "$fixture_root" --component-plist', workflow)
        self.assertIn("Mentat CLI survived uninstall", workflow)
        self.assertIn("python scripts/build_native.py", workflow)
        self.assertIn("--require-hashes -r requirements-native.lock", workflow)
        self.assertIn("unsigned", workflow)
        self.assertIn("api/health", workflow)
        self.assertIn("unins000.exe", workflow)
        self.assertIn("upgrade-sentinel.txt", workflow)
        self.assertIn("mentat-baseline.pkg", workflow)
        self.assertIn("MyAppVersion=0.0.0", workflow)
        self.assertIn("stale-from-baseline.txt", workflow)
        self.assertIn("Upgrade retained stale application files", workflow)
        self.assertIn("Mentat remained healthy after stop", workflow)
        self.assertIn("pkgutil --forget dev.mentat.local", workflow)
        self.assertIn("Mentat console CLI missing", workflow)
        self.assertIn("sudo installer", workflow)
        self.assertNotIn("actions/checkout@v", workflow)
        self.assertNotIn("actions/setup-python@v", workflow)
        self.assertNotIn("actions/upload-artifact@v", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("pull_request_target", workflow)

    def test_signed_release_path_is_manual_protected_and_ephemeral(self):
        workflow = (
            ROOT / ".github" / "workflows" / "signed-release-artifacts.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertIn("environment: beta-release", workflow)
        self.assertEqual(
            workflow.count("github.ref == 'refs/heads/main' && github.ref_protected"),
            4,
        )
        self.assertEqual(workflow.count("Verify trusted source revision"), 3)
        self.assertIn("--require-hashes -r requirements-native.lock", workflow)
        self.assertIn("notarytool submit", workflow)
        self.assertIn("stapler validate", workflow)
        self.assertIn("spctl --assess --type execute", workflow)
        self.assertIn("security import", workflow)
        self.assertIn(" -x -k ", workflow)
        self.assertIn("signtool.exe", workflow.lower())
        self.assertIn("Import-PfxCertificate", workflow)
        self.assertIn("mentat-signing-thumbprint", workflow)
        self.assertIn("Smoke the exact signed macOS package", workflow)
        self.assertIn("Mentat remained healthy after stop", workflow)
        self.assertIn('item.__setitem__("BundleIsRelocatable", False)', workflow)
        self.assertNotIn("pkgbuild --component dist/Mentat.app", workflow)
        self.assertIn("Smoke the exact signed Windows installer", workflow)
        self.assertIn("Signed release and tag required", workflow)
        self.assertIn("Verified Python release artifacts", workflow)
        self.assertIn("python scripts/verify_python_artifacts.py dist", workflow)
        self.assertIn("release-bundle/SHA256SUMS", workflow)
        self.assertIn("release-bundle/release-manifest.json", workflow)
        self.assertIn("Upload exact release recovery bundle", workflow)
        self.assertIn("retention-days: 14", workflow)
        self.assertIn('git push origin "refs/tags/$RELEASE_TAG"', workflow)
        self.assertIn("if: always()", workflow)
        self.assertNotIn("actions/checkout@v", workflow)
        self.assertNotIn("actions/setup-python@v", workflow)
        self.assertNotIn("actions/upload-artifact@v", workflow)
        self.assertNotIn("actions/download-artifact@v", workflow)

    def test_native_installers_use_platform_data_safe_install_locations(self):
        windows = (ROOT / "packaging" / "windows" / "Mentat.iss").read_text(encoding="utf-8")
        builder = (ROOT / "scripts" / "build_native.py").read_text(encoding="utf-8")
        self.assertIn("DefaultDirName={localappdata}\\Programs\\Mentat", windows)
        self.assertIn('#define MyAppExeName "Mentat Launcher.exe"', windows)
        self.assertIn("PrivilegesRequired=lowest", windows)
        self.assertIn("OutputDir={#MyAppOutputDir}", windows)
        self.assertIn('package_root / "Applications" / "Mentat.app"', builder)
        self.assertIn('"--install-location",\n                "/",', builder)
        self.assertIn("/DMyAppSourceDir=", builder)
        self.assertIn("/DMyAppOutputDir=", builder)

    def test_localhost_is_normalized_to_literal_loopback(self):
        args = SimpleNamespace(host="localhost")
        with patch.object(runtime_config, "DEFAULT_CONFIG_FILE", Path("/definitely/missing")):
            with patch.object(runtime_config, "LOCAL_CONFIG_FILE", Path("/definitely/missing-local")):
                with patch.object(runtime_config, "LEGACY_DEFAULT_CONFIG_FILE", Path("/definitely/missing-legacy")):
                    with patch.object(runtime_config, "LEGACY_LOCAL_CONFIG_FILE", Path("/definitely/missing-legacy-local")):
                        config = runtime_config.load_app_config(args)
        self.assertEqual(config.host, "127.0.0.1")

    def test_product_version_is_consistent_in_server_and_health(self):
        self.assertEqual(__version__, "0.1.0b1")
        self.assertEqual(DISPLAY_VERSION, "v0.1.0-beta.1")
        self.assertEqual(server.Handler.server_version, f"Mentat/{__version__}")

    def test_installed_asset_fallback_stays_inside_prefix_share(self):
        with patch.object(runtime_config, "BASE_DIR", Path("/missing/mentat")):
            self.assertEqual(
                runtime_config.bundled_asset_dir("public"),
                runtime_config.INSTALLED_ASSET_ROOT / "public",
            )

    def test_frozen_macos_uses_real_resources_instead_of_framework_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            contents = Path(temporary) / "Mentat.app" / "Contents"
            executable = contents / "MacOS" / "Mentat"
            resources = contents / "Resources" / "data"
            executable.parent.mkdir(parents=True)
            executable.touch()
            resources.mkdir(parents=True)
            with patch.object(runtime_config.sys, "frozen", True, create=True):
                with patch.object(runtime_config.sys, "platform", "darwin"):
                    with patch.object(runtime_config.sys, "executable", str(executable)):
                        self.assertEqual(
                            runtime_config.bundled_asset_dir("data"),
                            resources.resolve(),
                        )


class CliTests(unittest.TestCase):
    def test_version_is_light_and_friendly(self):
        output = io.StringIO()
        with self.assertRaises(SystemExit) as raised, redirect_stdout(output):
            cli.main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn(DISPLAY_VERSION, output.getvalue())
        self.assertIn(__version__, output.getvalue())

    def test_runtime_arguments_forward_config_with_server_spelling(self):
        args = cli.build_parser().parse_args(
            ["status", "--config", "example.toml", "--port", "8891"]
        )
        self.assertEqual(
            cli._forward_runtime_arguments(args),
            ["--config", "example.toml", "--port", "8891"],
        )

    def test_doctor_output_does_not_include_private_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            private_root = Path(temporary) / "private-user-data"
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cli.main(["doctor", "--data-dir", str(private_root)])
            payload = json.loads(output.getvalue())
        self.assertIn(exit_code, {0, 2})
        self.assertEqual(payload["version"], __version__)
        self.assertEqual(payload["network"], "loopback-only")
        self.assertNotIn(str(private_root), output.getvalue())

    def test_start_runs_preflight_before_the_server_module(self):
        args = cli.build_parser().parse_args(["start", "--port", "8891"])
        with patch.object(cli, "run_lifecycle", return_value=0) as preflight:
            with patch.object(cli.subprocess, "call", return_value=0) as call:
                self.assertEqual(cli.run_start(args), 0)
        preflight.assert_called_once_with("preflight", args)
        self.assertEqual(
            call.call_args.args[0],
            [sys.executable, "-m", "server", "--port", "8891"],
        )
        self.assertEqual(
            call.call_args.kwargs["env"]["MENTAT_LAUNCHER_PID"],
            str(os.getpid()),
        )

    def test_native_start_opens_browser_only_after_health_is_ready(self):
        args = cli.build_parser().parse_args(
            ["start", "--open-browser", "--port", "8895"]
        )
        process = MagicMock()
        process.poll.return_value = None
        process.wait.return_value = 0
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(cli, "run_lifecycle", return_value=0):
            with patch.object(
                cli,
                "_load_config",
                return_value=(None, SimpleNamespace(host="127.0.0.1", port=8895)),
            ):
                with patch.object(cli.subprocess, "Popen", return_value=process):
                    with patch.object(cli, "urlopen", return_value=response):
                        with patch.object(cli.webbrowser, "open") as open_browser:
                            self.assertEqual(cli.run_start(args), 0)
        open_browser.assert_called_once_with("http://127.0.0.1:8895")
        process.wait.assert_called_once_with()

    def test_frozen_start_uses_internal_native_server_mode(self):
        args = cli.build_parser().parse_args(["start", "--port", "8895"])
        with patch.object(cli.sys, "frozen", True, create=True):
            with patch.object(cli, "run_lifecycle", return_value=0):
                with patch.object(cli.subprocess, "call", return_value=0) as call:
                    self.assertEqual(cli.run_start(args), 0)
        self.assertEqual(call.call_args.args[0], [sys.executable, "--port", "8895"])
        self.assertEqual(call.call_args.kwargs["env"]["MENTAT_NATIVE_SERVER"], "1")


if __name__ == "__main__":
    unittest.main()
