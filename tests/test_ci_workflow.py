from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SHARD_RUNNER = ROOT / "scripts" / "run_unittest_shards.py"
ROADMAP = (ROOT / "ROAD_TO_BETA.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


class CiWorkflowContractTests(unittest.TestCase):
    def workflow(self) -> str:
        self.assertTrue(WORKFLOW.exists(), "The early CI workflow must exist")
        return WORKFLOW.read_text(encoding="utf-8")

    def test_runs_for_pull_requests_and_main_pushes(self):
        workflow = self.workflow()

        self.assertIn("on:\n  pull_request:\n  push:\n    branches:\n      - main", workflow)

    def test_declares_the_complete_os_and_python_matrix(self):
        workflow = self.workflow()

        for runner in ("ubuntu-latest", "macos-latest", "windows-latest"):
            self.assertEqual(workflow.count(f"          - {runner}"), 1)
        for version in ("3.11", "3.12", "3.13"):
            self.assertEqual(workflow.count(f'          - "{version}"'), 1)
        self.assertIn("runs-on: ${{ matrix.os }}", workflow)
        self.assertIn("python-version: ${{ matrix.python-version }}", workflow)
        self.assertIn("fail-fast: false", workflow)
        self.assertNotIn("\n        include:", workflow)
        self.assertNotIn("\n        exclude:", workflow)

    def test_uses_fixed_official_toolchain_actions_and_pinned_dependencies(self):
        workflow = self.workflow()

        self.assertIn("uses: actions/checkout@v6", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("uses: actions/setup-python@v6", workflow)
        self.assertIn("uses: actions/setup-node@v7", workflow)
        self.assertIn("node-version: 24", workflow)
        self.assertIn("python -m pip install -r requirements.txt", workflow)
        action_uses = [
            line.strip()
            for line in workflow.splitlines()
            if line.strip().startswith("uses:")
        ]
        self.assertEqual(
            action_uses,
            [
                "uses: actions/checkout@v6",
                "uses: actions/setup-python@v6",
                "uses: actions/setup-node@v7",
            ],
        )

    def test_every_job_runs_all_agreed_checks(self):
        workflow = self.workflow()

        for command in (
            "python -m compileall -q .",
            "python -m unittest discover -s tests -v",
        ):
            self.assertEqual(workflow.count(command), 1)
        for command in (
            "node --check public/core.js",
            "node --check public/app.js",
            "node --check scripts/browser_smoke.mjs",
        ):
            self.assertEqual(workflow.count(f"run: {command}"), 1)
        self.assertEqual(workflow.count("python scripts/run_unittest_shards.py"), 1)
        self.assertIn("if: runner.os != 'Windows'", workflow)
        self.assertIn("if: runner.os == 'Windows'", workflow)

    def test_windows_shards_cover_each_test_module_exactly_once(self):
        self.assertTrue(SHARD_RUNNER.exists())
        namespace: dict[str, object] = {
            "__name__": "ci_shard_contract",
            "__file__": str(SHARD_RUNNER),
        }
        exec(SHARD_RUNNER.read_text(encoding="utf-8"), namespace)

        modules = namespace["test_modules"]()
        shards = namespace["partition_modules"](modules)
        flattened = tuple(module for shard in shards for module in shard)

        def suite_modules(suite):
            selected = set()
            for item in suite:
                if isinstance(item, unittest.TestSuite):
                    selected.update(suite_modules(item))
                else:
                    module = item.__class__.__module__
                    self.assertNotEqual(module, "unittest.loader")
                    selected.add(
                        module if module.startswith("tests.") else f"tests.{module}"
                    )
            return selected

        discovered = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
        expected = tuple(sorted(suite_modules(discovered)))
        self.assertEqual(tuple(sorted(flattened)), expected)
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(namespace["SHARD_COUNT"], 3)
        self.assertEqual(len(shards), 3)
        self.assertTrue(all(shards))

        with TemporaryDirectory() as temporary:
            sample = Path(temporary)
            (sample / "testroot.py").touch()
            package = sample / "package"
            package.mkdir()
            (package / "__init__.py").touch()
            (package / "test_nested.py").touch()
            nonpackage = sample / "nonpackage"
            nonpackage.mkdir()
            (nonpackage / "test_hidden.py").touch()
            invalid_package = sample / "bad-package"
            invalid_package.mkdir()
            (invalid_package / "__init__.py").touch()
            (invalid_package / "test_hidden.py").touch()
            selected = namespace["discoverable_test_paths"](sample)
            self.assertEqual(
                tuple(path.relative_to(sample).as_posix() for path in selected),
                (
                    "bad-package/test_hidden.py",
                    "package/test_nested.py",
                    "testroot.py",
                ),
            )

    def test_workflow_is_read_only_and_secret_free(self):
        workflow = self.workflow()
        lowered = workflow.lower()

        self.assertEqual(workflow.count("permissions:"), 1)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn(": write", lowered)
        self.assertIsNone(re.search(r"\bsecrets\s*(?:\.|\[)", lowered))
        for forbidden in (
            "pull_request_target:",
            "write-all",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_project_records_describe_only_the_early_guardrail(self):
        self.assertIn("Implemented by `.github/workflows/ci.yml`", ROADMAP)
        self.assertIn("all nine OS/Python combinations", ROADMAP)
        self.assertIn(
            "Finish Milestone 1",
            ROADMAP.split("## Current next actions", 1)[1],
        )
        self.assertIn(
            "upgrade and uninstall-data-preservation",
            ROADMAP.split("## Current next actions", 1)[1],
        )
        self.assertNotIn("Land the early CI guardrail", ROADMAP)
        self.assertIn("Added the early GitHub Actions guardrail", CHANGELOG)
        self.assertIn("does not yet add packaging", CHANGELOG)


if __name__ == "__main__":
    unittest.main()
