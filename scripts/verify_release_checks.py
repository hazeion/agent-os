#!/usr/bin/env python3
"""Verify stable workflow jobs succeeded for the exact release commit."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

REQUIRED_WORKFLOWS = {
    "ci.yml": "CI required",
    "native-artifacts.yml": "Native artifacts required",
    "quality-gates.yml": "Quality gates required",
}


def latest_completed_run(payload: dict, sha: str) -> dict | None:
    matches = [
        run
        for run in payload.get("workflow_runs", [])
        if run.get("head_sha") == sha
        and run.get("event") == "push"
        and run.get("status") == "completed"
    ]
    return max(matches, key=lambda run: int(run.get("id", 0)), default=None)


def latest_named_job(payload: dict, name: str) -> dict | None:
    matches = [job for job in payload.get("jobs", []) if job.get("name") == name]
    return max(matches, key=lambda job: int(job.get("id", 0)), default=None)


def _fetch(url: str, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    sha = os.environ.get("GITHUB_SHA", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid GitHub repository identity")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("invalid release commit SHA")
    if not token:
        raise ValueError("missing GitHub workflow token")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    missing: list[str] = []
    for workflow, required_job in REQUIRED_WORKFLOWS.items():
        workflow_id = urllib.parse.quote(workflow, safe="")
        runs_url = (
            f"{api_url}/repos/{repository}/actions/workflows/{workflow_id}/runs"
            f"?head_sha={sha}&event=push&per_page=10"
        )
        run = latest_completed_run(_fetch(runs_url, headers), sha)
        if not run or run.get("conclusion") != "success":
            missing.append(required_job)
            continue
        jobs_url = (
            f"{api_url}/repos/{repository}/actions/runs/{run['id']}/jobs?per_page=100"
        )
        job = latest_named_job(_fetch(jobs_url, headers), required_job)
        if not job or job.get("status") != "completed" or job.get("conclusion") != "success":
            missing.append(required_job)
    if missing:
        print(f"Release checks not successful: {', '.join(sorted(missing))}", file=sys.stderr)
        return 1
    print("Exact release commit passed every stable required workflow job")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
