import json
import sqlite3
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("anthropic", MagicMock())

from balanceai_backend.db import create_schema
from balanceai_backend.models.report import ReportDefinition
from balanceai_backend.servers.bookkeeping_server import (
    create_report_definition,
    generate_report,
    list_report_definitions,
    delete_report_definition,
)

# SQL template equivalent to the old hardcoded generate_report bucketing logic,
# now expressed as a reusable template with :start_date / :end_date params.
_STANDARD_BUCKETING_SQL = """
    SELECT
        je.date,
        SUM(CASE WHEN je.account = 'cash' AND je.debit > 0 AND je.category = 'income' THEN je.debit ELSE 0 END) AS income,
        SUM(CASE WHEN je.account = 'essential_expense' AND je.debit > 0 THEN je.debit ELSE 0 END) AS essential_expenses,
        SUM(CASE WHEN je.account = 'non_essential_expense' AND je.debit > 0 THEN je.debit ELSE 0 END) AS non_essential_expenses,
        SUM(CASE WHEN je.account = 'transfer' AND je.credit > 0 THEN je.credit ELSE 0 END) AS transfers
    FROM journal_entries je
    WHERE je.date BETWEEN :start_date AND :end_date
    GROUP BY je.date
    ORDER BY je.date
"""

_UNPARAMETERIZED_SQL = "SELECT SUM(je.credit) FROM journal_entries je WHERE je.account = 'cash' AND je.credit > 0 AND je.category = 'cigarettes' AND je.date BETWEEN '2025-10-01' AND '2025-10-31'"

_LLM_PARAMETERIZED_SQL = "SELECT SUM(je.credit) FROM journal_entries je WHERE je.account = 'cash' AND je.credit > 0 AND je.category = 'cigarettes' AND je.date BETWEEN :start_date AND :end_date"

_LLM_RESPONSE = json.dumps(
    {
        "sql": _LLM_PARAMETERIZED_SQL,
        "parameters": [
            {
                "name": "start_date",
                "description": "start of reporting period (inclusive)",
                "example_value": "2025-10-01",
            },
            {
                "name": "end_date",
                "description": "end of reporting period (inclusive)",
                "example_value": "2025-10-31",
            },
        ],
    }
)


@pytest.fixture
def in_memory_conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    create_schema(c)
    yield c
    c.close()


@pytest.fixture
def seeded_conn(in_memory_conn):
    """In-memory DB pre-loaded with one day of activity matching the bucketing report columns."""
    in_memory_conn.executescript("""
        INSERT INTO journals VALUES ('j1', 'acct-1', 'chase', 'debit', 'Test journal', '2025-10-01', '2025-10-31');

        -- Income: cash debit leg
        INSERT INTO journal_entries VALUES ('e1', 'j1', '2025-10-01', 'cash', 'Paycheck', 5000.0, 0.0, 'income', 0.0, 'Self');
        -- Essential expense: essential_expense debit leg
        INSERT INTO journal_entries VALUES ('e2', 'j1', '2025-10-05', 'essential_expense', 'Whole Foods', 120.0, 0.0, 'groceries', 0.0, 'Self');
        -- Non-essential expense: non_essential_expense debit leg
        INSERT INTO journal_entries VALUES ('e3', 'j1', '2025-10-10', 'non_essential_expense', 'Netflix', 15.0, 0.0, 'entertainment', 0.0, 'Self');
        -- Transfer: transfer credit leg
        INSERT INTO journal_entries VALUES ('e4', 'j1', '2025-10-15', 'transfer', 'Savings transfer', 0.0, 500.0, 'transfer', 0.0, 'Self');
    """)
    return in_memory_conn


@pytest.fixture(autouse=True)
def mock_gemini(monkeypatch):
    """Patch gemini_converse in the bookkeeping server for all create_report_definition tests."""
    with patch(
        "balanceai_backend.servers.bookkeeping_server.gemini_converse",
        return_value=_LLM_RESPONSE,
    ) as m:
        yield m


class TestCreateReportDefinition:
    _PROMPT = "Track whether I'm cutting back on cigarettes month over month"

    def test_saves_definition_to_db(self, in_memory_conn):
        with patch(
            "balanceai_backend.servers.bookkeeping_server._save_report_definition"
        ) as mock_save:
            result = create_report_definition(
                name="Cigarette Report",
                prompt=self._PROMPT,
                unparameterized_sql=_UNPARAMETERIZED_SQL,
            )

        mock_save.assert_called_once()
        saved: ReportDefinition = mock_save.call_args[0][0]
        assert saved.name == "Cigarette Report"
        assert saved.prompt == self._PROMPT
        assert ":start_date" in saved.sql_template
        assert ":end_date" in saved.sql_template
        assert saved.unparameterized_sql == _UNPARAMETERIZED_SQL
        assert saved.report_definition_id == result["report_definition_id"]

    def test_returns_definition_dict(self):
        with patch("balanceai_backend.servers.bookkeeping_server._save_report_definition"):
            result = create_report_definition(
                name="Cigarette Report",
                prompt=self._PROMPT,
                unparameterized_sql=_UNPARAMETERIZED_SQL,
                description="Monthly cigarette spending by merchant",
            )

        assert result["name"] == "Cigarette Report"
        assert result["prompt"] == self._PROMPT
        assert "BETWEEN :start_date AND :end_date" in result["sql_template"]
        assert result["description"] == "Monthly cigarette spending by merchant"
        assert result["unparameterized_sql"] == _UNPARAMETERIZED_SQL
        assert "report_definition_id" in result
        assert "created_at" in result

    def test_date_literals_are_parameterized(self):
        with patch(
            "balanceai_backend.servers.bookkeeping_server._save_report_definition"
        ) as mock_save:
            create_report_definition(
                name="Test", prompt=self._PROMPT, unparameterized_sql=_UNPARAMETERIZED_SQL
            )

        saved: ReportDefinition = mock_save.call_args[0][0]
        assert "BETWEEN :start_date AND :end_date" in saved.sql_template
        assert "'2025-10-01'" not in saved.sql_template
        assert "'2025-10-31'" not in saved.sql_template

    def test_parameters_stored_from_llm_response(self):
        with patch(
            "balanceai_backend.servers.bookkeeping_server._save_report_definition"
        ) as mock_save:
            create_report_definition(
                name="Test", prompt=self._PROMPT, unparameterized_sql=_UNPARAMETERIZED_SQL
            )

        saved: ReportDefinition = mock_save.call_args[0][0]
        assert len(saved.parameters) == 2
        param_names = {p["name"] for p in saved.parameters}
        assert param_names == {"start_date", "end_date"}


