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

        for runner in ("ubuntu-latest", "macos-latest"):
            self.assertEqual(workflow.count(f"          - {runner}"), 1)
        for version in ("3.11", "3.12", "3.13"):
            self.assertEqual(workflow.count(f'          - "{version}"'), 2)
        self.assertIn("runs-on: ${{ matrix.os }}", workflow)
        self.assertEqual(workflow.count("runs-on: windows-latest"), 1)
        self.assertIn("python-version: ${{ matrix.python-version }}", workflow)
        self.assertEqual(workflow.count("fail-fast: false"), 2)
        self.assertIn(
            "group:\n          - 0\n          - 1\n          - 2\n"
            "          - 3\n          - 4\n          - 5\n"
            "          - 6\n          - 7\n          - 8\n"
            "          - 9\n          - 10\n          - 11",
            workflow,
        )
        self.assertIn(
            "windows-latest / Python ${{ matrix.python-version }} / "
            "group ${{ matrix.group }}",
            workflow,
        )
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
                "uses: actions/checkout@v6",
                "uses: actions/setup-python@v6",
                "uses: actions/setup-node@v7",
            ],
        )

    def test_every_job_runs_all_agreed_checks(self):
        workflow = self.workflow()

        self.assertEqual(workflow.count("python -m compileall -q ."), 2)
        self.assertEqual(
            workflow.count("python -m unittest discover -s tests -v"),
            1,
        )
        for command in (
            "node --check public/core.js",
            "node --check public/app.js",
            "node --check scripts/browser_smoke.mjs",
        ):
            self.assertEqual(workflow.count(f"run: {command}"), 2)
        self.assertEqual(
            workflow.count(
                "python scripts/run_unittest_shards.py --run-group "
                "${{ matrix.group }}"
            ),
            1,
        )
        self.assertEqual(workflow.count("Run bounded Windows test group"), 1)
        self.assertNotIn("if: runner.os", workflow)

    def test_windows_shards_cover_each_test_exactly_once(self):
        method_sys_path = list(sys.path)
        self.addCleanup(sys.path.__setitem__, slice(None), method_sys_path)
        self.assertTrue(SHARD_RUNNER.exists())
        namespace: dict[str, object] = {
            "__name__": "ci_shard_contract",
            "__file__": str(SHARD_RUNNER),
        }
        exec(SHARD_RUNNER.read_text(encoding="utf-8"), namespace)

        modules = namespace["test_modules"]()
        weighted = namespace["weighted_units"](modules)
        shards = namespace["partition_units"](weighted)
        flattened = tuple(unit for shard in shards for unit in shard)

        def suite_ids(suite):
            selected = []
            for item in suite:
                if isinstance(item, unittest.TestSuite):
                    selected.extend(suite_ids(item))
                else:
                    selected.append(namespace["_canonical_test_id"](item))
            return selected

        loader = unittest.TestLoader()
        discovered = loader.discover(str(ROOT / "tests"))
        self.assertEqual(loader.errors, [])
        expected_ids = Counter(suite_ids(discovered))
        self.assertEqual(
            Counter(flattened),
            Counter(unit for unit, _weight in weighted),
        )
        sharded_ids = Counter()
        covered_modules = set()
        for shard in shards:
            sharded_ids.update(suite_ids(namespace["_build_shard_suite"](shard)))
            for unit in shard:
                if unit.startswith(namespace["MODULE_UNIT_PREFIX"]):
                    covered_modules.add(
                        unit.removeprefix(namespace["MODULE_UNIT_PREFIX"])
                    )
                else:
                    self.assertTrue(unit.startswith(namespace["TEST_UNIT_PREFIX"]))
                    identifier = unit.removeprefix(namespace["TEST_UNIT_PREFIX"])
                    covered_modules.add(namespace["_split_module_for_id"](identifier))
        self.assertEqual(sharded_ids, expected_ids)
        expected_modules = tuple(
            f"tests.{path.stem}"
            for path in sorted((ROOT / "tests").glob("test*.py"))
            if re.fullmatch(r"[_a-zA-Z]\w*\.py", path.name)
        )
        self.assertEqual(tuple(sorted(covered_modules)), expected_modules)
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertTrue(all(count >= 0 for _unit, count in weighted))
        shard_totals = [
            sum(dict(weighted)[unit] for unit in shard)
            for shard in shards
        ]
        self.assertLessEqual(
            max(shard_totals) - min(shard_totals),
            namespace["SPLIT_TEST_WEIGHT"],
        )
        self.assertEqual(namespace["SHARD_COUNT"], 12)
        self.assertEqual(namespace["SHARD_GROUP_COUNT"], 12)
        self.assertEqual(namespace["MAX_CONCURRENT_SHARDS"], 4)
        self.assertEqual(namespace["PROCESS_STOP_TIMEOUT_SECONDS"], 5)
        self.assertEqual(
            namespace["ISOLATED_PROCESS_GROUP_FLAGS"],
            getattr(namespace["subprocess"], "CREATE_NEW_PROCESS_GROUP", 0),
        )
        self.assertEqual(len(shards), 12)
        self.assertTrue(all(shards))
        groups = namespace["shard_groups"](shards)
        self.assertEqual(len(groups), 12)
        self.assertTrue(all(len(group) == 1 for group in groups))
        self.assertEqual(
            Counter(shard for group in groups for shard in group),
            Counter(shards),
        )
        self.assertEqual(
            sum(
                namespace["_build_shard_suite"](
                    tuple(unit for shard in group for unit in shard)
                ).countTestCases()
                for group in groups
            ),
            sum(namespace["_build_shard_suite"](shard).countTestCases() for shard in shards),
        )
        for module in namespace["SPLITTABLE_MODULES"]:
            source = (ROOT / Path(*module.split("."))).with_suffix(".py").read_text(
                encoding="utf-8"
            )
            self.assertIsNone(
                re.search(
                    r"\b(?:addClassCleanup|enterClassContext|"
                    r"addModuleCleanup|enterModuleContext)\b",
                    source,
                )
            )
        self.assertEqual(
            namespace["partition_units"](
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
            (sample / "test_class_cleanup.py").write_text(
                "import unittest\n"
                "class CleanupTest(unittest.TestCase):\n"
                "    def test_cleanup(self):\n"
                "        pass\n"
                "    @classmethod\n"
                "    def doClassCleanups(cls):\n"
                "        return super().doClassCleanups()\n"
                "CleanupTest.addClassCleanup(lambda: None)\n",
                encoding="utf-8",
            )
            (sample / "test_module_cleanup_alias.py").write_text(
                "import unittest\n"
                "cleanup = unittest.addModuleCleanup\n"
                "cleanup(lambda: None)\n"
                "class CleanupTest(unittest.TestCase):\n"
                "    def test_cleanup(self):\n"
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
                cleanup_suite = namespace["_discover_module"](
                    "tests.test_class_cleanup"
                )
                with self.assertRaisesRegex(RuntimeError, "has cleanups"):
                    namespace["_split_tests"](
                        "tests.test_class_cleanup", cleanup_suite
                    )
                cleanup_case = next(namespace["_tests_in"](cleanup_suite))
                cleanup_case.__class__._class_cleanups.clear()
                with self.assertRaisesRegex(RuntimeError, "has fixtures"):
                    namespace["_split_tests"](
                        "tests.test_class_cleanup", cleanup_suite
                    )
                module_cleanups_before = list(unittest.case._module_cleanups)
                with self.assertRaisesRegex(RuntimeError, "module has cleanups"):
                    namespace["_discover_split_tests"](
                        "tests.test_module_cleanup_alias"
                    )
                self.assertEqual(unittest.case._module_cleanups, module_cleanups_before)
            finally:
                namespace["TESTS"] = original_tests
                sys.path[:] = original_sys_path
                for module in (
                    "testroot",
                    "test_skip",
                    "test_load_pattern",
                    "test_nested",
                    "test_class_cleanup",
                    "test_module_cleanup_alias",
                ):
                    sys.modules.pop(module, None)
            package = sample / "package"
            package.mkdir()
            (package / "__init__.py").touch()
            (package / "test_nested.py").touch()
            with self.assertRaisesRegex(RuntimeError, "package-style"):
                namespace["discoverable_test_paths"](sample)

        class FakeProcess:
            active = 0
            max_active = 0

            def __init__(self, result=0, polls_until_done=2):
                self.result = result
                self.polls_until_done = polls_until_done
                self.polls = 0
                self.done = False
                self.terminated = False
                self.waited = False
                self.killed = False
                self.pid = 4321 + FakeProcess.active
                FakeProcess.active += 1
                FakeProcess.max_active = max(FakeProcess.max_active, FakeProcess.active)

            def poll(self):
                if self.done:
                    return self.result
                self.polls += 1
                if self.polls < self.polls_until_done:
                    return None
                self.done = True
                FakeProcess.active -= 1
                return self.result

            def terminate(self):
                self.terminated = True
                if not self.done:
                    self.done = True
                    FakeProcess.active -= 1

            def wait(self, timeout=None):
                if not self.done:
                    self.done = True
                    FakeProcess.active -= 1
                self.waited = True
                return self.result

            def kill(self):
                self.killed = True
                self.terminate()

        group_spawned = []
        original_spawn = namespace["_spawn_shard"]
        namespace["_spawn_shard"] = (
            lambda shard: group_spawned.append(
                FakeProcess(result=1 if len(group_spawned) == 1 else 0)
            )
            or group_spawned[-1]
        )
        try:
            self.assertEqual(namespace["run_group"]((shards[0],)), 1)
        finally:
            namespace["_spawn_shard"] = original_spawn
        self.assertEqual(
            [process.result for process in group_spawned],
            [0, 1, *([0] * (len(shards[0]) - 2))],
        )
        self.assertTrue(all(process.waited for process in group_spawned))
        self.assertEqual(FakeProcess.active, 0)

        interrupted = FakeProcess()
        original_wait = interrupted.wait
        interrupted.wait = lambda timeout=None: (
            (_ for _ in ()).throw(KeyboardInterrupt())
            if timeout is None
            else original_wait(timeout)
        )
        stopped = []
        original_stop = namespace["_stop_process_tree"]
        namespace["_spawn_shard"] = lambda _shard: interrupted
        namespace["_stop_process_tree"] = lambda process: (
            stopped.append(process),
            (_ for _ in ()).throw(RuntimeError("cleanup failed")),
        )[-1]
        try:
            with self.assertRaises(KeyboardInterrupt):
                namespace["run_group"](((shards[0][0],),))
        finally:
            namespace["_spawn_shard"] = original_spawn
            namespace["_stop_process_tree"] = original_stop
        self.assertEqual(stopped, [interrupted])
        interrupted.terminate()
        self.assertEqual(FakeProcess.active, 0)

        class HangingTreeProcess:
            def __init__(self):
                self.pid = 9876
                self.signals = []
                self.wait_timeouts = []
                self.killed = False

            def poll(self):
                return None

            def send_signal(self, sent):
                self.signals.append(sent)

            def wait(self, timeout=None):
                self.wait_timeouts.append(timeout)
                if len(self.wait_timeouts) == 1:
                    raise namespace["subprocess"].TimeoutExpired("unit", timeout)
                return 0

            def kill(self):
                self.killed = True

        hanging = HangingTreeProcess()
        if namespace["IS_WINDOWS"]:
            taskkill_commands = []
            original_run = namespace["subprocess"].run
            namespace["subprocess"].run = (
                lambda command, **_kwargs: taskkill_commands.append(command)
            )
            try:
                namespace["_stop_process_tree"](hanging)
            finally:
                namespace["subprocess"].run = original_run
            self.assertEqual(
                hanging.signals,
                [namespace["signal"].CTRL_BREAK_EVENT],
            )
            self.assertEqual(
                taskkill_commands,
                [["taskkill", "/PID", "9876", "/T", "/F"]],
            )
        else:
            group_signals = []
            original_killpg = namespace["os"].killpg
            namespace["os"].killpg = (
                lambda pid, sent: group_signals.append((pid, sent))
            )
            try:
                namespace["_stop_process_tree"](hanging)
            finally:
                namespace["os"].killpg = original_killpg
            self.assertEqual(
                group_signals,
                [
                    (9876, namespace["signal"].SIGTERM),
                    (9876, namespace["signal"].SIGKILL),
                ],
            )
        self.assertEqual(hanging.wait_timeouts, [5, 5])
        self.assertFalse(hanging.killed)

        spawned = []
        original_sleep = namespace["time"].sleep
        namespace["_spawn_shard"] = lambda shard: spawned.append(FakeProcess()) or spawned[-1]
        namespace["time"].sleep = lambda _seconds: None
        try:
            self.assertEqual(namespace["run_shards"](shards), 0)
        finally:
            namespace["_spawn_shard"] = original_spawn
            namespace["time"].sleep = original_sleep
        self.assertEqual(len(spawned), 12)
        self.assertEqual(FakeProcess.max_active, 4)

        spawned.clear()
        FakeProcess.active = 0
        FakeProcess.max_active = 0
        namespace["_spawn_shard"] = (
            lambda shard: spawned.append(FakeProcess(result=1 if not spawned else 0))
            or spawned[-1]
        )
        namespace["time"].sleep = lambda _seconds: None
        try:
            self.assertEqual(namespace["run_shards"](shards), 1)
        finally:
            namespace["_spawn_shard"] = original_spawn
            namespace["time"].sleep = original_sleep
        self.assertEqual(len(spawned), 12)
        self.assertEqual(FakeProcess.active, 0)

        spawned.clear()
        FakeProcess.active = 0
        FakeProcess.max_active = 0
        namespace["_spawn_shard"] = (
            lambda shard: spawned.append(FakeProcess(polls_until_done=99))
            or spawned[-1]
        )
        namespace["time"].sleep = lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt())
        stopped.clear()
        namespace["_stop_process_tree"] = lambda process: (
            stopped.append(process),
            (_ for _ in ()).throw(RuntimeError("cleanup failed"))
            if len(stopped) == 1
            else None,
        )[-1]
        try:
            with self.assertRaises(KeyboardInterrupt):
                namespace["run_shards"](shards)
        finally:
            namespace["_spawn_shard"] = original_spawn
            namespace["time"].sleep = original_sleep
            namespace["_stop_process_tree"] = original_stop
        self.assertEqual(len(spawned), 4)
        self.assertEqual(stopped, spawned)
        for process in spawned:
            process.terminate()
        self.assertEqual(FakeProcess.active, 0)

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
            "Continue Milestone 2",
            ROADMAP.split("## Current next actions", 1)[1],
        )
        self.assertIn(
            "remote sessions and approval responses",
            ROADMAP.split("## Current next actions", 1)[1],
        )
        self.assertNotIn("Land the early CI guardrail", ROADMAP)
        self.assertIn("Added the early GitHub Actions guardrail", CHANGELOG)
        self.assertIn("does not yet add packaging", CHANGELOG)


if __name__ == "__main__":
    unittest.main()
