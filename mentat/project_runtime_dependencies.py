"""Qualification-only dependency inspection, staging and explicit public audit.

Artifact inspection and staging are offline; the explicit auditor queries PyPI.
No downloaded code is imported or executed. The baseline source, pyproject and
uv.lock stay intact. Caller-supplied audit JSON is reported evidence, never a
trusted readiness receipt or a claim that a scanner was actually executed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path
import selectors
import signal
import shutil
import subprocess
import sys
from tempfile import mkdtemp
import time
import tomllib
import zipfile

import deploy
from mentat import project_runtime_origin as origin

# Reconstructed from the current baseline audit and exact public wheel metadata.
# This fixed comparison is NOT the undocumented historical seven-package choice.
CANDIDATE_SHA256 = "7dfea05f8a5f10060ffc548877ff2f3795654e1a2730beb3b3bfc916205950f6"
REPLACEMENT_VERSIONS = {
    "aiohttp": "3.14.4", "anyio": "4.14.2", "httpcore2": "2.12.0", "httpx2": "2.12.0",
    "mcp": "2.2.0", "multidict": "6.9.1", "oauthlib": "4.0.0", "pip": "26.2",
    "pyjwt": "2.15.0", "urllib3": "2.8.0", "yarl": "1.25.1", "mcp-types": "2.2.0",
}
UNRESOLVED_ADVISORIES = frozenset()
PYJWT_OPTIONS_REVIEW = {
    "advisory": "PYSEC-2026-4146", "package": "pyjwt", "version": "2.15.0",
    "wheel_sha256": "7a3742debf6b879e912dbb9819ceec1594be812452b78c5f2e2dfc56564954f8",
    "fixed_commit": "0c87c8c8b1a74cac99ad8115f3050efcb7fbed35",
    "release_commit": "1d41a6478e1562e68ff667fcd703356acf085f68",
    "member": "jwt/api_jwt.py", "member_git_blob_sha1": "a63191df0683f86cd946399a4461884b248a5b1c",
}
MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_REQUIREMENTS = 512
AUDIT_SECONDS = 300
AUDITOR_VERSION = "2.10.1"
AUDIT_CLEANUP_SECONDS = 5
TARGET = {
    "implementation_name": "cpython", "implementation_version": "3.13.14",
    "os_name": "posix", "platform_machine": "x86_64", "platform_release": "",
    "platform_system": "Linux", "platform_version": "", "python_full_version": "3.13.14",
    "platform_python_implementation": "CPython", "python_version": "3.13",
    "sys_platform": "linux", "extra": "",
}


class DependencyQualificationError(RuntimeError):
    pass


def _fail(code):
    raise DependencyQualificationError("runtime_dependencies." + code)


def _json(raw, maximum):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= maximum:
        _fail("document")
    try:
        return json.loads(raw, object_pairs_hook=origin._pairs)
    except (ValueError, TypeError, UnicodeError, RecursionError, origin.OriginError):
        _fail("document")


def load_candidate(path=None):
    """Accept one fixed comparison document, never an arbitrary replacement list."""
    if CANDIDATE_SHA256 is None or not REPLACEMENT_VERSIONS:
        _fail("candidate_unavailable")
    path = path or Path(deploy.__file__).with_name("project-runtime-dependency-candidate.json")
    with path.open("rb") as reader:
        raw = reader.read(128 * 1024 + 1)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != CANDIDATE_SHA256:
        _fail("candidate_identity")
    document = _json(raw, 128 * 1024)
    baseline, baseline_digest = origin.load_lock()
    try:
        if (set(document) != {"format", "purpose", "baseline_sha256", "replacements"}
                or type(document["format"]) is not int or document["format"] != 1
                or document["purpose"] != "dependency-qualification-comparison"
                or document["baseline_sha256"] != baseline_digest
                or not isinstance(document["replacements"], list)
                or len(document["replacements"]) != len(REPLACEMENT_VERSIONS)):
            _fail("candidate")
        indexed = {item["name"]: item for item in baseline["wheels"]}
        selected = {}
        for item in document["replacements"]:
            if (not isinstance(item, dict)
                    or set(item) != {"name", "version", "filename", "sha256", "size", "url"}
                    or item["name"] not in REPLACEMENT_VERSIONS or item["name"] in selected
                    or item["name"] not in indexed
                    or item["version"] != REPLACEMENT_VERSIONS[item["name"]]
                    or item["version"] == indexed[item["name"]]["version"]):
                _fail("replacement")
            # Reuse the existing bounded wheel-coordinate validation without
            # changing what the baseline's official/supplement labels mean.
            from urllib.parse import urlsplit
            url = urlsplit(item["url"])
            if (origin._canonical(item["name"]) != item["name"]
                    or "/" in origin._name(item["filename"])
                    or not item["filename"].endswith(".whl")
                    or not origin._HEX.fullmatch(item["sha256"])
                    or type(item["size"]) is not int or not 0 < item["size"] <= origin.MAX_ARCHIVE
                    or url.scheme != "https" or url.netloc != "files.pythonhosted.org"
                    or not url.path.startswith("/packages/") or url.query or url.fragment
                    or url.path.rsplit("/", 1)[-1] != item["filename"]):
                _fail("replacement")
            selected[item["name"]] = dict(item, authority="qualification-replacement")
        if set(selected) != set(REPLACEMENT_VERSIONS):
            _fail("replacement")
        candidate = deepcopy(baseline)
        candidate["wheels"] = [selected.get(item["name"], item) for item in candidate["wheels"]]
        if len({item["filename"] for item in candidate["wheels"]}) != len(candidate["wheels"]):
            _fail("replacement")
    except (KeyError, TypeError, ValueError, origin.OriginError):
        _fail("candidate")
    return candidate, baseline, digest


def _advisory_reviews(candidate):
    items = [item for item in candidate["wheels"] if item["name"] == "pyjwt"]
    if not items:
        return []
    if (len(items) != 1 or items[0]["version"] != PYJWT_OPTIONS_REVIEW["version"]
            or items[0]["sha256"] != PYJWT_OPTIONS_REVIEW["wheel_sha256"]):
        _fail("advisory_review")
    return [dict(PYJWT_OPTIONS_REVIEW)]


def _metadata(data, item):
    # Force all existing ZIP path, type, metadata and expansion guards before
    # treating metadata as dependency evidence. Never run package entry points.
    for _member in origin.wheel_members(data, item):
        pass
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        names = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        if item["name"] == "pyjwt":
            review = _advisory_reviews({"wheels": [item]})[0]
            if hashlib.sha256(data).hexdigest() != review["wheel_sha256"]:
                _fail("advisory_review")
            member = wheel.getinfo(review["member"])
            if member.file_size > 512 * 1024:
                _fail("advisory_review")
            content = wheel.read(member)
            blob = b"blob " + str(len(content)).encode("ascii") + b"\x00" + content
            if hashlib.sha1(blob).hexdigest() != review["member_git_blob_sha1"]:
                _fail("advisory_review")
        return BytesParser().parsebytes(wheel.read(names[0]))


def inspect_dependencies(artifacts: Path):
    """Check the exact selected graph against unchanged upstream requirements."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        _fail("unsupported")
    if not artifacts.is_absolute() or ".." in artifacts.parts:
        _fail("artifacts")
    try:
        from packaging.requirements import Requirement
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
    except ImportError:
        _fail("inspector_unavailable")
    candidate, baseline, digest = load_candidate()
    fd = origin._open_directory(artifacts)
    try:
        source = origin._artifact(fd, baseline["source"])
        documents = {member.path: member.data for member in origin.tar_members(source, "source")
                     if member.path in {"source/uv.lock", "source/pyproject.toml"}}
        if (set(documents) != {"source/uv.lock", "source/pyproject.toml"}
                or not isinstance(documents["source/pyproject.toml"], bytes)
                or len(documents["source/pyproject.toml"]) > 512 * 1024):
            _fail("source_metadata")
        origin.validate_wheel_authority(baseline, documents["source/uv.lock"])
        project = tomllib.loads(documents["source/pyproject.toml"].decode())["project"]
        if not isinstance(project, dict) or Version("3.13.14") not in SpecifierSet(project.get("requires-python", "")):
            _fail("python_requirement")
        metadata = {item["name"]: _metadata(origin._artifact(fd, item), item)
                    for item in candidate["wheels"]}
    finally:
        os.close(fd)
    versions = {item["name"]: item["version"] for item in candidate["wheels"]}
    requirements = {"hermes-source": project.get("dependencies", [])}
    for name, headers in metadata.items():
        requires_python = headers.get_all("Requires-Python", [])
        if len(requires_python) > 1 or (requires_python and Version("3.13.14") not in SpecifierSet(requires_python[0])):
            _fail("python_requirement")
        requirements[name] = headers.get_all("Requires-Dist", [])
    extras = {name: {""} for name in requirements}
    conflicts = set()
    try:
        changed = True
        while changed:
            changed = False
            for owner, values in requirements.items():
                if not isinstance(values, list) or len(values) > MAX_REQUIREMENTS:
                    _fail("requirements")
                for text in values:
                    if not isinstance(text, str) or len(text) > 4096:
                        _fail("requirements")
                    requirement = Requirement(text)
                    name = origin._canonical(requirement.name)
                    if requirement.marker and not any(requirement.marker.evaluate(dict(TARGET, extra=extra))
                                                      for extra in extras[owner]):
                        continue
                    if requirement.url or name not in versions or Version(versions[name]) not in requirement.specifier:
                        conflicts.add((owner, name, str(requirement.specifier), bool(requirement.url)))
                        continue
                    if len(requirement.extras) > 32:
                        _fail("requirements")
                    additional = set(requirement.extras) - extras[name]
                    if additional:
                        extras[name].update(additional)
                        changed = True
    except (ValueError, KeyError, TypeError, origin.OriginError):
        _fail("requirements")
    return {"format": 1, "purpose": "dependency-qualification-comparison", "candidate_sha256": digest,
            "unresolved_advisories": sorted(UNRESOLVED_ADVISORIES), "reviewed_advisories": _advisory_reviews(candidate),
            "packages": versions, "dependency_conflicts": [list(value) for value in sorted(conflicts)],
            "source_pyproject_sha256": hashlib.sha256(documents["source/pyproject.toml"]).hexdigest(),
            "source_uv_lock_sha256": hashlib.sha256(documents["source/uv.lock"]).hexdigest(),
            "provider_calls": 0, "production_qualified": False}


