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


@pytest.mark.parametrize(
    "columns",
    [
        "id TEXT PRIMARY KEY, source TEXT",  # before BL-16
        "raw_transaction_id TEXT PRIMARY KEY, source TEXT",  # before source transactions
    ],
)
def test_an_older_database_is_rejected(columns):
    db = sqlite3.connect(":memory:")
    db.execute(f"CREATE TABLE raw_transactions ({columns})")
    with pytest.raises(RuntimeError, match="predates source transactions"):
        connection._check_schema_is_current(db)
