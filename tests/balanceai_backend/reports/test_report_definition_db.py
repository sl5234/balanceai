import sqlite3

import pytest

from balanceai_backend.db import create_schema
from balanceai_backend.models.report import ReportDefinition
from balanceai_backend.reports.report_definition_db import (
    delete_report_definition,
    find_report_definitions,
    save_report_definition,
    update_report_definition,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_definition():
    return ReportDefinition(
        name="Monthly Budget",
        prompt="Show monthly income and expenses",
        sql_template="SELECT je.date FROM journal_entries je WHERE je.date BETWEEN :start_date AND :end_date",
        description="Daily activity for a date range.",
    )


class TestSaveReportDefinition:
    def test_inserts_definition(self, db, sample_definition):
        save_report_definition(sample_definition, db)

        row = db.execute(
            "SELECT * FROM report_definitions WHERE report_definition_id = ?",
            (sample_definition.report_definition_id,),
        ).fetchone()
        assert row is not None

    def test_all_fields_persisted(self, db, sample_definition):
        save_report_definition(sample_definition, db)

        row = db.execute(
            "SELECT * FROM report_definitions WHERE report_definition_id = ?",
            (sample_definition.report_definition_id,),
        ).fetchone()
        assert row["report_definition_id"] == sample_definition.report_definition_id
        assert row["name"] == sample_definition.name
        assert row["prompt"] == sample_definition.prompt
        assert row["sql_template"] == sample_definition.sql_template
        assert row["description"] == sample_definition.description
        assert row["unparameterized_sql"] == sample_definition.unparameterized_sql
        assert row["created_at"] == sample_definition.created_at

    def test_unparameterized_sql_is_persisted_when_provided(self, db):
        defn = ReportDefinition(
            name="With Sample",
            prompt="",
            sql_template="SELECT 1",
            description="",
            unparameterized_sql="SELECT SUM(je.debit) FROM journal_entries je WHERE je.date = '2025-10-01'",
        )
        save_report_definition(defn, db)

        row = db.execute(
            "SELECT unparameterized_sql FROM report_definitions WHERE report_definition_id = ?",
            (defn.report_definition_id,),
        ).fetchone()
        assert row["unparameterized_sql"] == defn.unparameterized_sql

    def test_unparameterized_sql_is_null_when_not_provided(self, db):
        defn = ReportDefinition(
            name="No Sample", prompt="", sql_template="SELECT 1", description=""
        )
        save_report_definition(defn, db)

        row = db.execute(
            "SELECT unparameterized_sql FROM report_definitions WHERE report_definition_id = ?",
            (defn.report_definition_id,),
        ).fetchone()
        assert row["unparameterized_sql"] is None

    def test_duplicate_id_raises(self, db, sample_definition):
        save_report_definition(sample_definition, db)

        with pytest.raises(sqlite3.IntegrityError):
            save_report_definition(sample_definition, db)

    def test_multiple_definitions_saved(self, db):
        d1 = ReportDefinition(name="A", prompt="p1", sql_template="SELECT 1", description="")
        d2 = ReportDefinition(name="B", prompt="p2", sql_template="SELECT 2", description="")
        save_report_definition(d1, db)
        save_report_definition(d2, db)

        count = db.execute("SELECT COUNT(*) FROM report_definitions").fetchone()[0]
        assert count == 2


class TestFindReportDefinitions:
    def test_returns_empty_list_when_none_saved(self, db):
        assert find_report_definitions(conn=db) == []

    def test_returns_all_definitions(self, db):
        d1 = ReportDefinition(name="A", prompt="", sql_template="SELECT 1", description="")
        d2 = ReportDefinition(name="B", prompt="", sql_template="SELECT 2", description="")
        save_report_definition(d1, db)
        save_report_definition(d2, db)

        results = find_report_definitions(conn=db)

        assert len(results) == 2

    def test_filter_by_id(self, db):
        d1 = ReportDefinition(name="A", prompt="", sql_template="SELECT 1", description="")
        d2 = ReportDefinition(name="B", prompt="", sql_template="SELECT 2", description="")
        save_report_definition(d1, db)
        save_report_definition(d2, db)

        results = find_report_definitions(report_definition_id=d1.report_definition_id, conn=db)

        assert len(results) == 1
        assert results[0].report_definition_id == d1.report_definition_id

    def test_unknown_id_returns_empty(self, db):
        assert find_report_definitions(report_definition_id="nonexistent", conn=db) == []

    def test_results_ordered_newest_first(self, db):
        # Use explicit created_at values to control ordering
        d_old = ReportDefinition(name="Old", prompt="", sql_template="SELECT 1", description="")
        d_old.created_at = "2025-01-01T00:00:00"
        d_new = ReportDefinition(name="New", prompt="", sql_template="SELECT 2", description="")
        d_new.created_at = "2025-06-01T00:00:00"

        save_report_definition(d_old, db)
        save_report_definition(d_new, db)

        results = find_report_definitions(conn=db)

        assert results[0].name == "New"
        assert results[1].name == "Old"

    def test_fields_are_correctly_mapped(self, db, sample_definition):
        save_report_definition(sample_definition, db)

        results = find_report_definitions(
            report_definition_id=sample_definition.report_definition_id, conn=db
        )

        assert len(results) == 1
        d = results[0]
        assert d.report_definition_id == sample_definition.report_definition_id
        assert d.name == sample_definition.name
        assert d.prompt == sample_definition.prompt
        assert d.sql_template == sample_definition.sql_template
        assert d.description == sample_definition.description
        assert d.unparameterized_sql == sample_definition.unparameterized_sql
        assert d.created_at == sample_definition.created_at


class TestUpdateReportDefinition:
    def test_updates_name(self, db, sample_definition):
        save_report_definition(sample_definition, db)
        sample_definition.name = "Updated Name"

        update_report_definition(sample_definition, db)

        row = db.execute(
            "SELECT name FROM report_definitions WHERE report_definition_id = ?",
            (sample_definition.report_definition_id,),
        ).fetchone()
        assert row["name"] == "Updated Name"

    def test_updates_sql_template(self, db, sample_definition):
        save_report_definition(sample_definition, db)
        sample_definition.sql_template = "SELECT je.date, je.debit FROM journal_entries je WHERE je.date BETWEEN :start_date AND :end_date"

        update_report_definition(sample_definition, db)

        row = db.execute(
            "SELECT sql_template FROM report_definitions WHERE report_definition_id = ?",
            (sample_definition.report_definition_id,),
        ).fetchone()
        assert "je.debit" in row["sql_template"]

    def test_updates_all_mutable_fields(self, db, sample_definition):
        save_report_definition(sample_definition, db)
        sample_definition.name = "New Name"
        sample_definition.prompt = "New prompt"
        sample_definition.sql_template = "SELECT 99"
        sample_definition.description = "New description"

        update_report_definition(sample_definition, db)

        results = find_report_definitions(
            report_definition_id=sample_definition.report_definition_id, conn=db
        )
        d = results[0]
        assert d.name == "New Name"
        assert d.prompt == "New prompt"
        assert d.sql_template == "SELECT 99"
        assert d.description == "New description"
        assert d.unparameterized_sql is None

    def test_updates_unparameterized_sql(self, db, sample_definition):
        save_report_definition(sample_definition, db)
        sample_definition.unparameterized_sql = (
            "SELECT SUM(je.debit) FROM journal_entries je WHERE je.date = '2025-10-01'"
        )

        update_report_definition(sample_definition, db)

        results = find_report_definitions(
            report_definition_id=sample_definition.report_definition_id, conn=db
        )
        assert results[0].unparameterized_sql == sample_definition.unparameterized_sql

    def test_raises_when_not_found(self, db, sample_definition):
        with pytest.raises(ValueError, match=sample_definition.report_definition_id):
            update_report_definition(sample_definition, db)

    def test_does_not_affect_other_definitions(self, db):
        d1 = ReportDefinition(name="A", prompt="", sql_template="SELECT 1", description="")
        d2 = ReportDefinition(name="B", prompt="", sql_template="SELECT 2", description="")
        save_report_definition(d1, db)
        save_report_definition(d2, db)

        d1.name = "A updated"
        update_report_definition(d1, db)

        results = find_report_definitions(report_definition_id=d2.report_definition_id, conn=db)
        assert results[0].name == "B"


class TestDeleteReportDefinition:
    def test_deletes_definition(self, db, sample_definition):
        save_report_definition(sample_definition, db)

        delete_report_definition(sample_definition.report_definition_id, db)

        assert (
            find_report_definitions(
                report_definition_id=sample_definition.report_definition_id, conn=db
            )
            == []
        )

    def test_raises_when_not_found(self, db):
        with pytest.raises(ValueError, match="nonexistent"):
            delete_report_definition("nonexistent", db)

    def test_does_not_delete_other_definitions(self, db):
        d1 = ReportDefinition(name="A", prompt="", sql_template="SELECT 1", description="")
        d2 = ReportDefinition(name="B", prompt="", sql_template="SELECT 2", description="")
        save_report_definition(d1, db)
        save_report_definition(d2, db)

        delete_report_definition(d1.report_definition_id, db)

        remaining = find_report_definitions(conn=db)
        assert len(remaining) == 1
        assert remaining[0].report_definition_id == d2.report_definition_id
