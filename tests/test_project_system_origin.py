"""Fixed public-origin parsing and actual bounded Linux inspection checks."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from mentat import project_system_origin as origin
from mentat import project_system_origin_worker as worker


def signed(body):
    return b'-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA512\n\n'+body+b'-----BEGIN PGP SIGNATURE-----\nfixture\n-----END PGP SIGNATURE-----\n'


def package(pin):
    return (f'Package: {pin.package}\nVersion: {pin.version}\nArchitecture: amd64\n'
            f'Filename: {pin.filename}\nSize: {pin.size}\nSHA256: {pin.archive_digest}\n\n').encode()


def archive(items):
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w',format=tarfile.USTAR_FORMAT) as writer:
        for name,value,kind in items:
            item=tarfile.TarInfo(name)
            item.type=kind
            item.size=len(value) if kind==tarfile.REGTYPE else 0
            if kind==tarfile.SYMTYPE: item.linkname='elsewhere'
            writer.addfile(item,io.BytesIO(value) if item.size else None)
    return output.getvalue()


class SystemOriginParsingTests(unittest.TestCase):
    def test_signed_frame_refuses_unsigned_prefix_suffix_second_message_and_bad_escape(self):
        raw=signed(b'Origin: Ubuntu\n- -dash\n')
        self.assertEqual(origin._signed_text(raw),b'Origin: Ubuntu\n-dash')
        for altered in (b'unsigned\n'+raw,raw+b'unsigned\n',raw+raw,signed(b'-bad\n'),b'x'*262145):
            with self.subTest(case=altered[:24]),self.assertRaises(origin.SystemOriginError):
                origin._signed_text(altered)

    def test_signature_status_requires_exact_primary_signer_and_strong_single_signature(self):
        valid=('[GNUPG:] NEWSIG\n[GNUPG:] VALIDSIG '+origin.FINGERPRINT+
               ' 2026-09-30 1790740742 0 4 0 1 10 01 '+origin.FINGERPRINT+'\n').encode()
        origin._signature_status(valid)
        for raw in (valid+valid,valid.replace(origin.FINGERPRINT.encode(),b'f'*40),
                    valid+b'[GNUPG:] BADSIG invalid\n',valid.replace(b'1 10 01',b'1 2 01'),
                    b'not status\n',b'x'*16385):
            with self.assertRaises(origin.SystemOriginError): origin._signature_status(raw)

    def test_release_identity_unique_fields_and_hash_coordinates(self):
        payload=('Origin: Ubuntu\nLabel: Ubuntu\nCodename: resolute\nSuite: resolute\nSHA256:\n '+
                 'a'*64+' 2 main/binary-amd64/Packages').encode()
        self.assertEqual(origin._release_fields(payload,'resolute')['main/binary-amd64/Packages'],('a'*64,2))
        for raw in (payload.replace(b'Suite: resolute',b'Suite: wrong'),payload+b'\nOrigin: Ubuntu',
                    payload.replace(b'main/binary-amd64/Packages',b'../Packages'),
                    payload+b'\n '+'a'.encode()*64+b' 2 main/binary-amd64/Packages'):
            with self.assertRaises(origin.SystemOriginError): origin._release_fields(raw,'resolute')

    def test_package_selection_refuses_duplicates_wrong_pins_and_unterminated_stanzas(self):
        pin=origin.PINS[0]
        raw=package(pin)
        origin._package_stanzas(raw,[pin])
        for invalid in (raw+raw,raw.replace(pin.archive_digest.encode(),b'0'*64),raw[:-1],
                        raw.replace(b'Size: ',b'Size: 0'),raw.replace(b'Architecture: amd64',b'Architecture: all'),
                        raw.replace(b'\n\n',b'\nPackage: bubblewrap\n\n'),b'x'*65537+b'\n'):
            with self.assertRaises(origin.SystemOriginError): origin._package_stanzas(invalid,[pin])
        ignored=b'Package: ignored\n'+(b' '+b'x'*32768+b'\n')*3+b'\n'+raw
        with self.assertRaises(origin.SystemOriginError): origin._package_stanzas(ignored,[pin])

    def test_tar_regular_selected_member_and_canonical_debian_root(self):
        name=origin.PINS[0].member
        raw=archive([('.',b'',tarfile.DIRTYPE),('./'+name,b'public',tarfile.REGTYPE)])
        self.assertEqual(origin._member(raw,name),b'public')
        for entries in ([(name,b'public',tarfile.REGTYPE)]*2,
                        [('../'+name,b'public',tarfile.REGTYPE)],[(name,b'',tarfile.SYMTYPE)],
                        [(name+'/',b'public',tarfile.REGTYPE)]):
            with self.assertRaises(origin.SystemOriginError): origin._member(archive(entries),name)

    def test_raw_tar_declared_size_metadata_sparse_and_truncation_refuse_before_decode(self):
        name=origin.PINS[0].member
        for kind in (tarfile.XHDTYPE,tarfile.XGLTYPE,tarfile.GNUTYPE_LONGNAME,tarfile.GNUTYPE_SPARSE):
            item=tarfile.TarInfo(name)
            item.type=kind
            item.size=origin.MAX_MEMBER+1
            raw=item.tobuf(tarfile.GNU_FORMAT)+bytes(1024)
            with self.assertRaises(origin.SystemOriginError): origin._member(raw,name)
        raw=archive([(name,b'public',tarfile.REGTYPE)])
        for altered in (raw[:510],raw[:513],raw[:-1024]+b'x'*1024):
            with self.assertRaises(origin.SystemOriginError): origin._member(altered,name)

    def test_parent_report_schema_digests_types_and_sample_window_are_exact(self):
        valid={'format':1,'scope':'ubuntu-26.04-amd64-public-helper-bytes',
               'helpers':origin._expected_helpers(),'sampled_at':101.0}
        self.assertTrue(origin._valid_report(valid,100,102))
        for field,value in (('format',True),('sampled_at',99),('sampled_at',float('nan')),('scope','ready')):
            self.assertFalse(origin._valid_report({**valid,field:value},100,102))
        for value in (float(valid['helpers'][0]['size']),'wrong'):
            altered=deepcopy(valid)
            altered['helpers'][0]['size']=value
            self.assertFalse(origin._valid_report(altered,100,102))

    def test_parent_discards_matching_result_when_cleanup_crosses_deadline(self):
        from mentat import project_scope_inspector
        class Slot:
            closed=False
            def __init__(self,*args,**kwargs): pass
            def execute(self,**kwargs):
                return {'format':1,'scope':'ubuntu-26.04-amd64-public-helper-bytes',
                        'helpers':origin._expected_helpers(),'sampled_at':101}
            def close(self): Slot.closed=True
        with patch.object(project_scope_inspector,'_InspectionSlot',Slot),patch.object(origin.sys,'platform','linux'),\
             patch.object(origin.time,'monotonic',side_effect=(0,1,30.1)),patch.object(origin.time,'time',return_value=101):
            with self.assertRaises(origin.SystemOriginError): origin.verify_helpers(Path.cwd())
        self.assertTrue(Slot.closed)

    def test_worker_duplicate_keys_and_public_entry_refuse_arbitrary_inputs(self):
        with self.assertRaises(ValueError): json.loads('{"root":1,"root":2}',object_pairs_hook=worker._pairs)
        with self.assertRaises(origin.SystemOriginError): origin.verify_helpers('not a trusted absolute Path')

    def test_unverified_group_retains_owner_and_never_resignals_on_recheck(self):
        class Process:
            _mentat_process_group=1234
            stdin=stdout=None
            def poll(self): return 0
        class Base:
            def __init__(self):
                self._process=Process()
                self._reader=None
                self.terminations=0
            def _terminate_owned(self):
                self.terminations+=1
                self._process=None
        slot=origin._helper_slot_type(Base)()
        with patch.object(origin.os,'killpg',create=True) as observe,\
             patch.object(origin.time,'monotonic',side_effect=(0,1)):
            with self.assertRaises(origin.SystemOriginError) as caught: slot._terminate_owned()
        self.assertIs(caught.exception._mentat_worker_owner,slot)
        self.assertIsNotNone(slot._process)
        self.assertEqual(slot.terminations,1)
        observe.assert_called_once_with(1234,0)
        with patch.object(origin.os,'killpg',side_effect=ProcessLookupError(),create=True) as observe:
            slot._terminate_owned()
        self.assertEqual(slot.terminations,1)
        self.assertIsNone(slot._process)
        observe.assert_called_once_with(1234,0)

    def test_inherited_cleanup_failure_retains_no_resignal_state_before_super(self):
        class Process:
            _mentat_process_group=1234
            stdin=stdout=None
            def poll(self): return 0
        class Base:
            def __init__(self):
                self._process=Process()
                self._reader=None
                self.terminations=0
            def _terminate_owned(self):
                self.terminations+=1
                raise RuntimeError('injected owned cleanup failure')
        slot=origin._helper_slot_type(Base)()
        with self.assertRaises(RuntimeError) as caught: slot._terminate_owned()
        self.assertIs(caught.exception._mentat_worker_owner,slot)
        self.assertIsNotNone(slot._process)
        with patch.object(origin.os,'killpg',side_effect=ProcessLookupError(),create=True) as observe:
            slot._terminate_owned()
        observe.assert_called_once_with(1234,0)
        self.assertEqual(slot.terminations,1)
        self.assertIsNone(slot._process)
        with patch.object(origin.os,'killpg',side_effect=ProcessLookupError(),create=True) as observe:
            slot._terminate_owned()
        self.assertEqual(slot.terminations,1)
        self.assertIsNone(slot._process)
        observe.assert_not_called()

    def test_exact_unreaped_child_is_retained_until_poll_verifies_it(self):
        class Child:
            calls=0
            def poll(self):
                self.calls+=1
                return None if self.calls==1 else 0
        child=Child()
        origin._UNREAPED_CHILDREN.append(child)
        try:
            with patch.object(origin.time,'sleep') as wait: origin._drain_children()
            wait.assert_called_once_with(0.02)
            self.assertEqual(child.calls,2)
        finally:
            if child in origin._UNREAPED_CHILDREN: origin._UNREAPED_CHILDREN.remove(child)


@unittest.skipUnless(sys.platform=='linux','Actual Linux fixed verification boundary required')
class LinuxSystemOriginTests(unittest.TestCase):
    def stage(self,directory):
        root=Path(directory)
        for name in origin._NAMES:
            target=root/name
            target.write_bytes(b'public')
            target.chmod(0o600)
        return root

    def test_stage_redirected_files_replacement_and_unsafe_modes_refuse(self):
        with TemporaryDirectory() as directory:
            root=self.stage(directory)
            first=next(iter(origin._NAMES))
            snapshot=origin._Snapshots(root)
            self.assertEqual(snapshot.read(first,100,time.monotonic()+2),b'public')
            (root/first).rename(root/'detached')
            (root/first).write_bytes(b'public')
            with self.assertRaises(origin.SystemOriginError): snapshot.close()
        with TemporaryDirectory() as directory:
            root=self.stage(directory)
            first=next(iter(origin._NAMES))
            (root/first).chmod(0o666)
            snapshot=origin._Snapshots(root)
            try:
                with self.assertRaises(origin.SystemOriginError): snapshot.read(first,100,time.monotonic()+2)
            finally: snapshot.close()

    def test_sealed_public_bytes_cannot_be_rewritten(self):
        descriptor=origin._sealed(b'public')
        try:
            self.assertEqual(os.read(descriptor,6),b'public')
            with self.assertRaises(OSError): os.write(descriptor,b'changed')
        finally: os.close(descriptor)

    def test_command_byte_cap_and_timeout_use_fixed_environment(self):
        real=subprocess.Popen
        for code in ("import sys;sys.stdout.write('x'*17000)","import time;time.sleep(60)"):
            calls=[]
            def spawn(command,**kwargs):
                calls.append((command,kwargs))
                return real([sys.executable,'-I','-c',code],**kwargs)
            descriptor=origin._sealed(b'public')
            try:
                with patch.object(origin.subprocess,'Popen',side_effect=spawn),self.assertRaises(origin.SystemOriginError):
                    origin._command(['/usr/bin/gpgv'],descriptor,time.monotonic()+0.25,16384)
            finally: os.close(descriptor)
            self.assertEqual(calls[0][1]['env'],{'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':'/nonexistent'})

    def test_failed_command_retains_exact_child_when_wait_cannot_verify_cleanup(self):
        real=subprocess.Popen
        owned=[]
        class DelayedWait:
            def __init__(self,process):
                self.process=process
                self.stdout,self.stderr=process.stdout,process.stderr
            def poll(self): return self.process.poll()
            def kill(self): self.process.kill()
            def wait(self,timeout): raise subprocess.TimeoutExpired('fixed-test-command',timeout)
        def spawn(command,**kwargs):
            process=real([sys.executable,'-I','-c',"import sys,time;sys.stdout.write('x'*17000);sys.stdout.flush();time.sleep(60)"],**kwargs)
            proxy=DelayedWait(process)
            owned.append(proxy)
            return proxy
        descriptor=origin._sealed(b'public')
        try:
            with patch.object(origin.subprocess,'Popen',side_effect=spawn),self.assertRaises(subprocess.TimeoutExpired) as caught:
                origin._command(['/usr/bin/gpgv'],descriptor,time.monotonic()+2,16384)
            self.assertIs(caught.exception._mentat_command_owner,owned[0])
            self.assertIn(owned[0],origin._UNREAPED_CHILDREN)
        finally:
            os.close(descriptor)
            for proxy in owned:
                if proxy.process.poll() is None: proxy.process.kill()
                proxy.process.wait(timeout=1)
            origin._drain_children()

    def test_actual_fixed_worker_matches_all_signed_helpers_without_source_change(self):
        supplied=os.environ.get('MENTAT_TEST_HELPER_ORIGIN')
        if not supplied: self.skipTest('Operator-staged public helper artifacts unavailable')
        root=Path(supplied)
        before={name:origin._identity((root/name).stat()) for name in origin._NAMES}
        result=origin.verify_helpers(root)
        self.assertEqual(result['helpers'],origin._expected_helpers())
        self.assertEqual({name:origin._identity((root/name).stat()) for name in origin._NAMES},before)


if __name__=='__main__':
    unittest.main()
