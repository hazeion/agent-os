import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from types import ModuleType
from unittest.mock import patch
import zipfile

from mentat import project_runtime_origin as origin


def tar(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in entries:
            item = tarfile.TarInfo(name)
            if isinstance(data, tuple):
                item.type = tarfile.SYMTYPE
                item.linkname = data[0]
                archive.addfile(item)
            else:
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))
    return buffer.getvalue()


def wheel(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def pax_record(key, value):
    payload = (key + "=" + value + "\n").encode()
    length = len(payload) + 3
    while True:
        actual = len(payload) + 1 + len(str(length))
        if actual == length:
            return str(length).encode() + b" " + payload
        length = actual


class PublicOriginTests(unittest.TestCase):
    def test_fixed_generated_launcher_preserves_nonzero_main_return(self):
        package, module = ModuleType("hermes_cli"), ModuleType("hermes_cli.main")
        module.main = lambda: 7
        with (patch.dict(sys.modules, {"hermes_cli": package, "hermes_cli.main": module}),
              self.assertRaises(SystemExit) as failure):
            exec(compile(origin._hermes_launcher(), "<fixed-public-wrapper>", "exec"), {"__name__": "__main__"})
        self.assertEqual(failure.exception.code, 7)

    def test_packaged_lock_contains_exact_public_anchors_and_explicit_supplements(self):
        lock, digest = origin.load_lock()
        self.assertEqual(lock["source_commit"], origin.COMMIT)
        self.assertEqual(lock["python"]["sha256"], "571a710c62520b26dbadbd16e8850e24565c01dea94440223bc16caa21614021")
        self.assertEqual(len(lock["wheels"]), 111)
        self.assertEqual({item["name"] for item in lock["wheels"] if item["authority"] == "pypi-supplement"},
                         {"botocore", "pip", "s3transfer", "tabulate", "tornado"})
        self.assertEqual(len(digest), 64)

    def test_tar_rejects_unsafe_names_links_special_members_and_duplicates(self):
        entries = [
            [("root/../outside", b"bad")], [("/root/file", b"bad")],
            [("root/file", ("../../outside",))], [("root/file", ("/outside",))],
            [("root/file", b"first"), ("root/file", b"second")],
            [("root/file", b"first"), ("different/file", b"second")],
        ]
        for value in entries:
            with self.subTest(value=value), self.assertRaises(origin.OriginError):
                list(origin.tar_members(tar(value), "source"))
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            item = tarfile.TarInfo("root/socket")
            item.type = tarfile.FIFOTYPE
            archive.addfile(item)
        with self.assertRaises(origin.OriginError):
            list(origin.tar_members(buffer.getvalue(), "source"))

    def test_python_selects_only_public_runtime_and_retains_safe_links(self):
        members = list(origin.tar_members(tar([
            ("python/bin/python3.13", b"public interpreter"), ("python/bin/python3", ("python3.13",)),
            ("python/lib/python3.13/public.py", b"public code"),
            ("python/lib/python3.13/__pycache__/public.pyc", b"cache"),
            ("python/include/public.h", b"unused header")]), "python"))
        self.assertEqual([member.path for member in members], ["python/bin/python3.13", "python/bin/python3",
                                                               "python/lib/python3.13/public.py"])
        self.assertEqual(members[1].link, "python3.13")

    def test_indirect_link_parent_escape_and_cycles_fail_without_host_resolution(self):
        origin._validate_link_graph([origin.Member("source/alias", link="directory"),
                                    origin.Member("source/directory/alias", link="../file")])
        for links in ([origin.Member("source/base", link="nested/alias"),
                       origin.Member("source/nested/alias", link=".."),
                       origin.Member("source/escape", link="base/../outside")],
                      [origin.Member("source/a", link="b"), origin.Member("source/b", link="a")]):
            with self.subTest(links=links), self.assertRaises(origin.OriginError):
                origin._validate_link_graph(links)
        with self.assertRaises(origin.OriginError):
            origin._validate_link_graph([origin.Member("venv/bin/python", link="/unrelated/python")])

    def test_wheel_relocations_are_fixed_and_package_launchers_omitted(self):
        members = list(origin.wheel_members(wheel([
            ("public.py", b"code"), ("pkg.data/purelib/extra.py", b"extra"),
            ("pkg.data/data/share/pkg/readme", b"data"), ("pkg.data/scripts/arbitrary", b"launcher"),
            ("pkg.data/headers/pkg.h", b"header")
        ])))
        self.assertEqual([member.path for member in members], [origin.SITE + "public.py",
                          origin.SITE + "extra.py", "venv/share/pkg/readme"])
        for name in ("../escape", "a//file", "a/./file", "pkg.data/unknown/file"):
            with self.subTest(name=name), self.assertRaises(origin.OriginError):
                list(origin.wheel_members(wheel([(name, b"bad")])))
        for replacement in (b"a\\file", b"a\x00file"):
            # ZipInfo normalizes Windows separators on creation; exercise raw
            # archive bytes rather than that normalized fixture.
            data = wheel([("a!file", b"bad")]).replace(b"a!file", replacement)
            with self.subTest(replacement=replacement), self.assertRaises(origin.OriginError):
                list(origin.wheel_members(data))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            item = zipfile.ZipInfo("malicious")
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(item, "outside")
        with self.assertRaises(origin.OriginError):
            list(origin.wheel_members(buffer.getvalue()))

    def test_parser_budgets_refuse_before_expanding_large_members(self):
        for function, data in ((origin.wheel_members, wheel([("file", b"abcd")])),
                               (lambda value: origin.tar_members(value, "source"), tar([("root/file", b"abcd")]))):
            with patch.object(origin, "MAX_ARCHIVE", 3), self.assertRaises(origin.OriginError):
                list(function(data))
        with patch.object(origin, "MAX_ARCHIVE", 3), self.assertRaises(origin.OriginError):
            list(origin.tar_members(tar([("python/include/unused.h", b"abcd")]), "python"))
        with patch.object(origin, "MAX_EXPANDED", 3), self.assertRaises(origin.OriginError):
            list(origin.tar_members(tar([("python/include/unused.h", b"ab"),
                                        ("python/lib/public.py", b"cd")]), "python"))

    def test_tar_metadata_is_bounded_before_stdlib_extension_processing(self):
        for kind in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK):
            item = tarfile.TarInfo("metadata")
            item.type, item.size = kind, origin.MAX_EXPANDED + 1
            data = gzip.compress(item.tobuf(tarfile.USTAR_FORMAT) + bytes(1024))
            with (self.subTest(kind=kind), patch.object(origin.tarfile, "open", side_effect=AssertionError("late")),
                  self.assertRaises(origin.OriginError)):
                list(origin.tar_members(data, "source"))
        for key, value in (("GNU.sparse.major", "1"), ("size", str(origin.MAX_ARCHIVE + 1))):
            payload = pax_record(key, value)
            item = tarfile.TarInfo("metadata")
            item.type, item.size = tarfile.XHDTYPE, len(payload)
            data = gzip.compress(item.tobuf(tarfile.USTAR_FORMAT) + payload + bytes(512 - len(payload)) + bytes(1024))
            with (self.subTest(key=key), patch.object(origin.tarfile, "open", side_effect=AssertionError("late")),
                  self.assertRaises(origin.OriginError)):
                list(origin.tar_members(data, "source"))
        payload = pax_record("comment", "ok")
        item = tarfile.TarInfo("metadata")
        item.type, item.size = tarfile.XGLTYPE, len(payload)
        chunk = item.tobuf(tarfile.USTAR_FORMAT) + payload + bytes(512 - len(payload))
        with (patch.object(origin, "MAX_MEMBERS", 2),
              patch.object(origin.tarfile, "open", side_effect=AssertionError("late")),
              self.assertRaises(origin.OriginError)):
            list(origin.tar_members(gzip.compress(chunk * 3 + bytes(1024)), "source"))

    def test_zip_actual_count_is_bounded_before_zipinfo_allocation(self):
        raw = bytearray(wheel([("first", b""), ("second", b""), ("third", b"")]))
        struct.pack_into("<HH", raw, len(raw) - 22 + 8, 1, 1)
        with (patch.object(origin, "MAX_MEMBERS", 2),
              patch.object(origin.zipfile, "ZipFile", side_effect=AssertionError("late")),
              self.assertRaises(origin.OriginError)):
            list(origin.wheel_members(bytes(raw)))

    def test_wheel_authority_binds_exact_upstream_tuple_and_supplement_pins(self):
        wheel_entry = {"name": "demo", "version": "1.0", "authority": "official-uv-lock",
                       "url": "https://files.pythonhosted.org/packages/demo.whl", "sha256": "1" * 64,
                       "size": 20}
        uv_bytes = ('[[package]]\nname="demo"\nversion="1.0"\n'
                    'wheels=[{url="https://files.pythonhosted.org/packages/demo.whl",'
                    'hash="sha256:' + "1" * 64 + '",size=20}]\n').encode()
        lock = {"uv_lock_sha256": hashlib.sha256(uv_bytes).hexdigest(), "wheels": [wheel_entry]}
        with patch.object(origin, "_SUPPLEMENTS", {}):
            origin.validate_wheel_authority(lock, uv_bytes)
            for field, value in (("name", "other"), ("version", "2.0"), ("sha256", "2" * 64),
                                 ("size", 21), ("url", "https://files.pythonhosted.org/packages/other.whl"),
                                 ("authority", "pypi-supplement")):
                changed = dict(lock, wheels=[dict(wheel_entry, **{field: value})])
                with self.subTest(field=field), self.assertRaises(origin.OriginError):
                    origin.validate_wheel_authority(changed, uv_bytes)
        supplement = dict(wheel_entry, authority="pypi-supplement")
        with patch.object(origin, "_SUPPLEMENTS", {"demo": ("1.0", "1" * 64)}):
            origin.validate_wheel_authority(dict(lock, wheels=[supplement]), uv_bytes)
            with self.assertRaises(origin.OriginError):
                origin.validate_wheel_authority(dict(lock, wheels=[dict(supplement, sha256="2" * 64)]), uv_bytes)

    def test_wheel_metadata_must_match_approved_coordinate(self):
        data = wheel([("demo-1.0.dist-info/METADATA", b"Name: Demo\nVersion: 1.0\n\n"), ("demo.py", b"code")])
        expected = {"name": "demo", "version": "1.0"}
        self.assertEqual(len(list(origin.wheel_members(data, expected))), 2)
        with self.assertRaises(origin.OriginError):
            list(origin.wheel_members(data, dict(expected, version="2.0")))
        duplicated = wheel([("demo-1.0.dist-info/METADATA", b"Name: Demo\nName: Other\nVersion: 1.0\n\n")])
        with self.assertRaises(origin.OriginError):
            list(origin.wheel_members(duplicated, expected))

    def test_unsupported_platform_fails_before_read_or_write(self):
        with (patch.object(origin.sys, "platform", "win32"), patch.object(origin, "load_lock") as loaded,
              patch.object(origin, "_open_directory") as opened, self.assertRaises(origin.OriginError)):
            origin.build_stage(Path("unused"), Path("unused"))
        loaded.assert_not_called()
        opened.assert_not_called()

    def test_lock_refuses_duplicate_keys_and_unsafe_artifact_names(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "lock.json"
            path.write_text('{"format":1,"format":1}')
            with self.assertRaises(origin.OriginError):
                origin.load_lock(path)
            lock, _ = origin.load_lock()
            lock["source"]["filename"] = "../escape.tar.gz"
            path.write_text(json.dumps(lock))
            with self.assertRaises(origin.OriginError):
                origin.load_lock(path)
            lock, _ = origin.load_lock()
            lock["wheels"][0]["authority"] = "unverified"
            path.write_text(json.dumps(lock))
            with self.assertRaises(origin.OriginError):
                origin.load_lock(path)


@unittest.skipUnless(origin.sys.platform == "linux", "Linux descriptor-relative staging")
class LinuxOriginTests(unittest.TestCase):
    def test_swapped_stage_reads_held_source_and_refuses_successful_report(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            destination = root / "stage"
            public_wheel = wheel([("demo-1.0.dist-info/METADATA", b"Name: Demo\nVersion: 1.0\n\n"),
                                  ("demo.py", b"public bytes")])
            wheel_sha = hashlib.sha256(public_wheel).hexdigest()
            public_url = "https://files.pythonhosted.org/packages/demo.whl"
            uv_bytes = ('[[package]]\nname="demo"\nversion="1.0"\nwheels=[{url="' + public_url
                        + '",hash="sha256:' + wheel_sha + '",size=' + str(len(public_wheel)) + '}]\n').encode()
            raw = {"source": tar([("root/uv.lock", uv_bytes)]),
                   "python": tar([("python/bin/python3.13", b"fake interpreter, never executed")]),
                   "demo": public_wheel}
            entries = {}
            for name, data in raw.items():
                filename = name + (".whl" if name == "demo" else ".tar.gz")
                (artifacts / filename).write_bytes(data)
                entries[name] = {"filename": filename, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            entry = dict(entries["demo"], name="demo", version="1.0", authority="official-uv-lock", url=public_url)
            lock = {"source": entries["source"], "python": entries["python"], "wheels": [entry],
                    "uv_lock_sha256": hashlib.sha256(uv_bytes).hexdigest()}
            add = origin._Stage.add
            swapped = False

            def swapping(stage, member):
                nonlocal swapped
                add(stage, member)
                if not swapped:
                    swapped = True
                    destination.rename(root / "detached")
                    destination.mkdir(mode=0o700)
                    (destination / "source").mkdir()
                    (destination / "source/uv.lock").write_bytes(b"foreign named file")

            with (patch.object(origin, "load_lock", return_value=(lock, "0" * 64)),
                  patch.object(origin, "_SUPPLEMENTS", {}), patch.object(origin._Stage, "add", swapping),
                  self.assertRaisesRegex(origin.OriginError, "runtime_origin.destination")):
                origin.build_stage(artifacts, destination)
            self.assertTrue(swapped)
            self.assertEqual((destination / "source/uv.lock").read_bytes(), b"foreign named file")
            self.assertEqual((root / "detached/source/uv.lock").read_bytes(), uv_bytes)

    def test_hash_verification_parses_only_captured_bytes_and_refuses_symlink(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "public.whl"
            data = b"public artifact"
            path.write_bytes(data)
            item = {"filename": path.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            descriptor = origin._open_directory(root)
            try:
                verified = origin._artifact(descriptor, item)
                path.write_bytes(b"replaced bytes")
                self.assertEqual(verified, data)
                with self.assertRaises(origin.OriginError):
                    origin._artifact(descriptor, item)
                alias = root / "alias.whl"
                alias.symlink_to(path)
                with self.assertRaises(OSError):
                    origin._artifact(descriptor, dict(item, filename=alias.name))
            finally:
                os.close(descriptor)

    def test_stage_refuses_symlink_ancestors_collisions_and_links_before_files(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage_path = root / "stage"
            stage_path.mkdir()
            outside = root / "outside"
            outside.mkdir()
            stage = origin._Stage(stage_path)
            try:
                stage.add(origin.Member("source/alias", link="directory"))
                stage.add(origin.Member("source/directory/file", b"public"))
                self.assertFalse((stage_path / "source/alias").exists())
                stage.finish_links()
                self.assertEqual((stage_path / "source/alias/file").read_bytes(), b"public")
                with self.assertRaises(origin.OriginError):
                    stage.add(origin.Member("source/directory/file", b"changed"))
                (stage_path / "foreign").symlink_to(outside)
                with self.assertRaises(OSError):
                    stage.add(origin.Member("foreign/file", b"escape"))
                self.assertFalse((outside / "file").exists())
            finally:
                stage.close()

    def test_existing_stage_is_never_overwritten(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage = root / "stage"
            stage.mkdir()
            (stage / "sentinel").write_bytes(b"retained")
            with self.assertRaises(FileExistsError):
                origin.build_stage(root, stage)
            self.assertEqual((stage / "sentinel").read_bytes(), b"retained")


if __name__ == "__main__":
    unittest.main()
