"""Integration tests for analyze_financial_question.

Tests cover the four core spending Q&A use cases from IDEAS.md:
  1. How much did I spend in the last X days/weeks/months?
  2. How much did I spend on [category]?
  3. How much did I spend at [merchant]?
  4. What are my biggest expenses this month?

Run with:
    pytest integ_tests/ -v

Requires a configured Gemini API key (via settings).

Synthetic dataset — October 2025:
  Spending:
    Whole Foods  $120  groceries   Oct 05
    Shell         $50  gas         Oct 10
    Netflix       $15  entertainment Oct 12
    Whole Foods   $80  groceries   Oct 20
    Amazon        $95  shopping    Oct 25
    Total spending: $360

  Income:
    Acme Corp  $5,000  income  Oct 01

  Transfers:
    Bank of America 9999  $500   transfer  Oct 08
    Bank of America 9999  $1,000 transfer  Oct 22
"""

import sqlite3
import time
from datetime import date
from unittest.mock import patch

import pytest

from balanceai_backend.db import create_schema
from balanceai_backend.servers.bookkeeping_server import analyze_financial_question

# ---------------------------------------------------------------------------
# Synthetic database
# ---------------------------------------------------------------------------

_JOURNAL_ENTRIES = [
    # (journal_entry_id, journal_id, date, account, description, debit, credit, category, tax, recipient)
    # Salary income $5,000 — Oct 01
    (
        "e01",
        "j1",
        "2025-10-01",
        "cash",
        "Salary from Acme Corp",
        5000.0,
        0.0,
        "income",
        0.0,
        "Self",
    ),
    (
        "e02",
        "j1",
        "2025-10-01",
        "sale",
        "Salary from Acme Corp",
        0.0,
        5000.0,
        "income",
        0.0,
        "Acme Corp",
    ),
    # Whole Foods $120 — Oct 05
    (
        "e03",
        "j1",
        "2025-10-05",
        "essential_expense",
        "Whole Foods grocery run",
        120.0,
        0.0,
        "groceries",
        0.0,
        "Self",
    ),
    (
        "e04",
        "j1",
        "2025-10-05",
        "cash",
        "Whole Foods grocery run",
        0.0,
        120.0,
        "groceries",
        0.0,
        "Whole Foods",
    ),
    # Shell $50 — Oct 10
    ("e05", "j1", "2025-10-10", "essential_expense", "Gas at Shell", 50.0, 0.0, "gas", 0.0, "Self"),
    ("e06", "j1", "2025-10-10", "cash", "Gas at Shell", 0.0, 50.0, "gas", 0.0, "Shell"),
    # Netflix $15 — Oct 12
    (
        "e07",
        "j1",
        "2025-10-12",
        "non_essential_expense",
        "Netflix subscription",
        15.0,
        0.0,
        "entertainment",
        0.0,
        "Self",
    ),
    (
        "e08",
        "j1",
        "2025-10-12",
        "cash",
        "Netflix subscription",
        0.0,
        15.0,
        "entertainment",
        0.0,
        "Netflix",
    ),
    # Whole Foods $80 — Oct 20
    (
        "e09",
        "j1",
        "2025-10-20",
        "essential_expense",
        "Whole Foods grocery run",
        80.0,
        0.0,
        "groceries",
        0.0,
        "Self",
    ),
    (
        "e10",
        "j1",
        "2025-10-20",
        "cash",
        "Whole Foods grocery run",
        0.0,
        80.0,
        "groceries",
        0.0,
        "Whole Foods",
    ),
    # Amazon $95 — Oct 25
    (
        "e11",
        "j1",
        "2025-10-25",
        "essential_expense",
        "Amazon purchase",
        95.0,
        0.0,
        "shopping",
        0.0,
        "Self",
    ),
    ("e12", "j1", "2025-10-25", "cash", "Amazon purchase", 0.0, 95.0, "shopping", 0.0, "Amazon"),
    # Transfer to Bank of America 9999 $500 — Oct 08
    (
        "e13",
        "j1",
        "2025-10-08",
        "cash",
        "Transfer to Bank of America 9999",
        500.0,
        0.0,
        "transfer",
        0.0,
        "Self",
    ),
    (
        "e14",
        "j1",
        "2025-10-08",
        "transfer",
        "Transfer to Bank of America 9999",
        0.0,
        500.0,
        "transfer",
        0.0,
        "Bank of America 9999",
    ),
    # Transfer to Bank of America 9999 $1,000 — Oct 22
    (
        "e15",
        "j1",
        "2025-10-22",
        "cash",
        "Transfer to Bank of America 9999",
        1000.0,
        0.0,
        "transfer",
        0.0,
        "Self",
    ),
    (
        "e16",
        "j1",
        "2025-10-22",
        "transfer",
        "Transfer to Bank of America 9999",
        0.0,
        1000.0,
        "transfer",
        0.0,
        "Bank of America 9999",
    ),
]


