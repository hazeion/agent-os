"""Private descriptor-owned output publication; no SQLite or Run authority."""
from dataclasses import dataclass, field
import hashlib
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

from mentat.project_namespace_evidence import completion_acceptance_deadline, completion_metadata
from mentat.project_worker_scope import _open_directory
from private_state import console_root, database_path

MAX_OUTPUT_BYTES = 32 * 1024
_ISSUER = object()
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')


class OutputBlobError(RuntimeError):
    pass


def _fail():
    raise OutputBlobError('project_output.blob_unavailable')


def _owner(details, *, directory=False):
    if (details.st_uid != os.getuid() or details.st_mode & 0o077
            or not (stat.S_ISDIR(details.st_mode) if directory else stat.S_ISREG(details.st_mode))):
        _fail()


def _root(root):
    if sys.platform != 'linux' or not {os.open, os.mkdir, os.unlink, os.link} <= os.supports_dir_fd:
        _fail()
    path = console_root(Path(root))
    descriptor = _open_directory(path)
    try:
        details = os.fstat(descriptor)
        _owner(details, directory=True)
        return descriptor, (details.st_dev, details.st_ino)
    except BaseException:
        os.close(descriptor)
        raise


def _child(parent, name, *, create=False):
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        _owner(os.fstat(descriptor), directory=True)
        if create:
            os.fsync(descriptor)
            os.fsync(parent)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _verify(parent, name, digest, size):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = os.fstat(descriptor)
        _owner(before)
        if before.st_size != size:
            _fail()
        payload = b''
        while len(payload) <= size:
            chunk = os.read(descriptor, size + 1 - len(payload))
            if not chunk:
                break
            payload += chunk
        # Deduplication must sync the named inode, not only a discarded temp.
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (len(payload) != size or hashlib.sha256(payload).hexdigest() != digest
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or (after.st_dev, after.st_ino) != (named.st_dev, named.st_ino)):
            _fail()
    finally:
        os.close(descriptor)


@dataclass(frozen=True, repr=False)
class PublishedOutputBlob:
    sha256: str = field(repr=False)
    byte_size: int = field(repr=False)
    _root_identity: tuple = field(repr=False)
    _issuer: object = field(repr=False)

    def __post_init__(self):
        if (type(self) is not PublishedOutputBlob or self._issuer is not _ISSUER
                or not isinstance(self.sha256, str) or _SHA256.fullmatch(self.sha256) is None
                or type(self.byte_size) is not int or not 1 <= self.byte_size <= MAX_OUTPUT_BYTES
                or type(self._root_identity) is not tuple or len(self._root_identity) != 2
                or any(type(value) is not int or not 0 <= value < 2**64 for value in self._root_identity)
                or self._root_identity[1] == 0):
            _fail()

    def verify(self, root):
        """Exact readback only; this does not bind or retain an attachment."""
        self.__post_init__()
        root_fd, identity = _root(root)
        descriptors = [root_fd]
        try:
            if identity != self._root_identity:
                _fail()
            for name in ('blobs', 'sha256', self.sha256[:2]):
                descriptors.append(_child(descriptors[-1], name))
            _verify(descriptors[-1], self.sha256, self.sha256, self.byte_size)
        except (OSError, ValueError, RuntimeError) as error:
            if isinstance(error, OutputBlobError):
                raise
            raise OutputBlobError('project_output.blob_unavailable') from error
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)


