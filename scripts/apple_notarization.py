#!/usr/bin/env python3
"""Submit one macOS package to Apple and safely follow that exact request."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Callable, Mapping, Sequence


PHASE_LIMIT_SECONDS = 4 * 60 * 60
SUBMIT_TIMEOUT_SECONDS = 10 * 60
STATUS_TIMEOUT_SECONDS = 2 * 60
LOG_TIMEOUT_SECONDS = 3 * 60
POLL_INTERVAL_SECONDS = 2 * 60
MAX_CONSECUTIVE_STATUS_FAILURES = 10
SUBMISSION_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class NotarizationError(RuntimeError):
    """A safe, operator-facing notarization failure."""


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise NotarizationError(f"Required protected environment value is missing: {name}")
    return value


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NotarizationError(f"Apple returned invalid structured output in {path.name}") from exc
    if not isinstance(payload, dict):
        raise NotarizationError(f"Apple returned an invalid object in {path.name}")
    return payload


def _run_to_file(
    command: Sequence[str],
    output_path: Path,
    timeout: float,
    runner: Callable[..., subprocess.CompletedProcess],
) -> None:
    if timeout <= 0:
        raise NotarizationError("No time remains for the Apple notarization command")
    with output_path.open("w", encoding="utf-8") as output:
        runner(command, check=True, stdout=output, text=True, timeout=timeout)


def _notary_command(
    action: str,
    credentials: Sequence[str],
    *arguments: str,
) -> list[str]:
    return ["xcrun", "notarytool", action, *arguments, *credentials]


def _credentials(environment: Mapping[str, str]) -> list[str]:
    return [
        "--apple-id",
        _required(environment, "MAC_NOTARY_APPLE_ID"),
        "--password",
        _required(environment, "MAC_NOTARY_PASSWORD"),
        "--team-id",
        _required(environment, "MAC_NOTARY_TEAM_ID"),
    ]


def _job_window(environment: Mapping[str, str], wall_clock: Callable[[], float]) -> float:
    deadline_epoch = float(_required(environment, "MENTAT_MACOS_NOTARY_DEADLINE_EPOCH"))
    return max(0.0, deadline_epoch - wall_clock())


def submit_package(
    package: Path,
    environment: Mapping[str, str],
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    monotonic: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
) -> str:
    if not package.is_file():
        raise NotarizationError("The signed macOS package does not exist")

    runner_temp = Path(_required(environment, "RUNNER_TEMP"))
    runner_temp.mkdir(parents=True, exist_ok=True)
    step_summary = Path(_required(environment, "GITHUB_STEP_SUMMARY"))
    step_output = Path(_required(environment, "GITHUB_OUTPUT"))
    credentials = _credentials(environment)

    start = monotonic()
    deadline = start + _job_window(environment, wall_clock)
    if deadline <= start:
        raise NotarizationError(
            "The reserved notarization window expired before submission; no upload was attempted"
        )

    submission_file = runner_temp / "mentat-notary-submission.json"
    submit_command = _notary_command(
        "submit",
        credentials,
        str(package),
        "--output-format",
        "json",
    )
    try:
        _run_to_file(
            submit_command,
            submission_file,
            min(SUBMIT_TIMEOUT_SECONDS, deadline - monotonic()),
            runner,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NotarizationError(
            "Apple submission did not return a request ID; the workflow will not resubmit automatically"
        ) from exc

    submission_id = str(_read_json(submission_file).get("id", ""))
    if not SUBMISSION_ID_PATTERN.fullmatch(submission_id):
        raise NotarizationError("Invalid notarization submission ID")
    try:
        with step_summary.open("a", encoding="utf-8") as summary:
            summary.write(f"Apple notarization submission: `{submission_id}`\n")
        with step_output.open("a", encoding="utf-8") as output:
            output.write(f"submission_id={submission_id}\n")
    except OSError as exc:
        raise NotarizationError(
            "The validated Apple submission ID could not be persisted to the completed step"
        ) from exc
    return submission_id


def wait_for_submission(
    submission_id: str,
    environment: Mapping[str, str],
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    monotonic: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    if not SUBMISSION_ID_PATTERN.fullmatch(submission_id):
        raise NotarizationError("Invalid notarization submission ID")
    runner_temp = Path(_required(environment, "RUNNER_TEMP"))
    runner_temp.mkdir(parents=True, exist_ok=True)
    credentials = _credentials(environment)
    start = monotonic()
    deadline = min(
        start + PHASE_LIMIT_SECONDS,
        start + _job_window(environment, wall_clock),
    )
    if deadline <= start:
        raise NotarizationError(
            f"The reserved status window expired for submission {submission_id}"
        )
    status_file = runner_temp / "mentat-notary-status.json"
    log_file = runner_temp / "mentat-notary-log.json"

    consecutive_failures = 0
    last_status = "not yet available"
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise NotarizationError(
                f"Status deadline expired for submission {submission_id}; "
                f"last known status: {last_status}"
            )
        info_command = _notary_command(
            "info",
            credentials,
            submission_id,
            "--output-format",
            "json",
        )
        try:
            _run_to_file(
                info_command,
                status_file,
                min(STATUS_TIMEOUT_SECONDS, remaining),
                runner,
            )
            last_status = str(_read_json(status_file).get("status", ""))
            consecutive_failures = 0
        except (OSError, subprocess.SubprocessError):
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_STATUS_FAILURES:
                raise NotarizationError(
                    f"Status remained unreachable for submission {submission_id} "
                    f"after {MAX_CONSECUTIVE_STATUS_FAILURES} consecutive checks"
                )
        else:
            if last_status == "Accepted":
                break
            if last_status in {"Invalid", "Rejected"}:
                log_command = [
                    "xcrun",
                    "notarytool",
                    "log",
                    submission_id,
                    *credentials,
                    str(log_file),
                ]
                remaining = deadline - monotonic()
                try:
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(log_command, 0)
                    runner(
                        log_command,
                        check=True,
                        text=True,
                        timeout=min(LOG_TIMEOUT_SECONDS, remaining),
                    )
                except (OSError, subprocess.SubprocessError):
                    print(
                        "Apple declined the submission and its diagnostic log could not be downloaded.",
                        file=sys.stderr,
                    )
                raise NotarizationError(
                    f"Apple notarization ended with status {last_status} for submission {submission_id}"
                )
            if last_status != "In Progress":
                raise NotarizationError(
                    f"Unexpected Apple notarization status {last_status!r} "
                    f"for submission {submission_id}"
                )

        remaining = deadline - monotonic()
        if remaining <= 0:
            continue
        sleep(min(POLL_INTERVAL_SECONDS, remaining))

    log_command = [
        "xcrun",
        "notarytool",
        "log",
        submission_id,
        *credentials,
        str(log_file),
    ]
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise NotarizationError(
            f"Apple accepted submission {submission_id} at the status deadline; "
            "no time remained to retrieve its completed log"
        )
    try:
        runner(
            log_command,
            check=True,
            text=True,
            timeout=min(LOG_TIMEOUT_SECONDS, remaining),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NotarizationError(
            f"Apple accepted submission {submission_id}, but its completed log could not be downloaded"
        ) from exc
    return submission_id


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2 or arguments[0] not in {"submit", "wait"}:
        print("usage: apple_notarization.py {submit SIGNED_PACKAGE|wait SUBMISSION_ID}", file=sys.stderr)
        return 2
    try:
        if arguments[0] == "submit":
            submit_package(Path(arguments[1]), os.environ)
        else:
            wait_for_submission(arguments[1], os.environ)
    except (NotarizationError, ValueError) as exc:
        print(f"Apple notarization failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
