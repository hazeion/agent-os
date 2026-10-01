"""Fixed disposable FUSE inspection; potentially blocking calls stay here."""
from __future__ import annotations

import array
import ctypes
import json
import os
import socket
import stat
import sys


def inspect(descriptor):
    details = os.fstat(descriptor)
    if not stat.S_ISDIR(details.st_mode):
        raise ValueError("directory")
    buffer = ctypes.create_string_buffer(256)
    library = ctypes.CDLL(None, use_errno=True)
    library.fstatfs.argtypes = (ctypes.c_int, ctypes.c_void_p)
    library.fstatfs.restype = ctypes.c_int
    if library.fstatfs(descriptor, ctypes.byref(buffer)) or ctypes.c_long.from_buffer(buffer).value != 0x65735546:
        raise ValueError("filesystem")
    if not os.fstatvfs(descriptor).f_flag & os.ST_RDONLY:
        raise ValueError("readonly")
    with open("/proc/self/fdinfo/" + str(descriptor)) as source:
        fields = dict(line.split(":", 1) for line in source.read(4096).splitlines() if ":" in line)
    return [int(fields["mnt_id"]), details.st_dev, details.st_ino]


def main():
    endpoint = socket.socket(fileno=int(sys.argv[1]))
    base = int(sys.argv[2])
    mode = sys.argv[3]
    descriptors = []
    flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        root = os.open("mount", flags, dir_fd=base)
        descriptors.append(root)
        identity = inspect(root)
        unreachable = []
        if mode in {"roots", "namespace", "bundle"}:
            names = ("source", "venv", "python", "system_lib", "system_lib64") if mode == "bundle" else ("source", "venv", "python")
            for name in names:
                child = os.open(name, flags, dir_fd=root)
                descriptors.append(child)
                if inspect(child)[0] != identity[0]:
                    raise ValueError("nested")
            if mode in {"namespace", "bundle"}:
                for base_fd, parts in ((descriptors[1], ("hermes_cli", "main.py")),
                                       (descriptors[2], ("pyvenv.cfg",))):
                    parent = os.dup(base_fd)
                    try:
                        for part in parts[:-1]:
                            child = os.open(part, flags, dir_fd=parent)
                            os.close(parent)
                            parent = child
                        child = os.open(parts[-1], os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                        try:
                            if not stat.S_ISREG(os.fstat(child).st_mode):
                                raise ValueError("sentinel")
                        finally:
                            os.close(child)
                    finally:
                        os.close(parent)
            if mode == "bundle":
                report = os.open("runtime-libraries.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
                try:
                    payload = os.read(report, 32769)
                finally:
                    os.close(report)
                if len(payload) > 32768: raise ValueError("report")
                metadata = json.loads(payload)
                if (not isinstance(metadata, dict) or metadata.get("format") != 1
                        or not isinstance(metadata.get("unreachable_paths"), list) or len(metadata["unreachable_paths"]) > 16
                        or any(not isinstance(value, str) or len(value) > 512 for value in metadata["unreachable_paths"])):
                    raise ValueError("report")
                unreachable = metadata["unreachable_paths"]
            output = descriptors[1:]
        elif mode == "root":
            output = descriptors[:1]
        else:
            raise ValueError("mode")
        data = json.dumps({"version": 1, "identity": identity, "unreachable_paths": unreachable}).encode("ascii")
        endpoint.sendmsg([data], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", output))])
        return 0
    except (OSError, ValueError):
        return 1
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
        endpoint.close()


if __name__ == "__main__":
    raise SystemExit(main())
