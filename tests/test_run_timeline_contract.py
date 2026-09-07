"""Shared wire fixture verified against real canonical SQLite event projections."""

from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_runtime import AgentRun, RunStatus, SubmissionDisposition, SubmissionOutcome
from mentat.local_bridge import bridge_run_events_payload
from mentat_db import connect
from private_state import history_path
from run_repository import RunRepository, runtime_binding_digest
import server
from tests.sqlite_authority_support import ensure_run_sqlite_authority
from tests.test_run_repository import task_fixture, timestamp


FIXTURE = Path(__file__).parent / "fixtures" / "run_timeline_contract.json"


def canonical_timelines():
    payloads = []
    for status in (RunStatus.RUNNING, RunStatus.FAILED):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task = task_fixture()
            (root / "tasks.json").write_text(json.dumps([task]), encoding="utf-8")
            (root / "tasks.json").chmod(0o600)
            ensure_run_sqlite_authority(root, history_path(root))
            digest = runtime_binding_digest(
                agent_id="agent-main", runtime_type="codex",
                runtime_config_id="default", runtime_agent_ref="default",
                capabilities=("run.start",),
            )
            with closing(connect(root)) as connection:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="timeline-contract-key-0001",
                    dispatch_id="dispatch_timeline_contract",
                    run_id="run_timeline_contract", task=task, task_revision=1,
                    agent_id="agent-main", runtime_type="codex",
                    runtime_config_id="default", binding_digest=digest,
                    capabilities=("run.start",), now=timestamp(),
                )
                repository.claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=digest, now=timestamp(1),
                )
                repository.record_submission_outcome(
                    dispatch_id=reservation.dispatch_id,
                    outcome=SubmissionOutcome(
                        SubmissionDisposition.ACCEPTED,
                        run=AgentRun(
                            id=reservation.run_id, task_id=task["id"],
                            agent_id="agent-main", runtime_type="codex", status=status,
                        ),
                        runtime_run_ref="private-codex-reference",
                    ),
                    now=timestamp(2),
                )
            with patch.object(server, "DATA_DIR", root):
                payload, code = bridge_run_events_payload(reservation.run_id, 0)
            if code != 200:
                raise AssertionError(f"Canonical timeline failed: {code}")
            payloads.append(payload)
    return payloads


class RunTimelineContractTests(unittest.TestCase):
    def test_browser_fixture_matches_real_accepted_and_failed_codex_timelines(self):
        payloads = canonical_timelines()
        self.assertEqual(payloads, json.loads(FIXTURE.read_text(encoding="utf-8")))
        self.assertNotIn("private-codex-reference", json.dumps(payloads))


if __name__ == "__main__":
    unittest.main()
