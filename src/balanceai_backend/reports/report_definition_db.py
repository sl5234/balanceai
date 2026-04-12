import json
import sqlite3

from balanceai_backend.db import conn as _default_conn
from balanceai_backend.models.report import ReportDefinition


def _build_report_definition(row) -> ReportDefinition:
    raw_params = row["parameters"]
    parameters = json.loads(raw_params) if raw_params else []
    return ReportDefinition(
        report_definition_id=row["report_definition_id"],
        name=row["name"],
        prompt=row["prompt"],
        sql_template=row["sql_template"],
        description=row["description"],
        unparameterized_sql=row["unparameterized_sql"],
        parameters=parameters,
        created_at=row["created_at"],
    )


def find_report_definitions(
    report_definition_id: str | None = None,
    conn: sqlite3.Connection = _default_conn,
) -> list[ReportDefinition]:
    """Find report definitions, optionally filtered by report_definition_id."""
    query = "SELECT * FROM report_definitions WHERE 1=1"
    params: list = []
    if report_definition_id is not None:
        query += " AND report_definition_id = ?"
        params.append(report_definition_id)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [_build_report_definition(row) for row in rows]


def save_report_definition(
    defn: ReportDefinition,
    conn: sqlite3.Connection = _default_conn,
) -> None:
    """Insert a new report definition into storage."""
    with conn:
        conn.execute(
            "INSERT INTO report_definitions"
            " (report_definition_id, name, prompt, sql_template, description,"
            "  unparameterized_sql, parameters, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                defn.report_definition_id,
                defn.name,
                defn.prompt,
                defn.sql_template,
                defn.description,
                defn.unparameterized_sql,
                json.dumps(defn.parameters),
                defn.created_at,
            ),
        )


def update_report_definition(
    updated: ReportDefinition,
    conn: sqlite3.Connection = _default_conn,
) -> None:
    """Update an existing report definition. Raises ValueError if not found."""
    if not find_report_definitions(report_definition_id=updated.report_definition_id, conn=conn):
        raise ValueError(f"ReportDefinition {updated.report_definition_id} not found")
    with conn:
        conn.execute(
            "UPDATE report_definitions"
            " SET name=?, prompt=?, sql_template=?, description=?, unparameterized_sql=?, parameters=?"
            " WHERE report_definition_id=?",
            (
                updated.name,
                updated.prompt,
                updated.sql_template,
                updated.description,
                updated.unparameterized_sql,
                json.dumps(updated.parameters),
                updated.report_definition_id,
            ),
        )


def delete_report_definition(
    report_definition_id: str,
    conn: sqlite3.Connection = _default_conn,
) -> None:
    """Delete a report definition. Raises ValueError if not found."""
    if not find_report_definitions(report_definition_id=report_definition_id, conn=conn):
        raise ValueError(f"ReportDefinition {report_definition_id} not found")
    with conn:
        conn.execute(
            "DELETE FROM report_definitions WHERE report_definition_id = ?",
            (report_definition_id,),
        )
