"""Offline public-artifact staging for Project runtime qualification.

This builds a new disposable candidate from reviewed public artifact digests.
It never reads an installed Hermes home/venv, downloads, installs, submits a
model request, or grants runtime readiness or Run authority.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from email.parser import BytesParser
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import struct
import sys
import tarfile
import tomllib
from urllib.parse import urlsplit
import zipfile

import deploy
from mentat.project_worker_scope import _open_directory

MAX_ARCHIVE = 128 * 1024 * 1024
MAX_MEMBERS = 40_000
MAX_EXPANDED = 1024 * 1024 * 1024
SITE = "venv/lib/python3.13/site-packages/"
VIRTUAL = "/opt/mentat-runtime"
COMMIT = "f97608f178d1ffeca59860195ab7da295f7c8e5f"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SUPPLEMENTS = {
    "botocore": ("1.42.97", "77d2c8ce1bc592d3fbd7c01c35836f4a5b0cac2ca03ccdf6ffc60faa16b5fadc"),
    "pip": ("26.1.2", "382ff9f685ee3bc25864f820aa50505825f10f5458ffff07e30a6d96e5715cab"),
    "s3transfer": ("0.16.1", "61bcd00ccb83b21a0fe7e91a553fff9729d46c83b4e0106e7c314a733891f7c2"),
    "tabulate": ("0.10.0", "f0b0622e567335c8fabaaa659f1b33bcb6ddfe2e496071b743aa113f8774f2d3"),
    "tornado": ("6.5.10", "bdf942448169e5336451d0494d7e3d81cfa726d5aa312affdc4682dd62a62f6d"),
}


def _canonical(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value) is None:
        _fail("lock")
    return re.sub(r"[-_.]+", "-", value).lower()


class OriginError(RuntimeError):
    pass


def _fail(code):
    raise OriginError("runtime_origin." + code)


def _name(value):
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024
            or "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(part in ("", ".", "..") for part in value.split("/"))):
        _fail("path")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("lock")
        result[key] = value
    return result


def load_lock(path=None):
    path = path or Path(deploy.__file__).with_name("project-runtime-origin-lock.json")
    with path.open("rb") as reader:
        data = reader.read(128 * 1024 + 1)
    if len(data) > 128 * 1024:
        _fail("lock")
    try:
        lock = json.loads(data, object_pairs_hook=_pairs)
        if (set(lock) != {"format", "source_commit", "uv_lock_sha256", "source", "python", "wheels"}
                or type(lock["format"]) is not int or lock["format"] != 1
                or lock["source_commit"] != COMMIT or not _HEX.fullmatch(lock["uv_lock_sha256"])
                or not isinstance(lock["wheels"], list) or not 1 <= len(lock["wheels"]) <= 128):
            _fail("lock")
        names = set()
        for artifact in [lock["source"], lock["python"], *lock["wheels"]]:
            expected = {"filename", "sha256", "size", "url"}
            if artifact in lock["wheels"]:
                expected |= {"authority", "name", "version"}
            if set(artifact) != expected or not isinstance(artifact["url"], str):
                _fail("lock")
            filename = _name(artifact["filename"])
            if ("/" in filename or filename in names or not _HEX.fullmatch(artifact["sha256"])
                    or type(artifact["size"]) is not int or not 0 < artifact["size"] <= MAX_ARCHIVE):
                _fail("lock")
            names.add(filename)
        if (not lock["source"]["filename"].endswith(".tar.gz")
                or not lock["python"]["filename"].endswith(".tar.gz")
                or any(not item["filename"].endswith(".whl") for item in lock["wheels"])):
            _fail("lock")
        packages = set()
        for item in lock["wheels"]:
            url = urlsplit(item["url"])
            if (item["name"] != _canonical(item["name"]) or item["name"] in packages
                    or not isinstance(item["version"], str)
                    or re.fullmatch(r"[0-9A-Za-z.+!_-]{1,80}", item["version"]) is None
                    or item["authority"] not in ("official-uv-lock", "pypi-supplement")
                    or url.scheme != "https" or url.netloc != "files.pythonhosted.org"
                    or not url.path.startswith("/packages/") or url.query or url.fragment
                    or url.path.rsplit("/", 1)[-1] != item["filename"]):
                _fail("lock")
            packages.add(item["name"])
    except (TypeError, KeyError, ValueError, UnicodeError, RecursionError):
        _fail("lock")
    return lock, hashlib.sha256(data).hexdigest()


def validate_wheel_authority(lock, uv_bytes):
    """Prove every claimed upstream relation; supplements are separate pins."""
    if len(uv_bytes) > 8 * 1024 * 1024 or hashlib.sha256(uv_bytes).hexdigest() != lock["uv_lock_sha256"]:
        _fail("lock")
    try:
        packages = tomllib.loads(uv_bytes.decode())["package"]
        supplements = set()
        for item in lock["wheels"]:
            if item["authority"] == "pypi-supplement":
                if _SUPPLEMENTS.get(item["name"]) != (item["version"], item["sha256"]):
                    _fail("authority")
                supplements.add(item["name"])
                continue
            matches = [package for package in packages if _canonical(package["name"]) == item["name"]
                       and package["version"] == item["version"]]
            expected = (item["url"], "sha256:" + item["sha256"], item["size"])
            if len(matches) != 1 or expected not in {
                    (wheel["url"], wheel["hash"], wheel["size"]) for wheel in matches[0].get("wheels", [])}:
                _fail("authority")
        if supplements != set(_SUPPLEMENTS):
            _fail("authority")
    except (TypeError, KeyError, ValueError, UnicodeError, RecursionError):
        _fail("authority")


def _artifact(directory, item):
    fd = os.open(item["filename"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 dir_fd=directory)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_size != item["size"]:
            _fail("artifact")
        chunks, remaining = [], item["size"] + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            _fail("artifact")
        # Parse only these verified in-memory bytes, never a mutable source FD.
        return data
    finally:
        os.close(fd)


def _pax_metadata(data):
    allowed = {"path", "linkpath", "size", "uid", "gid", "uname", "gname",
               "mtime", "atime", "ctime", "comment"}
    position = 0
    while position < len(data):
        space = data.find(b" ", position, position + 8)
        if space < 0 or not data[position:space].isdigit():
            _fail("tar")
        length = int(data[position:space])
        end = position + length
        if not length or end > len(data) or end <= space + 1 or data[end - 1:end] != b"\n":
            _fail("tar")
        record = data[space + 1:end - 1]
        key, separator, value = record.partition(b"=")
        try:
            key = key.decode("ascii")
        except UnicodeError:
            _fail("tar")
        if not separator or key not in allowed or len(value) > 1024:
            _fail("tar")
        if key == "size" and (not value.isdigit() or len(value) > 10 or int(value) > MAX_ARCHIVE):
            _fail("budget")
        position = end


def _tar_preflight(data):
    """Bound raw metadata/payload before tarfile parses PAX/GNU extensions."""
    count = total = extensions = 0
    metadata_types = {tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK}
    with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as stream:
        while True:
            block = stream.read(512)
            if len(block) != 512:
                _fail("tar")
            if block == bytes(512):
                if stream.read(512) != bytes(512):
                    _fail("tar")
                tail = stream.read(64 * 1024 + 1)
                if len(tail) > 64 * 1024 or any(tail):
                    _fail("tar")
                return
            count += 1
            if count > MAX_MEMBERS:
                _fail("budget")
            try:
                item = tarfile.TarInfo.frombuf(block, "utf-8", "strict")
            except (tarfile.TarError, ValueError, UnicodeError):
                _fail("tar")
            size = item.size
            if not 0 <= size <= MAX_ARCHIVE:
                _fail("budget")
            rounded = (size + 511) // 512 * 512
            total += 512 + rounded
            if total > MAX_EXPANDED:
                _fail("budget")
            if item.type in metadata_types:
                extensions += 1
                if size > 64 * 1024 or extensions > 8:
                    _fail("budget")
                payload = stream.read(rounded)
                if len(payload) != rounded:
                    _fail("tar")
                payload = payload[:size]
                if item.type in (tarfile.XHDTYPE, tarfile.XGLTYPE):
                    _pax_metadata(payload)
                elif len(payload.rstrip(b"\x00")) > 1024:
                    _fail("path")
            else:
                extensions = 0
                if not (item.isfile() or item.isdir() or item.issym()) or item.type == tarfile.GNUTYPE_SPARSE:
                    _fail("tar")
                if not item.isfile() and size:
                    _fail("tar")
                remaining = rounded
                while remaining:
                    chunk = stream.read(min(remaining, 64 * 1024))
                    if not chunk:
                        _fail("tar")
                    remaining -= len(chunk)


def _zip_preflight(data):
    """Count actual central records before ZipFile allocates ZipInfo objects."""
    if len(data) < 22:
        _fail("zip")
    signature, disk, central_disk, disk_count, declared_count, size, offset, comment = struct.unpack_from(
        "<4s4H2LH", data, len(data) - 22)
    if (signature != b"PK\x05\x06" or disk or central_disk or comment or disk_count != declared_count
            or not 0 < declared_count <= MAX_MEMBERS or offset + size != len(data) - 22):
        _fail("zip")
    position, count = offset, 0
    while position < offset + size:
        count += 1
        if count > MAX_MEMBERS or position + 46 > offset + size:
            _fail("budget")
        header = struct.unpack_from("<4s6H3L5H2L", data, position)
        name_size, extra_size, comment_size = header[10:13]
        if (header[0] != b"PK\x01\x02" or header[13] or header[3] & 1
                or not 0 < name_size <= 1024 or extra_size > 4096 or comment_size > 1024):
            _fail("zip")
        position += 46 + name_size + extra_size + comment_size
        if position > offset + size:
            _fail("zip")
    if count != declared_count or position != offset + size:
        _fail("zip")


@dataclass(frozen=True)
class Member:
    path: str
    data: bytes | None = None
    executable: bool = False
    link: str | None = None


def tar_members(data, kind):
    _tar_preflight(data)
    seen = set()
    count = total = 0
    prefix = None
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for item in archive:
            count += 1
            if count > MAX_MEMBERS:
                _fail("budget")
            name = _name(item.name[:-1] if item.isdir() and item.name.endswith("/") else item.name)
            parts = name.split("/")
            if prefix is None:
                prefix = parts[0]
            if parts[0] != prefix or (kind == "python" and prefix != "python"):
                _fail("tar")
            relative = "/".join(parts[1:])
            if name in seen:
                _fail("duplicate")
            seen.add(name)
            # Charge even unselected public include/share/cache payloads before
            # tar iteration can decompress past them.
            total += item.size
            if not 0 <= item.size <= MAX_ARCHIVE or total > MAX_EXPANDED:
                _fail("budget")
            if item.isdir():
                if item.size:
                    _fail("tar")
                continue
            if not relative or not (item.isfile() or item.issym()):
                _fail("tar")
            if kind == "python" and not relative.startswith(("bin/", "lib/")):
                continue
            if "__pycache__" in relative.split("/") or relative.endswith((".pyc", ".pyo")):
                continue
            target = kind + "/" + relative
            if item.issym():
                if item.size:
                    _fail("tar")
                link = item.linkname
                if (not link or link.startswith("/") or "\\" in link
                        or any(ord(c) < 32 or ord(c) == 127 for c in link)
                        or len(link.encode("utf-8")) > 1024):
                    _fail("link")
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative), link))
                if resolved == ".." or resolved.startswith("../"):
                    _fail("link")
                yield Member(target, link=link)
            else:
                content = archive.extractfile(item).read(item.size + 1)
                if len(content) != item.size:
                    _fail("tar")
                yield Member(target, content, bool(item.mode & 0o111))


def wheel_members(data, expected=None):
    _zip_preflight(data)
    seen = set()
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        items = archive.infolist()
        if len(items) > MAX_MEMBERS:
            _fail("budget")
        if expected is not None:
            metadata = [item for item in items if item.filename.endswith(".dist-info/METADATA")]
            if len(metadata) != 1 or metadata[0].file_size > 512 * 1024:
                _fail("metadata")
            headers = BytesParser().parsebytes(archive.read(metadata[0]))
            if (headers.get_all("Name") != [headers.get("Name")]
                    or headers.get_all("Version") != [expected["version"]]
                    or _canonical(headers.get("Name")) != expected["name"]):
                _fail("metadata")
        for item in items:
            if item.filename != item.orig_filename:
                _fail("path")
            name = _name(item.filename[:-1] if item.is_dir() else item.filename)
            if name in seen:
                _fail("duplicate")
            seen.add(name)
            mode = item.external_attr >> 16
            if item.flag_bits & 1 or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                _fail("zip")
            if item.is_dir():
                continue
            total += item.file_size
            if not 0 <= item.file_size <= MAX_ARCHIVE or total > MAX_EXPANDED:
                _fail("budget")
            parts = name.split("/")
            if parts[0].endswith(".data"):
                if len(parts) < 3:
                    _fail("zip")
                if parts[1] in ("purelib", "platlib"):
                    target = SITE + "/".join(parts[2:])
                elif parts[1] == "data":
                    target = "venv/" + "/".join(parts[2:])
                elif parts[1] in ("scripts", "headers"):
                    # Neither arbitrary package launchers nor build headers are
                    # used by the fixed proposal operation.
                    continue
                else:
                    _fail("zip")
            else:
                target = SITE + name
            content = archive.read(item)
            if len(content) != item.file_size:
                _fail("zip")
            yield Member(target, content, bool(mode & 0o111))


def _validate_link_graph(links):
    targets = {member.path: member.link for member in links}
    for member in links:
        if member.path in {"venv/bin/" + name for name in ("python", "python3", "python3.13")}:
            if member.link != VIRTUAL + "/python/bin/python3.13":
                _fail("link")
            continue
        parts = member.path.split("/")[:-1]
        if not parts or parts[0] not in ("source", "python") or member.link.startswith("/"):
            _fail("link")
        root = parts[0]
        pending = member.link.split("/")
        expansions = 0
        while pending:
            component = pending.pop(0)
            if component in ("", "."):
                continue
            if component == "..":
                if len(parts) <= 1:
                    _fail("link")
                parts.pop()
                continue
            parts.append(component)
            target = targets.get("/".join(parts))
            if target is not None:
                expansions += 1
                if expansions > 32 or target.startswith("/"):
                    _fail("link")
                parts.pop()
                pending = target.split("/") + pending
        if not parts or parts[0] != root:
            _fail("link")


class _Stage:
    def __init__(self, root=None, *, descriptor=None):
        self.fd = _open_directory(root) if descriptor is None else os.dup(descriptor)
        details = os.fstat(self.fd)
        self.identity = (details.st_dev, details.st_ino)
        self.seen, self.links = set(), []
        self.total = 0
        self.digest = hashlib.sha256()

    def close(self):
        os.close(self.fd)

    def _parent(self, name):
        parts = _name(name).split("/")
        descriptor = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor, parts[-1]
        except BaseException:
            os.close(descriptor)
            raise

    def add(self, member):
        if member.path in self.seen:
            _fail("collision")
        self.seen.add(member.path)
        self.total += len(member.data) if member.data is not None else 0
        if len(self.seen) > MAX_MEMBERS or self.total > MAX_EXPANDED:
            _fail("budget")
        self.digest.update(json.dumps([member.path, member.executable, member.link,
            hashlib.sha256(member.data).hexdigest() if member.data is not None else None],
            ensure_ascii=True, separators=(",", ":")).encode() + b"\n")
        if member.link is not None:
            self.links.append(member)
            return
        parent, name = self._parent(member.path)
        try:
            descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o555 if member.executable else 0o444, dir_fd=parent)
            with os.fdopen(descriptor, "wb") as writer:
                writer.write(member.data)
        finally:
            os.close(parent)

    def finish_links(self):
        # No regular payload can traverse an archive-supplied symlink.
        # Lexical normalization alone misses a link followed by '..'; resolve
        # the bounded private link graph without following any host path.
        _validate_link_graph(self.links)
        for member in self.links:
            parent, name = self._parent(member.path)
            try:
                os.symlink(member.link, name, dir_fd=parent)
            finally:
                os.close(parent)


def _read_stage_lock(stage):
    directory = os.open("source", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=stage.fd)
    descriptor = None
    try:
        descriptor = os.open("uv.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=directory)
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or not 0 < details.st_size <= 8 * 1024 * 1024:
            _fail("lock")
        with os.fdopen(descriptor, "rb") as reader:
            descriptor = None
            data = reader.read(8 * 1024 * 1024 + 1)
        if len(data) != details.st_size:
            _fail("lock")
        return data
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


def _verify_stage_name(parent, destination, stage):
    named = os.stat(destination.name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISDIR(named.st_mode) or (named.st_dev, named.st_ino) != stage.identity:
        _fail("destination")
    current = _open_directory(destination.parent)
    try:
        before, after = os.fstat(parent), os.fstat(current)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            _fail("destination")
    finally:
        os.close(current)


def _hermes_launcher():
    return ("#!" + VIRTUAL + "/venv/bin/python\nfrom hermes_cli.main import main\n"
            "if __name__ == '__main__':\n    raise SystemExit(main())\n").encode()


def build_stage(artifacts: Path, destination: Path):
    if sys.platform != "linux" or not hasattr(os, "O_NOFOLLOW"):
        _fail("unsupported")
    lock, lock_digest = load_lock()
    artifacts_fd = _open_directory(artifacts)
    parent = None
    child = None
    stage = None
    try:
        if not destination.is_absolute() or destination.name in ("", ".", "..") or ".." in destination.parts:
            _fail("destination")
        parent = _open_directory(destination.parent)
        parent_details = os.fstat(parent)
        if (parent_details.st_uid not in (0, os.getuid())
                or parent_details.st_mode & 0o022 and not parent_details.st_mode & stat.S_ISVTX):
            _fail("destination")
        os.mkdir(destination.name, 0o700, dir_fd=parent)
        child = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=parent)
        details = os.fstat(child)
        if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700:
            _fail("destination")
        stage = _Stage(descriptor=child)
        for kind in ("source", "python"):
            for member in tar_members(_artifact(artifacts_fd, lock[kind]), kind):
                stage.add(member)
        validate_wheel_authority(lock, _read_stage_lock(stage))
        for item in lock["wheels"]:
            for member in wheel_members(_artifact(artifacts_fd, item), item):
                stage.add(member)
        stage.add(Member("venv/pyvenv.cfg", ("home = " + VIRTUAL + "/python/bin\n"
                        "include-system-site-packages = false\nversion = 3.13.14\n").encode()))
        stage.add(Member(SITE + "mentat_hermes_source.pth", (VIRTUAL + "/source\n").encode()))
        for name in ("python", "python3", "python3.13"):
            stage.add(Member("venv/bin/" + name, link=VIRTUAL + "/python/bin/python3.13"))
        stage.add(Member("venv/bin/hermes", _hermes_launcher(), True))
        stage.finish_links()
        _verify_stage_name(parent, destination, stage)
        return {"format": 1, "source_commit": COMMIT, "artifact_lock_sha256": lock_digest,
                "members": len(stage.seen), "expanded_bytes": stage.total,
                "payload_inventory_sha256": stage.digest.hexdigest(), "wheels": len(lock["wheels"]),
                "virtual_root": VIRTUAL, "provider_calls": 0, "production_qualified": False}
    finally:
        if stage is not None:
            stage.close()
        if child is not None:
            os.close(child)
        if parent is not None:
            os.close(parent)
        os.close(artifacts_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build_stage(args.artifacts, args.stage), sort_keys=True))
        return 0
    except (OriginError, OSError, ValueError, tarfile.TarError, zipfile.BadZipFile):
        print("runtime_origin.failed; any created stage remains a disposable incomplete candidate", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
