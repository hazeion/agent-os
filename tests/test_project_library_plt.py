"""Low-level hostile metadata fixtures; no fixture claims library provenance."""
from dataclasses import replace
import hashlib
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from mentat import project_library_plt as plt
from mentat import project_runtime_host_trust as host
from mentat.project_runtime_elf import RuntimeElfError, inspect_host_elf
from tests.test_project_runtime_host_trust import elf as helper_elf


BASE = 0x1000
A = 0x4000
GOT = 0x6000
DYNAMIC = 0x400


def fixture(role="libc"):
    raw = bytearray(0x4000)
    ident = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into('<16sHHIQQQIHHHHHH', raw, 0, ident, 3, 62, 1, 0, 64, 0, 0, 64, 56, 4, 0, 0, 0)
    for n, values in enumerate([(1,4,0,BASE,0,0x2000,0x2000,4096),
                                (1,5,0x2000,A,0,0x1000,0x1000,4096),
                                (1,6,0x3000,GOT,0,0x1000,0x1000,4096)]):
        struct.pack_into('<IIQQQQQQ', raw, 64+n*56, *values)
    strings = bytearray(b'\0'); offsets = {}
    for text in ['func',plt.MARKER,'libc.so.6','ld-linux-x86-64.so.2','GLIBC_PRIVATE','libm.so.6']:
        offsets[text]=len(strings); strings.extend(text.encode()+b'\0')
    raw[0x800:0x800+len(strings)] = strings
    tags=[(5,0x1800),(10,len(strings)),(6,0x1900),(11,24),(4,0x1a00),(0x6ffffef5,0x1b00),
          (0x6ffffff0,0x1c00),(0x6ffffffc,0x1d00),(0x6ffffffd,1),(0x6ffffffe,0x1e00),(0x6fffffff,1),
          (23,0x1f00),(2,48),(20,7),(9,24),(14,offsets['libc.so.6' if role=='libc' else 'libm.so.6']),
          (1,offsets['ld-linux-x86-64.so.2' if role=='libc' else 'libc.so.6']),
          (0x70000000,A),(0x70000001,32),(0x70000003,16),(21,0),(0,0)]
    positions={}
    for n,(tag,value) in enumerate(tags):
        struct.pack_into('<qQ',raw,DYNAMIC+16*n,tag,value);positions[tag]=DYNAMIC+16*n
    struct.pack_into('<IIQQQQQQ',raw,64+3*56,2,4,DYNAMIC,BASE+DYNAMIC,0,len(tags)*16,len(tags)*16,8)
    # Three bounded symbols; symbol1 is the sole JUMP_SLOT reference.
    struct.pack_into('<IBBHQQ',raw,0x900+24,offsets['func'],0x12,0,0,0,0)
    struct.pack_into('<II4I',raw,0xa00,1,3,1,0,2,0)
    struct.pack_into('<IIIIQIII',raw,0xb00,1,1,1,5,0,1,2,3)
    struct.pack_into('<3H',raw,0xc00,0,2,1)
    definition=plt.MARKER if role=='libc' else 'libm.so.6'
    struct.pack_into('<HHHHIII',raw,0xd00,1,0 if role=='libc' else 1,2 if role=='libc' else 1,1,plt._elf_hash(definition),20,0)
    struct.pack_into('<II',raw,0xd00+20,offsets[definition],0)
    provider='ld-linux-x86-64.so.2' if role=='libc' else 'libc.so.6'
    requirement='GLIBC_PRIVATE' if role=='libc' else plt.MARKER
    struct.pack_into('<HHIII',raw,0xe00,1,1,offsets[provider],16,0)
    struct.pack_into('<IHHII',raw,0xe00+16,plt._elf_hash(requirement),0,3 if role=='libc' else 2,offsets[requirement],0)
    struct.pack_into('<QQq',raw,0xf00,GOT,(1<<32)|7,A+4)
    struct.pack_into('<QQq',raw,0xf00+24,GOT+8,37,A+0x100)
    for n in range(2):
        slot=GOT+8*n; location=A+16*n
        raw[0x2000+16*n:0x2010+16*n]=bytes.fromhex('f3 0f 1e fa ff 25')+struct.pack('<i',slot-location-10)+bytes.fromhex('66 0f 1f 44 00 00')
    raw[0x2100]=0xc3
    profile=plt._Profile(len(raw),'fixture',A,32,1,1,role)
    return raw,profile,positions,offsets


