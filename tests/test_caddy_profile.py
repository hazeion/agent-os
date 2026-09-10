from __future__ import annotations

import hashlib
import base64
from contextlib import redirect_stdout
import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from deploy.caddy.profile import (
    CADDY_VERSION,
    DeploymentProfileError,
    load_release_lock,
    render_caddyfile,
    validate_deployment_state,
    validate_owned_path,
    validate_profile,
    verify_downloaded_release,
    verify_signed_checksums,
)
from deploy.caddy import linux_harness


PROFILE = {"profile": "remote-caddy-v1", "enabled": False, "host": "mentat.example.com", "node_upstream": "127.0.0.1:8888"}


class _Result:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class CaddyProfileTests(unittest.TestCase):
    def test_renderer_is_exact_edge_only_and_never_enables_the_profile(self):
        rendered = render_caddyfile(PROFILE)
        self.assertIn("admin 127.0.0.1:2019", rendered)
        self.assertIn("https://mentat.example.com", rendered)
        self.assertIn("reverse_proxy 127.0.0.1:8888", rendered)
        self.assertIn("Strict-Transport-Security \"max-age=86400\"", rendered)
        self.assertIn("strict_sni_host on", rendered)
        self.assertIn("respond 404", rendered)
        self.assertIn("redir @canonical https://mentat.example.com{uri} 308", rendered)
        self.assertNotIn(" permanent", rendered)
        self.assertIn('Cache-Control "private, no-store, no-transform"', rendered)
        self.assertIn("@timeline path /api/runs/*/events", rendered)
        self.assertNotIn("flush_interval", rendered)
        for header in ("Forwarded", "X-Real-IP"):
            self.assertIn(f"header_up -{header}", rendered)
        for header in ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto"):
            self.assertNotIn(f"header_up -{header}", rendered)
            self.assertNotIn(f"header_up {header}", rendered)
        for prohibited in ("tls internal", "on_demand", "trusted_proxies", "proxy_protocol", "import ", "log {", "{$"):
            self.assertNotIn(prohibited, rendered)
        for bad_host in ("*.example.com", "127.0.0.1", "localhost", "mentat.local", "https://mentat.example.com", "MENTAT.example.com"):
            with self.subTest(bad_host=bad_host):
                with self.assertRaises(DeploymentProfileError):
                    render_caddyfile({**PROFILE, "host": bad_host})
        for field, value in (("enabled", True), ("node_upstream", "localhost:8888"), ("node_upstream", "127.0.0.1:9999")):
            with self.subTest(field=field, value=value):
                with self.assertRaises(DeploymentProfileError):
                    validate_profile({**PROFILE, field: value})

    def test_lock_is_exact_release_inventory_and_rejects_tampering(self):
        lock = load_release_lock()
        self.assertEqual(lock["version"], CADDY_VERSION)
        self.assertEqual(set(lock["architectures"]), {"amd64", "arm64"})
        self.assertEqual(lock["module_inventory"]["sha256"], hashlib.sha256(b"").hexdigest())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "lock.json"
            path.write_text('{"version":"2.11.4"}', encoding="utf-8")
            with self.assertRaises(DeploymentProfileError):
                load_release_lock(path)

    def test_release_verifier_rejects_wrong_digest_before_a_binary_runs(self):
        lock = load_release_lock()
        item = lock["architectures"]["amd64"]
        signed = lock["signed_checksums"]
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary) / "release"
            release.mkdir()
            # Deliberately invalid bytes must fail before a binary could run.
            for name in (item["archive"], item["sbom"], signed["file"], signed["signature"], signed["certificate"]):
                (release / name).write_bytes(b"wrong")
            with self.assertRaisesRegex(DeploymentProfileError, "digest mismatch"):
                verify_downloaded_release(release, "amd64")

    def test_release_verifier_rejects_nonstandard_module_output_after_asset_validation(self):
        lock = load_release_lock()
        item = lock["architectures"]["amd64"]
        signed = lock["signed_checksums"]
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary) / "release"
            release.mkdir()
            for name in (item["archive"], item["sbom"], signed["file"], signed["signature"], signed["certificate"]):
                (release / name).write_text("x", encoding="utf-8")
            (release / signed["file"]).write_text(f"{item['official_checksum_sha512']}  {item['archive']}\n", encoding="utf-8")
            binary = Path(temporary) / "caddy"
            binary.write_text("not executed", encoding="utf-8")
            digests = {
                item["archive"]: item["archive_sha256"], item["sbom"]: item["sbom_sha256"],
                signed["file"]: signed["sha256"], signed["signature"]: signed["signature_sha256"], signed["certificate"]: signed["certificate_sha256"],
            }
            environments = []
            def fake_hash(path: Path) -> str:
                return digests.get(path.name, "")
            def fake_runner(command, **kwargs):
                environments.append(kwargs.get("env"))
                if command[1:] == ["version"]:
                    return _Result(f"v{CADDY_VERSION} h1:fixture")
                return _Result("example.custom.module v1\n")
            with patch("deploy.caddy.profile._sha256_file", side_effect=fake_hash):
                with self.assertRaisesRegex(DeploymentProfileError, "custom module"):
                    verify_downloaded_release(release, "amd64", caddy_binary=binary, runner=fake_runner)
            self.assertEqual(len(environments), 2)
            self.assertEqual(environments[0], environments[1])
            self.assertEqual(
                set(environments[0]),
                {"HOME", "LANG", "LC_ALL", "PATH", "XDG_CONFIG_HOME", "XDG_DATA_HOME"},
            )

    def test_signed_checksum_gate_pins_caddy_release_identity(self):
        lock = load_release_lock()
        signed = lock["signed_checksums"]
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary) / "release"
            release.mkdir()
            pem = b"-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n"
            contents = {
                signed["file"]: b"checksums", signed["signature"]: b"signature",
                signed["certificate"]: base64.b64encode(pem),
            }
            for name, content in contents.items():
                (release / name).write_bytes(content)
            cosign = Path(temporary) / "cosign"
            cosign.write_text("not executed", encoding="utf-8")
            digests = {
                signed["file"]: signed["sha256"], signed["signature"]: signed["signature_sha256"],
                signed["certificate"]: signed["certificate_sha256"],
            }
            commands = []
            environments = []
            def fake_hash(path: Path) -> str:
                return digests.get(path.name, "")
            def fake_runner(command, **_kwargs):
                commands.append(command)
                environments.append(_kwargs.get("env"))
                return _Result("")
            with patch("deploy.caddy.profile._sha256_file", side_effect=fake_hash):
                verify_signed_checksums(release, cosign, runner=fake_runner)
            self.assertEqual(len(commands), 1)
            self.assertIn("verify-blob", commands[0])
            self.assertIn(signed["certificate_identity"], commands[0])
            self.assertIn(signed["certificate_oidc_issuer"], commands[0])
            self.assertEqual(
                set(environments[0]),
                {"HOME", "LANG", "LC_ALL", "PATH", "XDG_CONFIG_HOME", "XDG_DATA_HOME"},
            )

    def test_deployment_state_remains_external_and_disabled(self):
        state = {
            "profile": "remote-caddy-v1", "enabled": False, "service_account": "mentat", "caddy_account": "caddy",
            "config_path": "/etc/mentat/caddy/Caddyfile", "state_path": "/var/lib/caddy",
            "log_path": "/var/log/mentat/caddy/access-disabled.log", "manifest_path": "/var/lib/mentat/caddy/remote-caddy-v1.json",
            "binary_path": "/usr/local/lib/mentat/caddy/caddy",
        }
        checked = validate_deployment_state(state, repository_root=Path("/workspace/agent-os"))
        self.assertEqual(checked["state_path"], "/var/lib/caddy")
        for change in ({"enabled": True}, {"config_path": "/workspace/agent-os/Caddyfile"}, {"service_account": "root"}):
            with self.subTest(change=change):
                with self.assertRaises(DeploymentProfileError):
                    validate_deployment_state({**state, **change}, repository_root=Path("/workspace/agent-os"))

    def test_owned_path_gate_rejects_links_owner_mismatch_and_broad_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.write_text("x", encoding="utf-8")
            link = root / "link"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(DeploymentProfileError):
                validate_owned_path(link, expected_uid=0, directory=False)
            with patch.object(Path, "lstat", return_value=type("Stat", (), {"st_mode": stat.S_IFREG | stat.S_IWGRP, "st_uid": 0})()):
                with self.assertRaises(DeploymentProfileError):
                    validate_owned_path(target, expected_uid=0, directory=False)
            with patch.object(Path, "lstat", return_value=type("Stat", (), {"st_mode": stat.S_IFREG, "st_uid": 42})()):
                with self.assertRaises(DeploymentProfileError):
                    validate_owned_path(target, expected_uid=0, directory=False)

    def test_harness_output_reports_the_real_disposable_execution_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release, caddy, cosign, certificate, key = [root / name for name in ("release", "caddy", "cosign", "cert", "key")]
            release.mkdir()
            for path in (caddy, cosign, certificate, key):
                path.write_text("fixture", encoding="utf-8")
            stream = io.StringIO()
            with patch.object(linux_harness, "_require_linux"), patch.object(linux_harness, "verify_signed_checksums"), patch.object(linux_harness, "verify_downloaded_release"), patch.object(linux_harness, "validate_rendered_config"), patch.object(linux_harness, "run_disposable_integration") as integration, redirect_stdout(stream):
                result = linux_harness.main([
                    "--release-dir", str(release), "--architecture", "amd64", "--caddy-bin", str(caddy),
                    "--cosign-bin", str(cosign), "--host", "mentat.example.test", "--run-disposable",
                    "--test-cert", str(certificate), "--test-key", str(key),
                ])
            self.assertEqual(result, 0)
            integration.assert_called_once()
            self.assertIn("disposable loopback integration passed", stream.getvalue())

    def test_caddy_fmt_diff_accepts_context_only_and_rejects_changed_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            caddy = Path(temporary) / "caddy"
            caddy.write_text("fixture", encoding="utf-8")
            with patch(
                "deploy.caddy.linux_harness.subprocess.run",
                side_effect=[_Result("  canonical line\n"), _Result("")],
            ):
                linux_harness.validate_rendered_config(caddy, "mentat.example.test")
            with patch(
                "deploy.caddy.linux_harness.subprocess.run",
                return_value=_Result("- old line\n+ new line\n"),
            ):
                with self.assertRaisesRegex(DeploymentProfileError, "not canonical"):
                    linux_harness.validate_rendered_config(caddy, "mentat.example.test")

    def test_required_ci_uses_typed_paths_module_execution_and_both_architectures(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("verify_signed_checksums(release, Path(cosign))", workflow)
        self.assertIn('verify_downloaded_release(release, "amd64")', workflow)
        self.assertIn('verify_downloaded_release(release, "arm64")', workflow)
        self.assertIn("python -m deploy.caddy.linux_harness", workflow)
        self.assertNotIn("python deploy/caddy/linux_harness.py", workflow)

    def test_local_launchers_do_not_reference_the_disabled_profile(self):
        root = Path(__file__).resolve().parents[1]
        for relative in (
            "run.sh",
            "run.bat",
            "mentat_lifecycle.py",
            "mentat/cli.py",
            "mentat/web_runtime.py",
            "scripts/mentat_web_preview.py",
        ):
            with self.subTest(relative=relative):
                source = (root / relative).read_text(encoding="utf-8")
                self.assertNotIn("remote-caddy-v1", source)
                self.assertNotIn("deploy.caddy", source)


if __name__ == "__main__":
    unittest.main()
