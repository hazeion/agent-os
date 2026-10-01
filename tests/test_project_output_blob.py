"""Private bytes are immutable or disposable, never registered Run results."""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import mentat_db
from mentat import project_output_blob as blobs
from mentat import project_namespace_evidence as evidence
from mentat import project_worker_namespace as namespaces
from mentat.project_scope_evidence import _issue as issue_scope
from mentat.project_worker_scope import LinuxWorkerScope
from private_state import console_root, private_state_lock
from task_repository import _open_repository_database


def terminal_fixture(text):
    # Exact inert trusted-Python evidence fixture; no process/Run/provider.
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
    handle._verified_result=(text,len(text.encode()))
    handle._verified_deadline=scope._deadline
    return handle.completion_witness()


class OutputBlobBoundaryTests(unittest.TestCase):
    def test_raw_values_cannot_grant_publication_or_readback_authority(self):
        with self.assertRaises(blobs.OutputBlobError):
            blobs.PublishedOutputBlob('a'*64,1,(),None)
        for raw in ({},True,None,b'output'):
            with self.assertRaises(ValueError): blobs.publish_output_blob(Path.cwd(),raw)

    @unittest.skipIf(sys.platform=='linux','Unsupported platform test')
    def test_unsupported_platform_refuses_before_storage(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            with self.assertRaises(blobs.OutputBlobError):
                blobs.publish_output_blob(root,terminal_fixture('result'))
            self.assertEqual(list(root.iterdir()),[])


@unittest.skipUnless(sys.platform=='linux','Descriptor-relative Linux publication')
class OutputBlobLinuxTests(unittest.TestCase):
    def setUp(self):
        self.temporary=TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        with closing(mentat_db.connect(self.root)): pass

    def publish(self,witness):
        with private_state_lock(self.root): return blobs.publish_output_blob(self.root,witness)

    def test_exact_utf8_bytes_deduplicate_without_creating_sqlite_authority(self):
        text='{"version":1,"summary":"Garage 界","questions":[],"tasks":[]}'
        witness=terminal_fixture(text)
        first=self.publish(witness)
        second=self.publish(witness)
        self.assertEqual((first.sha256,first.byte_size),(second.sha256,len(text.encode())))
        expected=console_root(self.root)/'blobs'/'sha256'/first.sha256[:2]/first.sha256
        self.assertEqual(expected.read_bytes(),text.encode())
        self.assertEqual(expected.stat().st_mode & 0o777,0o600)
        first.verify(self.root)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM attachments').fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM blobs').fetchone()[0],0)
        self.assertEqual(list(expected.parent.glob('.mentat-output-*')),[])

    def test_symlinked_root_prefix_or_final_file_never_receives_output(self):
        for target in ('console','prefix','file'):
            with self.subTest(target=target),TemporaryDirectory() as temporary:
                outside=Path(temporary)
                witness=terminal_fixture('exact result')
                digest=hashlib.sha256(b'exact result').hexdigest()
                private=console_root(self.root)
                if target=='console':
                    retained=private.with_name('original-console')
                    private.rename(retained)
                    private.symlink_to(outside,target_is_directory=True)
                    reset=lambda: (private.unlink(),retained.rename(private))
                else:
                    parent=private/'blobs'/'sha256'
                    parent.mkdir(parents=True,mode=0o700,exist_ok=True)
                    (private/'blobs').chmod(0o700)
                    parent.chmod(0o700)
                    if target=='prefix':
                        selected=parent/digest[:2]
                        selected.symlink_to(outside,target_is_directory=True)
                    else:
                        parent=parent/digest[:2]
                        parent.mkdir(mode=0o700,exist_ok=True)
                        selected=parent/digest
                        (outside/'external').write_bytes(b'protected')
                        selected.symlink_to(outside/'external')
                    reset=lambda: selected.unlink()
                before={item.name:item.read_bytes() for item in outside.iterdir() if item.is_file()}
                try:
                    with self.assertRaises((blobs.OutputBlobError,OSError)):
                        self.publish(witness)
                    self.assertEqual({item.name:item.read_bytes() for item in outside.iterdir() if item.is_file()},before)
                    self.assertFalse(any(item.name.startswith('.mentat-output-') for item in outside.iterdir()))
                finally: reset()

    def test_existing_mismatched_blob_is_never_overwritten(self):
        witness=terminal_fixture('exact result')
        digest=hashlib.sha256(b'exact result').hexdigest()
        parent=console_root(self.root)/'blobs'/'sha256'/digest[:2]
        parent.mkdir(parents=True,exist_ok=True)
        for item in (parent,parent.parent,parent.parent.parent): item.chmod(0o700)
        selected=parent/digest
        selected.write_bytes(b'conflict')
        selected.chmod(0o600)
        with self.assertRaises(blobs.OutputBlobError): self.publish(witness)
        self.assertEqual(selected.read_bytes(),b'conflict')
        self.assertEqual(list(parent.glob('.mentat-output-*')),[])

    def test_existing_named_dedup_inode_itself_is_synced(self):
        witness=terminal_fixture('exact result')
        digest=hashlib.sha256(b'exact result').hexdigest()
        parent=console_root(self.root)/'blobs'/'sha256'/digest[:2]
        parent.mkdir(parents=True,exist_ok=True)
        for item in (parent,parent.parent,parent.parent.parent): item.chmod(0o700)
        selected=parent/digest
        selected.write_bytes(b'exact result')
        selected.chmod(0o600)
        expected=(selected.stat().st_dev,selected.stat().st_ino)
        synced=[]
        original=os.fsync
        def recorded(descriptor):
            details=os.fstat(descriptor)
            synced.append((details.st_dev,details.st_ino))
            return original(descriptor)
        with patch.object(blobs.os,'fsync',side_effect=recorded): self.publish(witness)
        self.assertIn(expected,synced)

    def test_expired_witness_refuses_before_any_blob_and_late_fsync_never_returns_success(self):
        witness=terminal_fixture('exact result')
        with patch.object(evidence.time,'monotonic',return_value=witness._origin._scope._deadline):
            with self.assertRaises(ValueError): self.publish(witness)
        self.assertFalse((console_root(self.root)/'blobs').exists())
        original=os.fsync
        def expire_after_sync(descriptor):
            original(descriptor)
            witness._origin._scope._deadline=time.monotonic()-1
        with patch.object(blobs.os,'fsync',side_effect=expire_after_sync):
            with self.assertRaises(blobs.OutputBlobError): self.publish(witness)

    def test_original_root_replacement_invalidates_readback(self):
        publication=self.publish(terminal_fixture('exact result'))
        private=console_root(self.root)
        retained=private.with_name('old-console')
        private.rename(retained)
        private.mkdir(mode=0o700)
        with self.assertRaises(blobs.OutputBlobError): publication.verify(self.root)

    def test_malformed_publication_fields_fail_before_any_path_traversal(self):
        from dataclasses import replace
        publication=self.publish(terminal_fixture('exact result'))
        for values in ({'sha256':'../external'},{'sha256':'/'+'a'*63},
                       {'sha256':'A'*64},{'byte_size':True},{'byte_size':32769},
                       {'_root_identity':(1,0)},{'_root_identity':(True,2)}):
            with self.subTest(values=values),self.assertRaises(blobs.OutputBlobError):
                replace(publication,**values)
        forged=blobs.PublishedOutputBlob.__new__(blobs.PublishedOutputBlob)
        for name,value in {'sha256':'../external','byte_size':1,
                          '_root_identity':publication._root_identity,'_issuer':blobs._ISSUER}.items():
            object.__setattr__(forged,name,value)
        with patch.object(blobs,'_root') as opened,self.assertRaises(blobs.OutputBlobError):
            forged.verify(self.root)
        opened.assert_not_called()

    def test_database_helper_has_no_commit_or_retained_source_authority(self):
        publication=self.publish(terminal_fixture('exact result'))
        with _open_repository_database(self.root) as (connection,guard):
            with self.assertRaises(blobs.OutputBlobError):
                blobs._record_attachment(connection,self.root,publication,identity_guard=guard)
            connection.execute('BEGIN IMMEDIATE')
            attachment,blob=blobs._record_attachment(connection,self.root,publication,identity_guard=guard)
            self.assertTrue(connection.in_transaction)
            self.assertEqual(connection.execute('SELECT blob_id FROM attachments WHERE id=?',(attachment,)).fetchone()[0],blob)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_retained_attachments').fetchone()[0],0)
            connection.rollback()
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM attachments').fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM blobs').fetchone()[0],0)
            publication.verify(self.root)

    def test_failed_database_step_rolls_back_even_if_outer_caller_commits(self):
        publication=self.publish(terminal_fixture('exact result'))
        with _open_repository_database(self.root) as (connection,guard):
            connection.execute("CREATE TRIGGER refuse_output_attachment BEFORE INSERT ON attachments BEGIN SELECT RAISE(ABORT,'fixture'); END")
            connection.execute('BEGIN IMMEDIATE')
            with self.assertRaises(mentat_db.sqlite3.IntegrityError):
                blobs._record_attachment(connection,self.root,publication,identity_guard=guard)
            connection.commit()
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM attachments').fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM blobs').fetchone()[0],0)

    def test_dedup_requires_exact_ready_blob_metadata_and_never_rewrites_it(self):
        publication=self.publish(terminal_fixture('exact result'))
        with _open_repository_database(self.root) as (connection,guard):
            connection.execute('BEGIN IMMEDIATE')
            first=blobs._record_attachment(connection,self.root,publication,identity_guard=guard)
            second=blobs._record_attachment(connection,self.root,publication,identity_guard=guard)
            self.assertNotEqual(first[0],second[0])
            self.assertEqual(first[1],second[1])
            connection.commit()
            connection.execute("UPDATE blobs SET state='missing'")
            connection.commit()
            connection.execute('BEGIN IMMEDIATE')
            with self.assertRaises(blobs.OutputBlobError):
                blobs._record_attachment(connection,self.root,publication,identity_guard=guard)
            connection.commit()
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM attachments').fetchone()[0],2)
            self.assertEqual(connection.execute('SELECT state FROM blobs').fetchone()[0],'missing')

    def test_foreign_database_or_guard_cannot_record_another_roots_bytes(self):
        publication=self.publish(terminal_fixture('exact result'))
        with TemporaryDirectory() as temporary:
            other=Path(temporary)
            with closing(mentat_db.connect(other)): pass
            with _open_repository_database(other) as (foreign,foreign_guard), _open_repository_database(self.root) as (own,own_guard):
                foreign.execute('BEGIN IMMEDIATE')
                for guard in (foreign_guard,own_guard):
                    with self.assertRaises(blobs.OutputBlobError):
                        blobs._record_attachment(foreign,self.root,publication,identity_guard=guard)
                foreign.commit()
                self.assertEqual(foreign.execute('SELECT COUNT(*) FROM blobs').fetchone()[0],0)
                self.assertEqual(foreign.execute('SELECT COUNT(*) FROM attachments').fetchone()[0],0)
                own.execute('BEGIN IMMEDIATE')
                with self.assertRaises(blobs.OutputBlobError):
                    blobs._record_attachment(own,self.root,publication,identity_guard=foreign_guard)
                own.commit()
                self.assertEqual(own.execute('SELECT COUNT(*) FROM attachments').fetchone()[0],0)

    def test_same_path_connections_cannot_exchange_opening_guards(self):
        publication=self.publish(terminal_fixture('exact result'))
        with _open_repository_database(self.root) as (first,first_guard), _open_repository_database(self.root) as (second,second_guard):
            first.execute('BEGIN IMMEDIATE')
            with self.assertRaises(blobs.OutputBlobError):
                blobs._record_attachment(first,self.root,publication,identity_guard=second_guard)
            first.commit()
            second.execute('BEGIN IMMEDIATE')
            with self.assertRaises(blobs.OutputBlobError):
                blobs._record_attachment(second,self.root,publication,identity_guard=first_guard)
            second.commit()
            self.assertEqual(first.execute('SELECT COUNT(*) FROM attachments').fetchone()[0],0)


if __name__=='__main__': unittest.main()
