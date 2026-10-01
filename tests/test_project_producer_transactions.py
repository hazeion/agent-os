"""Real scoped output conversion shares one authority transaction with Stop."""
from contextlib import closing
import json
import sys
import threading
import unittest
from unittest.mock import patch

import mentat_db
import project_context
import project_producers
import project_output_reservations
from private_state import private_state_lock
from tests import test_project_producers as fixtures
from tests.test_project_worker_journal import GENERATION


def _run_owned_race(fixture,threads,barrier):
    try:
        for thread in threads: thread.start()
        for thread in threads: thread.join(10)
    finally:
        # A failed second start or interrupted join must not leave a child
        # mutating the disposable root after its fixture has been removed.
        barrier.abort()
        cleanup_errors=[]
        for thread in threads:
            if thread.ident is not None:
                try: thread.join(10)
                except BaseException as error: cleanup_errors.append(error)
        if any(thread.is_alive() for thread in threads):
            fixture._retain=True
            fixtures._RETAINED_PRODUCER_FIXTURES.append((fixture,threads))
        if cleanup_errors: raise cleanup_errors[0]


class ProducerRaceOwnershipTests(unittest.TestCase):
    def test_second_start_failure_aborts_barrier_and_drains_first_child(self):
        from types import SimpleNamespace
        fixture=SimpleNamespace(_retain=False)
        barrier=threading.Barrier(2)
        finished=threading.Event()
        def child():
            try: barrier.wait(5)
            except threading.BrokenBarrierError: pass
            finally: finished.set()
        threads=[threading.Thread(target=child) for _ in range(2)]
        with patch.object(threads[1],'start',side_effect=RuntimeError('injected start failure')):
            with self.assertRaisesRegex(RuntimeError,'injected start failure'):
                _run_owned_race(fixture,threads,barrier)
        self.assertTrue(finished.is_set())
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(fixture._retain)

    def test_interrupted_join_still_drains_started_children(self):
        from types import SimpleNamespace
        fixture=SimpleNamespace(_retain=False)
        barrier=threading.Barrier(2)
        def child():
            try: barrier.wait(5)
            except threading.BrokenBarrierError: pass
        threads=[threading.Thread(target=child) for _ in range(2)]
        original=threads[0].join
        interrupted=[False]
        def join(timeout):
            if not interrupted[0]:
                interrupted[0]=True
                raise KeyboardInterrupt('injected interrupted join')
            return original(timeout)
        with patch.object(threads[0],'join',side_effect=join):
            with self.assertRaises(KeyboardInterrupt):
                _run_owned_race(fixture,threads,barrier)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(fixture._retain)


