from contextlib import contextmanager, ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mentat import project_runtime_dependencies as dependencies
from mentat import project_runtime_origin as origin
from tests import test_project_runtime_origin as fixtures


@contextmanager
def candidate_fixture(*, source_requirements=(), wheel_requirements=None):
    """Synthetic public artifacts, never imported, installed or executed."""
    with TemporaryDirectory() as temporary, ExitStack() as patches:
        root = Path(temporary).resolve()
        replacements = {"package-" + letter: "2.0" for letter in "abcdefg"}
        artifacts = root / "artifacts"
        artifacts.mkdir()
        def artifact(filename, raw):
            (artifacts / filename).write_bytes(raw)
            return {"filename": filename, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                    "url": "https://files.pythonhosted.org/packages/fixture/" + filename}
        baseline_wheels, changed = [], []
        for name in [*replacements, "unchanged"]:
            for version in ("1.0", "2.0") if name in replacements else ("1.0",):
                fields = [f"Name: {name}", f"Version: {version}", "Requires-Python: >=3.13,<3.14"]
                fields += ["Requires-Dist: " + value for value in (wheel_requirements or {}).get(name, ())]
                raw = fixtures.wheel([(name.replace("-", "_") + f"-{version}.dist-info/METADATA",
                                       ("\n".join(fields) + "\n\n").encode()),
                                      (name.replace("-", "_") + ".py", b"# inert public fixture\n")])
                entry = dict(artifact(f"{name.replace('-', '_')}-{version}-py3-none-any.whl", raw),
                             name=name, version=version)
                if version == "1.0":
                    baseline_wheels.append(dict(entry, authority="official-uv-lock"))
                else:
                    changed.append(entry)
        uv = "".join('[[package]]\nname=' + json.dumps(item["name"]) + '\nversion="1.0"\nwheels=[{url='
                     + json.dumps(item["url"]) + ',hash="sha256:' + item["sha256"] + '",size='
                     + str(item["size"]) + '}]\n' for item in baseline_wheels).encode()
        pyproject = ('[project]\nname="hermes-agent"\nversion="0.0"\ndependencies='
                     + json.dumps(list(source_requirements)) + '\n').encode()
        source = artifact("source.tar.gz", fixtures.tar([("upstream/uv.lock", uv),
                                                        ("upstream/pyproject.toml", pyproject)]))
        python = artifact("python.tar.gz", fixtures.tar([("python/bin/python3.13", b"inert interpreter")]))
        baseline = {"format": 1, "source_commit": origin.COMMIT, "uv_lock_sha256": hashlib.sha256(uv).hexdigest(),
                    "source": source, "python": python, "wheels": baseline_wheels}
        baseline_digest = hashlib.sha256(json.dumps(baseline, sort_keys=True).encode()).hexdigest()
        document = {"format": 1, "purpose": "dependency-qualification-comparison", "baseline_sha256": baseline_digest,
                    "replacements": changed}
        path = root / "candidate.json"
        raw = json.dumps(document, sort_keys=True).encode()
        path.write_bytes(raw)
        patches.enter_context(patch.object(origin, "load_lock", return_value=(baseline, baseline_digest)))
        patches.enter_context(patch.object(origin, "_SUPPLEMENTS", {}))
        patches.enter_context(patch.object(dependencies, "REPLACEMENT_VERSIONS", replacements))
        patches.enter_context(patch.object(dependencies, "UNRESOLVED_ADVISORIES", frozenset()))
        patches.enter_context(patch.object(dependencies, "CANDIDATE_SHA256", hashlib.sha256(raw).hexdigest()))
        original_load = dependencies.load_candidate
        patches.enter_context(patch.object(dependencies, "load_candidate", side_effect=lambda: original_load(path)))
        yield root, artifacts, document, original_load, path


AUDIT_PLATFORM = os.name == "posix" and all(
    hasattr(os, name)
    for name in ("waitid", "WNOWAIT", "WEXITED", "WNOHANG", "P_PID", "CLD_EXITED")
)


