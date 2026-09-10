"""Pure validation and rendering for the disabled Linux Caddy profile.

This module intentionally has no install, download, process-start, socket, or
launcher entry point.  It provides the artifacts a later, separately approved
activation operation must validate again under its own privileges.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any, Mapping, Sequence


CADDY_VERSION = "2.11.4"
PROFILE_NAME = "remote-caddy-v1"
NODE_UPSTREAM = "127.0.0.1:8888"
HSTS_MAX_AGE_SECONDS = 86_400
LOCK_PATH = Path(__file__).with_name("caddy-lock.json")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class DeploymentProfileError(ValueError):
    """The disabled profile cannot safely describe the supplied deployment."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeploymentProfileError(message)


def canonical_caddy_host(value: object) -> str:
    host = str(value or "")
    _require(host == host.lower() and host == host.strip(), "canonical host must be lowercase and trimmed")
    _require(0 < len(host) <= 253 and "." in host, "canonical host must be a non-wildcard DNS name")
    _require("*" not in host and ":" not in host and "/" not in host, "canonical host must not be wildcard, IP, or URL")
    labels = host.split(".")
    _require(all(_DNS_LABEL.fullmatch(label) for label in labels), "canonical host has an invalid DNS label")
    _require(host not in {"localhost", "local"} and not host.endswith(".localhost") and not host.endswith(".local"), "canonical host must not be local")
    _require(not re.fullmatch(r"[0-9.]+", host), "canonical host must not be an IP literal")
    return host


def validate_profile(profile: Mapping[str, object]) -> dict[str, object]:
    """Validate immutable profile inputs; activation is intentionally rejected."""

    _require(isinstance(profile, Mapping), "profile must be a mapping")
    _require(set(profile) == {"profile", "enabled", "host", "node_upstream"}, "profile fields are fixed")
    _require(profile["profile"] == PROFILE_NAME, "unknown deployment profile")
    _require(profile["enabled"] is False, "remote-caddy-v1 remains disabled pending a later approval")
    host = canonical_caddy_host(profile["host"])
    _require(profile["node_upstream"] == NODE_UPSTREAM, "Node upstream must be literal 127.0.0.1:8888")
    return {"profile": PROFILE_NAME, "enabled": False, "host": host, "node_upstream": NODE_UPSTREAM}


def render_caddyfile(profile: Mapping[str, object]) -> str:
    """Render the one production Caddyfile shape, without writing it anywhere."""

    checked = validate_profile(profile)
    host = str(checked["host"])
    return f'''# Generated only by deploy.caddy.profile; deployment remains disabled.
{{
\tadmin 127.0.0.1:2019
\tpersist_config off
\tgrace_period 35s
\tauto_https disable_redirects
\tservers {{
\t\tstrict_sni_host on
\t\tprotocols h1 h2
\t}}
}}

http:// {{
\t@canonical host {host}
\tredir @canonical https://{host}{{uri}} 308
\trespond 404
}}

https://{host} {{
\theader {{
\t\t-Server
\t\tStrict-Transport-Security "max-age={HSTS_MAX_AGE_SECONDS}"
\t}}
\t@timeline path /api/runs/*/events
\theader @timeline {{
\t\tCache-Control "private, no-store, no-transform"
\t\tX-Accel-Buffering "no"
\t}}
\treverse_proxy {NODE_UPSTREAM} {{
\t\theader_up -Forwarded
\t\theader_up -X-Real-IP
\t\theader_up Host {host}
\t}}
}}
'''


def _lock_error(message: str) -> DeploymentProfileError:
    return DeploymentProfileError(f"invalid Caddy release lock: {message}")


