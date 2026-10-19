"""Real qualification scopes require their original committed scope receipt."""
from contextlib import closing
import sys
import unittest
from unittest.mock import patch

import mentat_db
import private_console_unit
import project_inference_broker as broker
import project_scope_journal as scopes
from run_repository import RunRepository, RunRepositoryError
from mentat.project_worker_scope import LinuxWorkerScope
from tests import test_project_inference_broker as fixtures
from tests.test_project_worker_journal import GENERATION
from tests.qualification_scope_support import start_recorded_scope, close_recorded_scope


@unittest.skipUnless(sys.platform=='linux','Actual owned Linux scope required')
class ScopedQualificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ProjectInferenceBrokerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root,self.run=self.fixture.root,self.fixture.run

    def test_owned_scope_qualifies_without_archival_or_default_source_acceptance(self):
        scope=LinuxWorkerScope()
        receipt=None
        actual=None
        try:
            original_start=scope.start_inert
            def check_starting_commit():
                with closing(mentat_db.connect(self.root)) as connection:
                    retained=scopes.read_scope(connection,self.run)
                    self.assertEqual((retained.state,retained.revision),('starting',2))
                    self.assertIsNone(scope._process)
                return original_start()
            with patch.object(scope,'start_inert',side_effect=check_starting_commit):
                receipt=start_recorded_scope(self.root,self.run,GENERATION,scope)
            with closing(mentat_db.connect(self.root)) as connection:
                RunRepository(connection).validate(private_qualification_proposals=True)
                with self.assertRaises(RunRepositoryError): RunRepository(connection).validate()
                with self.assertRaises(RunRepositoryError):
                    RunRepository(connection).validate(private_archival_proposals=True)
                with self.assertRaises(RunRepositoryError):
                    RunRepository(connection).validate(private_archival_proposals=True,private_qualification_proposals=True)
            with self.assertRaises(private_console_unit.PrivateConsoleUnitError):
                private_console_unit.capture_private_console_unit(self.root)
            actual=broker.QualificationInferenceBroker(self.root,self.run,GENERATION,self.fixture.backend,scope)
            reply=actual.handle_body(self.fixture._body())
            self.assertNotEqual(reply,broker._UNKNOWN)
            self.assertEqual(self.fixture.backend.calls,1)
            self.assertEqual(tuple(self.fixture._call_state()[:3]),('succeeded',1,'PROBE_OK'))
        finally:
            if actual is not None: actual.stop()
            if receipt is not None: close_recorded_scope(self.root,self.run,GENERATION,scope,receipt)
            elif not scope._closed: scope.close_verified()
        with closing(mentat_db.connect(self.root)) as connection:
            RunRepository(connection).validate(private_archival_proposals=True)

    def test_unrecorded_real_scope_never_falls_back_to_os_or_synthetic_scope(self):
        scope=LinuxWorkerScope()
        try:
            scope.start_inert()
            with self.assertRaises(broker.InferenceBrokerError):
                broker.QualificationInferenceBroker(self.root,self.run,GENERATION,self.fixture.backend,scope)
            self.assertEqual(self.fixture.backend.calls,0)
            self.assertIsNone(self.fixture._call_state())
        finally: scope.close_verified()

    def test_changed_scope_state_refuses_new_debit_and_known_result_replay(self):
        for submitted in (False,True):
            with self.subTest(submitted=submitted):
                # Each attempt owns a new complete disposable fixture.
                fixture=fixtures.ProjectInferenceBrokerTests()
                fixture.setUp()
                scope=LinuxWorkerScope()
                receipt=None
                actual=None
                try:
                    receipt=start_recorded_scope(fixture.root,fixture.run,GENERATION,scope)
                    actual=broker.QualificationInferenceBroker(fixture.root,fixture.run,GENERATION,fixture.backend,scope)
                    if submitted: self.assertNotEqual(actual.handle_body(fixture._body()),broker._UNKNOWN)
                    with closing(mentat_db.connect(fixture.root)) as connection:
                        connection.execute('BEGIN IMMEDIATE')
                        changed=scopes.transition_scope(connection,run_id=fixture.run,generation=GENERATION,
                            claim_token=receipt[0],expected_revision=receipt[1],target='unknown')
                        connection.commit()
                    receipt=(receipt[0],changed.revision)
                    self.assertEqual(actual.handle_body(fixture._body()),broker._UNKNOWN)
                    self.assertEqual(fixture.backend.calls,int(submitted))
                    self.assertEqual(fixture._call_state() is not None,submitted)
                finally:
                    if actual is not None: actual.stop()
                    if receipt is not None: close_recorded_scope(fixture.root,fixture.run,GENERATION,scope,receipt)
                    elif not scope._closed: scope.close_verified()
                    fixture.doCleanups()

    def test_synthetic_scope_cannot_override_a_recorded_real_scope(self):
        scope=LinuxWorkerScope()
        receipt=None
        try:
            receipt=start_recorded_scope(self.root,self.run,GENERATION,scope)
            with self.assertRaises(broker.InferenceBrokerError):
                broker.QualificationInferenceBroker(self.root,self.run,GENERATION,self.fixture.backend,self.fixture.scope)
            self.assertEqual(self.fixture.backend.calls,0)
        finally:
            if receipt is not None: close_recorded_scope(self.root,self.run,GENERATION,scope,receipt)
            elif not scope._closed: scope.close_verified()

    def test_wrong_kernel_scope_and_changed_epoch_refuse_before_backend(self):
        scope=LinuxWorkerScope()
        other=LinuxWorkerScope()
        receipt=None
        actual=None
        try:
            receipt=start_recorded_scope(self.root,self.run,GENERATION,scope)
            other.start_inert()
            with self.assertRaises(broker.InferenceBrokerError):
                broker.QualificationInferenceBroker(self.root,self.run,GENERATION,self.fixture.backend,other)
            actual=broker.QualificationInferenceBroker(self.root,self.run,GENERATION,self.fixture.backend,scope)
            with closing(mentat_db.connect(self.root)) as connection:
                connection.execute('UPDATE mentat_project_context_access_state SET approval_epoch=? WHERE singleton=1',(b'z'*32,))
                connection.commit()
            self.assertEqual(actual.handle_body(self.fixture._body()),broker._UNKNOWN)
            self.assertEqual(self.fixture.backend.calls,0)
            self.assertIsNone(self.fixture._call_state())
        finally:
            if actual is not None: actual.stop()
            if not other._closed: other.close_verified()
            if receipt is not None: close_recorded_scope(self.root,self.run,GENERATION,scope,receipt)
            elif not scope._closed: scope.close_verified()


if __name__=='__main__':
    unittest.main()