def audit_requirements(candidate):
    """Exact no-resolution input for an independent disposable pip-audit run."""
    return "".join(f"{item['name']}=={item['version']} --hash=sha256:{item['sha256']}\n"
                   for item in sorted(candidate["wheels"], key=lambda item: item["name"])).encode("ascii")


def validate_audit_report(raw: bytes):
    """Bind reported findings to every selected coordinate without waivers."""
    candidate, _baseline, digest = load_candidate()
    document = _json(raw, MAX_REPORT_BYTES)
    expected = {item["name"]: item["version"] for item in candidate["wheels"]}
    try:
        if (not isinstance(document, dict) or set(document) - {"dependencies", "fixes"}
                or not isinstance(document.get("dependencies"), list)
                or len(document["dependencies"]) != len(expected)
                or document.get("fixes", []) != []):
            _fail("audit_inventory")
        seen = set()
        for item in document["dependencies"]:
            if (set(item) != {"name", "version", "vulns"} or item["name"] in seen
                    or expected.get(item["name"]) != item["version"] or not isinstance(item["vulns"], list)):
                _fail("audit_inventory")
            if item["vulns"]:
                _fail("audit_vulnerabilities")
            seen.add(item["name"])
        if seen != set(expected):
            _fail("audit_inventory")
    except (TypeError, KeyError):
        _fail("audit_inventory")
    return {"candidate_sha256": digest, "audit_report_sha256": hashlib.sha256(raw).hexdigest(),
            "reported_packages": len(seen), "reported_vulnerabilities": 0,
            "unresolved_advisories": sorted(UNRESOLVED_ADVISORIES), "reviewed_advisories": _advisory_reviews(candidate),
            "scanner_execution_verified": False, "production_qualified": False}