def load_release_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
    """Read and structurally pin the reviewed upstream release inventory."""

    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise _lock_error("lock is not a regular file")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _lock_error("lock is unreadable") from exc
    if not isinstance(raw, dict):
        raise _lock_error("top-level value is not an object")
    required = {"schema", "profile", "version", "release_base_url", "signed_checksums", "architectures", "module_inventory"}
    if set(raw) != required or raw["schema"] != 1 or raw["profile"] != PROFILE_NAME or raw["version"] != CADDY_VERSION:
        raise _lock_error("schema, profile, or version changed")
    expected_base = f"https://github.com/caddyserver/caddy/releases/download/v{CADDY_VERSION}/"
    if raw["release_base_url"] != expected_base:
        raise _lock_error("release origin changed")
    signed = raw["signed_checksums"]
    if not isinstance(signed, dict) or set(signed) != {"file", "sha256", "signature", "signature_sha256", "certificate", "certificate_sha256", "certificate_identity", "certificate_oidc_issuer"}:
        raise _lock_error("signed checksum inventory changed")
    for field in ("sha256", "signature_sha256", "certificate_sha256"):
        if not isinstance(signed[field], str) or not _SHA256.fullmatch(signed[field]):
            raise _lock_error(f"signed checksum {field} is invalid")
    if signed["certificate_identity"] != f"https://github.com/caddyserver/caddy/.github/workflows/release.yml@refs/tags/v{CADDY_VERSION}" or signed["certificate_oidc_issuer"] != "https://token.actions.githubusercontent.com":
        raise _lock_error("Cosign certificate identity changed")
    architectures = raw["architectures"]
    if not isinstance(architectures, dict) or set(architectures) != {"amd64", "arm64"}:
        raise _lock_error("Linux architecture inventory changed")
    for architecture, item in architectures.items():
        if not isinstance(item, dict) or set(item) != {"archive", "archive_sha256", "official_checksum_sha512", "sbom", "sbom_sha256"}:
            raise _lock_error(f"{architecture} inventory changed")
        for field in ("archive_sha256", "sbom_sha256"):
            if not isinstance(item[field], str) or not _SHA256.fullmatch(item[field]):
                raise _lock_error(f"{architecture} {field} is invalid")
        if not isinstance(item["official_checksum_sha512"], str) or not re.fullmatch(r"[0-9a-f]{128}", item["official_checksum_sha512"]):
            raise _lock_error(f"{architecture} official checksum is invalid")
        for field in ("archive", "sbom"):
            name = item[field]
            if not isinstance(name, str) or "/" in name or "\\" in name or not name.startswith(f"caddy_{CADDY_VERSION}_linux_{architecture}"):
                raise _lock_error(f"{architecture} {field} is not a pinned Linux release asset")
    module_inventory = raw["module_inventory"]
    if not isinstance(module_inventory, dict) or set(module_inventory) != {"command", "sha256", "meaning"}:
        raise _lock_error("module inventory changed")
    if module_inventory["command"] != ["list-modules", "--skip-standard", "--versions"] or module_inventory["sha256"] != hashlib.sha256(b"").hexdigest():
        raise _lock_error("module inventory is not the exact empty non-standard inventory")
    return raw


