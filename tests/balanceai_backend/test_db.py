"""Tests for db.py utilities."""

import sqlite3

import pytest

from balanceai_backend.db import get_distinct_accounts, get_distinct_categories, get_schema_summary


@pytest.fixture
def db():
    """In-memory SQLite database for testing."""
    connection = sqlite3.connect(":memory:")
    yield connection
    connection.close()


class TestGetSchemaSummary:

    def test_empty_database_returns_empty_string(self, db):
        assert get_schema_summary(db) == ""

    def test_single_table(self, db):
        db.execute("CREATE TABLE users (id INTEGER, name TEXT)")
        result = get_schema_summary(db)
        assert result == "users(id INTEGER, name TEXT)"

    def test_multiple_tables_sorted_alphabetically(self, db):
        db.execute("CREATE TABLE zebra (id INTEGER)")
        db.execute("CREATE TABLE apple (id INTEGER)")
        lines = get_schema_summary(db).splitlines()
        assert lines[0].startswith("apple")
        assert lines[1].startswith("zebra")

    def test_includes_column_types(self, db):
        db.execute("CREATE TABLE t (x REAL, y TEXT, z INTEGER)")
        result = get_schema_summary(db)
        assert "x REAL" in result
        assert "y TEXT" in result
        assert "z INTEGER" in result

    def test_excludes_constraint_noise(self, db):
        db.execute("""
            CREATE TABLE t (
                id TEXT PRIMARY KEY,
                val REAL NOT NULL DEFAULT 0.0
            )
        """)
        result = get_schema_summary(db)
        assert "NOT NULL" not in result
        assert "DEFAULT" not in result
        assert "PRIMARY KEY" not in result

    def test_excludes_foreign_key_noise(self, db):
        db.execute("CREATE TABLE parent (id TEXT PRIMARY KEY)")
        db.execute("""
            CREATE TABLE child (
                id TEXT PRIMARY KEY,
                parent_id TEXT NOT NULL REFERENCES parent(id) ON DELETE CASCADE
            )
        """)
        result = get_schema_summary(db)
        assert "REFERENCES" not in result
        assert "ON DELETE CASCADE" not in result

    def test_real_schema_tables_present(self):
        """Smoke test against the real DB — journals and journal_entries must appear."""
        from balanceai_backend.db import conn
        result = get_schema_summary(conn)
        assert "journals(" in result
        assert "journal_entries(" in result

    def test_real_schema_key_columns_present(self):
        """Key columns used in queries must be present in the summary."""
        from balanceai_backend.db import conn
        result = get_schema_summary(conn)
        for col in ("recipient", "credit", "debit", "category", "date"):
            assert col in result, f"Expected column '{col}' in schema summary"


@pytest.fixture
def db_with_entries():
    """In-memory DB with a journal_entries table seeded with test rows."""
    connection = sqlite3.connect(":memory:")
    connection.execute("""
        CREATE TABLE journal_entries (
            journal_entry_id TEXT PRIMARY KEY,
            date TEXT,
            account TEXT,
            category TEXT,
            debit REAL,
            credit REAL
        )
    """)
    connection.executemany(
        "INSERT INTO journal_entries VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("1", "2025-10-01", "checking", "dining", 0, 50.0),
            ("2", "2025-10-02", "checking", "groceries", 0, 20.0),
            ("3", "2025-10-03", "savings", "dining", 0, 30.0),
            ("4", "2025-10-04", "checking", None, 0, 10.0),
            ("5", "2025-10-05", "savings", None, 0, 5.0),
        ],
    )
    yield connection
    connection.close()


class TestGetDistinctCategories:

    def test_returns_distinct_values(self, db_with_entries):
        result = get_distinct_categories(db_with_entries)
        assert sorted(c for c in result if c is not None) == ["dining", "groceries"]

    def test_includes_null(self, db_with_entries):
        result = get_distinct_categories(db_with_entries)
        assert None in result

    def test_empty_table_returns_empty_list(self, db_with_entries):
        db_with_entries.execute("DELETE FROM journal_entries")
        assert get_distinct_categories(db_with_entries) == []

    def test_no_duplicates(self, db_with_entries):
        result = get_distinct_categories(db_with_entries)
        assert len(result) == len(set(result))


class TestGetDistinctAccounts:

    def test_returns_distinct_values(self, db_with_entries):
        result = get_distinct_accounts(db_with_entries)
        assert sorted(result) == ["checking", "savings"]

    def test_no_duplicates(self, db_with_entries):
        result = get_distinct_accounts(db_with_entries)
        assert len(result) == len(set(result))

    def test_empty_table_returns_empty_list(self, db_with_entries):
        db_with_entries.execute("DELETE FROM journal_entries")
        assert get_distinct_accounts(db_with_entries) == []

    def test_includes_null(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE journal_entries (account TEXT)")
        connection.execute("INSERT INTO journal_entries VALUES (NULL)")
        result = get_distinct_accounts(connection)
        assert None in result
        connection.close()
