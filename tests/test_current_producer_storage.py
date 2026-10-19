"""Current producer schema safety, with no older-root upgrade path."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import mentat_db


class Schema46CurrentTests(unittest.TestCase):
    def test_fresh_current_keeps_closed_admission_and_retained_output_roots(self):
        with TemporaryDirectory() as temporary:
            with closing(mentat_db.connect(Path(temporary))) as connection:
                self.assertEqual(mentat_db.SCHEMA_VERSION, 46)
                self.assertEqual(mentat_db.schema_signature_state(connection, 46), 'expected')
                for name in ('bindings', 'stops', 'outputs'):
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_producer_' + name).fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name GLOB 'mentat_project_producer_*'").fetchone()[0], 6)
                self.assertIsNotNone(connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_runs_project_proposal_closed_insert'").fetchone())
                self.assertIn('mentat_project_producer_outputs', connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_retained_attachments'").fetchone()[0])
                self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_current_drift_refuses_without_repair(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with closing(mentat_db.connect(root)):
                pass
            path = mentat_db.database_path(root)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('DROP TRIGGER mentat_project_output_reservation_immutable')
                connection.commit()
            before = path.read_bytes()
            with self.assertRaises(mentat_db.MentatDatabaseError):
                mentat_db.connect(root)
            self.assertEqual(path.read_bytes(), before)

    def test_failed_fresh_install_rolls_back_every_object_and_receipt(self):
        with closing(sqlite3.connect(':memory:', isolation_level=None)) as connection:
            broken = ((46, mentat_db.CURRENT_BOOTSTRAP_SQL + '\nSELECT missing_producer_column;'),)
            with patch.object(mentat_db, 'MIGRATIONS', broken):
                with self.assertRaises(sqlite3.OperationalError):
                    mentat_db.migrate(connection)
            self.assertEqual(connection.execute('SELECT name FROM sqlite_master').fetchall(), [])


if __name__ == '__main__':
    unittest.main()