class LibraryPltTests(unittest.TestCase):
    def reject(self, raw, profile):
        with self.assertRaises(RuntimeElfError): plt._validate_plt(bytes(raw),profile)

    def test_complete_metadata_fixture_accepts_both_roles_without_execution(self):
        for role in ['libc','libm']:
            raw,profile,_,_=fixture(role)
            self.assertEqual(plt._validate_plt(bytes(raw),profile).soname,role+'.so.6')

    def test_fixed_member_selection_requires_exact_compiled_identity(self):
        raw,profile,_,_=fixture();path='/usr/lib/x86_64-linux-gnu/libc.so.6'
        with self.assertRaises(RuntimeElfError):plt._inspect_fixed_member(path,bytes(raw))
        matching=replace(profile,digest=hashlib.sha256(raw).hexdigest())
        with patch.dict(plt._PROFILES,{path:matching}):
            self.assertEqual(plt._inspect_fixed_member(path,bytes(raw)).soname,'libc.so.6')
            for changed in [bytes(raw)+b'changed',bytes(raw[:-1]),bytes(len(raw))]:
                with self.assertRaises(RuntimeElfError):plt._inspect_fixed_member(path,changed)
            with self.assertRaises(RuntimeElfError):plt._inspect_fixed_member(path+'.other',bytes(raw))

    def test_ordinary_parser_and_public_graph_still_refuse_tagged_members(self):
        raw,_,_,_=fixture();payload=bytes(raw)
        with self.assertRaises(RuntimeElfError):inspect_host_elf(payload)
        helper=helper_elf(executable=True);pin=host._HELPERS['bwrap']
        with patch.dict(host._HELPERS,{'bwrap':replace(pin,member_size=len(helper),member_digest=hashlib.sha256(helper).hexdigest())}):
            with self.assertRaises(host.HostClosureError):
                host.audit_fixed_helper_closure('bwrap',(('/usr/bin/bwrap',helper),('/usr/lib/x86_64-linux-gnu/libc.so.6',payload)))

    def test_partial_duplicate_and_unknown_processor_tags_refuse(self):
        for mutation in ['missing','duplicate','unknown']:
            raw,profile,pos,_=fixture()
            if mutation=='missing':struct.pack_into('<q',raw,pos[0x70000001],12)
            elif mutation=='duplicate':struct.pack_into('<qQ',raw,pos[21],0x70000000,A)
            else:struct.pack_into('<qQ',raw,pos[21],0x70000002,1)
            self.reject(raw,profile)

    def test_entry_size_alignment_size_and_overflow_refuse(self):
        for entry in [0,8,24,32]:
            raw,profile,pos,_=fixture();struct.pack_into('<Q',raw,pos[0x70000003]+8,entry);self.reject(raw,profile)
        raw,profile,pos,_=fixture();struct.pack_into('<Q',raw,pos[0x70000000]+8,A+1);self.reject(raw,replace(profile,address=A+1))
        raw,profile,pos,_=fixture();struct.pack_into('<Q',raw,pos[0x70000001]+8,31);self.reject(raw,replace(profile,table_bytes=31))
        with self.assertRaises(RuntimeElfError):plt._add(0xfffffffffffffff0,32)

    def test_plt_requires_unique_read_execute_file_mapping_without_write(self):
        for change in ['wx','bss','overlap']:
            raw,profile,_,_=fixture()
            if change=='wx':struct.pack_into('<I',raw,64+56+4,7)
            elif change=='bss':struct.pack_into('<Q',raw,64+56+32,16)
            else:
                struct.pack_into('<H',raw,56,5)
                struct.pack_into('<IIQQQQQQ',raw,64+4*56,1,5,0x2008,A+8,0,8,8,1)
            self.reject(raw,profile)

    def test_template_nop_displacement_and_got_uniqueness_refuse(self):
        for offset in [0x2000,0x2004,0x200f]:
            raw,profile,_,_=fixture();raw[offset]^=1;self.reject(raw,profile)
        for displacement in [1,0x7fffffff]:
            raw,profile,_,_=fixture();struct.pack_into('<i',raw,0x2006,displacement);self.reject(raw,profile)
        raw,profile,_,_=fixture();struct.pack_into('<i',raw,0x2016,GOT-(A+16)-10);self.reject(raw,profile)
        raw,profile,_,_=fixture();struct.pack_into('<I',raw,64+2*56+4,7);self.reject(raw,profile)

    def test_rela_type_size_count_slot_and_addend_constraints(self):
        for tag,value in [(20,17),(9,16),(2,72)]:
            raw,profile,pos,_=fixture();struct.pack_into('<Q',raw,pos[tag]+8,value);self.reject(raw,profile)
        for info in [8,(1<<32)|37,(3<<32)|7,7]:
            raw,profile,_,_=fixture();struct.pack_into('<Q',raw,0xf00+8,info);self.reject(raw,profile)
        raw,profile,_,_=fixture();struct.pack_into('<q',raw,0xf00+16,A);self.reject(raw,profile)
        raw,profile,_,_=fixture();struct.pack_into('<Q',raw,0xf00+24,GOT);self.reject(raw,profile)
        for resolver in [0,GOT,A+4,-1]:
            raw,profile,_,_=fixture();struct.pack_into('<q',raw,0xf00+24+16,resolver);self.reject(raw,profile)
        raw,profile,_,_=fixture();struct.pack_into('<Q',raw,0xf00+24+8,(1<<32)|37);self.reject(raw,profile)

    def test_sysv_gnu_hash_counts_chains_and_bloom_are_bounded(self):
        for offset,value in [(0xa00,65537),(0xa00+4,65537),(0xa00+8,3),(0xa00+16,1),
                             (0xb00,0),(0xb00+4,4),(0xb00+8,0),(0xb00+8,3),(0xb00+12,64),
                             (0xb00+24,3),(0xb00+24,2),(0xb00+32,2)]:
            raw,profile,_,_=fixture();struct.pack_into('<I',raw,offset,value);self.reject(raw,profile)

    def test_symbol_string_and_version_bounds_refuse(self):
        for offset,value,fmt in [(0x900+24,9999,'<I'),(0xc00+2,4,'<H'),(0xd00+6,5000,'<H'),
                                 (0xd00+12,0,'<I'),(0xd00+16,20,'<I'),(0xe00+8,0,'<I'),
                                 (0xe00+16+6,2,'<H'),(0xe00+16,123,'<I')]:
            raw,profile,_,_=fixture();struct.pack_into(fmt,raw,offset,value);self.reject(raw,profile)
        raw,profile,pos,_=fixture();struct.pack_into('<Q',raw,pos[10]+8,1024*1024+1);self.reject(raw,profile)
        raw,profile,pos,_=fixture();struct.pack_into('<Q',raw,pos[11]+8,16);self.reject(raw,profile)
        raw,profile,_,_=fixture();raw[0x801:0x800+128]=b'x'*127;self.reject(raw,profile)

    def test_marker_is_structured_and_correct_provider_not_text_search(self):
        raw,profile,_,offsets=fixture();name='X'+plt.MARKER[1:]
        raw[0x800+offsets[plt.MARKER]]=ord('X');struct.pack_into('<I',raw,0xd00+8,plt._elf_hash(name));self.reject(raw,profile)
        raw,profile,_,offsets=fixture('libm');struct.pack_into('<I',raw,0xe00+4,offsets['ld-linux-x86-64.so.2']);self.reject(raw,profile)
        raw,profile,_,_=fixture('libm');struct.pack_into('<H',raw,0xe00+16+4,2);self.reject(raw,profile)

    def test_shared_graph_rejects_stale_parsed_byte_binding(self):
        helper=helper_elf(executable=True);pin=host._HELPERS['bwrap']
        with patch.dict(host._HELPERS,{'bwrap':replace(pin,member_size=len(helper),member_digest=hashlib.sha256(helper).hexdigest())}):
            members=host._prepare_members('bwrap',(('/usr/bin/bwrap',helper),))
            stale=host._ParsedElf('0'*64,len(helper),inspect_host_elf(helper))
            with self.assertRaises(host.HostClosureError):host._audit_graph('bwrap',members,{'/usr/bin/bwrap':stale})


if __name__=='__main__':unittest.main()
