"""Private readback parsing and fixed inert-scope observations."""

import sys
import time
import unittest
from contextlib import closing
import hashlib
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mentat import project_scope_readback as readback
from mentat import project_scope_inspector as inspector
from mentat.project_worker_scope import LinuxWorkerScope
import mentat_db
import project_scope_journal as journal
from private_state import database_path
from tests.test_project_scope_journal import _ScopeJournalFixture
from tests.test_project_worker_journal import GENERATION


class ReadbackReplyTests(unittest.TestCase):
    def test_duplicate_extra_non_ascii_oversized_and_malformed_fields_fail(self):
        fields=frozenset({'a','b'})
        self.assertEqual(readback._ascii_fields(b'a=1\nb=2\n',fields),{'a':'1','b':'2'})
        for raw in (b'a=1\na=2\nb=2',b'a=1\nb=2\nc=3',b'a=\xff\nb=2',b'a=1',b'a=1\n\nb=2',b'x'*8193):
            with self.subTest(raw=raw[:20]),self.assertRaises(readback.ScopeReadbackError):
                readback._ascii_fields(raw,fields)

    def test_expired_budget_never_queries_a_unit(self):
        with patch.object(readback,'_plan'),patch.object(readback,'_identity'),patch.object(readback,'_unit_state') as query:
            self.assertEqual(readback._observe_kernel({},None,time.monotonic()-1).state,'unknown')
        query.assert_not_called()

    def test_public_entry_rejects_platform_and_arbitrary_references(self):
        with self.assertRaises(ValueError):
            inspector.inspect_scope('arbitrary',run_id='run_x',generation=GENERATION,expected_revision=1)

    def test_contradictory_reply_and_stale_timestamp_are_rejected(self):
        valid={'state':'matching_empty','reason':'descriptor_empty','sampled_at':101}
        self.assertTrue(inspector._valid_result(valid,100,102))
        for altered in ({**valid,'reason':'launcher_matching'},{**valid,'sampled_at':99},
                        {**valid,'sampled_at':103},{**valid,'sampled_at':float('nan')},
                        {**valid,'state':[]},{**valid,'extra':'no'}):
            self.assertFalse(inspector._valid_result(altered,100,102))

    def test_late_cleanup_discards_otherwise_matching_candidate(self):
        class Slot:
            closed=False
            def __init__(self,*args,**kwargs): pass
            def execute(self,**kwargs):
                return {'state':'matching_empty','reason':'descriptor_empty','sampled_at':101}
            def close(self): Slot.closed=True
        with patch.object(inspector,'_InspectionSlot',Slot),patch.object(inspector.sys,'platform','linux'),\
             patch.object(inspector.time,'monotonic',side_effect=(0,1,9.9,10.1)),patch.object(inspector.time,'time',return_value=101):
            result=inspector.inspect_scope(Path.cwd(),run_id='run_x',generation=GENERATION,expected_revision=1)
        self.assertTrue(Slot.closed)
        self.assertEqual(result.state,'unknown')