@unittest.skipUnless(sys.platform=='linux','Actual Linux scoped producer required')
class ProducerTransactionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ProducerIntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_concurrent_stop_and_capture_commit_only_one_truthful_outcome(self):
        fixture=self.fixture
        results={}
        errors=[]
        def race(witness,receipt):
            barrier=threading.Barrier(2)
            def capture():
                try:
                    barrier.wait(5)
                    results['capture']=project_producers.register_output(fixture.root,
                        run_id=fixture.run,generation=GENERATION,holder_token=fixture.holder,
                        scope_token=receipt[0],scope_revision=receipt[1],expected_revision=3,witness=witness)
                except project_producers.journal.WorkerJournalError:
                    results['capture']='conflict'
                except BaseException as error: errors.append(error)
            def stop():
                try:
                    barrier.wait(5)
                    with private_state_lock(fixture.root),closing(mentat_db.connect(fixture.root)) as connection:
                        connection.execute('BEGIN IMMEDIATE')
                        results['stop']=project_producers.request_stop(connection,run_id=fixture.run,
                            generation=GENERATION,holder_token=fixture.holder,expected_revision=3)
                        connection.commit()
                except project_producers.journal.WorkerJournalError:
                    results['stop']='conflict'
                except BaseException as error: errors.append(error)
            threads=[threading.Thread(target=target) for target in (capture,stop)]
            _run_owned_race(fixture,threads,barrier)
            self.assertFalse(fixture._retain)
            self.assertEqual(errors,[])
        try:
            fixture.execute(json.dumps(fixtures.PROPOSAL,separators=(',',':')),before_capture=race)
        except project_producers.journal.WorkerJournalError:
            self.assertEqual(results.get('capture'),'conflict')
        self.assertEqual(len(results),2)
        self.assertEqual(sum(result=='conflict' for result in results.values()),1)
        with closing(mentat_db.connect(fixture.root)) as connection:
            project_producers.producer_ids(connection)
            status=connection.execute('SELECT status FROM mentat_runs').fetchone()[0]
            counts=tuple(connection.execute('SELECT (SELECT COUNT(*) FROM mentat_project_producer_stops),'
                '(SELECT COUNT(*) FROM mentat_project_producer_outputs)').fetchone())
            self.assertIn((status,counts),[('unknown',(1,0)),('completed',(0,1))])
            self.assertEqual(project_output_reservations.pending_capacity(connection),
                             (1,32768) if status=='unknown' else (0,0))

    def test_reserved_metadata_ceiling_and_existing_blob_allow_atomic_conversion(self):
        fixture=self.fixture
        fixed={}
        def stage_existing_blob(witness,receipt):
            from mentat.project_output_blob import publish_output_blob,_record_attachment
            from task_repository import _open_repository_database,_guarded_transaction
            with private_state_lock(fixture.root),_open_repository_database(fixture.root) as (connection,guard):
                with _guarded_transaction(connection,guard):
                    publication=publish_output_blob(fixture.root,witness)
                    _,fixed['blob']=_record_attachment(connection,fixture.root,publication,identity_guard=guard)
                    guard.capture()
            with closing(mentat_db.connect(fixture.root)) as connection:
                sizes=[]
                original=project_context._encoded
                def measured(value):
                    raw=original(value)
                    sizes.append(len(raw))
                    return raw
                with patch.object(project_context,'_encoded',side_effect=measured):
                    project_context.validate_project_context_connection(connection)
                # Hold metadata remains conservatively charged after conversion.
                fixed['budget']=max(sizes)
                fixed['limit']=patch.object(project_context,'OUTPUT_RESERVATION_MAX_METADATA_BYTES',fixed['budget'])
                fixed['limit'].start()
        try:
            fixture.execute(json.dumps(fixtures.PROPOSAL,separators=(',',':')),before_capture=stage_existing_blob)
        finally:
            if 'limit' in fixed: fixed['limit'].stop()
        with closing(mentat_db.connect(fixture.root)) as connection:
            self.assertEqual(connection.execute('SELECT blob_id FROM mentat_project_producer_outputs').fetchone()[0],fixed['blob'])
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM blobs WHERE id=?',(fixed['blob'],)).fetchone()[0],1)
            self.assertEqual(project_output_reservations.pending_capacity(connection),(0,0))
            project_context.validate_project_context_connection(connection)

    def test_live_backup_refuses_tampered_input_provenance_before_publication(self):
        import data_backup_restore
        import data_layout
        import data_schema
        from tempfile import TemporaryDirectory
        from pathlib import Path
        root=self.fixture.root
        for name in data_layout.SEED_FILE_NAMES:
            path=root/name
            if not path.exists():
                path.write_text(json.dumps({'theme':'midnight'} if name=='dashboard.json' else []),encoding='utf-8')
            path.chmod(0o600)
        for name in data_layout.DATA_ROOT_DIRECTORY_NAMES:
            (root/name).mkdir(mode=0o700,exist_ok=True)
        with TemporaryDirectory() as temporary:
            seeds=Path(temporary)/'seeds'
            seeds.mkdir()
            for name in data_layout.SEED_FILE_NAMES:
                (seeds/name).write_bytes((root/name).read_bytes())
            preview=data_schema.preview_schema_migration(seeds,root,home=Path(temporary))
            self.assertEqual(preview.status,'ready')
            result=data_schema.migrate_data_schema(seeds,root,confirmation_token=preview.confirmation_token,home=Path(temporary))
            self.assertEqual(result.status,'migrated')
        good=data_backup_restore.create_durable_backup(root)
        self.assertEqual(good.status,'created')
        before=tuple(sorted(path.name for path in (root/'backups').iterdir()))
        with closing(mentat_db.connect(root)) as connection:
            trigger=connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_project_producer_binding_immutable'").fetchone()[0]
            body=json.loads(connection.execute('SELECT body_json FROM mentat_project_producer_bindings').fetchone()[0])
            body['query_digest']='f'*64
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DROP TRIGGER mentat_project_producer_binding_immutable')
            connection.execute('UPDATE mentat_project_producer_bindings SET body_json=?,receipt_digest=?',
                               (project_producers.journal._encoded(body),project_producers.journal._digest(body)))
            connection.execute(trigger)
            connection.commit()
        refused=data_backup_restore.create_durable_backup(root)
        self.assertEqual(refused.status,'blocked')
        self.assertEqual(tuple(sorted(path.name for path in (root/'backups').iterdir())),before)


if __name__=='__main__': unittest.main()