class TestGenerateReport:
    def test_reproduces_standard_bucketing_output(self, seeded_conn, tmp_path):
        """
        Verifies that generate_report returns the correct row_count and writes
        expected columns and values to the CSV when local_path is provided.
        """
        defn = ReportDefinition(
            name="Standard Budget Report",
            prompt="",
            sql_template=_STANDARD_BUCKETING_SQL,
            description="",
        )
        out_csv = str(tmp_path / "report.csv")

        with (
            patch(
                "balanceai_backend.servers.bookkeeping_server._find_report_definitions",
                return_value=[defn],
            ),
            patch("balanceai_backend.servers.bookkeeping_server.conn", seeded_conn),
        ):
            result = generate_report(
                report_definition_id=defn.report_definition_id,
                parameters={"start_date": "2025-10-01", "end_date": "2025-10-31"},
                local_path=out_csv,
            )

        assert result["parameters"]["start_date"] == "2025-10-01"
        assert result["parameters"]["end_date"] == "2025-10-31"
        assert result["row_count"] == 4
        assert result["sql"] == _STANDARD_BUCKETING_SQL
        assert result["local_path"] == out_csv
        assert "rows" not in result

        import csv as _csv

        with open(out_csv, newline="") as f:
            reader = _csv.DictReader(f)
            rows = list(reader)

        expected_columns = {
            "date",
            "income",
            "essential_expenses",
            "non_essential_expenses",
            "transfers",
        }
        assert expected_columns.issubset(set(rows[0].keys()))

        income_row = next(r for r in rows if float(r["income"]) > 0)
        assert float(income_row["income"]) == pytest.approx(5000.0)

        essential_row = next(r for r in rows if float(r["essential_expenses"]) > 0)
        assert float(essential_row["essential_expenses"]) == pytest.approx(120.0)

        non_essential_row = next(r for r in rows if float(r["non_essential_expenses"]) > 0)
        assert float(non_essential_row["non_essential_expenses"]) == pytest.approx(15.0)

        transfer_row = next(r for r in rows if float(r["transfers"]) > 0)
        assert float(transfer_row["transfers"]) == pytest.approx(500.0)

    def test_no_local_path_omits_local_path_key(self, seeded_conn):
        defn = ReportDefinition(
            name="Test",
            prompt="",
            sql_template=_STANDARD_BUCKETING_SQL,
            description="",
        )

        with (
            patch(
                "balanceai_backend.servers.bookkeeping_server._find_report_definitions",
                return_value=[defn],
            ),
            patch("balanceai_backend.servers.bookkeeping_server.conn", seeded_conn),
        ):
            result = generate_report(
                report_definition_id=defn.report_definition_id,
                parameters={"start_date": "2025-10-01", "end_date": "2025-10-31"},
            )

        assert result["row_count"] == 4
        assert "local_path" not in result
        assert "rows" not in result

    def test_raises_when_definition_not_found(self):
        with patch(
            "balanceai_backend.servers.bookkeeping_server._find_report_definitions", return_value=[]
        ):
            with pytest.raises(ValueError, match="not found"):
                generate_report(report_definition_id="nonexistent")

    def test_date_range_filters_rows(self, seeded_conn):
        defn = ReportDefinition(
            name="Test",
            prompt="",
            sql_template=_STANDARD_BUCKETING_SQL,
            description="",
        )

        with (
            patch(
                "balanceai_backend.servers.bookkeeping_server._find_report_definitions",
                return_value=[defn],
            ),
            patch("balanceai_backend.servers.bookkeeping_server.conn", seeded_conn),
        ):
            # Only Oct 1 falls in this range (income entry)
            result = generate_report(
                report_definition_id=defn.report_definition_id,
                parameters={"start_date": "2025-10-01", "end_date": "2025-10-03"},
            )

        assert result["row_count"] == 1


class TestListAndDeleteReportDefinitions:
    def test_list_returns_all_definitions(self):
        defns = [
            ReportDefinition(name="A", prompt="", sql_template="SELECT 1", description=""),
            ReportDefinition(name="B", prompt="", sql_template="SELECT 2", description=""),
        ]
        with patch(
            "balanceai_backend.servers.bookkeeping_server._find_report_definitions",
            return_value=defns,
        ):
            result = list_report_definitions()

        assert len(result) == 2
        assert result[0]["name"] == "A"
        assert result[1]["name"] == "B"

    def test_delete_calls_db_and_returns_id(self):
        with patch(
            "balanceai_backend.servers.bookkeeping_server._delete_report_definition"
        ) as mock_delete:
            result = delete_report_definition("def-123")

        mock_delete.assert_called_once_with("def-123")
        assert result == {"report_definition_id": "def-123"}
