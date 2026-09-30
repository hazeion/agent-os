"""Canonical Agent occupancy survives changes in private adapter scope."""

from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
import threading
import unittest

from agent_runtime import RunStatus, RuntimeCapacity
from conversation_repository import ConversationRepository
from orchestration_service import OrchestrationService, OrchestrationServiceError
from mentat_db import connect
from run_repository import RunRepository, save_authoritative_run_summaries
from tests import test_orchestration_service as fixtures
from tests.test_run_repository import run_fixture

_RETAINED_STALLED_ROOTS=[]


class AgentCapacityContinuityTests(unittest.TestCase):
    def test_new_qualified_scope_cannot_bypass_unresolved_agent_run(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            fixture=fixtures.OrchestrationServiceTests()
            runtime=fixtures.FakeRuntime(root,raises=True)
            fixture.qualify_codex_capacity(runtime)
            runtime.capacity_limit=2
            service,first_id=fixture.prepare_conversation(root,runtime)
            second_id=ConversationRepository(root,supported_runtime_types=('codex',)).create(
                agent_id='agent-service').conversation.id
            first=service.submit_conversation_turn(conversation_id=first_id,text='Retain unresolved old work',
                                                   idempotency_key='capacity-old-scope-request')
            runtime.capacity_scope='codex-app-server:'+'b'*64
            second=service.submit_conversation_turn(conversation_id=second_id,text='Wait for exact old work reconciliation',
                                                    idempotency_key='capacity-new-scope-request')
            self.assertEqual(first.run.status,'unknown')
            self.assertEqual(second.disposition,'blocked')
            self.assertEqual(second.turn.blocked_reason,'capacity')
            self.assertIsNone(second.run)
            self.assertEqual(len(runtime.calls),1)

    def test_changed_scope_preserves_task_and_conversation_shared_capacity(self):
        for task_first in (False,True):
            with self.subTest(task_first=task_first),TemporaryDirectory() as directory:
                root=Path(directory)
                fixture=fixtures.OrchestrationServiceTests()
                runtime=fixtures.FakeRuntime(root,raises=True)
                fixture.qualify_codex_capacity(runtime)
                runtime.capacity_limit=2
                service,conversation=fixture.prepare_conversation(root,runtime)
                task_ids=iter(('dispatch_scope_continuity','run_scope_continuity'))
                task_service=OrchestrationService(root,runtime_registry=service.runtime_registry,
                    agent_registry=service.agent_registry,id_factory=lambda _:next(task_ids))
                if task_first:
                    first=task_service.dispatch_task(task_id='task-service',expected_revision=1,
                                                     idempotency_key='capacity-task-first-request')
                else:
                    first=service.submit_conversation_turn(conversation_id=conversation,text='Keep the Console work occupied',
                                                           idempotency_key='capacity-console-first-request')
                runtime.capacity_scope='codex-app-server:'+'b'*64
                if task_first:
                    result=service.submit_conversation_turn(conversation_id=conversation,text='Wait for the old Task scope',
                                                            idempotency_key='capacity-console-next-request')
                    self.assertEqual(result.disposition,'blocked')
                    self.assertIsNone(result.run)
                else:
                    with self.assertRaisesRegex(OrchestrationServiceError,'dispatch.capacity_unavailable'):
                        task_service.dispatch_task(task_id='task-service',expected_revision=1,
                                                   idempotency_key='capacity-task-next-request')
                self.assertEqual(first.run.status,'unknown')
                self.assertEqual(len(runtime.calls),1)

    def test_success_does_not_release_queue_while_another_old_scope_run_is_active(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            fixture=fixtures.OrchestrationServiceTests()
            runtime=fixtures.FakeRuntime(root)
            fixture.qualify_codex_capacity(runtime)
            runtime.capacity_limit=2
            service,first_id=fixture.prepare_conversation(root,runtime)
            second_id=ConversationRepository(root,supported_runtime_types=('codex',)).create(
                agent_id='agent-service').conversation.id
            counters={}
            def identifier(prefix):
                counters[prefix]=counters.get(prefix,0)+1
                return f'{prefix}_scope_queue_{counters[prefix]}'
            service.id_factory=identifier
            first=service.submit_conversation_turn(conversation_id=first_id,text='Finish this one exactly',
                                                   idempotency_key='capacity-queue-first-request')
            service.submit_conversation_turn(conversation_id=second_id,text='Keep another old-scope Run active',
                                              idempotency_key='capacity-queue-other-request')
            queued=service.submit_conversation_turn(conversation_id=first_id,text='Do not start in a new scope',
                                                    idempotency_key='capacity-queue-followup-request')
            runtime.capacity_scope='codex-app-server:'+'b'*64
            runtime.observed_status=RunStatus.COMPLETED
            service.reconcile_run(run_id=first.run.id,owner='scope_queue_reconciliation')
            detail=ConversationRepository(root,supported_runtime_types=('codex',)).read(first_id)
            self.assertEqual(len(runtime.calls),2)
            self.assertEqual(detail.queued_turns[0].id,queued.turn.id)
            self.assertEqual(detail.queued_turns[0].blocked_reason,'capacity')

    def test_concurrent_different_scopes_reserve_only_one_agent_run(self):
        temporary=TemporaryDirectory()
        threads=[]
        barrier=threading.Barrier(2)
        try:
            root=Path(temporary.name)
            fixture=fixtures.OrchestrationServiceTests()
            runtime=fixtures.FakeRuntime(root,raises=True)
            fixture.qualify_codex_capacity(runtime)
            runtime.capacity_limit=2
            service,first_id=fixture.prepare_conversation(root,runtime)
            second_id=ConversationRepository(root,supported_runtime_types=('codex',)).create(
                agent_id='agent-service').conversation.id
            lock=threading.Lock()
            seen=set()
            declarations={}
            callback_errors=[]
            def capacity(_):
                name=threading.current_thread().name
                if name not in seen:
                    with lock:
                        seen.add(name)
                    try:
                        barrier.wait(timeout=10)
                    except BaseException as error:
                        callback_errors.append(error)
                        raise
                scope='codex-app-server:'+name*64
                declarations[name]=scope
                return RuntimeCapacity(scope=scope,limit=2)
            runtime.capacity_for_binding=capacity
            counters={}
            def identifier(prefix):
                with lock:
                    counters[prefix]=counters.get(prefix,0)+1
                    return f'{prefix}_scope_race_{counters[prefix]}'
            service.id_factory=identifier
            results=[]
            errors=[]
            def submit(conversation,name):
                try:
                    results.append(service.submit_conversation_turn(conversation_id=conversation,text='One exact Agent slot',
                                   idempotency_key='capacity-race-request-'+name))
                except BaseException as error:
                    errors.append(error)
            threads=[threading.Thread(target=submit,args=(conversation,name),name=name)
                     for conversation,name in ((first_id,'a'),(second_id,'b'))]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=15)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(callback_errors,[])
            self.assertEqual(set(declarations),{'a','b'})
            self.assertEqual(len(set(declarations.values())),2)
            self.assertEqual(errors,[])
            self.assertEqual(sorted(result.disposition for result in results),['blocked','unknown'])
            self.assertEqual(len(runtime.calls),1)
        finally:
            barrier.abort()
            for thread in threads:
                if thread.ident is not None:
                    thread.join(timeout=15)
            if any(thread.is_alive() for thread in threads):
                _RETAINED_STALLED_ROOTS.append(temporary)
            else:
                temporary.cleanup()

    def test_valid_historical_unscoped_binding_cannot_use_a_wider_ceiling(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            fixture=fixtures.OrchestrationServiceTests()
            runtime=fixtures.FakeRuntime(root)
            fixture.qualify_codex_capacity(runtime)
            runtime.capacity_limit=2
            service,conversation=fixture.prepare_conversation(root,runtime)
            legacy=run_fixture('run_legacy_capacity',status='unknown',bound=False)
            save_authoritative_run_summaries(root,[legacy])
            binding=service.agent_registry.get_runtime_binding('agent-service')
            record=next(record for record in service.agent_registry.list_agent_records() if record.agent.id=='agent-service')
            digest=service._binding_digest(record.agent,binding)
            with closing(connect(root)) as connection:
                connection.execute("UPDATE mentat_runs SET runtime_type='codex',runtime_binding_digest=? WHERE id=?",
                                   (digest,'run_legacy_capacity'))
                connection.commit()
                retained=RunRepository(connection).get_run('run_legacy_capacity')
                self.assertIsNone(retained.agent_id)
                self.assertIsNone(retained.capacity_scope_digest)
            result=service.submit_conversation_turn(conversation_id=conversation,text='Wait for unscoped historical work',
                                                    idempotency_key='capacity-legacy-scope-request')
            self.assertEqual(result.disposition,'blocked')
            self.assertIsNone(result.run)
            self.assertEqual(runtime.calls,[])

    def test_retry_does_not_bypass_another_unresolved_run_in_the_old_scope(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            fixture=fixtures.OrchestrationServiceTests()
            runtime=fixtures.FakeRuntime(root)
            fixture.qualify_codex_capacity(runtime)
            runtime.capacity_limit=2
            runtime.rejects=True
            service,first_id=fixture.prepare_conversation(root,runtime)
            second_id=ConversationRepository(root,supported_runtime_types=('codex',)).create(
                agent_id='agent-service').conversation.id
            counters={}
            def identifier(prefix):
                counters[prefix]=counters.get(prefix,0)+1
                return f'{prefix}_scope_retry_{counters[prefix]}'
            service.id_factory=identifier
            failed=service.submit_conversation_turn(conversation_id=first_id,text='Retain this failed attempt',
                                                    idempotency_key='capacity-retry-source-request')
            runtime.rejects=False
            active=service.submit_conversation_turn(conversation_id=second_id,text='Keep exact old-scope work active',
                                                    idempotency_key='capacity-retry-other-request')
            runtime.capacity_scope='codex-app-server:'+'b'*64
            with self.assertRaisesRegex(OrchestrationServiceError,'conversation.capacity_unavailable'):
                service.retry_conversation_run(conversation_id=first_id,source_run_id=failed.run.id,
                                                idempotency_key='capacity-retry-new-scope-request')
            with closing(connect(root)) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_runs').fetchone()[0],2)
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_conversation_run_attempts').fetchone()[0],0)
                self.assertEqual(RunRepository(connection).get_run(active.run.id).status,active.run.status)
            self.assertEqual(len(runtime.calls),2)


if __name__=='__main__':
    unittest.main()