@contextmanager
def _audit_directory():
    root = Path(mkdtemp(prefix="mentat-dependency-audit-")).resolve()
    ownership = {"safe_to_remove": True}
    try:
        yield root, ownership
    finally:
        # An unverified descendant may still use this owned root. Keep that
        # disposable public-only directory rather than delete beneath it.
        if ownership["safe_to_remove"]:
            shutil.rmtree(root)


def _wait_audit_exit(process, deadline):
    # WNOWAIT retains the exact spawned PID even after exit. Its group ID
    # therefore cannot be reused before the owned-group termination below.
    while time.monotonic() < deadline:
        result = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
        if result is not None and result.si_pid == process.pid:
            return result.si_status if result.si_code == os.CLD_EXITED else -result.si_status
        time.sleep(0.02)
    _fail("audit_timeout")


def _close_audit_group(process):
    deadline = time.monotonic() + AUDIT_CLEANUP_SECONDS
    try:
        # A waitable child, live or terminal, still pins the original identity.
        # No poll()/wait() may reap it before signaling this exact group.
        os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
        # start_new_session=True established this exact group at creation.
        # Darwin may no longer answer getpgid/getsid for a terminal child;
        # WNOWAIT still reserves its PID, so the original group cannot be reused.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            # Best-effort termination of the exact still-pinned leader cannot
            # substitute for group closure. The independent probe below must
            # still prove absence before success or directory removal.
            try:
                os.kill(process.pid, signal.SIGKILL)
            except OSError:
                pass
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
        # After reaping, probe only. Never send another signal to a potentially
        # reused numeric ID. Any surviving/ambiguous group refuses success.
        while time.monotonic() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                # Permission denial is never absence evidence. A finite owned
                # descendant may exit while we wait; accept only later ESRCH.
                pass
            time.sleep(0.02)
    except (OSError, ChildProcessError, subprocess.TimeoutExpired):
        return False
    return False


