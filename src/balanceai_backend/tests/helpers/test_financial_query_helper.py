import sqlite3

import pytest
from balanceai_backend.db.readonly_journal_connection import open_readonly_journal_connection
from balanceai_backend.helpers.financial_query_helper import hide_descriptions


@pytest.fixture
def conn(tmp_path):
    """Two journal lines: one whose description is raw bank text, and one
    whose description is also its counterparty."""
    path = tmp_path / "journal.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE journal_lines (description TEXT, counterparty TEXT)")
    db.executemany(
        "INSERT INTO journal_lines VALUES (?, ?)",
        [("SQ *BLUE BOTTLE 0423 OAKLAND", "Blue Bottle Coffee"), ("Shell", "Shell")],
    )
    db.commit()
    readonly = open_readonly_journal_connection(path)
    yield readonly
    readonly.close()
    db.close()


class TestHideDescriptions:
    @pytest.mark.parametrize("column", ["description", "d"])
    def test_hides_a_description_under_any_column_name(self, conn, column):
        rows = hide_descriptions([{column: "SQ *BLUE BOTTLE 0423 OAKLAND"}], conn=conn)
        assert rows == [{column: "[hidden description]"}]

    def test_keeps_a_description_that_is_also_a_counterparty(self, conn):
        rows = [{"description": "Shell"}]
        assert hide_descriptions(rows, conn=conn) == rows

    def test_keeps_everything_else(self, conn):
        row = {"counterparty": "Blue Bottle Coffee", "debit": 6.5, "date": "2025-10-22"}
        assert hide_descriptions([row], conn=conn) == [row]
