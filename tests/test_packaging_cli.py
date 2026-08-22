import ast
import io
import json
import os
import re
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import health_checks
import remote_hermes
import runtime_config
import server
from data_layout import SEED_FILE_NAMES
from mentat import __version__
from mentat import cli
from mentat import web_runtime
from mentat.version import DISPLAY_VERSION


ROOT = Path(__file__).resolve().parents[1]


class PackagingContractTests(unittest.TestCase):
    def test_pyproject_uses_single_version_source_and_pinned_dependencies(self):
        document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = document["project"]["dependencies"]
        runtime_requirements = {
            line.strip()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        self.assertEqual(document["project"]["dynamic"], ["version"])
        self.assertEqual(
            document["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "mentat.version.__version__",
        )
        self.assertEqual(document["project"]["requires-python"], ">=3.11,<3.14")
        self.assertTrue(all("==" in item for item in dependencies))
        self.assertSetEqual(set(dependencies), runtime_requirements)
        self.assertEqual(document["project"]["scripts"]["mentat"], "mentat.cli:main")
        self.assertIn(
            "delegation_artifacts",
            document["tool"]["setuptools"]["py-modules"],
        )
        self.assertIn(
            "hermes_browser_events",
            document["tool"]["setuptools"]["py-modules"],
        )
        self.assertIn(
            "hermes_event_refresh",
            document["tool"]["setuptools"]["py-modules"],
        )
        self.assertIn(
            "hermes_webhook_health",
            document["tool"]["setuptools"]["py-modules"],
        )
        self.assertIn(
            "hermes_webhook_store",
            document["tool"]["setuptools"]["py-modules"],
        )
        self.assertIn(
            "orchestration_service",
            document["tool"]["setuptools"]["py-modules"],
        )
        self.assertIn(
            "run_repository",
            document["tool"]["setuptools"]["py-modules"],
        )

    def test_source_manifest_allowlists_public_seed_files(self):
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertNotIn("recursive-include data", manifest)
        self.assertNotIn("recursive-include public", manifest)
        self.assertIn("prune data/private", manifest)
        self.assertIn("prune data/runtime", manifest)
        self.assertIn("include scripts/build_native.py", manifest)
        self.assertIn("include scripts/verify_macos_architecture.py", manifest)
        artifact_verifier = (
            ROOT / "scripts" / "verify_python_artifacts.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"scripts/verify_macos_architecture.py"', artifact_verifier)
        self.assertIn("include requirements-native.lock", manifest)
        for name in SEED_FILE_NAMES:
            self.assertIn(f"include data/{name}", manifest)
        for name in (
            "app.js",
            "core.js",
            "index.html",
            "mentat-logo.png",
            "mentat-mark-emerald.png",
            "styles.css",
        ):
            self.assertIn(f"include public/{name}", manifest)

    def test_emerald_mark_is_in_every_static_asset_inventory(self):
        asset = "mentat-mark-emerald.png"
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        spec = (ROOT / "packaging" / "mentat.spec").read_text(encoding="utf-8")
        verifier = (
            ROOT / "scripts" / "verify_python_artifacts.py"
        ).read_text(encoding="utf-8")
        self.assertIn(f"public/{asset}", pyproject)
        self.assertIn(f'"{asset}"', spec)
        self.assertIn(f"public/{asset}", verifier)

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
        self.assertIn("def build_web_runtime()", builder)
        self.assertIn('"web", "run", "build"', builder)
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
        self.assertIn('"--mentat-private-bridge"', entry)

    def test_native_ci_builds_unsigned_artifacts_without_signing_secrets(self):
        workflow = (
            ROOT / ".github" / "workflows" / "native-artifacts.yml"
        ).read_text(encoding="utf-8")
        matrix = workflow.split("      matrix:\n", 1)[1].split("\n    steps:\n", 1)[0]
        self.assertEqual(matrix.count("          - label:"), 3)
        self.assertIn(
            "          - label: macOS Apple Silicon\n"
            "            runner: macos-15\n"
            "            architecture: arm64\n",
            matrix,
        )
        self.assertIn(
            "          - label: macOS Intel\n"
            "            runner: macos-15-intel\n"
            "            architecture: x86_64\n",
            matrix,
        )
        self.assertLess(workflow.index("runner: macos-15\n"), workflow.index("runner: macos-15-intel\n"))
        self.assertIn("architecture: arm64", workflow)
        self.assertIn("architecture: x86_64", workflow)
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
        self.assertIn("python scripts/verify_macos_architecture.py", workflow)
        self.assertIn('test "$(uname -m)" = "$EXPECTED_MACOS_ARCHITECTURE"', workflow)
        self.assertIn("mentat-macos-arm64-unsigned", workflow)
        self.assertIn("mentat-macos-x86_64-unsigned", workflow)
        self.assertIn("--require-hashes -r requirements-native.lock", workflow)
        self.assertIn("unsigned", workflow)
        self.assertIn("api/bridge/health", workflow)
        self.assertIn("Install the frozen web dependency tree", workflow)
        self.assertIn("Resources/web/server.js", workflow)
        self.assertIn("_internal/web/server.js", workflow)
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

    def test_signed_release_payload_counts_match_native_manifest(self):
        spec_path = ROOT / "packaging" / "mentat.spec"
        spec_text = spec_path.read_text(encoding="utf-8")
        spec_tree = ast.parse(spec_text, filename=str(spec_path))
        manifest_counts = {}
        manifest_names = {"PUBLIC_ASSETS", "PUBLIC_SEEDS"}
        for name in manifest_names:
            assignments = [
                statement
                for statement in spec_tree.body
                if isinstance(statement, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == name
                    for target in statement.targets
                )
            ]
            self.assertEqual(len(assignments), 1, f"expected one literal {name} assignment")
            self.assertIsInstance(
                assignments[0].value,
                ast.Tuple,
                f"{name} must remain an immutable tuple literal",
            )
            writes = [
                node
                for node in ast.walk(spec_tree)
                if isinstance(node, ast.Name)
                and node.id == name
                and isinstance(node.ctx, ast.Store)
            ]
            self.assertEqual(len(writes), 1, f"unsupported additional write to {name}")
            manifest_counts[name] = len(ast.literal_eval(assignments[0].value))

        datas_assignments = [
            statement
            for statement in spec_tree.body
            if isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "datas"
                for target in statement.targets
            )
        ]
        self.assertEqual(len(datas_assignments), 1)
        public_comprehension = datas_assignments[0].value
        self.assertIsInstance(public_comprehension, ast.ListComp)
        self.assertEqual(len(public_comprehension.generators), 1)
        public_generator = public_comprehension.generators[0]
        self.assertIsInstance(public_generator.iter, ast.Name)
        self.assertEqual(public_generator.iter.id, "PUBLIC_ASSETS")
        self.assertIsInstance(public_comprehension.elt, ast.Tuple)
        self.assertEqual(ast.literal_eval(public_comprehension.elt.elts[1]), "public")
        seed_extensions = [
            statement
            for statement in spec_tree.body
            if isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Attribute)
            and statement.value.func.attr == "extend"
            and isinstance(statement.value.func.value, ast.Name)
            and statement.value.func.value.id == "datas"
            and any(
                isinstance(node, ast.Name)
                and node.id == "PUBLIC_SEEDS"
                and isinstance(node.ctx, ast.Load)
                for node in ast.walk(statement.value)
            )
        ]
        self.assertEqual(len(seed_extensions), 1)
        seed_call = seed_extensions[0].value
        self.assertEqual(len(seed_call.args), 1)
        self.assertFalse(seed_call.keywords)
        seed_comprehension = seed_call.args[0]
        self.assertIsInstance(seed_comprehension, ast.GeneratorExp)
        self.assertEqual(len(seed_comprehension.generators), 1)
        seed_generator = seed_comprehension.generators[0]
        self.assertIsInstance(seed_generator.iter, ast.Name)
        self.assertEqual(seed_generator.iter.id, "PUBLIC_SEEDS")
        self.assertIsInstance(seed_comprehension.elt, ast.Tuple)
        self.assertEqual(ast.literal_eval(seed_comprehension.elt.elts[1]), "data")

        workflow = (
            ROOT / ".github" / "workflows" / "signed-release-artifacts.yml"
        ).read_text(encoding="utf-8")
        macos_job = workflow[
            workflow.index("  macos:\n") : workflow.index("  windows:\n")
        ]
        inspection_step = macos_job[
            macos_job.index("      - name: Build and inspect unsigned macOS content\n") :
            macos_job.index("      - name: Import protected signing identities\n")
        ]
        workflow_matches = re.findall(
            r'^          test "\$\(find dist/Mentat\.app/Contents/Resources/'
            r"(public|data) -maxdepth 1 -type f \| wc -l \| tr -d ' '\)\" = ([0-9]+)$",
            inspection_step,
            flags=re.MULTILINE,
        )
        self.assertEqual(len(workflow_matches), 2)
        self.assertEqual({directory for directory, _ in workflow_matches}, {"public", "data"})
        workflow_counts = {
            directory: int(count) for directory, count in workflow_matches
        }

        self.assertEqual(
            manifest_counts,
            {
                "PUBLIC_ASSETS": workflow_counts.get("public"),
                "PUBLIC_SEEDS": workflow_counts.get("data"),
            },
        )

    def test_signed_release_path_is_manual_protected_and_ephemeral(self):
        workflow = (
            ROOT / ".github" / "workflows" / "signed-release-artifacts.yml"
        ).read_text(encoding="utf-8")
        signing_guide = (ROOT / "RELEASE_SIGNING.md").read_text(encoding="utf-8")
        normalized_signing_guide = " ".join(signing_guide.split())
        rehearsal = (ROOT / "RELEASE_REHEARSAL.md").read_text(encoding="utf-8")

        def section(start_marker, end_marker=None):
            start = workflow.index(start_marker)
            end = workflow.index(end_marker, start) if end_marker else len(workflow)
            return workflow[start:end]

        def job_step(job, name, next_name=None):
            start_marker = f"      - name: {name}\n"
            start = job.index(start_marker)
            if next_name is None:
                return job[start:]
            end_marker = f"      - name: {next_name}\n"
            return job[start : job.index(end_marker, start)]

        scope_input = section("      validation_scope:\n", "      release_tag:\n")
        release_tag_input = section("      release_tag:\n", "\npermissions:\n")
        macos_job = section("  macos:\n", "  windows:\n")
        windows_job = section("  windows:\n", "  python-package:\n")
        python_job = section("  python-package:\n", "  macos-validation:\n")
        validation_job = section("  macos-validation:\n", "  release:\n")
        release_job = section("  release:\n")
        submission_step = job_step(
            macos_job,
            "Submit macOS package for notarization",
            "Wait for notarization and staple macOS package",
        )
        notarization_step = job_step(
            macos_job,
            "Wait for notarization and staple macOS package",
            "Smoke the exact signed macOS package",
        )
        smoke_step = job_step(
            macos_job,
            "Smoke the exact signed macOS package",
            "Upload signed macOS package",
        )
        upload_step = job_step(
            macos_job,
            "Upload signed macOS package",
            "Remove signing material",
        )
        cleanup_step = job_step(macos_job, "Remove signing material")

        self.assertIn("workflow_dispatch", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertIn("environment: beta-release", workflow)
        self.assertIn("default: full-release", scope_input)
        self.assertIn("required: true", scope_input)
        self.assertEqual(
            [
                line.removeprefix("- ")
                for line in (item.strip() for item in scope_input.splitlines())
                if line.startswith("- ")
            ],
            ["full-release", "macos-only"],
        )
        self.assertIn("required: false", release_tag_input)
        self.assertIn("Validate protected dispatch inputs", workflow)
        self.assertIn('test -n "$RELEASE_TAG"', workflow)
        self.assertIn('test -z "$RELEASE_TAG"', workflow)
        self.assertIn("Unsupported validation scope", workflow)
        self.assertEqual(
            workflow.count("github.ref == 'refs/heads/main' && github.ref_protected"),
            4,
        )
        self.assertIn(
            "if: github.ref == 'refs/heads/main' && github.ref_protected\n",
            macos_job,
        )
        full_release_guard = (
            "if: github.ref == 'refs/heads/main' && github.ref_protected "
            "&& inputs.validation_scope == 'full-release'"
        )
        self.assertIn(full_release_guard, windows_job)
        self.assertIn(full_release_guard, python_job)
        self.assertIn(
            "if: ${{ always() && inputs.validation_scope == 'macos-only' }}",
            validation_job,
        )
        self.assertIn(
            "if: ${{ always() && inputs.validation_scope == 'full-release' }}",
            release_job,
        )
        for dependency in ("release-source", "macos", "windows", "python-package"):
            self.assertIn(f"      - {dependency}\n", validation_job)
            self.assertIn(f"      - {dependency}\n", release_job)
        self.assertIn("Verify isolated macOS validation outcome", validation_job)
        self.assertIn('test "$SOURCE_RESULT" = success', validation_job)
        self.assertIn('test "$MACOS_RESULT" = success', validation_job)
        self.assertIn('test "$WINDOWS_RESULT" = skipped', validation_job)
        self.assertIn('test "$PYTHON_RESULT" = skipped', validation_job)
        self.assertNotIn("contents: write", validation_job)
        self.assertEqual(workflow.count("contents: write"), 1)
        self.assertIn("contents: write", release_job)
        self.assertEqual(workflow.count("Verify trusted source revision"), 3)
        self.assertIn("--require-hashes -r requirements-native.lock", workflow)
        self.assertEqual(workflow.count("    timeout-minutes: 360\n"), 1)
        self.assertIn("    runs-on: ${{ matrix.runner }}\n", macos_job)
        self.assertIn("      fail-fast: false\n", macos_job)
        signed_matrix = macos_job.split("      matrix:\n", 1)[1].split(
            "    timeout-minutes:", 1
        )[0]
        self.assertEqual(signed_matrix.count("          - architecture:"), 2)
        self.assertLess(
            macos_job.index("          - architecture: arm64\n            runner: macos-15\n"),
            macos_job.index("          - architecture: x86_64\n            runner: macos-15-intel\n"),
        )
        self.assertIn("    timeout-minutes: 360\n", macos_job)
        self.assertIn("    environment: beta-release\n", macos_job)
        architecture_check = macos_job.index("python scripts/verify_macos_architecture.py")
        identity_import = macos_job.index("- name: Import protected signing identities")
        self.assertLess(architecture_check, identity_import)
        self.assertIn(
            'signed_package="dist/Mentat-${display_version}-macos-${EXPECTED_MACOS_ARCHITECTURE}-signed.pkg"',
            macos_job,
        )
        self.assertIn(
            "name: mentat-macos-${{ matrix.architecture }}-signed-notarized",
            upload_step,
        )
        self.assertIn(
            "path: dist/Mentat-*-macos-${{ matrix.architecture }}-signed.pkg",
            upload_step,
        )
        self.assertIn("Reserve macOS post-work window", macos_job)
        self.assertIn("MENTAT_MACOS_NOTARY_DEADLINE_EPOCH", macos_job)
        self.assertIn("+ 18000", macos_job)
        self.assertIn(
            'python scripts/apple_notarization.py submit "$signed_package"',
            submission_step,
        )
        self.assertIn("id: submit-macos-notarization", submission_step)
        self.assertIn(
            "steps.submit-macos-notarization.outputs.submission_id",
            notarization_step,
        )
        self.assertIn(
            'python scripts/apple_notarization.py wait "$MAC_NOTARY_SUBMISSION_ID"',
            notarization_step,
        )
        self.assertNotIn("apple_notarization.py submit", notarization_step)
        self.assertNotIn("xcrun notarytool submit", notarization_step)
        self.assertNotIn("--wait", notarization_step)
        for notary_file in (
            "mentat-notary-submission.json",
            "mentat-notary-status.json",
            "mentat-notary-log.json",
        ):
            self.assertIn(f'"$RUNNER_TEMP/{notary_file}"', cleanup_step)
        self.assertNotIn("continue-on-error:", notarization_step)
        self.assertNotIn("|| true", notarization_step)
        self.assertLess(
            notarization_step.index("python scripts/apple_notarization.py wait"),
            notarization_step.index("xcrun stapler staple"),
        )
        self.assertLess(
            notarization_step.index("xcrun stapler staple"),
            notarization_step.index("xcrun stapler validate"),
        )
        self.assertLess(
            notarization_step.index("xcrun stapler validate"),
            notarization_step.index("spctl --assess --type execute"),
        )
        self.assertLess(
            notarization_step.index("spctl --assess --type execute"),
            notarization_step.index("spctl --assess --type install"),
        )
        self.assertNotIn("continue-on-error:", smoke_step)
        self.assertNotIn("\n        if:", smoke_step)
        self.assertIn("actions/upload-artifact@", upload_step)
        self.assertNotIn("continue-on-error:", upload_step)
        self.assertNotIn("\n        if:", upload_step)
        self.assertEqual(cleanup_step.count("      - name:"), 1)
        self.assertIn("        if: always()\n", cleanup_step)
        self.assertNotIn("continue-on-error:", cleanup_step)
        self.assertTrue(macos_job.rstrip().endswith(cleanup_step.rstrip()))
        self.assertIn("security import", workflow)
        self.assertIn(" -x -k ", workflow)
        self.assertIn('MAC_KEYCHAIN_PASSWORD="$(openssl rand -hex 32)"', workflow)
        self.assertNotIn("secrets.MAC_KEYCHAIN_PASSWORD", workflow)
        self.assertIn(
            "https://www.apple.com/certificateauthority/DeveloperIDG2CA.cer",
            workflow,
        )
        self.assertIn(
            "F16CD3C54C7F83CEA4BF1A3E6A0819C8AAA8E4A1528FD144715F350643D2DF3A",  # pragma: allowlist secret
            workflow,
        )
        self.assertIn('test "$actual_g2_sha256" = "$G2_SHA256"', workflow)
        self.assertIn(
            'security list-keychains -d user > "$ORIGINAL_KEYCHAINS"',
            workflow,
        )
        self.assertIn(
            "security default-keychain -d user | sed "
            "'s/^[[:space:]]*\"//; s/\"[[:space:]]*$//'",
            workflow,
        )
        self.assertIn(
            'signing_keychains=("$RUNNER_TEMP/mentat-signing.keychain-db" "$login_keychain")',
            workflow,
        )
        self.assertIn('if test "$keychain" != "$login_keychain"', workflow)
        self.assertIn(
            'security list-keychains -d user -s "${signing_keychains[@]}"',
            workflow,
        )
        self.assertIn(
            'touch "$RUNNER_TEMP/mentat-keychain-list-change-attempted"',
            workflow,
        )
        self.assertIn(
            'security list-keychains -d user -s "${original_keychains[@]}"',
            workflow,
        )
        self.assertIn(
            'security find-certificate -a -Z "$login_keychain" > "$G2_INVENTORY" || g2_inventory_status=$?',
            workflow,
        )
        self.assertIn(
            'if test "$g2_inventory_status" -ne 0 && test "$g2_inventory_status" -ne 44',
            workflow,
        )
        self.assertIn('exit "$g2_inventory_status"', workflow)
        self.assertIn('grep -qi "$g2_sha1" "$G2_INVENTORY"', workflow)
        self.assertNotIn(
            'security find-certificate -a -Z "$login_keychain" |',
            workflow,
        )
        self.assertIn(
            'touch "$RUNNER_TEMP/mentat-g2-import-attempted"',
            workflow,
        )
        self.assertIn("umask 077", workflow)
        self.assertIn('chmod 600 "$RUNNER_TEMP/mentat-signing.p12"', workflow)
        self.assertIn(
            'test "$(stat -f \'%Lp\' "$RUNNER_TEMP/mentat-signing.p12")" = "600"',
            workflow,
        )
        self.assertIn(
            'touch "$RUNNER_TEMP/mentat-signing-keychain-create-attempted"',
            workflow,
        )
        self.assertIn("security delete-certificate -Z", workflow)
        self.assertIn(
            'elif test "$cleanup_inventory_status" -ne 44',
            workflow,
        )
        self.assertIn("cleanup_status=0", workflow)
        self.assertIn('exit "$cleanup_status"', workflow)
        self.assertNotIn("mapfile", workflow)
        g2_digest_check = workflow.index(
            'test "$actual_g2_sha256" = "$G2_SHA256"'
        )
        g2_attempt = workflow.index(
            'touch "$RUNNER_TEMP/mentat-g2-import-attempted"'
        )
        g2_import = workflow.index('security import "$G2_CERT"')
        p12_permissions = workflow.index(
            'chmod 600 "$RUNNER_TEMP/mentat-signing.p12"'
        )
        keychain_attempt = workflow.index(
            'touch "$RUNNER_TEMP/mentat-signing-keychain-create-attempted"'
        )
        keychain_create = workflow.index("security create-keychain")
        list_attempt = workflow.index(
            'touch "$RUNNER_TEMP/mentat-keychain-list-change-attempted"'
        )
        list_change = workflow.index(
            'security list-keychains -d user -s "${signing_keychains[@]}"'
        )
        self.assertLess(g2_digest_check, g2_attempt)
        self.assertLess(g2_attempt, g2_import)
        self.assertLess(p12_permissions, keychain_attempt)
        self.assertLess(keychain_attempt, keychain_create)
        self.assertLess(list_attempt, list_change)
        self.assertIn("signtool.exe", workflow.lower())
        self.assertIn("id-token: write", workflow)
        self.assertIn(
            "azure/login@532459ea530d8321f2fb9bb10d1e0bcf23869a43",
            workflow,
        )
        self.assertEqual(
            workflow.count(
                "azure/artifact-signing-action@c7ab2a863ab5f9a846ddb8265964877ef296ee82"
            ),
            2,
        )
        self.assertIn("vars.AZURE_ARTIFACT_SIGNING_ENDPOINT", workflow)
        self.assertIn("timestamp-rfc3161: http://timestamp.acs.microsoft.com", workflow)
        self.assertIn(
            '& $signTool.FullName verify /pa /all /v $executable\n'
            '            if ($LASTEXITCODE -ne 0) { throw "Application '
            'signature verification failed: $executable" }',
            workflow,
        )
        self.assertIn(
            '& $signTool.FullName verify /pa /all /v $installer.FullName\n'
            '          if ($LASTEXITCODE -ne 0) { throw "Installer signature '
            'verification failed: $($installer.FullName)" }',
            workflow,
        )
        self.assertNotIn("WINDOWS_CERTIFICATE_BASE64", workflow)
        self.assertNotIn("WINDOWS_CERTIFICATE_PASSWORD", workflow)
        self.assertNotIn("Import-PfxCertificate", workflow)
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
        self.assertLess(
            release_job.index("release-input/Mentat-*-macos-arm64-signed.pkg"),
            release_job.index("release-input/Mentat-*-macos-x86_64-signed.pkg"),
        )
        self.assertIn(
            'test "$(find release-archive -maxdepth 1 -type f | wc -l | tr -d \' \')" = 8',
            release_job,
        )
        self.assertIn("Upload exact release recovery bundle", workflow)
        self.assertIn("retention-days: 14", workflow)
        self.assertIn('git push origin "refs/tags/$RELEASE_TAG"', workflow)
        self.assertEqual(cleanup_step.count("if: always()"), 1)
        self.assertNotIn("actions/checkout@v", workflow)
        self.assertNotIn("actions/setup-python@v", workflow)
        self.assertNotIn("actions/upload-artifact@v", workflow)
        self.assertNotIn("actions/download-artifact@v", workflow)
        self.assertIn("[RELEASE_SIGNING.md](RELEASE_SIGNING.md)", rehearsal)
        self.assertIn(
            "repo:hazeion/agent-os:environment:beta-release",
            signing_guide,
        )
        self.assertIn("https://token.actions.githubusercontent.com", signing_guide)
        self.assertIn("api://AzureADTokenExchange", signing_guide)
        self.assertIn("Developer ID G2", signing_guide)
        self.assertIn(
            "F16CD3C54C7F83CEA4BF1A3E6A0819C8AAA8E4A1528FD144715F350643D2DF3A",  # pragma: allowlist secret
            signing_guide,
        )
        self.assertIn("Entity type: **Environment**", signing_guide)
        self.assertIn("service principal exists", normalized_signing_guide)
        self.assertIn("**Selected branches and tags**", signing_guide)
        self.assertIn("exactly one allowed branch: `main`", normalized_signing_guide)
        self.assertIn("four hours", normalized_signing_guide)
        self.assertIn("continues processing", normalized_signing_guide)
        self.assertIn("Do not immediately rerun", signing_guide)
        for name in (
            "MAC_CERTIFICATES_BASE64",
            "MAC_CERTIFICATES_PASSWORD",
            "MAC_APPLICATION_IDENTITY",
            "MAC_INSTALLER_IDENTITY",
            "MAC_NOTARY_APPLE_ID",
            "MAC_NOTARY_PASSWORD",
            "MAC_NOTARY_TEAM_ID",
            "AZURE_CLIENT_ID",
            "AZURE_TENANT_ID",
            "AZURE_SUBSCRIPTION_ID",
            "AZURE_ARTIFACT_SIGNING_ENDPOINT",
            "AZURE_ARTIFACT_SIGNING_ACCOUNT",
            "AZURE_ARTIFACT_SIGNING_PROFILE",
        ):
            self.assertIn(f"`{name}`", signing_guide)

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

    def test_connection_cli_has_no_api_key_value_argument(self):
        parser = cli.build_parser()
        self.assertNotIn(
            "--api-key",
            {
                option
                for action in parser._actions
                for option in action.option_strings
            },
        )
        configured = parser.parse_args(
            [
                "connection",
                "configure-remote",
                "--endpoint",
                "https://hermes.example",
                "--api-key-env",
                "MENTAT_REMOTE_HERMES_API_KEY",
            ]
        )
        self.assertFalse(hasattr(configured, "api_key"))

    def test_connection_status_and_two_step_local_confirmation_are_secret_free(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "operator-data"
            status_output = io.StringIO()
            with redirect_stdout(status_output):
                self.assertEqual(
                    cli.main(
                        [
                            "connection",
                            "status",
                            "--data-dir",
                            str(data_root),
                        ]
                    ),
                    0,
                )
            status = json.loads(status_output.getvalue())
            self.assertEqual(status["selection"]["mode"], "local")
            self.assertFalse(status["selection"]["remembered_remote"])
            self.assertNotIn(str(data_root), status_output.getvalue())

            preview_output = io.StringIO()
            with patch.object(cli.sys.stdin, "isatty", return_value=False):
                with redirect_stdout(preview_output):
                    self.assertEqual(
                        cli.main(
                            [
                                "connection",
                                "use",
                                "local",
                                "--data-dir",
                                str(data_root),
                            ]
                        ),
                        3,
                    )
            preview = json.loads(preview_output.getvalue())
            token = preview["confirmation_token"]
            self.assertRegex(token, r"^[0-9a-f]{64}$")
            confirmed_output = io.StringIO()
            with patch.object(cli, "_connection_server_running", return_value=False):
                with redirect_stdout(confirmed_output):
                    self.assertEqual(
                        cli.main(
                            [
                                "connection",
                                "use",
                                "local",
                                "--data-dir",
                                str(data_root),
                                "--confirm",
                                token,
                            ]
                        ),
                        0,
                    )
            confirmed = json.loads(confirmed_output.getvalue())
            self.assertTrue(confirmed["ok"])
            self.assertEqual(confirmed["selection"]["mode"], "local")

    def test_connection_mutation_refuses_while_server_is_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "operator-data"
            preview = remote_hermes.preview_remembered_connection(data_root, "local")
            token = remote_hermes.offline_confirmation_token(preview)
            output = io.StringIO()
            with patch.object(cli, "_connection_server_running", return_value=True):
                with patch.object(
                    remote_hermes,
                    "confirm_remembered_connection",
                    side_effect=AssertionError("must not mutate"),
                ):
                    with redirect_stdout(output):
                        self.assertEqual(
                            cli.main(
                                [
                                    "connection",
                                    "use",
                                    "local",
                                    "--data-dir",
                                    str(data_root),
                                    "--confirm",
                                    token,
                                ]
                            ),
                            2,
                        )
            payload = json.loads(output.getvalue())
            self.assertEqual(
                payload["error_code"],
                "connection_change_server_running",
            )

    def test_configure_remote_reads_environment_and_never_prints_private_values(self):
        secret = "cli-remote-secret-NEVER-PRINT-12345"
        endpoint = "https://private-hermes.example"
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "operator-data"
            argv = [
                "connection",
                "configure-remote",
                "--endpoint",
                endpoint,
                "--label",
                "Workshop remote",
                "--api-key-env",
                "MENTAT_REMOTE_HERMES_API_KEY",
                "--data-dir",
                str(data_root),
            ]
            preview_output = io.StringIO()
            with patch.dict(
                os.environ,
                {"MENTAT_REMOTE_HERMES_API_KEY": secret},
            ):
                with patch.object(cli.sys.stdin, "isatty", return_value=False):
                    with redirect_stdout(preview_output):
                        self.assertEqual(cli.main(argv), 3)
            serialized = preview_output.getvalue()
            self.assertNotIn(secret, serialized)
            self.assertNotIn(endpoint, serialized)
            self.assertNotIn(str(data_root), serialized)
            token = json.loads(serialized)["confirmation_token"]

            result = {
                "status": "selected",
                "selection": {
                    "mode": "remote",
                    "label": "Workshop remote",
                    "binding_id": "b" * 32,
                    "configured": True,
                },
                "discovery": {"trusted": True, "status": "healthy"},
            }
            confirmed_output = io.StringIO()
            with patch.dict(
                os.environ,
                {"MENTAT_REMOTE_HERMES_API_KEY": secret},
            ):
                with patch.object(
                    cli,
                    "_connection_server_running",
                    return_value=False,
                ):
                    with patch.object(
                        remote_hermes,
                        "confirm_connection_from_source",
                        return_value=result,
                    ):
                        with redirect_stdout(confirmed_output):
                            self.assertEqual(
                                cli.main([*argv, "--confirm", token]),
                                0,
                            )
            self.assertNotIn(secret, confirmed_output.getvalue())
            self.assertNotIn(endpoint, confirmed_output.getvalue())

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

    def test_setup_reports_an_exact_launch_command_and_planner_only_path(self):
        args = cli.build_parser().parse_args(["setup"])
        output = io.StringIO()
        with patch.object(
            cli,
            "_load_config",
            return_value=(None, SimpleNamespace()),
        ):
            with patch.object(
                server,
                "prepare_data_root_for_startup",
                return_value=None,
            ):
                with redirect_stdout(output):
                    self.assertEqual(cli.run_setup(args), 0)

        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["next_command"], "mentat start --open-browser")
        self.assertFalse(payload["repeat_setup_options"])
        self.assertIn("planning features without Hermes", payload["message"])
        self.assertNotIn("`mentat start` to open", payload["message"])

    def test_setup_custom_runtime_options_are_repeated_without_echoing_values(self):
        private_root = "/private/operator/data"
        args = cli.build_parser().parse_args(
            ["setup", "--data-dir", private_root, "--port", "8894"]
        )
        output = io.StringIO()
        with patch.object(
            cli,
            "_load_config",
            return_value=(None, SimpleNamespace()),
        ):
            with patch.object(
                server,
                "prepare_data_root_for_startup",
                return_value=None,
            ):
                with redirect_stdout(output):
                    self.assertEqual(cli.run_setup(args), 0)

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["next_command"], "mentat start --open-browser")
        self.assertTrue(payload["repeat_setup_options"])
        self.assertIn("with the same setup options", payload["message"])
        self.assertNotIn(private_root, output.getvalue())
        self.assertNotIn("8894", output.getvalue())

    def test_start_runs_preflight_before_the_node_gateway(self):
        args = cli.build_parser().parse_args(["start", "--port", "8891"])
        with patch.object(cli, "run_lifecycle", return_value=0) as preflight:
            with patch.object(
                cli,
                "_load_config",
                return_value=(None, SimpleNamespace(host="127.0.0.1", port=8891, data_dir=Path("/private/mentat"))),
            ):
                with patch.object(web_runtime, "run_gateway", return_value=0) as gateway:
                    self.assertEqual(cli.run_start(args), 0)
        preflight.assert_called_once_with("preflight", args)
        self.assertEqual(gateway.call_args.kwargs["host"], "127.0.0.1")
        self.assertEqual(gateway.call_args.kwargs["port"], 8891)
        self.assertEqual(gateway.call_args.kwargs["data_dir"], Path("/private/mentat"))
        self.assertEqual(gateway.call_args.kwargs["runtime_environment"]["MENTAT_LAUNCHER_PID"], str(os.getpid()))

    def test_native_start_opens_browser_only_after_health_is_ready(self):
        args = cli.build_parser().parse_args(
            ["start", "--legacy-ui", "--open-browser", "--port", "8895"]
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

    def test_frozen_start_uses_the_node_gateway_not_the_legacy_server(self):
        args = cli.build_parser().parse_args(["start", "--port", "8895"])
        with patch.object(cli.sys, "frozen", True, create=True):
            with patch.object(cli, "run_lifecycle", return_value=0):
                with patch.object(
                    cli,
                    "_load_config",
                    return_value=(None, SimpleNamespace(host="127.0.0.1", port=8895, data_dir=Path("/private/mentat"))),
                ):
                    with patch.object(web_runtime, "run_gateway", return_value=0) as gateway:
                        self.assertEqual(cli.run_start(args), 0)
        self.assertEqual(gateway.call_args.kwargs["port"], 8895)


if __name__ == "__main__":
    unittest.main()
