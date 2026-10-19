"""Private observation primitives. They grant no launch, signal or closure."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import time
import uuid
from mentat_db import schema_signature_state
from run_repository import RunRepository

from mentat import project_worker_scope as scopes
from mentat.process_identity import parse_linux_process_start_ticks
from project_scope_journal import _identity, _plan
from private_state import console_root, database_path
from task_repository import _read_database_snapshot, _validate_database_set
from project_context import validate_project_context_connection
from project_scope_journal import _row

_FIELDS = frozenset({'ActiveState','ControlGroup','InvocationID','LoadState'})


class ScopeReadbackError(RuntimeError):
    pass


def _remaining(deadline):
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise ScopeReadbackError('scope_readback.deadline')
    return remaining


def _ascii_fields(payload, expected, separator='=', limit=8192):
    if not isinstance(payload,bytes) or len(payload)>limit:
        raise ScopeReadbackError('scope_readback.reply')
    try:
        lines = payload.decode('ascii').splitlines()
    except UnicodeError:
        raise ScopeReadbackError('scope_readback.reply') from None
    result = {}
    for line in lines:
        pieces = line.split(separator,1) if separator else line.split()
        if len(pieces)!=2 or pieces[0] in result or pieces[0] not in expected:
            raise ScopeReadbackError('scope_readback.reply')
        result[pieces[0]]=pieces[1]
    if set(result)!=expected:
        raise ScopeReadbackError('scope_readback.reply')
    return result


def _unit_state(unit, uid, deadline):
    import pwd
    environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':pwd.getpwuid(uid).pw_dir,
                 'XDG_RUNTIME_DIR':f'/run/user/{uid}',
                 'DBUS_SESSION_BUS_ADDRESS':f'unix:path=/run/user/{uid}/bus'}
    command=['/usr/bin/systemctl','--user','show',unit,
        '-p','ActiveState','-p','ControlGroup','-p','InvocationID','-p','LoadState']
    # Bound allocation while reading, rather than checking capture_output after
    # an arbitrary amount of output has already accumulated.
    end=time.monotonic()+min(2.0,_remaining(deadline))
    process=subprocess.Popen(command,env=environment,stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True)
    output={}
    try:
        with selectors.DefaultSelector() as selector:
            for pipe in (process.stdout,process.stderr):
                os.set_blocking(pipe.fileno(),False)
                output[pipe]=bytearray()
                selector.register(pipe,selectors.EVENT_READ)
            while selector.get_map():
                for key,_ in selector.select(_remaining(end)):
                    data=os.read(key.fd,8193-len(output[key.fileobj]))
                    output[key.fileobj].extend(data)
                    if len(output[key.fileobj])>8192:
                        raise ScopeReadbackError('scope_readback.reply')
                    if not data:
                        selector.unregister(key.fileobj)
            if process.wait(timeout=_remaining(end))!=0:
                raise ScopeReadbackError('scope_readback.reply')
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=0.5)
        process.stdout.close()
        process.stderr.close()
    _remaining(deadline)
    fields=_ascii_fields(bytes(output[process.stdout]),_FIELDS)
    if (fields['ActiveState'] not in {'active','inactive','failed','activating','deactivating'}
            or fields['LoadState'] not in {'loaded','not-found'}):
        raise ScopeReadbackError('scope_readback.reply')
    return fields


def _launcher_ticks(pid):
    try:
        descriptor=os.open(f'/proc/{pid}/stat',scopes._FILE_FLAGS)
        try:
            raw=os.read(descriptor,4097)
        finally:
            os.close(descriptor)
        if len(raw)>4096:
            return None
        return parse_linux_process_start_ticks(raw.decode('ascii'),pid)
    except (OSError,UnicodeError,ValueError):
        return None


@dataclass(frozen=True)
class ScopeObservation:
    state: str
    reason: str
    sampled_at: float


def _observe_kernel(plan, identity, deadline, *, terminal=False):
    """Called only by the fixed inspection worker with validated private data.

    The caller's parent watchdog bounds the whole operation, including blocked
    filesystem or command IO. Missing old paths cannot recreate owner handles.
    """
    descriptor=None
    def sample(state,reason):
        _remaining(deadline)
        return ScopeObservation(state,reason,time.time())
    try:
        _plan(plan)
        _identity(identity,plan)
        _remaining(deadline)
        if not scopes.IS_LINUX or os.getuid()!=plan['uid']:
            return sample('unknown','platform_or_uid')
        boot_path=Path('/proc/sys/kernel/random/boot_id')
        with boot_path.open('rb') as boot:
            raw=boot.read(65)
        if len(raw)>64 or uuid.UUID(raw.decode('ascii').strip()).hex!=plan['boot_id']:
            return sample('unknown','boot_changed')
        relative=f"/user.slice/user-{plan['uid']}.slice/user@{plan['uid']}.service/app.slice/{plan['unit']}"
        before=_unit_state(plan['unit'],plan['uid'],deadline)
        if before['InvocationID']!=identity['invocation']:
            return sample('conflict','invocation_changed')
        if before['ControlGroup']!=relative:
            return sample('unknown','group_unavailable')
        descriptor=scopes._open_directory(scopes._CGROUP_ROOT/relative.lstrip('/'))
        _remaining(deadline)
        scopes._require_cgroup2(descriptor)
        details=os.fstat(descriptor)
        if (details.st_uid!=plan['uid'] or (details.st_dev,details.st_ino)!=(identity['device'],identity['inode'])):
            return sample('conflict','inode_changed')
        control=os.open('cgroup.events',scopes._FILE_FLAGS,dir_fd=descriptor)
        try:
            events=_ascii_fields(os.read(control,4097),frozenset({'populated','frozen'}),separator=None,limit=4096)
        finally:
            os.close(control)
        if any(value not in {'0','1'} for value in events.values()):
            raise ScopeReadbackError('scope_readback.reply')
        ticks=_launcher_ticks(identity['pid'])
        after=_unit_state(plan['unit'],plan['uid'],deadline)
        again=os.fstat(descriptor)
        if (before!=after or (again.st_dev,again.st_ino,again.st_uid)!=(details.st_dev,details.st_ino,details.st_uid)):
            return sample('unknown','changed_during_read')
        if events['populated']=='1':
            if terminal:
                return sample('conflict','terminal_populated')
            return sample('matching_populated','launcher_matching' if ticks==identity['start_ticks'] else 'launcher_unverified')
        return sample('matching_empty','descriptor_empty')
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError,KeyError):
        return ScopeObservation('unknown','unverified',time.time())
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _reference_snapshot(root, run_id, generation, revision, deadline):
    """Source-preserving committed snapshot, never an arbitrary caller handle."""
    _remaining(deadline)
    private=console_root(root)
    path=database_path(root)
    identities=_validate_database_set(path,private)
    # Reject redirected ancestors as well as a redirected final directory.
    descriptors=[]
    try:
        for directory_path in (root,private):
            descriptor=scopes._open_directory(directory_path)
            descriptors.append(descriptor)
            if os.fstat(descriptor).st_uid!=os.getuid():
                raise ScopeReadbackError('scope_readback.root')
        root_details,directory=(os.fstat(descriptor) for descriptor in descriptors)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
    root_identity=(root_details.st_dev,root_details.st_ino,directory.st_dev,directory.st_ino,identities[path])
    with _read_database_snapshot(path,private) as connection:
        connection.execute('BEGIN')
        version=connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
        if version not in {44,45}:
            raise ScopeReadbackError('scope_readback.schema')
        if schema_signature_state(connection,version)!='expected':
            raise ScopeReadbackError('scope_readback.schema')
        authority=RunRepository(connection).authority_receipt(required=True)
        validate_project_context_connection(connection,require_available=False)
        row=_row(connection,run_id)
        if row[1]!=generation or row[9]!=revision:
            raise ScopeReadbackError('scope_readback.reference_changed')
        epoch=connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state WHERE singleton=1').fetchone()[0]
        plan=json.loads(row[4])
        identity=json.loads(row[11]) if row[11] else None
        digest=hashlib.sha256(json.dumps([authority.__dict__,*row[:3],row[3].hex(),*row[4:]],
            sort_keys=True,separators=(',',':')).encode()).hexdigest()
        fenced=row[3]!=epoch
        connection.rollback()
    _remaining(deadline)
    after_root=os.lstat(root)
    after_private=os.lstat(private)
    if ((after_root.st_dev,after_root.st_ino,after_private.st_dev,after_private.st_ino,
         _validate_database_set(path,private)[path])!=root_identity):
        raise ScopeReadbackError('scope_readback.root_changed')
    return root_identity,epoch,digest,row[10],plan,identity,fenced


def _inspect_reference(root, run_id, generation, revision, deadline):
    before=_reference_snapshot(root,run_id,generation,revision,deadline)
    if before[6]:
        result=ScopeObservation('unknown','authority_fenced',time.time())
    elif before[5] is None:
        result=ScopeObservation('unknown','no_kernel_identity',time.time())
    else:
        result=_observe_kernel(before[4],before[5],deadline,terminal=before[3]=='stopped')
    after=_reference_snapshot(root,run_id,generation,revision,deadline)
    if before[:3]!=after[:3]:
        return ScopeObservation('unknown','reference_changed',time.time())
    _remaining(deadline)
    return result
