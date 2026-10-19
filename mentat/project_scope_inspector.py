"""Private bounded inspection entry point; no observed-process control."""

import json
import math
from pathlib import Path
import re
import sys
import threading
import time

from link_preview_workers import _WorkerSlot, minimal_worker_environment
from mentat.project_scope_readback import ScopeObservation

_REASONS = {
    'matching_populated': {'launcher_matching', 'launcher_unverified'},
    'matching_empty': {'descriptor_empty'},
    'conflict': {'invocation_changed', 'inode_changed', 'terminal_populated'},
    'unknown': {'platform_or_uid', 'boot_changed', 'group_unavailable',
                'changed_during_read', 'unverified', 'authority_fenced',
                'no_kernel_identity', 'reference_changed'},
}


def _valid_result(value, started_at, ended_at):
    return (isinstance(value,dict) and set(value)=={'state','reason','sampled_at'}
            and isinstance(value['state'],str) and value['state'] in _REASONS
            and isinstance(value['reason'],str) and value['reason'] in _REASONS[value['state']]
            and type(value['sampled_at']) in (int,float) and math.isfinite(value['sampled_at'])
            and started_at<=value['sampled_at']<=ended_at)


class _InspectionSlot(_WorkerSlot):
    def __init__(self, command, *, deadline, **kwargs):
        self._deadline = deadline
        self._timer = None
        self._timer_error = None
        super().__init__(command, **kwargs)

    def _spawn(self):
        super()._spawn()
        # The inherited reply watchdog starts after writing stdin. This timer
        # also bounds a blocked write and includes worker startup time.
        def expire():
            try:
                self.abort()
            except BaseException as error:
                self._timer_error = error
        self._timer = threading.Timer(max(0, self._deadline-time.monotonic()), expire)
        self._timer.daemon = True
        self._timer.start()

    def close(self):
        if self._timer is not None:
            self._timer.cancel()
        try:
            super().close()
        finally:
            if self._timer is not None:
                self._timer.join()
        if self._timer_error is not None:
            # Never discard unresolved cleanup ownership as an ordinary sample.
            raise self._timer_error

    def replace(self):
        # Preserve cleanup ownership, but never create another observation
        # process or replay an ambiguous request automatically.
        self.abort()


def _command():
    root=Path(__file__).resolve().parents[1]
    bootstrap=f"import runpy,sys;sys.path.insert(0,{str(root)!r});runpy.run_module('mentat.project_scope_readback_worker',run_name='__main__')"
    return (sys.executable,'-I','-c',bootstrap)


def inspect_scope(data_root, *, run_id, generation, expected_revision):
    """Observe exact private committed state, never execute/recover a Run."""
    if (sys.platform!='linux' or not isinstance(data_root,Path) or not data_root.is_absolute()
            or len(str(data_root).encode())>1024 or not isinstance(run_id,str)
            or re.fullmatch(r'run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}',run_id) is None
            or not isinstance(generation,str) or re.fullmatch('[0-9a-f]{32}',generation) is None
            or type(expected_revision) is not int or not 1<=expected_revision<=5):
        raise ValueError('scope_readback.invalid')
    deadline=time.monotonic()+10
    started_at=time.time()
    slot=None
    candidate=None
    try:
        slot=_InspectionSlot(_command(),deadline=deadline,clock=time.monotonic,environment=minimal_worker_environment(),
            operation_watchdog_seconds=10,maximum_line_bytes=4096)
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise ValueError()
        slot._operation_watchdog_seconds=remaining
        reference={'root':str(data_root),'run':run_id,'generation':generation,
                   'revision':expected_revision,'deadline':deadline}
        value=slot.execute(kind='scope_readback',url=json.dumps(reference,separators=(',',':')))
        if time.monotonic()>=deadline or not _valid_result(value,started_at,time.time()):
            raise ValueError()
        candidate=ScopeObservation(value['state'],value['reason'],value['sampled_at'])
    except Exception:
        candidate=None
    finally:
        if slot is not None:
            slot.close()
    # Cleanup is part of evidence acceptance, not an after-return detail.
    if candidate is None or time.monotonic()>=deadline:
        return ScopeObservation('unknown','unverified',time.time())
    return candidate
