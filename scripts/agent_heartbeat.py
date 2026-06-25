#!/usr/bin/env python
"""Publish live Agent Pulse heartbeats to a local Mentat dashboard.

Usage examples:

  python scripts/agent_heartbeat.py beat --name Hermes --status running \
    --project Mentat --current-task "Working on Agent Pulse"

  python scripts/agent_heartbeat.py run --name "Codex Worker" --project Mentat \
    --current-task "Implement feature" --interval 30 -- python worker.py

The script intentionally talks only to Mentat's project-owned API. It does not
modify Hermes core files or read private Hermes internals.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = os.environ.get("MENTAT_URL", "http://127.0.0.1:8888")
VALID_STATUSES = {"running", "idle", "blocked", "done", "failed"}


def str_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", ""}:
        return False
    raise argparse.ArgumentTypeError(f"Expected a boolean value, got {value!r}")


def heartbeat_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/api/agents/heartbeat"


def example_commands(base_url: str = DEFAULT_BASE_URL) -> dict[str, str]:
    resolved = base_url.rstrip("/")
    return {
        "beat": f'python scripts/agent_heartbeat.py beat --base-url {resolved} --name "Hermes" --project Mentat --current-task "Working on Mentat"',
        "run": f'python scripts/agent_heartbeat.py run --base-url {resolved} --name "Hermes Worker" --project Mentat --current-task "Implement feature" --interval 15 -- python worker.py',
    }


def build_payload(args: argparse.Namespace, *, status: str | None = None, latest_output: str | None = None) -> dict[str, Any]:
    resolved_status = status or args.status
    if resolved_status == "active":
        resolved_status = "running"
    if resolved_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status {resolved_status!r}; expected one of {sorted(VALID_STATUSES)}")

    payload = {
        "name": args.name,
        "status": resolved_status,
        "current_task": args.current_task,
        "project": args.project,
        "cwd": args.cwd or os.getcwd(),
        "model": args.model,
        "source": args.source,
        "latest_output": latest_output if latest_output is not None else args.latest_output,
        "needs_user_input": args.needs_user_input,
        "related_task_id": args.related_task_id,
    }
    if args.agent_id:
        payload["id"] = args.agent_id
    return {key: value for key, value in payload.items() if value not in (None, "")}


def post_heartbeat(base_url: str, payload: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        heartbeat_url(base_url),
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Mentat heartbeat rejected with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Mentat at {base_url}: {exc.reason}") from exc

    return json.loads(raw or "{}")


def print_result(label: str, result: dict[str, Any]) -> None:
    agent = result.get("agent") or {}
    summary = result.get("summary") or {}
    print(
        json.dumps(
            {
                "event": label,
                "ok": bool(result.get("ok")),
                "agent_id": agent.get("id"),
                "name": agent.get("name"),
                "status": agent.get("status"),
                "last_heartbeat": agent.get("last_heartbeat"),
                "summary": summary,
            },
            indent=2,
        )
    )


def command_after_separator(command: list[str]) -> list[str]:
    if command and command[0] == "--":
        command = command[1:]
    return command


def beat(args: argparse.Namespace) -> int:
    payload = build_payload(args)
    result = post_heartbeat(args.base_url, payload, timeout=args.timeout)
    print_result("heartbeat", result)
    return 0


def examples(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            {
                "base_url": args.base_url,
                "commands": example_commands(args.base_url),
                "notes": [
                    "Use beat for a one-shot status update.",
                    "Use run to wrap a long-running worker and publish periodic heartbeats.",
                ],
            },
            indent=2,
        )
    )
    return 0


def run_with_heartbeat(args: argparse.Namespace) -> int:
    command = command_after_separator(args.command)
    if not command:
        raise SystemExit("run requires a command after --")

    start_payload = build_payload(args, status="running", latest_output=args.latest_output or f"Starting command: {' '.join(command)}")
    start_result = post_heartbeat(args.base_url, start_payload, timeout=args.timeout)
    print_result("started", start_result)

    process = subprocess.Popen(command, cwd=args.cwd or None)
    try:
        while True:
            exit_code = process.poll()
            if exit_code is not None:
                final_status = "done" if exit_code == 0 else "failed"
                final_payload = build_payload(
                    args,
                    status=final_status,
                    latest_output=f"Command exited with code {exit_code}: {' '.join(command)}",
                )
                final_result = post_heartbeat(args.base_url, final_payload, timeout=args.timeout)
                print_result(final_status, final_result)
                return exit_code

            time.sleep(max(args.interval, 1))
            pulse_payload = build_payload(
                args,
                status="running",
                latest_output=f"Command still running with PID {process.pid}: {' '.join(command)}",
            )
            pulse_result = post_heartbeat(args.base_url, pulse_payload, timeout=args.timeout)
            print_result("heartbeat", pulse_result)
    except KeyboardInterrupt:
        process.terminate()
        interrupted_payload = build_payload(args, status="blocked", latest_output="Wrapper interrupted; child process terminated")
        interrupted_payload["needs_user_input"] = True
        interrupted_result = post_heartbeat(args.base_url, interrupted_payload, timeout=args.timeout)
        print_result("interrupted", interrupted_result)
        raise


def add_common_agent_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Mentat base URL; defaults to MENTAT_URL or http://127.0.0.1:8888")
    parser.add_argument("--agent-id", help="Stable ID to upsert; omit to derive from --name")
    parser.add_argument("--name", required=True, help="Agent display name")
    parser.add_argument("--status", default="running", help="Agent status: running, idle, blocked, done, failed")
    parser.add_argument("--current-task", help="Short description of what the agent is doing")
    parser.add_argument("--project", default="Mentat", help="Related project name")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory to report and use for wrapped commands")
    parser.add_argument("--model", help="Model/provider label, if known")
    parser.add_argument("--source", default="heartbeat-script", help="Source label stored with the heartbeat")
    parser.add_argument("--latest-output", help="Short status/output summary")
    parser.add_argument("--needs-user-input", type=str_bool, default=False, help="Whether this agent currently needs user input")
    parser.add_argument("--related-task-id", help="Mentat task ID related to this agent run")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout in seconds")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish Agent Pulse heartbeat records to Mentat")
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    examples_parser = subparsers.add_parser("examples", help="Print ready-to-run producer wiring examples")
    examples_parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Mentat base URL; defaults to MENTAT_URL or http://127.0.0.1:8888")
    examples_parser.set_defaults(func=examples)

    beat_parser = subparsers.add_parser("beat", help="Publish one heartbeat record")
    add_common_agent_args(beat_parser)
    beat_parser.set_defaults(func=beat)

    run_parser = subparsers.add_parser("run", help="Wrap a command and publish running/done/failed heartbeats")
    add_common_agent_args(run_parser)
    run_parser.add_argument("--interval", type=float, default=30.0, help="Seconds between running heartbeats")
    run_parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after --")
    run_parser.set_defaults(func=run_with_heartbeat)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"agent_heartbeat.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