def run_audit():
    """Run the fixed auditor in this disposable tool environment, never install."""
    from importlib.metadata import PackageNotFoundError, version
    if os.name != "posix" or any(not hasattr(os, name) for name in ("waitid", "WNOWAIT", "WEXITED", "WNOHANG", "P_PID", "CLD_EXITED")):
        _fail("audit_platform")
    try:
        if version("pip-audit") != AUDITOR_VERSION:
            _fail("auditor_version")
    except PackageNotFoundError:
        _fail("auditor_unavailable")
    candidate, _baseline, candidate_digest = load_candidate()
    with _audit_directory() as (root, ownership):
        requirements = root / "requirements.txt"
        requirements.write_bytes(audit_requirements(candidate))
        requirements.chmod(0o600)
        command = [sys.executable, "-I", "-m", "pip_audit", "--requirement", str(requirements),
                   "--no-deps", "--disable-pip", "--require-hashes", "--strict", "--format", "json",
                   "--desc", "off", "--aliases", "off", "--progress-spinner", "off",
                   "--vulnerability-service", "pypi", "--timeout", "10", "--cache-dir", str(root / "cache")]
        environment = {"PATH": os.defpath, "HOME": str(root), "LANG": "C.UTF-8",
                       "XDG_CONFIG_HOME": str(root / "config"), "XDG_CACHE_HOME": str(root / "cache")}
        deadline = time.monotonic() + AUDIT_SECONDS
        process = subprocess.Popen(command, cwd=root, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   start_new_session=True, close_fds=True)
        ownership["safe_to_remove"] = False
        data = bytearray()
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        _fail("audit_timeout")
                    for key, _events in selector.select(min(remaining, 0.2)):
                        chunk = os.read(key.fd, min(65536, MAX_REPORT_BYTES + 1 - len(data)))
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            data.extend(chunk)
                            if len(data) > MAX_REPORT_BYTES:
                                _fail("audit_output")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _fail("audit_timeout")
            code = _wait_audit_exit(process, deadline)
            if time.monotonic() >= deadline:
                _fail("audit_timeout")
            report = validate_audit_report(bytes(data))
            if code != 0 or report["candidate_sha256"] != candidate_digest:
                _fail("audit_failed")
            if time.monotonic() >= deadline:
                _fail("audit_timeout")
            return dict(report, scanner_execution_verified=True, auditor="pip-audit",
                        auditor_version=AUDITOR_VERSION, vulnerability_service="pypi")
        finally:
            try:
                ownership["safe_to_remove"] = _close_audit_group(process)
            finally:
                process.stdout.close()
            if not ownership["safe_to_remove"]:
                _fail("audit_cleanup_unverified")
            if time.monotonic() >= deadline:
                _fail("audit_timeout")


def build_candidate_stage(artifacts: Path, destination: Path):
    if sys.platform != "linux" or not hasattr(os, "O_NOFOLLOW"):
        _fail("unsupported")
    evidence = inspect_dependencies(artifacts)
    if evidence["dependency_conflicts"]:
        _fail("dependency_conflicts")
    if evidence["unresolved_advisories"]:
        _fail("advisory_review")
    candidate, baseline, digest = load_candidate()
    if evidence["candidate_sha256"] != digest:
        _fail("candidate_identity")
    def validate_authority(_lock, uv_bytes):
        origin.validate_wheel_authority(baseline, uv_bytes)
    report = origin._build_stage(artifacts, destination, candidate, digest, validate_authority)
    return dict(report, purpose="dependency-qualification-only", dependency_evidence=evidence)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--audit-report", type=Path)
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.audit and args.audit_report is None and args.artifacts is None and args.stage is None:
            result = run_audit()
        elif not args.audit and args.audit_report is not None and args.artifacts is None and args.stage is None:
            with args.audit_report.open("rb") as reader:
                result = validate_audit_report(reader.read(MAX_REPORT_BYTES + 1))
        elif not args.audit and args.audit_report is None and args.artifacts is not None:
            result = build_candidate_stage(args.artifacts, args.stage) if args.stage is not None else inspect_dependencies(args.artifacts)
        else:
            parser.error("provide artifacts, or one audit report")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (DependencyQualificationError, origin.OriginError, OSError, ValueError, KeyError,
            tomllib.TOMLDecodeError, zipfile.BadZipFile):
        print("runtime_dependencies.failed; no qualification or readiness granted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