@contextmanager
def synthetic_auditor():
    # These tests replace Popen with inert Python fixtures, not pip-audit.
    with patch("importlib.metadata.version", return_value=dependencies.AUDITOR_VERSION):
        yield


class DependencyQualificationTests(unittest.TestCase):
    def test_fixed_reconstructed_comparison_is_twelve_changes_and_not_production(self):
        candidate, baseline, digest = dependencies.load_candidate()
        self.assertEqual(digest, dependencies.CANDIDATE_SHA256)
        self.assertEqual(len(candidate["wheels"]), 111)
        changed = {item["name"] for item, prior in zip(candidate["wheels"], baseline["wheels"]) if item != prior}
        self.assertEqual(changed, set(dependencies.REPLACEMENT_VERSIONS))
        self.assertEqual(len(changed), 12)
        self.assertEqual(candidate["source"], baseline["source"])
        self.assertEqual(candidate["python"], baseline["python"])
        self.assertEqual(candidate["uv_lock_sha256"], baseline["uv_lock_sha256"])
        self.assertEqual(dependencies.UNRESOLVED_ADVISORIES, frozenset())
        self.assertEqual(dependencies._advisory_reviews(candidate), [dependencies.PYJWT_OPTIONS_REVIEW])

    def test_specific_pyjwt_review_binds_wheel_coordinate_and_exact_release_member(self):
        content = b"# synthetic public review fixture\noptions = dict(options)\n"
        raw = fixtures.wheel([("pyjwt-2.15.0.dist-info/METADATA", b"Name: PyJWT\nVersion: 2.15.0\n\n"),
                              ("jwt/api_jwt.py", content)])
        entry = {"name": "pyjwt", "version": "2.15.0", "sha256": hashlib.sha256(raw).hexdigest()}
        blob = b"blob " + str(len(content)).encode() + b"\x00" + content
        review = dict(dependencies.PYJWT_OPTIONS_REVIEW, wheel_sha256=entry["sha256"],
                      member_git_blob_sha1=hashlib.sha1(blob).hexdigest())
        with patch.object(dependencies, "PYJWT_OPTIONS_REVIEW", review):
            self.assertEqual(dependencies._metadata(raw, entry)["Version"], "2.15.0")
            with self.assertRaisesRegex(dependencies.DependencyQualificationError, "advisory_review"):
                dependencies._advisory_reviews({"wheels": [dict(entry, version="2.14.0")]})
            with patch.object(dependencies, "PYJWT_OPTIONS_REVIEW", dict(review, member_git_blob_sha1="0" * 40)), \
                    self.assertRaisesRegex(dependencies.DependencyQualificationError, "advisory_review"):
                dependencies._metadata(raw, entry)
            changed = fixtures.wheel([("pyjwt-2.15.0.dist-info/METADATA", b"Name: PyJWT\nVersion: 2.15.0\n\n"),
                                     ("jwt/api_jwt.py", content + b"# changed\n")])
            with self.assertRaisesRegex(dependencies.DependencyQualificationError, "advisory_review"):
                dependencies._metadata(changed, entry)

    def test_missing_candidate_identity_refuses_before_reading_any_candidate(self):
        with patch.object(dependencies, "CANDIDATE_SHA256", None), patch.object(Path, "open") as opened:
            with self.assertRaisesRegex(dependencies.DependencyQualificationError, "candidate_unavailable"):
                dependencies.load_candidate()
            opened.assert_not_called()

    def test_exact_candidate_replaces_only_seven_and_retains_source_and_python(self):
        with candidate_fixture() as (_root, _artifacts, _document, _load, _path):
            candidate, baseline, digest = dependencies.load_candidate()
            self.assertEqual(candidate["source"], baseline["source"])
            self.assertEqual(candidate["python"], baseline["python"])
            self.assertEqual(candidate["uv_lock_sha256"], baseline["uv_lock_sha256"])
            changed = [(a, b) for a, b in zip(candidate["wheels"], baseline["wheels"]) if a != b]
            self.assertEqual(len(changed), 7)
            self.assertTrue(all(a["authority"] == "qualification-replacement" for a, _b in changed))
            self.assertEqual(len(digest), 64)
            candidate["source"]["size"] = 1
            self.assertNotEqual(candidate["source"], baseline["source"])

    def test_changed_document_and_changed_baseline_fail_closed(self):
        with candidate_fixture() as (_root, _artifacts, document, load, path):
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(dependencies.DependencyQualificationError, "candidate_identity"):
                load(path)
            raw = json.dumps(dict(document, baseline_sha256="0" * 64), sort_keys=True).encode()
            path.write_bytes(raw)
            with patch.object(dependencies, "CANDIDATE_SHA256", hashlib.sha256(raw).hexdigest()), \
                    self.assertRaisesRegex(dependencies.DependencyQualificationError, "candidate"):
                load(path)

    def test_candidate_policy_rejects_missing_extra_duplicate_wrong_version_and_url(self):
        with candidate_fixture() as (_root, _artifacts, document, load, path):
            variants = []
            for key, value in (("name", "unchanged"), ("version", "9.0"),
                               ("filename", "../outside.whl"), ("url", "https://example.com/other.whl"),
                               ("size", True)):
                bad = deepcopy(document)
                bad["replacements"][0][key] = value
                variants.append(bad)
            variants += [dict(document, replacements=document["replacements"][:-1]),
                         dict(document, replacements=document["replacements"] + [document["replacements"][0]]),
                         dict(document, replacements=[document["replacements"][0]] * 7)]
            for bad in variants:
                raw = json.dumps(bad, sort_keys=True).encode()
                path.write_bytes(raw)
                with self.subTest(bad=bad), patch.object(dependencies, "CANDIDATE_SHA256", hashlib.sha256(raw).hexdigest()), \
                        self.assertRaises(dependencies.DependencyQualificationError):
                    load(path)

    @unittest.skipUnless(os.name == "posix", "descriptor-relative artifact inspection")
    def test_graph_uses_verified_artifacts_and_unchanged_source_requirements(self):
        with candidate_fixture(source_requirements=["package-a==2.0"],
                               wheel_requirements={"package-a": ["package-b>=2", "absent; sys_platform == 'win32'"]}) as (
                _root, artifacts, _document, _load, _path):
            before = {p.name: p.read_bytes() for p in artifacts.iterdir()}
            report = dependencies.inspect_dependencies(artifacts)
            self.assertEqual(report["dependency_conflicts"], [])
            self.assertFalse(report["production_qualified"])
            self.assertEqual(report["provider_calls"], 0)
            self.assertEqual(before, {p.name: p.read_bytes() for p in artifacts.iterdir()})
            item = next(p for p in artifacts.iterdir() if p.name.startswith("package_a-2"))
            item.write_bytes(item.read_bytes() + b"tampered")
            with self.assertRaises(origin.OriginError):
                dependencies.inspect_dependencies(artifacts)

    @unittest.skipUnless(os.name == "posix", "descriptor-relative artifact inspection")
    def test_upstream_pin_conflict_is_visible_and_prevents_candidate_stage(self):
        with candidate_fixture(source_requirements=["package-a==1.0"]) as (root, artifacts, *_rest):
            report = dependencies.inspect_dependencies(artifacts)
            self.assertEqual(report["dependency_conflicts"], [["hermes-source", "package-a", "==1.0", False]])
            with patch.object(dependencies.sys, "platform", "linux"), patch.object(origin, "_build_stage") as stage, \
                    self.assertRaisesRegex(dependencies.DependencyQualificationError, "dependency_conflicts"):
                dependencies.build_candidate_stage(artifacts, root / "stage")
            stage.assert_not_called()
            self.assertFalse((root / "stage").exists())

    @unittest.skipUnless(os.name == "posix", "descriptor-relative artifact inspection")
    def test_unresolved_advisory_blocks_staging_even_with_compatible_declared_graph(self):
        with candidate_fixture() as (root, artifacts, *_rest), \
                patch.object(dependencies, "UNRESOLVED_ADVISORIES", frozenset({"unresolved-fixture"})), \
                patch.object(dependencies.sys, "platform", "linux"), \
                patch.object(origin, "_build_stage") as stage:
            report = dependencies.inspect_dependencies(artifacts)
            self.assertEqual(report["dependency_conflicts"], [])
            self.assertEqual(report["unresolved_advisories"], ["unresolved-fixture"])
            with self.assertRaisesRegex(dependencies.DependencyQualificationError, "advisory_review"):
                dependencies.build_candidate_stage(artifacts, root / "stage")
            stage.assert_not_called()
            self.assertFalse((root / "stage").exists())

    @unittest.skipUnless(os.name == "posix", "descriptor-relative inert stage")
    def test_candidate_stage_preserves_upstream_files_and_refuses_existing_destination(self):
        with candidate_fixture(source_requirements=["package-a>=1"]) as (root, artifacts, *_rest):
            destination = root / "stage"
            with patch.object(dependencies.sys, "platform", "linux"):
                report = dependencies.build_candidate_stage(artifacts, destination)
                self.assertEqual(report["purpose"], "dependency-qualification-only")
                self.assertFalse(report["production_qualified"])
                self.assertEqual(report["provider_calls"], 0)
                candidate, baseline, _digest = dependencies.load_candidate()
                source = artifacts / baseline["source"]["filename"]
                members = {member.path: member.data for member in origin.tar_members(source.read_bytes(), "source")}
                for name in ("pyproject.toml", "uv.lock"):
                    self.assertEqual((destination / "source" / name).read_bytes(), members["source/" + name])
                for item in candidate["wheels"]:
                    metadata = destination / origin.SITE / (item["name"].replace("-", "_") + f"-{item['version']}.dist-info/METADATA")
                    self.assertIn(("Version: " + item["version"]).encode(), metadata.read_bytes())
                with self.assertRaises(FileExistsError):
                    dependencies.build_candidate_stage(artifacts, destination)
            self.assertEqual((destination / "source/uv.lock").read_bytes(), members["source/uv.lock"])

    @unittest.skipUnless(os.name == "posix", "descriptor-relative artifact inspection")
    def test_activated_extras_and_missing_dependency_are_not_ignored(self):
        with candidate_fixture(source_requirements=["package-a[feature]"], wheel_requirements={
            "package-a": ["missing>=1; extra == 'feature'"],
        }) as (_root, artifacts, *_rest):
            self.assertEqual(dependencies.inspect_dependencies(artifacts)["dependency_conflicts"],
                             [["package-a", "missing", ">=1", False]])

    def test_audit_requires_exact_complete_inventory_and_zero_findings(self):
        with candidate_fixture():
            candidate, *_rest = dependencies.load_candidate()
            document = {"dependencies": [{"name": item["name"], "version": item["version"], "vulns": []}
                                         for item in candidate["wheels"]], "fixes": []}
            report = dependencies.validate_audit_report(json.dumps(document).encode())
            self.assertEqual(report["reported_packages"], 8)
            self.assertFalse(report["scanner_execution_verified"])
            self.assertFalse(report["production_qualified"])
            variants = [dict(document, dependencies=document["dependencies"][:-1]),
                        dict(document, dependencies=document["dependencies"] + [document["dependencies"][0]])]
            for field, value in (("version", "0"), ("vulns", [{"id": "fixture-advisory"}]), ("name", "unknown")):
                changed = deepcopy(document)
                changed["dependencies"][0][field] = value
                variants.append(changed)
            for changed in variants:
                with self.subTest(changed=changed), self.assertRaises(dependencies.DependencyQualificationError):
                    dependencies.validate_audit_report(json.dumps(changed).encode())
            self.assertEqual(dependencies.audit_requirements(candidate).count(b"==2.0 --hash=sha256:"), 7)

    def test_audit_refuses_unsupported_platform_before_tool_or_artifact_access(self):
        with patch.object(dependencies.os, "name", "nt"), \
                patch("importlib.metadata.version") as version, \
                patch.object(dependencies, "load_candidate") as load, \
                self.assertRaisesRegex(dependencies.DependencyQualificationError, "audit_platform"):
            dependencies.run_audit()
        version.assert_not_called()
        load.assert_not_called()

    @unittest.skipUnless(AUDIT_PLATFORM, "audit worker requires non-reaping POSIX waitid")
    def test_audit_refuses_missing_or_wrong_tool_before_artifact_access(self):
        from importlib.metadata import PackageNotFoundError
        for options, reason in (({"side_effect": PackageNotFoundError("pip-audit")}, "auditor_unavailable"),
                                ({"return_value": "0.0"}, "auditor_version")):
            with self.subTest(reason=reason), patch("importlib.metadata.version", **options), \
                    patch.object(dependencies, "load_candidate") as load, \
                    self.assertRaisesRegex(dependencies.DependencyQualificationError, reason):
                dependencies.run_audit()
            load.assert_not_called()

    @unittest.skipUnless(AUDIT_PLATFORM, "audit worker requires non-reaping POSIX waitid")
    def test_fixed_audit_worker_bounds_output_and_does_not_inherit_secrets(self):
        actual_spawn = subprocess.Popen
        for failure in (None, "oversize", "timeout", "exit"):
            with self.subTest(failure=failure), candidate_fixture(), synthetic_auditor():
                candidate, *_rest = dependencies.load_candidate()
                raw = json.dumps({"dependencies": [{"name": item["name"], "version": item["version"], "vulns": []}
                                                   for item in candidate["wheels"]], "fixes": []}).encode()
                processes = []
                def spawn(command, **options):
                    self.assertEqual(command[:4], [sys.executable, "-I", "-m", "pip_audit"])
                    self.assertIn("--no-deps", command)
                    self.assertIn("--disable-pip", command)
                    self.assertIn("--strict", command)
                    self.assertIn("--require-hashes", command)
                    self.assertNotIn("--ignore-vuln", command)
                    self.assertEqual(set(options["env"]), {"PATH", "HOME", "LANG", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"})
                    self.assertNotIn("OPENAI_API_KEY", options["env"])
                    requirements = Path(command[command.index("--requirement") + 1])
                    self.assertEqual(requirements.read_bytes(), dependencies.audit_requirements(candidate))
                    code = ("import time; time.sleep(60)" if failure == "timeout" else
                            "import sys;sys.stdout.buffer.write(" + repr(b"x" * 4097 if failure == "oversize" else raw)
                            + ");sys.exit(" + ("2" if failure == "exit" else "0") + ")")
                    process = actual_spawn([sys.executable, "-I", "-c", code], **options)
                    processes.append(process)
                    return process
                with patch.object(dependencies.subprocess, "Popen", side_effect=spawn), \
                        patch.object(dependencies, "AUDIT_SECONDS", 0.5 if failure == "timeout" else 5.0), \
                        patch.object(dependencies, "MAX_REPORT_BYTES", 4096), \
                        patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-never-inherit"}):  # pragma: allowlist secret -- inert refusal fixture
                    if failure:
                        with self.assertRaises(dependencies.DependencyQualificationError):
                            dependencies.run_audit()
                    else:
                        report = dependencies.run_audit()
                        self.assertTrue(report["scanner_execution_verified"])
                        self.assertFalse(report["production_qualified"])
                self.assertEqual(len(processes), 1)
                self.assertIsNotNone(processes[0].poll())

    @unittest.skipUnless(AUDIT_PLATFORM, "audit worker requires non-reaping POSIX waitid")
    def test_leader_exit_cannot_leave_a_descendant_on_success_or_timeout(self):
        actual_spawn = subprocess.Popen
        for inherited_stdout in (True, False):
            with self.subTest(inherited_stdout=inherited_stdout), candidate_fixture(), synthetic_auditor():
                candidate, *_rest = dependencies.load_candidate()
                raw = json.dumps({"dependencies": [{"name": item["name"], "version": item["version"], "vulns": []}
                                                   for item in candidate["wheels"]], "fixes": []}).encode()
                processes, roots = [], []
                def spawn(_command, **options):
                    roots.append(options["cwd"])
                    code = ("import subprocess,sys; "
                            # A finite child cannot leak if the host denies
                            # group signaling. Closure must still be observed.
                            "subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(0.6)'],"
                            "stdin=subprocess.DEVNULL,stdout="
                            + ("None" if inherited_stdout else "subprocess.DEVNULL")
                            + ",stderr=subprocess.DEVNULL,close_fds=True);"
                            "sys.stdout.buffer.write(" + repr(raw) + ");sys.stdout.flush()")
                    process = actual_spawn([sys.executable, "-I", "-c", code], **options)
                    processes.append(process)
                    return process
                with patch.object(dependencies.subprocess, "Popen", side_effect=spawn), \
                        patch.object(dependencies, "AUDIT_SECONDS", 0.2 if inherited_stdout else 2.0):
                    if inherited_stdout:
                        with self.assertRaisesRegex(dependencies.DependencyQualificationError, "audit_timeout"):
                            dependencies.run_audit()
                    else:
                        self.assertTrue(dependencies.run_audit()["scanner_execution_verified"])
                self.assertEqual(len(processes), 1)
                self.assertIsNotNone(processes[0].returncode)
                with self.assertRaises(ProcessLookupError):
                    os.killpg(processes[0].pid, 0)
                self.assertFalse(roots[0].exists())

    @unittest.skipUnless(AUDIT_PLATFORM, "audit worker requires non-reaping POSIX waitid")
    def test_unverified_group_closure_refuses_success_and_retains_owned_directory(self):
        actual_spawn = subprocess.Popen
        close = dependencies._close_audit_group
        with candidate_fixture(), synthetic_auditor():
            candidate, *_rest = dependencies.load_candidate()
            raw = json.dumps({"dependencies": [{"name": item["name"], "version": item["version"], "vulns": []}
                                               for item in candidate["wheels"]], "fixes": []}).encode()
            roots, processes = [], []
            def spawn(_command, **options):
                roots.append(options["cwd"])
                process = actual_spawn([sys.executable, "-I", "-c", "import sys;sys.stdout.buffer.write(" + repr(raw) + ")"], **options)
                processes.append(process)
                return process
            def unverified(process):
                self.assertTrue(close(process))
                return False
            try:
                with patch.object(dependencies.subprocess, "Popen", side_effect=spawn), \
                        patch.object(dependencies, "_close_audit_group", side_effect=unverified), \
                        self.assertRaisesRegex(dependencies.DependencyQualificationError, "audit_cleanup_unverified"):
                    dependencies.run_audit()
                self.assertTrue(roots[0].exists())
                self.assertIsNotNone(processes[0].returncode)
            finally:
                # The injected result follows actual verified closure above.
                for root in roots:
                    shutil.rmtree(root)

    def test_baseline_build_has_no_candidate_policy_or_side_effect(self):
        baseline, digest = origin.load_lock()
        with patch.object(origin.sys, "platform", "linux"), patch.object(origin, "_build_stage", return_value={}) as build, \
                patch.object(dependencies, "load_candidate", side_effect=AssertionError("candidate path")):
            self.assertEqual(origin.build_stage(Path("artifacts"), Path("stage")), {})
        build.assert_called_once_with(Path("artifacts"), Path("stage"), baseline, digest, origin.validate_wheel_authority)

    def test_candidate_stage_is_linux_only_before_artifact_access(self):
        with patch.object(dependencies.sys, "platform", "win32"), patch.object(dependencies, "load_candidate") as load, \
                self.assertRaisesRegex(dependencies.DependencyQualificationError, "unsupported"):
            dependencies.build_candidate_stage(Path("unused"), Path("unused"))
        load.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "descriptor-relative artifact inspection")
    def test_relative_artifact_root_is_rejected_before_candidate_access(self):
        with patch.object(dependencies, "load_candidate") as load, \
                self.assertRaisesRegex(dependencies.DependencyQualificationError, "artifacts"):
            dependencies.inspect_dependencies(Path("relative"))
        load.assert_not_called()
