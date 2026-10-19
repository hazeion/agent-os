"""Local completion witnesses cannot be reconstructed from caller metadata."""
from copy import copy
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from mentat import project_namespace_evidence as evidence
from mentat import project_worker_namespace as namespaces
from mentat.project_worker_scope import WorkerScopeError
from mentat.project_worker_scope import LinuxWorkerScope
from mentat.project_scope_evidence import _issue as issue_scope


class NamespaceCompletionTests(unittest.TestCase):
    def test_deadline_is_pinned_before_wait_and_cannot_be_extended_or_repaired(self):
        for deadline,changed in ((None,10**12),(float('inf'),10**12),(10**12,10**12+1)):
            scope=MagicMock()
            scope._deadline=deadline
            lifecycle=MagicMock()
            handle=namespaces.NamespaceWorker(scope,lifecycle,9999)
            scope._deadline=changed
            with self.subTest(deadline=deadline),self.assertRaises(WorkerScopeError): handle.wait()
            lifecycle.recvmsg.assert_not_called()
            self.assertIsNone(handle._verified_result)

    def test_raw_values_and_public_constructor_cannot_issue_evidence(self):
        for value in (True,{},None,b'output'):
            with self.assertRaises(ValueError): evidence.completion_metadata(value)
        with self.assertRaises(ValueError):
            evidence.NamespaceCompletionWitness(('a'*64,None,None,False),('output',10),None,None,None)

    def test_missing_handoff_success_or_real_scope_cannot_issue_evidence(self):
        handle=namespaces.NamespaceWorker(MagicMock(),MagicMock(),9999)
        with self.assertRaises(WorkerScopeError): handle.completion_witness()
        handle._handoff_context=('a'*64,None,None,False)
        handle._verified_result=('output',10)
        with self.assertRaises(WorkerScopeError): handle.completion_witness()

    def test_boolean_packet_version_is_not_terminal_evidence(self):
        scope=MagicMock()
        scope._deadline=10**12
        scope.deadline_hit=False
        lifecycle=MagicMock()
        packet={'version':True,'kind':'terminal','exit_code':0,'text':'output','output_bytes':10}
        lifecycle.recvmsg.return_value=(json.dumps(packet).encode(),[],0,None)
        handle=namespaces.NamespaceWorker(scope,lifecycle,9999,handoff_context=('a'*64,None,None,False))
        with patch.object(namespaces.socket,'CMSG_SPACE',side_effect=lambda size:size,create=True),\
             patch.object(namespaces.socket,'MSG_CMSG_CLOEXEC',0,create=True),self.assertRaises(WorkerScopeError):
            handle.wait()
        self.assertIsNone(handle._verified_result)
        self.assertIsNone(handle._completion_witness)
        scope.stop_local_and_verify.assert_not_called()

    def test_failed_exit_or_unverified_cleanup_retains_no_completion_snapshot(self):
        for exit_code,cleanup in ((1,True),(0,False)):
            scope=MagicMock()
            scope._deadline=10**12
            scope.deadline_hit=False
            scope._process.returncode=0
            scope._control.recv.return_value=b'EXIT 0\n'
            scope.stop_local_and_verify.return_value=cleanup
            lifecycle=MagicMock()
            packet={'version':1,'kind':'terminal','exit_code':exit_code,'text':'output','output_bytes':10}
            lifecycle.recvmsg.return_value=(json.dumps(packet).encode(),[],0,None)
            handle=namespaces.NamespaceWorker(scope,lifecycle,9999,handoff_context=('a'*64,None,None,False))
            with patch.object(namespaces.socket,'CMSG_SPACE',side_effect=lambda size:size,create=True),\
                 patch.object(namespaces.socket,'MSG_CMSG_CLOEXEC',0,create=True),self.assertRaises(WorkerScopeError):
                handle.wait()
            self.assertIsNone(handle._verified_result)
            with self.assertRaises(WorkerScopeError): handle.completion_witness()

    def test_concurrent_getters_retain_one_original_immutable_witness(self):
        # Inert trusted-Python closed-scope fixture; no process or Run is issued.
        scope=LinuxWorkerScope.__new__(LinuxWorkerScope)
        scope._lock=threading.RLock()
        scope._closed=True
        scope.deadline_hit=False
        scope._deadline=time.monotonic()+20
        values={'unit':'mentat-project-worker-'+'a'*32+'.scope','boot_id':'b'*32,'uid':1000,
                'memory_bytes':512*1024*1024,'processes':32,'cpu_percent':100,'wall_seconds':20,
                'invocation':'c'*32,'device':1,'inode':2,'pid':3,'start_ticks':4}
        scope._closed_witness=issue_scope('closed',scope,values)
        handle=namespaces.NamespaceWorker(scope,MagicMock(),9999,handoff_context=('a'*64,None,None,False))
        scope._namespace_worker=handle
        handle._verified_result=('output',10)
        barrier=threading.Barrier(2)
        handle._verified_deadline=scope._deadline
        original=evidence._issue
        calls=[]
        def slow_issue(*args):
            calls.append(args)
            threading.Event().wait(0.05)
            return original(*args)
        def request():
            barrier.wait(timeout=2)
            return handle.completion_witness()
        with patch.object(evidence,'_issue',side_effect=slow_issue),ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(request) for _ in range(2)]
            first,second=[future.result(timeout=2) for future in futures]
        self.assertIs(first,second)
        self.assertEqual(len(calls),1)
        self.assertEqual(evidence.completion_metadata(first),evidence.completion_metadata(second))
        self.assertEqual(evidence.completion_acceptance_deadline(first),scope._deadline)
        # Waiting or issuing a witness later must never reset conversion time.
        with patch.object(evidence.time,'monotonic',return_value=scope._deadline):
            with self.assertRaisesRegex(ValueError,'expired'):
                evidence.completion_acceptance_deadline(first)
        self.assertEqual(evidence.completion_metadata(first),evidence.completion_metadata(second))


if __name__=='__main__':
    unittest.main()
