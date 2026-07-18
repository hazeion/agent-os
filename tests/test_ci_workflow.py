from collections import Counter
from pathlib import Path
import re
import sys
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
        method_sys_path = list(sys.path)
        self.addCleanup(sys.path.__setitem__, slice(None), method_sys_path)
        self.assertTrue(SHARD_RUNNER.exists())
        namespace: dict[str, object] = {
            "__name__": "ci_shard_contract",
            "__file__": str(SHARD_RUNNER),
        }
        exec(SHARD_RUNNER.read_text(encoding="utf-8"), namespace)

        modules = namespace["test_modules"]()
        weighted = namespace["weighted_modules"](modules)
        shards = namespace["partition_modules"](weighted)
        flattened = tuple(module for shard in shards for module in shard)

        def suite_ids(suite):
            selected = []
            for item in suite:
                if isinstance(item, unittest.TestSuite):
                    selected.extend(suite_ids(item))
                else:
                    selected.append(item.id())
            return selected

        loader = unittest.TestLoader()
        discovered = loader.discover(str(ROOT / "tests"))
        self.assertEqual(loader.errors, [])
        expected_ids = Counter(suite_ids(discovered))
        sharded_ids = Counter()
        for module in modules:
            sharded_ids.update(suite_ids(namespace["_discover_module"](module)))
        self.assertEqual(sharded_ids, expected_ids)
        expected_modules = tuple(
            f"tests.{path.stem}"
            for path in sorted((ROOT / "tests").glob("test*.py"))
            if re.fullmatch(r"[_a-zA-Z]\w*\.py", path.name)
        )
        self.assertEqual(tuple(sorted(flattened)), expected_modules)
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(tuple(module for module, _count in weighted), modules)
        self.assertTrue(all(count >= 0 for _module, count in weighted))
        self.assertEqual(namespace["SHARD_COUNT"], 6)
        self.assertEqual(len(shards), 6)
        self.assertTrue(all(shards))
        self.assertEqual(
            namespace["partition_modules"](
                (
                    ("tests.a", 8),
                    ("tests.b", 7),
                    ("tests.c", 6),
                    ("tests.d", 5),
                    ("tests.e", 4),
                    ("tests.f", 3),
                    ("tests.g", 2),
                ),
                3,
            ),
            (
                ("tests.a", "tests.f", "tests.g"),
                ("tests.b", "tests.e"),
                ("tests.c", "tests.d"),
            ),
        )

        with TemporaryDirectory() as temporary:
            sample = Path(temporary)
            (sample / "testroot.py").touch()
            nonpackage = sample / "nonpackage"
            nonpackage.mkdir()
            (nonpackage / "test_hidden.py").touch()
            selected = namespace["discoverable_test_paths"](sample)
            self.assertEqual(
                tuple(path.relative_to(sample).as_posix() for path in selected),
                ("testroot.py",),
            )
            (sample / "test_skip.py").write_text(
                "import unittest\nraise unittest.SkipTest('not on this platform')\n",
                encoding="utf-8",
            )
            (sample / "test_load_pattern.py").write_text(
                "import os\n"
                "def load_tests(loader, tests, pattern):\n"
                "    if pattern != 'test*.py':\n"
                "        raise RuntimeError(pattern)\n"
                "    root = os.path.join(os.path.dirname(__file__), 'external')\n"
                "    return loader.discover(root, pattern=pattern, top_level_dir=root)\n",
                encoding="utf-8",
            )
            external = sample / "external"
            external.mkdir()
            (external / "test_nested.py").write_text(
                "import unittest\n"
                "class NestedTest(unittest.TestCase):\n"
                "    def test_nested(self):\n"
                "        pass\n",
                encoding="utf-8",
            )
            original_tests = namespace["TESTS"]
            original_sys_path = list(sys.path)
            namespace["TESTS"] = sample
            try:
                self.assertEqual(
                    namespace["_discover_module"]("tests.testroot").countTestCases(),
                    0,
                )
                skipped_suite = namespace["_discover_module"]("tests.test_skip")
                result = unittest.TestResult()
                skipped_suite.run(result)
                self.assertTrue(result.wasSuccessful())
                self.assertEqual(len(result.skipped), 1)
                self.assertEqual(
                    namespace["_discover_module"](
                        "tests.test_load_pattern"
                    ).countTestCases(),
                    1,
                )
            finally:
                namespace["TESTS"] = original_tests
                sys.path[:] = original_sys_path
                for module in (
                    "testroot",
                    "test_skip",
                    "test_load_pattern",
                    "test_nested",
                ):
                    sys.modules.pop(module, None)
            package = sample / "package"
            package.mkdir()
            (package / "__init__.py").touch()
            (package / "test_nested.py").touch()
            with self.assertRaisesRegex(RuntimeError, "package-style"):
                namespace["discoverable_test_paths"](sample)

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