def _safe_regular(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DeploymentProfileError(f"required release asset is missing: {path.name}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise DeploymentProfileError(f"release asset is not a regular file: {path.name}")
    return metadata


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def caddy_subprocess_environment(state_root: Path) -> dict[str, str]:
    """Return the complete credential-free environment for Caddy commands."""

    root = Path(state_root)
    _require(root.is_absolute(), "Caddy subprocess state root must be absolute")
    return {
        "HOME": str(root),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_DATA_HOME": str(root / "data"),
    }


def _read_checked_asset(release_dir: Path, name: object, digest: object) -> Path:
    if not isinstance(name, str) or not isinstance(digest, str) or "/" in name or "\\" in name:
        raise DeploymentProfileError("release lock referenced an unsafe asset")
    asset = release_dir / name
    _safe_regular(asset)
    if _sha256_file(asset) != digest:
        raise DeploymentProfileError(f"release asset digest mismatch: {name}")
    return asset


def verify_signed_checksums(release_dir: Path, cosign_binary: Path, *, runner: Any = subprocess.run) -> None:
    """Verify Caddy's official signed checksum manifest with its pinned identity.

    Caddy publishes this release certificate as base64-encoded PEM. The decoded
    public certificate exists only in a temporary file for Cosign; this cannot
    create a TLS server certificate, state, key, or listener.
    """

    lock = load_release_lock()
    signed = lock["signed_checksums"]
    checksums = _read_checked_asset(release_dir, signed["file"], signed["sha256"])
    signature = _read_checked_asset(release_dir, signed["signature"], signed["signature_sha256"])
    certificate = _read_checked_asset(release_dir, signed["certificate"], signed["certificate_sha256"])
    _safe_regular(cosign_binary)
    encoded = certificate.read_bytes().strip()
    try:
        pem = encoded if encoded.startswith(b"-----BEGIN CERTIFICATE-----") else base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise DeploymentProfileError("Caddy release certificate encoding is invalid") from exc
    if not pem.startswith(b"-----BEGIN CERTIFICATE-----") or not pem.rstrip().endswith(b"-----END CERTIFICATE-----"):
        raise DeploymentProfileError("Caddy release certificate is not PEM")
    with tempfile.TemporaryDirectory(prefix="mentat-caddy-cosign-") as temporary:
        state_root = Path(temporary)
        decoded = state_root / "release-certificate.pem"
        decoded.write_bytes(pem)
        result = runner(
            [
                str(cosign_binary), "verify-blob", "--certificate", str(decoded), "--signature", str(signature),
                "--certificate-identity", str(signed["certificate_identity"]),
                "--certificate-oidc-issuer", str(signed["certificate_oidc_issuer"]), str(checksums),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=caddy_subprocess_environment(state_root),
        )
    if getattr(result, "returncode", 1) != 0:
        raise DeploymentProfileError("official Caddy checksum signature did not verify")


def verify_downloaded_release(
    release_dir: Path,
    architecture: str,
    *,
    caddy_binary: Path | None = None,
    runner: Any = subprocess.run,
) -> dict[str, str]:
    """Verify already-downloaded assets; this never downloads or installs Caddy."""

    lock = load_release_lock()
    if architecture not in lock["architectures"]:
        raise DeploymentProfileError("unsupported Linux architecture")
    try:
        metadata = release_dir.lstat()
    except OSError as exc:
        raise DeploymentProfileError("release directory is missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise DeploymentProfileError("release directory is unsafe")
    item = lock["architectures"][architecture]
    checked: dict[str, str] = {}
    for name_field, digest_field in (
        ("archive", "archive_sha256"),
        ("sbom", "sbom_sha256"),
    ):
        checked[name_field] = str(_read_checked_asset(release_dir, item[name_field], item[digest_field]))
    signed = lock["signed_checksums"]
    for name_field, digest_field in (
        ("file", "sha256"),
        ("signature", "signature_sha256"),
        ("certificate", "certificate_sha256"),
    ):
        checked[f"checksums_{name_field}"] = str(_read_checked_asset(release_dir, signed[name_field], signed[digest_field]))

    checksums = (release_dir / str(signed["file"])).read_text(encoding="utf-8", errors="strict")
    expected_line = f"{item['official_checksum_sha512']}  {item['archive']}"
    if expected_line not in checksums.splitlines():
        raise DeploymentProfileError("official checksum list does not attest the pinned archive")
    if caddy_binary is not None:
        _safe_regular(caddy_binary)
        with tempfile.TemporaryDirectory(prefix="mentat-caddy-binary-") as temporary:
            child_env = caddy_subprocess_environment(Path(temporary))
            version = runner(
                [str(caddy_binary), "version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                env=child_env,
            )
            version_tokens = str(getattr(version, "stdout", "")).strip().split()
            if getattr(version, "returncode", 1) != 0 or not version_tokens or version_tokens[0].removeprefix("v") != CADDY_VERSION:
                raise DeploymentProfileError("pinned Caddy binary version is not exact")
            command: Sequence[str] = [str(caddy_binary), *lock["module_inventory"]["command"]]
            modules = runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                env=child_env,
            )
            observed = str(getattr(modules, "stdout", "")).encode("utf-8")
            if getattr(modules, "returncode", 1) != 0 or hashlib.sha256(observed).hexdigest() != lock["module_inventory"]["sha256"]:
                raise DeploymentProfileError("Caddy binary has a non-standard or custom module")
        checked["binary"] = str(caddy_binary)
    return checked


def validate_deployment_state(state: Mapping[str, object], *, repository_root: Path) -> dict[str, str]:
    """Validate only the future profile's external, disabled state declaration.

    This intentionally validates no environment values, secrets, service units,
    or command lines.  A later root-owned activation must additionally check
    actual inode ownership and execute its own preview/confirmation transaction.
    """

    required = {
        "profile", "enabled", "service_account", "caddy_account", "config_path",
        "state_path", "log_path", "manifest_path", "binary_path",
    }
    _require(isinstance(state, Mapping) and set(state) == required, "deployment state fields are fixed")
    _require(state["profile"] == PROFILE_NAME and state["enabled"] is False, "deployment profile must remain disabled")
    _require(state["service_account"] == "mentat" and state["caddy_account"] == "caddy", "service accounts are fixed")
    root = repository_root.resolve(strict=False)
    paths: dict[str, str] = {}
    seen: list[Path] = []
    for field in ("config_path", "state_path", "log_path", "manifest_path", "binary_path"):
        value = state[field]
        _require(isinstance(value, str) and value.startswith("/") and "\\" not in value and ".." not in Path(value).parts, f"{field} must be an absolute Linux path")
        candidate = Path(value)
        _require(
            all(
                candidate != other
                and candidate not in other.parents
                and other not in candidate.parents
                for other in seen
            ),
            "deployment state paths must not overlap",
        )
        _require(root not in candidate.parents and candidate != root, "deployment state must stay outside the replaceable application tree")
        seen.append(candidate)
        paths[field] = value
    _require(paths["config_path"].startswith("/etc/mentat/caddy/"), "configuration must be root-owned external state")
    _require(paths["state_path"] == "/var/lib/caddy", "Caddy state directory is fixed")
    _require(paths["log_path"].startswith("/var/log/mentat/caddy/"), "logs must be external state")
    _require(paths["manifest_path"].startswith("/var/lib/mentat/caddy/"), "deployment manifest must be external state")
    _require(paths["binary_path"].startswith("/usr/local/lib/mentat/caddy/"), "pinned binary must be outside the application tree")
    return paths


def _validate_owned_component(
    metadata: os.stat_result,
    *,
    expected_uid: int,
    leaf: bool,
    directory: bool,
) -> None:
    expected_type = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if stat.S_ISLNK(metadata.st_mode) or not expected_type:
        raise DeploymentProfileError("deployment path is not the expected non-link type")
    allowed_owners = {expected_uid} if leaf else {0, expected_uid}
    if metadata.st_uid not in allowed_owners:
        raise DeploymentProfileError("deployment path owner is unsafe")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise DeploymentProfileError("deployment path is group or world writable")


def _validate_owned_path_fallback(path: Path, *, expected_uid: int, directory: bool) -> None:
    components = tuple(reversed(path.parents)) + (path,)
    try:
        for index, component in enumerate(components):
            leaf = index == len(components) - 1
            _validate_owned_component(
                component.lstat(),
                expected_uid=expected_uid,
                leaf=leaf,
                directory=directory if leaf else True,
            )
    except OSError as exc:
        raise DeploymentProfileError("deployment path is missing") from exc


def validate_owned_path(path: Path, *, expected_uid: int, directory: bool) -> None:
    """Descriptor-walk an absolute path without following unsafe components."""

    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or ".." in candidate.parts
        or expected_uid < 0
        or (os.name == "posix" and candidate.anchor != "/")
    ):
        raise DeploymentProfileError("deployment path is invalid")
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    if os.name != "posix" or not no_follow or not directory_flag:
        _validate_owned_path_fallback(
            candidate,
            expected_uid=expected_uid,
            directory=directory,
        )
        return

    current_fd: int | None = None
    try:
        current_fd = os.open(candidate.anchor, os.O_RDONLY | directory_flag | no_follow | close_on_exec)
        root_metadata = os.fstat(current_fd)
        _validate_owned_component(
            root_metadata,
            expected_uid=expected_uid,
            leaf=False,
            directory=True,
        )
        relative_parts = candidate.parts[1:]
        for index, part in enumerate(relative_parts):
            leaf = index == len(relative_parts) - 1
            flags = os.O_RDONLY | no_follow | close_on_exec
            if not leaf or directory:
                flags |= directory_flag
            else:
                flags |= getattr(os, "O_NONBLOCK", 0)
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
            _validate_owned_component(
                os.fstat(current_fd),
                expected_uid=expected_uid,
                leaf=leaf,
                directory=directory if leaf else True,
            )
    except OSError as exc:
        raise DeploymentProfileError("deployment path is missing or unsafe") from exc
    finally:
        if current_fd is not None:
            os.close(current_fd)
