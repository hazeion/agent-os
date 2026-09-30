"""Private witnesses from the fixed owned scope, with no provider or Run."""

import sys
import unittest

from mentat.project_scope_evidence import ScopeWitness, witness_metadata
from mentat.project_worker_scope import LinuxWorkerScope, WorkerScopeError


class ScopeWitnessShapeTests(unittest.TestCase):
    def test_raw_metadata_boolean_or_foreign_issuer_cannot_be_a_closure_witness(self):
        for value in (True, False, {}, {"kind": "closed", "unit": "untrusted"}, "closed"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                witness_metadata(value, "closed")
        with self.assertRaises(ValueError):
            ScopeWitness("closed", {}, object(), object())


@unittest.skipUnless(sys.platform == "linux", "Fixed Linux scope required")
class LinuxScopeWitnessTests(unittest.TestCase):
    def test_exact_owned_scope_closure_is_required_and_retained(self):
        scope = LinuxWorkerScope()
        try:
            plan = scope.journal_plan()
            metadata = witness_metadata(plan, "planned")
            self.assertNotIn("pid", metadata)
            self.assertNotIn("invocation", metadata)
            metadata["unit"] = "changed"
            self.assertNotEqual(plan.private_metadata()["unit"], "changed")
            with self.assertRaises(WorkerScopeError):
                scope.journal_closed_identity()
            scope.start_inert()
            with self.assertRaises(WorkerScopeError):
                witness_metadata(plan, "planned")
            owned = scope.journal_owned_identity()
            identity = witness_metadata(owned, "owned")
            self.assertEqual(identity["unit"], plan.private_metadata()["unit"])
            with self.assertRaises(ValueError):
                witness_metadata(owned, "closed")
            scope.close_verified()
            closed = scope.journal_closed_identity()
            self.assertEqual(witness_metadata(closed, "closed"), identity)
            with self.assertRaises(WorkerScopeError):
                witness_metadata(owned, "owned")
        finally:
            if not scope._closed:
                scope.close_verified()


if __name__ == "__main__":
    unittest.main()
