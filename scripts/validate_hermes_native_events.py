#!/usr/bin/env python
"""Validate Mentat's native-event contract against an exact Hermes checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


EXPECTED_TAG = "v2026.8.13"
EXPECTED_COMMIT = "f80f453ae0679347e38abc917c7f94f717bf96c5"

EXPECTED_SOURCE_SHA256 = {
    "agent/conversation_loop.py": "0b88b0d56dc3ecec63cb9a00ebebf60d87b7c02fd7d99623e1a2ac44bc25ff2a",
    "agent/outbound_webhooks.py": "c4e62b873b3413d9f3ca4d71ed95a650c443d66c86786d2cabb9029e1a5caf56",
    "agent/turn_finalizer.py": "95771d4cf06fe43440703de10766c6df24aa2c62cfa938eb3bc7d26ddb5d7e58",
    "cli.py": "a22440657da66a7f4debaff4b4220a8917ce84437614d425fd0d8321e6f7fc19",
    "gateway/run.py": "54deb156ec7aa699e5bbd36aee9691d1a1e8cccfbb15266d42a559b39f1db742",
    "hermes_cli/kanban_db.py": "467770190ee6d9fa04b02e854ee4fc08c93365f90858b5245c9048e9dc1ab091",
    "hermes_cli/main.py": "b3a2fee833b79c9c8bf4f028e185843a78d1cb1d89f06eee284da97c563e0544",
    "hermes_cli/plugins.py": "fef960a63a926abe277e6441523656372a29f6862de070d20db24c617d495b6c",
    "model_tools.py": "770e2bc1f7d4eda7e6a4f83b2079073a50b09a13c7166ce9ce9544e98a2cf8ed",
    "run_agent.py": "5226bface19b4ed867de9a0dcd4e5f949e5e476d724969d8163353f5dfe7945f",
    "tools/delegate_tool.py": "eff2c5ad3609a8572ad8cd133a0f799a1b83cb23f4cb01fc232ef577428011a5",
}

REQUIRED_SOURCE_MARKERS = {
    "hermes_cli/plugins.py": (
        "on_session_finalize", "on_session_reset", "post_api_request",
        "api_request_error", "post_tool_call", "kanban_task_claimed",
        "kanban_task_completed", "kanban_task_blocked",
        "on_kanban_worker_spawned", "on_kanban_worker_exited",
        "on_kanban_worker_stale_claim", "on_kanban_task_updated",
        "on_kanban_dispatch_tick",
    ),
    "agent/outbound_webhooks.py": (
        "def register_from_config", "_serialize_payload",
        "X-Hermes-Signature-256", "delivery_id",
    ),
    "cli.py": (
        "register_outbound_webhooks(_hooks_cfg)",
        '"on_session_finalize"', '"on_session_reset"',
    ),
    "hermes_cli/main.py": ("register_outbound_webhooks(_hooks_cfg)",),
    "gateway/run.py": ("register_outbound_webhooks(_hooks_cfg)",),
    "agent/conversation_loop.py": ('"on_session_start"', '"post_api_request"'),
    "agent/turn_finalizer.py": ('"on_session_end"',),
    "run_agent.py": ('"api_request_error"',),
    "model_tools.py": ('"post_tool_call"',),
    "tools/delegate_tool.py": ('"subagent_start"', '"subagent_stop"'),
    "hermes_cli/kanban_db.py": (
        '"kanban_task_claimed"', '"kanban_task_completed"',
        '"kanban_task_blocked"', '"on_kanban_worker_spawned"',
        '"on_kanban_worker_exited"', '"on_kanban_worker_stale_claim"',
        '"on_kanban_task_updated"', '"on_kanban_dispatch_tick"',
        '"--accept-hooks"', '"chat"', '"-q"', "subprocess.Popen",
    ),
}


def _git_output(root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def validate_source(root: Path, *, require_exact: bool = True) -> dict:
    root = root.expanduser().resolve()
    failures: list[dict[str, object]] = []
    hashes: dict[str, str] = {}
    for relative_path, markers in REQUIRED_SOURCE_MARKERS.items():
        path = root / relative_path
        try:
            body = path.read_bytes()
            source_text = body.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            failures.append({"file": relative_path, "missing": ["<readable UTF-8 file>"]})
            continue
        hashes[relative_path] = hashlib.sha256(body).hexdigest()
        missing = [marker for marker in markers if marker not in source_text]
        if missing:
            failures.append({"file": relative_path, "missing": missing})
        if (
            require_exact
            and hashes[relative_path] != EXPECTED_SOURCE_SHA256[relative_path]
        ):
            failures.append(
                {
                    "file": relative_path,
                    "error": "unexpected_sha256",
                    "expected_sha256": EXPECTED_SOURCE_SHA256[relative_path],
                    "actual_sha256": hashes[relative_path],
                }
            )

    actual_commit = None
    actual_tag_commit = None
    dirty_inspected_source = None
    if require_exact:
        actual_commit = _git_output(root, "rev-parse", "HEAD")
        actual_tag_commit = _git_output(
            root, "rev-parse", f"refs/tags/{EXPECTED_TAG}^{{commit}}"
        )
        dirty_inspected_source = _git_output(
            root, "status", "--porcelain", "--", *REQUIRED_SOURCE_MARKERS
        )
        if actual_commit != EXPECTED_COMMIT:
            failures.append(
                {
                    "file": ".git",
                    "error": "unexpected_commit",
                    "expected": EXPECTED_COMMIT,
                    "actual": actual_commit,
                }
            )
        if actual_tag_commit != EXPECTED_COMMIT:
            failures.append(
                {
                    "file": ".git",
                    "error": "unexpected_tag_target",
                    "expected": EXPECTED_COMMIT,
                    "actual": actual_tag_commit,
                }
            )
        if dirty_inspected_source is None:
            failures.append({"file": ".git", "error": "source_identity_unverified"})
        elif dirty_inspected_source:
            failures.append({"file": ".git", "error": "inspected_source_dirty"})
    return {
        "ok": not failures,
        "expected_tag": EXPECTED_TAG,
        "expected_commit": EXPECTED_COMMIT,
        "actual_commit": actual_commit,
        "actual_tag_commit": actual_tag_commit,
        "exact_identity_required": require_exact,
        "files_checked": len(REQUIRED_SOURCE_MARKERS),
        "source_sha256": hashes,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-source", type=Path, required=True)
    args = parser.parse_args()
    result = validate_source(args.hermes_source)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
