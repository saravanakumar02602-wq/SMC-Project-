import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend.database import connect_db, initialize_db, load_state, persist_state
from tests.test_server import baseline


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "manufacturer.sqlite"
        initialize_db(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_normalized_state_round_trip(self):
        expected = baseline()
        with closing(connect_db(self.path)) as connection, connection:
            persist_state(connection, expected)
            connection.execute(
                "UPDATE business_meta SET revision = 4 WHERE id = 1"
            )
            actual, revision = load_state(connection)
            self.assertEqual(revision, 4)
            self.assertEqual(actual, expected)

    def test_foreign_keys_reject_unknown_bom_material(self):
        with closing(connect_db(self.path)) as connection, connection:
            connection.execute(
                "INSERT INTO products VALUES ('snack', 'Snack', 5, 0, 0, 0)"
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO bill_of_materials VALUES ('snack', 'missing', 1)"
                )

    def test_migrates_existing_json_snapshot(self):
        legacy = baseline()
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite"
        with closing(sqlite3.connect(legacy_path)) as connection, connection:
            connection.execute(
                "CREATE TABLE app_state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL, "
                "revision INTEGER NOT NULL, updated_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO app_state VALUES (1, ?, 9, '2026-01-01')",
                (json.dumps(legacy),),
            )
        initialize_db(legacy_path)
        with closing(connect_db(legacy_path)) as connection:
            actual, revision = load_state(connection)
            self.assertEqual(revision, 9)
            self.assertEqual(actual, legacy)
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'app_state'"
                ).fetchone()
            )
            self.assertTrue(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sales_orders'"
                ).fetchone()
            )

    def test_empty_database_requires_bootstrap(self):
        with closing(connect_db(self.path)) as connection:
            state, revision = load_state(connection)
            self.assertIsNone(state)
            self.assertEqual(revision, 0)


if __name__ == "__main__":
    unittest.main()
