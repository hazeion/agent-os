"""The reusable worker slot must import without optional application packages."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class ScopeInspectorImportTests(unittest.TestCase):
    def test_fresh_isolated_slot_import_does_not_load_readback_or_pillow(self):
        root = Path(__file__).resolve().parents[1]
        environment = {key: os.environ[key] for key in
                       ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")
                       if key in os.environ}
        source = (
            "import importlib.util, sys\n"
            "assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode\n"
            "assert importlib.util.find_spec('PIL') is None\n"
            f"sys.path.insert(0, {str(root)!r})\n"
            "from mentat.project_scope_inspector import _InspectionSlot\n"
            "assert isinstance(_InspectionSlot, type)\n"
            "assert _InspectionSlot.__module__ == 'mentat.project_scope_inspector'\n"
            "assert 'mentat.project_scope_readback' not in sys.modules\n"
            "assert 'run_repository' not in sys.modules\n"
            "assert 'PIL' not in sys.modules\n"
            "print('slot-import-only')\n"
        )
        with TemporaryDirectory(prefix="mentat-scope-import-") as scratch:
            environment.update(HOME=scratch, USERPROFILE=scratch, TMPDIR=scratch)
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-S", "-c", source],
                cwd=root, env=environment, capture_output=True, text=True,
                timeout=15, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "slot-import-only")


if __name__ == "__main__":
    unittest.main()