def publish_output_blob(root, witness):
    """Publish bounded original terminal bytes; caller owns the private lock.

    The producer must verify Run/call/holder/Stop authority before invoking this
    helper and again in the atomic conversion transaction. These bytes remain
    disposable orphans until that transaction retains them.
    """
    metadata = completion_metadata(witness)
    completion_acceptance_deadline(witness)
    payload = metadata['result']['text'].encode('utf-8')
    if not 0 < len(payload) <= MAX_OUTPUT_BYTES:
        _fail()
    digest = hashlib.sha256(payload).hexdigest()
    root_fd, identity = _root(root)
    descriptors = [root_fd]
    temporary = None
    try:
        for name in ('blobs', 'sha256', digest[:2]):
            completion_acceptance_deadline(witness)
            descriptors.append(_child(descriptors[-1], name, create=True))
        parent = descriptors[-1]
        temporary = '.mentat-output-' + uuid.uuid4().hex + '.tmp'
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
        try:
            os.fchmod(descriptor, 0o600)
            remaining = memoryview(payload)
            while remaining:
                completion_acceptance_deadline(witness)
                written = os.write(descriptor, remaining)
                if written <= 0:
                    _fail()
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        completion_acceptance_deadline(witness)
        try:
            os.link(temporary, digest, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        except FileExistsError:
            pass
        _verify(parent, digest, digest, len(payload))
        os.unlink(temporary, dir_fd=parent)
        temporary = None
        os.fsync(parent)
        publication = PublishedOutputBlob(digest, len(payload), identity, _ISSUER)
        publication.verify(root)
        completion_acceptance_deadline(witness)
        return publication
    except (OSError, ValueError, RuntimeError) as error:
        if isinstance(error, OutputBlobError):
            raise
        raise OutputBlobError('project_output.blob_unavailable') from error
    finally:
        try:
            if temporary is not None:
                try:
                    os.unlink(temporary, dir_fd=descriptors[-1])
                except FileNotFoundError:
                    pass
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)


def _record_attachment(connection, root, publication, *, identity_guard, now=None):
    """Record exact bytes inside the caller's transaction; never retain a Run.

    The complete producer transaction must insert its conversion/reference and
    finalization before commit. This helper owns no connection or commit.
    """
    if not connection.in_transaction or type(publication) is not PublishedOutputBlob:
        _fail()
    from task_repository import _DatabaseIdentityGuard
    if type(identity_guard) is not _DatabaseIdentityGuard or identity_guard.connection is not connection:
        _fail()
    actual = [row[2] for row in connection.execute('PRAGMA database_list') if row[1] == 'main']
    expected_path = Path(os.path.abspath(database_path(root)))
    if (len(actual) != 1 or not actual[0] or Path(actual[0]) != expected_path
            or identity_guard.path != expected_path):
        _fail()
    identities = identity_guard.capture()
    publication.verify(root)
    created = time.time() if now is None else now
    if type(created) not in (int, float) or not math.isfinite(created) or not 0 < created < 1e12:
        _fail()
    created = float(created)
    key = publication.sha256[:2] + '/' + publication.sha256
    savepoint = 'project_output_blob_' + uuid.uuid4().hex
    connection.execute('SAVEPOINT ' + savepoint)
    try:
        row = connection.execute('SELECT id,storage_key,byte_size,state FROM blobs WHERE sha256=?',
                                 (publication.sha256,)).fetchone()
        if row is None:
            identifier = 'blob_' + uuid.uuid4().hex
            connection.execute('INSERT INTO blobs(id,sha256,storage_key,byte_size,state,created_at,updated_at) '
                               "VALUES(?,?,?,?,'ready',?,?)",
                               (identifier, publication.sha256, key, publication.byte_size, created, created))
        else:
            if tuple(row[1:]) != (key, publication.byte_size, 'ready'):
                _fail()
            identifier = row[0]
        attachment = 'attachment_' + uuid.uuid4().hex
        connection.execute('INSERT INTO attachments(id,blob_id,original_name,mime_type,kind,state,byte_size,created_at,updated_at) '
                           "VALUES(?,?,'project-proposal.json','application/json','text','attached',?,?,?)",
                           (attachment, identifier, publication.byte_size, created, created))
        publication.verify(root)
        identity_guard.verify(identities)
    except BaseException:
        connection.execute('ROLLBACK TO ' + savepoint)
        connection.execute('RELEASE ' + savepoint)
        raise
    connection.execute('RELEASE ' + savepoint)
    return attachment, identifier
