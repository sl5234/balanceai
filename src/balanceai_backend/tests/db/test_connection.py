import sqlite3

import pytest
from balanceai_backend.db import connection
from balanceai_backend.paths import SECRETS_DIR


def test_tests_never_use_the_real_data_folder():
    assert connection.DATA_DIR.resolve() != (SECRETS_DIR / "data").resolve()


def test_a_new_database_passes_the_schema_check():
    db = sqlite3.connect(":memory:")
    connection._check_schema_is_current(db)
    connection.create_schema(db)
    connection._check_schema_is_current(db)


def test_a_database_from_before_bl16_is_rejected():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE raw_transactions (id TEXT PRIMARY KEY, source TEXT)")
    with pytest.raises(RuntimeError, match="predates BL-16"):
        connection._check_schema_is_current(db)