@unittest.skipUnless(sys.platform=='linux','Actual Linux private snapshot required')
class ReferenceReadbackTests(_ScopeJournalFixture,unittest.TestCase):
    def fingerprint(self):
        path=database_path(self.root)
        return {str(item):hashlib.sha256(item.read_bytes()).hexdigest()
                for item in path.parent.glob(path.name+'*')}

    def test_fixed_worker_reads_committed_prepared_without_mutating_source(self):
        first=self.prepare()
        before=self.fingerprint()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-do-not-inherit','MENTAT_BRIDGE_TOKEN':'synthetic'}):
            result=inspector.inspect_scope(self.root,run_id=self.run,generation=GENERATION,expected_revision=first.revision)
        self.assertEqual((result.state,result.reason),('unknown','no_kernel_identity'),result)
        self.assertEqual(self.fingerprint(),before)

    def test_historical_schema44_readback_preserves_source_without_migration(self):
        first=self.prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DROP TRIGGER mentat_project_output_reservation_immutable')
            connection.execute('DROP TRIGGER mentat_project_output_reservation_retained')
            connection.execute('DROP TABLE mentat_project_output_reservations')
            connection.execute('DELETE FROM schema_migrations WHERE version=45')
            connection.commit()
        before=self.fingerprint()
        result=inspector.inspect_scope(self.root,run_id=self.run,generation=GENERATION,expected_revision=first.revision)
        self.assertEqual((result.state,result.reason),('unknown','no_kernel_identity'),result)
        self.assertEqual(self.fingerprint(),before)

    def test_uncommitted_change_is_not_observed_and_exact_references_fail_closed(self):
        self.prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('UPDATE mentat_project_context_access_state SET approval_epoch=? WHERE singleton=1',(b'z'*32,))
            result=inspector.inspect_scope(self.root,run_id=self.run,generation=GENERATION,expected_revision=1)
            connection.rollback()
        self.assertEqual(result.reason,'no_kernel_identity',result)
        for run,generation,revision in ((self.run,'c'*32,1),(self.run,GENERATION,2),('run_missing',GENERATION,1)):
            result=inspector.inspect_scope(self.root,run_id=run,generation=generation,expected_revision=revision)
            self.assertEqual(result.state,'unknown',result)

    def test_restore_epoch_fences_kernel_lookup_and_receipt_change_discards_sample(self):
        self.prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('UPDATE mentat_project_context_access_state SET approval_epoch=? WHERE singleton=1',(b'z'*32,))
            connection.commit()
        with patch.object(readback,'_observe_kernel') as query:
            result=readback._inspect_reference(self.root,self.run,GENERATION,1,time.monotonic()+10)
        self.assertEqual(result.reason,'authority_fenced')
        query.assert_not_called()
        original=readback._reference_snapshot
        calls=[]
        def changed(*args):
            value=original(*args)
            calls.append(value)
            if len(calls)==2:
                value=(*value[:2],'changed-digest',*value[3:])
            return value
        with patch.object(readback,'_reference_snapshot',side_effect=changed):
            result=readback._inspect_reference(self.root,self.run,GENERATION,1,time.monotonic()+10)
        self.assertEqual(result.reason,'reference_changed')

    def test_redirected_data_root_is_not_followed(self):
        self.prepare()
        with TemporaryDirectory() as directory:
            redirected=Path(directory)/'alias'
            redirected.symlink_to(self.root,target_is_directory=True)
            result=inspector.inspect_scope(redirected,run_id=self.run,generation=GENERATION,expected_revision=1)
        self.assertEqual(result.state,'unknown',result)

    def test_missing_malformed_authority_and_dropped_guard_refuse_before_kernel(self):
        self.prepare()
        statements=('DELETE FROM mentat_run_store_state',
                    "UPDATE mentat_run_store_state SET source_sha256='"+'z'*64+"'",
                    'DROP TRIGGER mentat_runs_project_proposal_closed_insert')
        for statement in statements:
            with closing(mentat_db.connect(self.root)) as connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute(statement)
                # Test the committed-snapshot validator without committing the
                # deliberately damaged synthetic source between subcases.
                connection.commit()
            with patch.object(readback,'_observe_kernel') as query,self.assertRaises(Exception):
                readback._inspect_reference(self.root,self.run,GENERATION,1,time.monotonic()+10)
            query.assert_not_called()
            # Each subcase owns a fresh disposable graph, never repairs source
            # authority through a production fallback.
            if statement!=statements[-1]:
                self.fixture.doCleanups()
                self.setUp()
                self.prepare()

    def test_actual_owned_scope_survives_observation_without_lifecycle_change(self):
        self.scope=LinuxWorkerScope()
        try:
            first=self.prepare()
            starting=self.move(first,'starting')
            self.scope.start_inert()
            owned=self.move(journal.ScopeReceipt(first.run_id,first.generation,starting.state,starting.revision,False,first.claim_token),
                            'owned',witness=self.scope.journal_owned_identity())
            before=self.fingerprint()
            result=inspector.inspect_scope(self.root,run_id=self.run,generation=GENERATION,expected_revision=owned.revision)
            self.assertEqual((result.state,result.reason),('matching_populated','launcher_matching'),result)
            self.assertEqual(self.fingerprint(),before)
            with self.assertRaises(journal.ScopeJournalError):
                self.move(journal.ScopeReceipt(first.run_id,first.generation,owned.state,owned.revision,False,first.claim_token),
                          'stopped',witness=result)
            self.assertEqual(self.fingerprint(),before)
            self.scope.stop_local_and_verify()
        finally:
            if not self.scope._closed:
                self.scope.close_verified()


