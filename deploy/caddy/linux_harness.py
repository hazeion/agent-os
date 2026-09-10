#!/usr/bin/env python3
"""Explicit Linux-only validation harness for the disabled Caddy profile.

It never downloads, installs, starts, or reloads Caddy.  CI or an approved
disposable namespace must supply an already verified binary and, for a full
network drill, a separately approved runner.  Keeping this harness dry is what
prevents an ordinary checkout from acquiring certificates or opening ports.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

from deploy.caddy.profile import (
    DeploymentProfileError,
    caddy_subprocess_environment,
    render_caddyfile,
    verify_downloaded_release,
    verify_signed_checksums,
)
from deploy.caddy.disposable_integration import run_disposable_integration


def _require_linux() -> None:
    if sys.platform != "linux":
        raise DeploymentProfileError("Caddy integration harness is Linux-only")


def _run(command: list[str], *, state_root: Path) -> None:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=caddy_subprocess_environment(state_root),
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise DeploymentProfileError(f"Caddy validation failed: {detail[-500:]}")


def validate_rendered_config(caddy: Path, host: str) -> None:
    """Run Caddy's parser only against a temporary file; no listener is opened."""

    with tempfile.TemporaryDirectory(prefix="mentat-caddy-validate-") as temporary:
        state_root = Path(temporary)
        config = state_root / "Caddyfile"
        config.write_text(render_caddyfile({"profile": "remote-caddy-v1", "enabled": False, "host": host, "node_upstream": "127.0.0.1:8888"}), encoding="utf-8")
        formatted = subprocess.run(
            [str(caddy), "fmt", "--diff", "--config", str(config)],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=caddy_subprocess_environment(state_root),
        )
        changed = any(
            line.startswith(("+ ", "- "))
            for line in formatted.stdout.splitlines()
        )
        if formatted.returncode or changed:
            detail = (formatted.stderr or formatted.stdout).strip()
            raise DeploymentProfileError(f"Caddyfile is not canonical: {detail[-500:]}")
        _run(
            [str(caddy), "adapt", "--validate", "--config", str(config), "--adapter", "caddyfile"],
            state_root=state_root,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", required=True, type=Path, help="pre-downloaded pinned release assets")
    parser.add_argument("--architecture", choices=("amd64", "arm64"), required=True)
    parser.add_argument("--caddy-bin", required=True, type=Path, help="pre-extracted Caddy binary")
    parser.add_argument("--cosign-bin", required=True, type=Path, help="pre-installed Cosign binary")
    parser.add_argument("--host", required=True, help="reviewed non-wildcard DNS name")
    parser.add_argument("--run-disposable", action="store_true", help="also run explicit real-Caddy loopback gates")
    parser.add_argument("--test-cert", type=Path, help="caller-supplied disposable TLS certificate")
    parser.add_argument("--test-key", type=Path, help="caller-supplied disposable TLS private key")
    args = parser.parse_args(argv)
    try:
        _require_linux()
        verify_signed_checksums(args.release_dir, args.cosign_bin)
        # This dry harness next verifies locked asset identities, exact binary
        # version, empty custom-module inventory, and the Caddy parser.
        verify_downloaded_release(args.release_dir, args.architecture, caddy_binary=args.caddy_bin)
        validate_rendered_config(args.caddy_bin, args.host)
        if args.run_disposable:
            if args.test_cert is None or args.test_key is None:
                raise DeploymentProfileError("--run-disposable requires caller-supplied --test-cert and --test-key")
            run_disposable_integration(caddy=args.caddy_bin, certificate=args.test_cert, key=args.test_key, host=args.host)
    except (DeploymentProfileError, OSError, subprocess.SubprocessError) as exc:
        print(f"disabled Caddy harness failed: {exc}", file=sys.stderr)
        return 1
    if args.run_disposable:
        print("disabled Caddy profile and disposable loopback integration passed; no public listener or ACME certificate was used")
    else:
        print("disabled Caddy profile parser gate passed; no listener, certificate, install, or reload was attempted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
