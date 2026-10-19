"""Real Linux process-death regression; no provider, TLS or public listener."""

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform == 'linux', 'Linux process guardian')
class OwnerSetupGuardTests(unittest.TestCase):
    def test_verified_stop_never_signals_a_reused_process_group(self):
        from mentat.owner_setup_guard import stop_guard
        class Exited:
            pid = 987654
            stdin = None
            def poll(self): return 0
        process = Exited()
        with patch('mentat.owner_setup_guard.os.killpg', side_effect=ProcessLookupError):
            self.assertTrue(stop_guard(process))
        with patch('mentat.owner_setup_guard.os.killpg', side_effect=AssertionError('must not signal again')):
            self.assertTrue(stop_guard(process))

    def test_parent_crash_or_guard_termination_closes_child_listener(self):
        guard = Path(__file__).resolve().parents[1] / 'mentat' / 'owner_setup_guard.py'
        for death in ('parent-crash', 'terminate', 'hangup', 'guard-crash'):
            with self.subTest(death=death), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                child = root / 'child.py'
                listener = root / 'listener.py'
                listener.write_text("import socket,time,json,os\nfrom pathlib import Path\ns=socket.socket();s.bind(('127.0.0.1',0));s.listen()\nPath(__file__).with_name('child.json').write_text(json.dumps({'pid':os.getpid(),'port':s.getsockname()[1]}))\ntime.sleep(120)\n")
                child.write_text("import subprocess,sys,time\nfrom pathlib import Path\nsubprocess.Popen([sys.executable,str(Path(__file__).with_name('listener.py'))])\ntime.sleep(120)\n")
                parent = root / 'parent.py'
                parent.write_text("import subprocess,sys,os,time,json,importlib.util\nfrom pathlib import Path\nspec=importlib.util.spec_from_file_location('guard',sys.argv[1]);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)\np=subprocess.Popen([sys.executable,'-I',sys.argv[1],'--parent-pid',str(os.getpid()),'--kind','node','--binary',sys.executable,'--resource',sys.argv[2]],stdin=subprocess.PIPE,start_new_session=True)\nPath(__file__).with_name('guard.json').write_text(json.dumps({'pid':p.pid}))\nwhile p.poll() is None: time.sleep(0.02)\nPath(__file__).with_name('stopped.json').write_text(json.dumps(module.stop_guard(p)))\n")
                process = subprocess.Popen([sys.executable, str(parent), str(guard), str(child)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                child_info = guard_info = None
                try:
                    deadline = time.monotonic() + 8
                    while not (root / 'child.json').exists():
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.02)
                    child_info = json.loads((root / 'child.json').read_text())
                    guard_info = json.loads((root / 'guard.json').read_text())
                    if death == 'parent-crash':
                        process.kill()
                        process.wait(3)
                    else:
                        os.kill(guard_info['pid'], {'terminate': signal.SIGTERM, 'hangup': signal.SIGHUP, 'guard-crash': signal.SIGKILL}[death])
                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            with socket.create_connection(('127.0.0.1', child_info['port']), timeout=0.1):
                                pass
                        except OSError:
                            break
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.02)
                    deadline = time.monotonic() + 3
                    while Path(f"/proc/{child_info['pid']}").exists():
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.02)
                    if death != 'parent-crash':
                        process.wait(5)
                        self.assertTrue(json.loads((root / 'stopped.json').read_text()))
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(3)
                    if guard_info:
                        try: os.killpg(guard_info['pid'], signal.SIGKILL)
                        except ProcessLookupError: pass


if __name__ == '__main__':
    unittest.main()