def _make_synthetic_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    conn.execute(
        "INSERT INTO journals VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("j1", "acct-1", "chase", "debit", "October 2025 Journal", "2025-10-01", "2025-10-31"),
    )
    conn.executemany(
        "INSERT INTO journal_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        _JOURNAL_ENTRIES,
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RATE_LIMIT_DELAY = 13  # seconds between Gemini calls (free tier: 5 req/min)


def _numeric_values(rows: list[dict]) -> list[float]:
    """Flatten all numeric values out of a list of row dicts."""
    return [float(v) for row in rows for v in row.values() if isinstance(v, (int, float))]


def _contains_approx(values: list[float], expected: float, rel: float = 0.01) -> bool:
    return any(abs(v - expected) / max(abs(expected), 1e-9) <= rel for v in values)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnalyzeFinancialQuestion:
    @pytest.fixture(autouse=True)
    def synthetic_db(self):
        db = _make_synthetic_db()
        with (
            patch("balanceai_backend.servers.bookkeeping_server.conn", db),
            patch("balanceai_backend.prompts.financial_query_prompt.conn", db),
            patch("balanceai_backend.services.gemini.DEFAULT_MODEL_ID", "gemini-2.5-flash-lite"),
        ):
            yield db
        db.close()

    # -----------------------------------------------------------------------
    # Idea #1 — How much did I spend in the last X days/weeks/months?
    # -----------------------------------------------------------------------

    def test_spend_in_period(self):
        """Total spending in October 2025 should be $360."""
        result = analyze_financial_question(
            question="How much did I spend in October 2025?",
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 31),
        )
        assert result["row_count"] >= 1
        assert _contains_approx(_numeric_values(result["rows"]), 360.0), (
            f"Expected 360.0 in rows, got: {result['rows']}"
        )
        time.sleep(RATE_LIMIT_DELAY)

    def test_spend_in_period_2(self):
        """Total spending in October 2025 should be $360."""
        result = analyze_financial_question(
            question="How much did I spend with the exception of transfers in October 2025?",
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 31),
        )
        assert result["row_count"] >= 1
        assert _contains_approx(_numeric_values(result["rows"]), 360.0), (
            f"Expected 360.0 in rows, got: {result['rows']}"
        )
        time.sleep(RATE_LIMIT_DELAY)

    def test_spend_in_first_half_of_month(self):
        """Spending Oct 1–15 should be $185 (Whole Foods $120 + Shell $50 + Netflix $15)."""
        result = analyze_financial_question(
            question="How much did I spend with the exception of transfers between October 1 and October 15, 2025?",
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 15),
        )
        assert result["row_count"] >= 1
        assert _contains_approx(_numeric_values(result["rows"]), 185.0), (
            f"Expected 185.0 in rows, got: {result['rows']}"
        )
        time.sleep(RATE_LIMIT_DELAY)

    # -----------------------------------------------------------------------
    # Idea #2 — How much did I spend on [category]?
    # -----------------------------------------------------------------------

    def test_spend_on_groceries(self):
        """Groceries total should be $200 ($120 + $80 at Whole Foods)."""
        result = analyze_financial_question(
            question="How much did I spend on groceries in October 2025?",
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 31),
        )
        assert result["row_count"] >= 1
        assert _contains_approx(_numeric_values(result["rows"]), 200.0), (
            f"Expected 200.0 in rows, got: {result['rows']}"
        )
        time.sleep(RATE_LIMIT_DELAY)

    def test_spend_on_gas(self):
        """Gas total should be $50."""
        result = analyze_financial_question(
            question="How much did I spend on gas in October 2025?",
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 31),
        )
        assert result["row_count"] >= 1
        assert _contains_approx(_numeric_values(result["rows"]), 50.0), (
            f"Expected 50.0 in rows, got: {result['rows']}"
        )
        time.sleep(RATE_LIMIT_DELAY)

    # -----------------------------------------------------------------------
    # Idea #3 — How much did I spend at [merchant]?
    # -----------------------------------------------------------------------

    def test_spend_at_whole_foods(self):
        """Whole Foods total should be $200 (two transactions: $120 + $80)."""
        result = analyze_financial_question(
            question="How much did I spend at Whole Foods in October 2025?",
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 31),
        )
        assert result["row_count"] >= 1
        assert _contains_approx(_numeric_values(result["rows"]), 200.0), (
            f"Expected 200.0 in rows, got: {result['rows']}"
        )
        assert "recipient" in result["sql"].lower(), (
            "SQL should filter by recipient for merchant queries"
        )
        time.sleep(RATE_LIMIT_DELAY)

    def test_spend_at_shell(self):
        """Shell total should be $50."""
        result = analyze_financial_question(
            question="How much did I spend at Shell in October 2025?",
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 31),
        )
        assert result["row_count"] >= 1
        assert _contains_approx(_numeric_values(result["rows"]), 50.0), (
            f"Expected 50.0 in rows, got: {result['rows']}"
        )
        time.sleep(RATE_LIMIT_DELAY)

    # -----------------------------------------------------------------------
    # Idea #4 — What are my biggest expenses this month?
    # -----------------------------------------------------------------------

    def test_biggest_expenses_returns_multiple_rows(self):
        """Should return multiple rows ranked by spend amount."""
        result = analyze_financial_question(
            question="What are my biggest expenses in October 2025?",
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 31),
        )
        assert result["row_count"] > 1, "Expected multiple rows for biggest expenses breakdown"
        time.sleep(RATE_LIMIT_DELAY)

    def test_biggest_expenses_top_is_whole_foods(self):
        """Whole Foods ($200) should be the top spender in October 2025."""
        result = analyze_financial_question(
            question="What are my biggest expenses in October 2025, ranked by total amount?",
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 31),
        )
        assert result["row_count"] >= 1
        # The first row should contain the largest value, which is 200.0 (Whole Foods)
        first_row_values = _numeric_values([result["rows"][0]])
        assert _contains_approx(first_row_values, 200.0), (
            f"Expected top expense to be 200.0 (Whole Foods), got first row: {result['rows'][0]}"
        )
        time.sleep(RATE_LIMIT_DELAY)
