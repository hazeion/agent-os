"""The producer layer upgrades only an exact schema45 consistency unit."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

import mentat_db


class Schema46ForwardMigrationTests(unittest.TestCase):
    def source(self, root):
        mentat_db.ensure_private_console_dir(root)
        path = mentat_db.database_path(root)
        with closing(sqlite3.connect(path)) as connection:
            for version, script in mentat_db.MIGRATIONS:
                if version > 45:
                    break
                connection.executescript(script)
                connection.execute('INSERT INTO schema_migrations VALUES (?,0)', (version,))
            connection.commit()
            self.assertEqual(mentat_db.schema_signature_state(connection,45),'expected')
        path.chmod(0o600)
        return path

    def test_exact_source_keeps_closed_admission_and_installs_retained_output_roots(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            self.source(root)
            with closing(mentat_db.connect(root)) as connection:
                self.assertEqual(mentat_db.SCHEMA_VERSION,46)
                self.assertEqual(mentat_db.schema_signature_state(connection,46),'expected')
                for name in ('bindings','stops','outputs'):
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_producer_'+name).fetchone()[0],0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name GLOB 'mentat_project_producer_*'").fetchone()[0],6)
                self.assertIsNotNone(connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_runs_project_proposal_closed_insert'").fetchone())
                self.assertIn('mentat_project_producer_outputs',connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_retained_attachments'").fetchone()[0])
                self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_source_drift_refuses_without_installing_any_producer_authority(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            path=self.source(root)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('DROP TRIGGER mentat_project_output_reservation_immutable')
                connection.commit()
            with self.assertRaisesRegex(mentat_db.MentatDatabaseError,'schema 45 cannot be safely upgraded'):
                mentat_db.connect(root)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0],45)
                self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE name GLOB 'mentat_project_producer_*'").fetchall(),[])

    def test_failed_layer_install_rolls_back_the_whole_migration(self):
        from unittest.mock import patch
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            path=self.source(root)
            migration=mentat_db.MIGRATIONS[-1]
            self.assertEqual(migration[0],46)
            broken=mentat_db.MIGRATIONS[:-1]+((46,migration[1]+'\nSELECT missing_producer_migration_column;'),)
            with patch.object(mentat_db,'MIGRATIONS',broken):
                with self.assertRaises(sqlite3.OperationalError):
                    mentat_db.connect(root)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0],45)
                self.assertEqual(mentat_db.schema_signature_state(connection,45),'expected')
                self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE name GLOB 'mentat_project_producer_*'").fetchall(),[])


if __name__=='__main__': unittest.main()
