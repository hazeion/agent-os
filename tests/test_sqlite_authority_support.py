"""Bounded worker cleanup preserves errors and live-worker fixture roots."""

from pathlib import Path
import shutil
import unittest
from unittest.mock import Mock

from tests import sqlite_authority_support as support


class WorkerDrainTests(unittest.TestCase):
    def stuck_worker(self):
        worker = Mock(ident=123, name="stuck-sqlite-worker")
        worker.is_alive.return_value = True
        return worker

    def test_stuck_worker_fails_with_bounded_join_and_retains_root(self):
        worker = self.stuck_worker()
        root = None
        try:
            with self.assertRaisesRegex(AssertionError, "stuck-sqlite-worker") as raised:
                with support.TemporaryDirectory() as root:
                    with support.drain_workers([worker]):
                        pass
            self.assertTrue(Path(root).is_dir())
            self.assertIn(root, str(raised.exception))
            timeout = worker.join.call_args.args[0]
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, support.THREAD_TIMEOUT)
        finally:
            if root:
                shutil.rmtree(root)

    def test_original_failure_remains_primary_with_stuck_worker_diagnostics(self):
        worker = self.stuck_worker()
        error = AssertionError("original ordering failure")
        root = None
        try:
            with self.assertRaises(AssertionError) as raised:
                with support.TemporaryDirectory() as root:
                    with support.drain_workers([worker]):
                        raise error
            self.assertIs(raised.exception, error)
            self.assertIn(root, error.__notes__[0])
            self.assertIn("stuck-sqlite-worker", error.__notes__[0])
            self.assertTrue(Path(root).is_dir())
        finally:
            if root:
                shutil.rmtree(root)

    def test_completed_worker_releases_gate_and_allows_root_cleanup(self):
        worker, gate = Mock(ident=123), Mock()
        worker.is_alive.return_value = False
        with support.TemporaryDirectory() as root:
            with support.drain_workers([worker], gate):
                pass
            gate.set.assert_called_once()
            worker.join.assert_called_once()
            self.assertTrue(Path(root).is_dir())
        self.assertFalse(Path(root).exists())
