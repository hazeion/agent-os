import unittest
from pathlib import Path
import tarfile

from scripts.check_tracked_secrets import new_candidates
from scripts.verify_release_checks import (
    REQUIRED_WORKFLOWS,
    latest_completed_run,
    latest_named_job,
)
from scripts.verify_python_artifacts import (
    PUBLIC_DATA_FILES,
    PUBLIC_MODULES,
    PUBLIC_PACKAGES,
    _parent_directories,
    _safe_names,
    _special_tar_members,
    _source_files,
    _wheel_files,
)


ROOT = Path(__file__).resolve().parents[1]


class CiQualityGateTests(unittest.TestCase):
    def test_main_matrix_uses_fixed_runners_and_immutable_actions(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        for runner in ("ubuntu-24.04", "macos-15-intel", "windows-2025"):
            self.assertIn(runner, workflow)
        self.assertIn("name: CI required", workflow)
        self.assertIn("needs:\n      - test\n      - windows-test", workflow)
        for floating in (
            "ubuntu-latest",
            "macos-latest",
            "windows-latest",
            "actions/checkout@v",
            "actions/setup-python@v",
            "actions/setup-node@v",
        ):
            self.assertNotIn(floating, workflow)
        self.assertEqual(workflow.count("actions/checkout@8e8c483"), 2)
        self.assertEqual(workflow.count("actions/setup-python@a309ff8"), 2)
        self.assertEqual(workflow.count("actions/setup-node@53b8394"), 2)
        self.assertEqual(workflow.count("node-version: 24.18.0"), 2)
        self.assertNotIn("pip install --upgrade pip", workflow)

    def test_main_matrix_keeps_read_only_permissions_and_safe_triggers(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("pull_request:", workflow)
        self.assertIn("push:\n    branches:\n      - main", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("${{ secrets.", workflow)

    def test_package_and_browser_gates_are_fixed_and_secret_free(self):
        workflow = (ROOT / ".github" / "workflows" / "quality-gates.yml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 4)
        self.assertEqual(workflow.count("python-version: \"3.13.14\""), 3)
        self.assertIn("node-version: 24.18.0", workflow)
        self.assertIn("--require-hashes -r requirements-native.lock", workflow)
        self.assertIn("--require-hashes -r requirements-quality.lock", workflow)
        self.assertIn("python scripts/verify_python_artifacts.py dist", workflow)
        self.assertIn("python -m build --no-isolation", workflow)
        self.assertIn("mentat-package-smoke", workflow)
        self.assertIn("python -m pipx install dist/*.whl", workflow)
        self.assertIn('PIPX_BIN_DIR="$smoke_root/bin"', workflow)
        self.assertIn("Installed Mentat remained healthy after stop", workflow)
        self.assertIn("node scripts/browser_smoke.mjs", workflow)
        self.assertIn("MENTAT_DATA_DIR=\"$RUNNER_TEMP/mentat-browser-data\"", workflow)
        self.assertIn("CHROME_PATH: /usr/bin/google-chrome", workflow)
        self.assertIn(
            "MENTAT_BROWSER_RUNTIME_DIR: ${{ runner.temp }}/browser-smoke-runtime",
            workflow,
        )
        self.assertIn("--require-hashes -r requirements-quality.lock", workflow)
        self.assertIn("pip_audit -r requirements.txt --strict", workflow)
        self.assertIn("pip_audit -r requirements-native.lock --strict", workflow)
        self.assertIn("python scripts/check_tracked_secrets.py", workflow)
        self.assertIn("name: Quality gates required", workflow)
        self.assertIn("PACKAGE_RESULT: ${{ needs.python-package.result }}", workflow)
        self.assertNotIn("${{ secrets.", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("@v", workflow)

    def test_native_gate_has_a_stable_required_result(self):
        workflow = (ROOT / ".github" / "workflows" / "native-artifacts.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("name: Native artifacts required", workflow)
        self.assertIn("BUILD_RESULT: ${{ needs.build.result }}", workflow)
        self.assertIn('run: test "$BUILD_RESULT" = success', workflow)
        self.assertIn("push:\n    branches:\n      - main", workflow)

    def test_signed_release_is_fail_closed_and_is_the_only_tag_creator(self):
        workflow = (
            ROOT / ".github" / "workflows" / "signed-release-artifacts.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("release_tag:", workflow)
        self.assertIn("name: Verify protected release source", workflow)
        self.assertIn("python scripts/verify_release_checks.py", workflow)
        self.assertIn("name: Signed release and tag required", workflow)
        self.assertIn("if: ${{ always() }}", workflow)
        self.assertIn("MACOS_RESULT: ${{ needs.macos.result }}", workflow)
        self.assertIn("WINDOWS_RESULT: ${{ needs.windows.result }}", workflow)
        self.assertIn('git push origin "refs/tags/$RELEASE_TAG"', workflow)

    def test_release_check_payload_requires_every_stable_success(self):
        sha = "a" * 40
        payload = {"workflow_runs": [
            {"id": 1, "head_sha": sha, "event": "push", "status": "completed", "conclusion": "success"},
            {"id": 2, "head_sha": sha, "event": "push", "status": "completed", "conclusion": "failure"},
            {"id": 99, "head_sha": sha, "event": "pull_request", "status": "completed", "conclusion": "success"},
        ]}
        self.assertEqual(latest_completed_run(payload, sha)["id"], 2)
        jobs = {"jobs": [
            {"id": 5, "name": "CI required", "status": "completed", "conclusion": "success"},
            {"id": 6, "name": "CI required", "status": "completed", "conclusion": "failure"},
        ]}
        self.assertEqual(latest_named_job(jobs, "CI required")["id"], 6)
        self.assertEqual(
            set(REQUIRED_WORKFLOWS.values()),
            {"CI required", "Native artifacts required", "Quality gates required"},
        )

    def test_artifact_allowlists_exclude_private_and_test_content(self):
        self.assertEqual(PUBLIC_PACKAGES, {"mentat"})
        self.assertIn("server", PUBLIC_MODULES)
        self.assertEqual(set(PUBLIC_DATA_FILES), {"share/mentat/public", "share/mentat/data"})
        for names in (_source_files(), _wheel_files()):
            self.assertFalse(any(name.startswith("tests/") for name in names))
            self.assertFalse(any("data/private" in name for name in names))
            self.assertFalse(any("data/runtime" in name for name in names))
            self.assertFalse(any("mentat.local.toml" in name for name in names))

    def test_artifact_name_validation_rejects_duplicates_and_traversal(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            _safe_names(["safe.txt", "safe.txt"], label="fixture")
        with self.assertRaisesRegex(ValueError, "unsafe"):
            _safe_names(["../private.txt"], label="fixture")
        self.assertEqual(
            _parent_directories({"root/child/file.txt", "top.txt"}),
            {"root", "root/child"},
        )
        fifo = tarfile.TarInfo("mentat_local-0.1.0b1/private-pipe")
        fifo.type = tarfile.FIFOTYPE
        self.assertEqual(
            _special_tar_members([fifo]),
            ["mentat_local-0.1.0b1/private-pipe"],
        )

    def test_secret_comparison_reports_only_new_fingerprints(self):
        baseline = {
            "results": {
                "safe.py": [{
                    "type": "Secret Keyword",
                    "hashed_secret": "reviewed",
                    "line_number": 1,
                }]
            }
        }
        current = {
            "results": {
                "safe.py": [{
                    "type": "Secret Keyword",
                    "hashed_secret": "reviewed",
                    "line_number": 4,
                }],
                "new.py": [{
                    "type": "Private Key",
                    "hashed_secret": "new-fingerprint",
                    "line_number": 9,
                }],
            }
        }
        self.assertEqual(
            new_candidates(current, baseline), [("new.py", "Private Key", 9)]
        )
        current["results"]["safe.py"].append({
            "type": "Secret Keyword",
            "hashed_secret": "reviewed",
            "line_number": 12,
        })
        self.assertIn(
            ("safe.py", "Secret Keyword", 12), new_candidates(current, baseline)
        )


if __name__ == "__main__":
    unittest.main()