@unittest.skipUnless(sys.platform=='linux','Owned Linux inspection process required')
class InspectionBoundaryTests(unittest.TestCase):
    def test_parent_watchdog_reaps_stalled_worker_without_replacement(self):
        started=time.monotonic()
        slot=inspector._InspectionSlot((sys.executable,'-I','-c','import time;time.sleep(60)'),
            deadline=started+0.25,clock=time.monotonic,environment={'LANG':'C.UTF-8'},
            operation_watchdog_seconds=0.25,maximum_line_bytes=4096)
        process=slot._process
        try:
            with self.assertRaises(Exception):
                slot.execute(kind='scope_readback',url='{}')
        finally:
            slot.close()
        self.assertIsNotNone(process.poll())
        self.assertIsNone(slot._process)
        self.assertLess(time.monotonic()-started,2)

    def test_systemd_fixed_command_output_cap_and_deadline(self):
        real=subprocess.Popen
        unit='mentat-project-worker-'+'a'*32+'.scope'
        for code in ("import sys;sys.stdout.write('x'*9000)","import time;time.sleep(60)"):
            captured=[]
            def spawn(command,**kwargs):
                captured.append((command,kwargs))
                return real([sys.executable,'-I','-c',code],**kwargs)
            started=time.monotonic()
            with patch.object(readback.subprocess,'Popen',side_effect=spawn),self.assertRaises(readback.ScopeReadbackError):
                readback._unit_state(unit,os.getuid(),time.monotonic()+0.25)
            self.assertLess(time.monotonic()-started,1.5)
            command,options=captured[0]
            self.assertEqual(command,['/usr/bin/systemctl','--user','show',unit,'-p','ActiveState','-p','ControlGroup',
                                      '-p','InvocationID','-p','LoadState'])
            self.assertEqual(set(options['env']),{'PATH','LANG','HOME','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'})

    def test_worker_environment_and_oversized_reply_are_bounded(self):
        self.assertEqual(inspector.minimal_worker_environment({'OPENAI_API_KEY':'synthetic','MENTAT_BRIDGE_TOKEN':'synthetic'}),
                         {'LANG':'C.UTF-8','PYTHONUTF8':'1'})
        code="import sys,time;sys.stdout.write('x'*4097);sys.stdout.flush();time.sleep(60)"
        slot=inspector._InspectionSlot((sys.executable,'-I','-c',code),deadline=time.monotonic()+2,
            clock=time.monotonic,environment={'LANG':'C.UTF-8'},operation_watchdog_seconds=2,maximum_line_bytes=4096)
        process=slot._process
        try:
            with self.assertRaises(Exception):
                slot.execute(kind='scope_readback',url='{}')
        finally:
            slot.close()
        self.assertIsNotNone(process.poll())

    def test_missing_reused_launcher_never_implies_empty_populated_scope(self):
        scope=LinuxWorkerScope()
        try:
            plan=scope.journal_plan().private_metadata()
            scope.start_inert()
            identity=scope.journal_owned_identity().private_metadata()
            with patch.object(readback,'_launcher_ticks',return_value=None):
                result=readback._observe_kernel(plan,identity,time.monotonic()+10)
            self.assertEqual((result.state,result.reason),('matching_populated','launcher_unverified'),result)
        finally:
            if not scope._closed:
                scope.close_verified()

    def test_changed_boot_uid_inode_invocation_and_filesystem_fail_closed(self):
        scope=LinuxWorkerScope()
        try:
            plan=scope.journal_plan().private_metadata()
            scope.start_inert()
            identity=scope.journal_owned_identity().private_metadata()
            for field,value,reason in (('boot_id','f'*32,'boot_changed'),('uid',os.getuid()+1,'platform_or_uid')):
                altered_plan={**plan,field:value}
                altered_identity={**identity,field:value}
                result=readback._observe_kernel(altered_plan,altered_identity,time.monotonic()+10)
                self.assertEqual((result.state,result.reason),('unknown',reason),result)
            altered={**identity,'inode':identity['inode']+1}
            self.assertEqual(readback._observe_kernel(plan,altered,time.monotonic()+10).reason,'inode_changed')
            altered={**identity,'invocation':'f'*32}
            self.assertEqual(readback._observe_kernel(plan,altered,time.monotonic()+10).reason,'invocation_changed')
            with patch.object(readback.scopes,'_require_cgroup2',side_effect=RuntimeError('wrong filesystem')):
                self.assertEqual(readback._observe_kernel(plan,identity,time.monotonic()+10).state,'unknown')
            original=readback._unit_state
            count=[]
            def changed(*args):
                reply=original(*args)
                count.append(reply)
                return {**reply,'ActiveState':'inactive'} if len(count)==2 else reply
            with patch.object(readback,'_unit_state',side_effect=changed):
                result=readback._observe_kernel(plan,identity,time.monotonic()+10)
            self.assertEqual(result.reason,'changed_during_read',result)
        finally:
            if not scope._closed:
                scope.close_verified()


@unittest.skipUnless(sys.platform=='linux','Actual fixed Linux scope required')
class LinuxReadbackTests(unittest.TestCase):
    def test_independent_reopen_observes_owned_scope_and_honest_cleanup(self):
        scope=LinuxWorkerScope()
        try:
            plan=scope.journal_plan().private_metadata()
            scope.start_inert()
            identity=scope.journal_owned_identity().private_metadata()
            result=readback._observe_kernel(plan,identity,time.monotonic()+10)
            self.assertEqual(result.state,'matching_populated',result)
            self.assertEqual(result.reason,'launcher_matching')
            terminal=readback._observe_kernel(plan,identity,time.monotonic()+10,terminal=True)
            self.assertEqual(terminal.state,'conflict')
            scope.stop_local_and_verify()
            after=readback._observe_kernel(plan,identity,time.monotonic()+10)
            self.assertIn(after.state,{'matching_empty','unknown','conflict'},after)
            self.assertNotEqual(after.state,'matching_populated')
        finally:
            if not scope._closed: scope.close_verified()


if __name__=='__main__':
    unittest.main()
