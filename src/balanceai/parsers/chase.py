import re
from datetime import date
from decimal import Decimal
from typing import NamedTuple

import pdfplumber

from balanceai.models import Account, Transaction, Bank
from balanceai.parsers import StatementParser, register_parser


class StatementPeriod(NamedTuple):
    start_date: date
    end_date: date


MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


@register_parser(Bank.CHASE)
class ChaseParser(StatementParser):
    """
    Parser for Chase bank statements.

    TODO: In the future, if we keep the statement parsing logic, we should probably
    pass the statement through LLM. This is just a temporary solution to get the data in.
    And at that time, we should probably use AWS Bedrock as opposed to model providers
    like OpenAI directly for additional security.
    """

    def parse(self, file_path: str) -> tuple[Account, list[Transaction]]:
        with pdfplumber.open(file_path) as pdf:
            all_text = ""
            all_tables = []

            for page in pdf.pages:
                all_text += page.extract_text() or ""
                tables = page.extract_tables()
                all_tables.extend(tables)

        account, beginning_balance = self._parse_account_info(all_text)
        transactions = self._parse_transactions(all_text, all_tables, account.id, beginning_balance)

        return account, transactions

    def _parse_account_info(self, text: str) -> tuple[Account, Decimal]:
        # Extract account number (last 4 digits typically shown)
        account_match = re.search(
            r"Account\s*(?:Number|#)?[:\s]*[X\*]*(\d{4})", text, re.IGNORECASE
        )
        account_id = account_match.group(1) if account_match else "0000"

        # Determine account type
        if "credit card" in text.lower():
            account_type = "credit_card"
        elif "savings" in text.lower():
            account_type = "savings"
        else:
            account_type = "checking"

        # Extract beginning balance
        beginning_match = re.search(
            r"(?:Beginning|Opening|Starting)\s*Balance[:\s]*\$?([\d,]+\.?\d*)", text, re.IGNORECASE
        )
        beginning_balance = (
            Decimal(beginning_match.group(1).replace(",", "")) if beginning_match else Decimal("0")
        )

        account = Account(
            id=account_id,
            bank=Bank.CHASE,
            account_type=account_type,
        )

        return account, beginning_balance

    def _parse_statement_period(self, text: str) -> StatementPeriod | None:
        """Parse statement period from various formats Chase might use."""

        # Format 1: "November 25, 2025 through December 19, 2025"
        pattern1 = r"(\w+)\s+(\d{1,2}),\s*(\d{4})\s+through\s+(\w+)\s+(\d{1,2}),\s*(\d{4})"
        match = re.search(pattern1, text, re.IGNORECASE)
        if match:
            start_month_name, start_day, start_year, end_month_name, end_day, end_year = match.groups()
            start_month = MONTH_NAMES.get(start_month_name.lower())
            end_month = MONTH_NAMES.get(end_month_name.lower())
            if start_month and end_month:
                try:
                    return StatementPeriod(
                        start_date=date(int(start_year), start_month, int(start_day)),
                        end_date=date(int(end_year), end_month, int(end_day)),
                    )
                except ValueError:
                    pass

        # Format 2: "December 20 - January 23, 2026" (year only at end)
        pattern2 = r"(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)\s+(\d{1,2}),?\s*(\d{4})"
        match = re.search(pattern2, text, re.IGNORECASE)
        if match:
            start_month_name, start_day, end_month_name, end_day, end_year = match.groups()
            start_month = MONTH_NAMES.get(start_month_name.lower())
            end_month = MONTH_NAMES.get(end_month_name.lower())
            if start_month and end_month:
                end_year = int(end_year)
                # If start month > end month, start is in previous year
                start_year = end_year - 1 if start_month > end_month else end_year
                try:
                    return StatementPeriod(
                        start_date=date(start_year, start_month, int(start_day)),
                        end_date=date(end_year, end_month, int(end_day)),
                    )
                except ValueError:
                    pass

        # Format 3: "12/20/2025 - 01/23/2026" or "12/20/25 - 01/23/26" (numeric with full/short year)
        pattern3 = r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s*[-–]\s*(\d{1,2})/(\d{1,2})/(\d{2,4})"
        match = re.search(pattern3, text)
        if match:
            sm, sd, sy, em, ed, ey = match.groups()
            # Handle 2-digit years
            start_year = int(sy) if len(sy) == 4 else 2000 + int(sy)
            end_year = int(ey) if len(ey) == 4 else 2000 + int(ey)
            try:
                return StatementPeriod(
                    start_date=date(start_year, int(sm), int(sd)),
                    end_date=date(end_year, int(em), int(ed)),
                )
            except ValueError:
                pass

        # Format 4: "12/20 - 01/23, 2026" (numeric month/day, year at end)
        pattern4 = r"(\d{1,2})/(\d{1,2})\s*[-–]\s*(\d{1,2})/(\d{1,2}),?\s*(\d{4})"
        match = re.search(pattern4, text)
        if match:
            sm, sd, em, ed, end_year = match.groups()
            sm, sd, em, ed = int(sm), int(sd), int(em), int(ed)
            end_year = int(end_year)
            # If start month > end month, start is in previous year
            start_year = end_year - 1 if sm > em else end_year
            try:
                return StatementPeriod(
                    start_date=date(start_year, sm, sd),
                    end_date=date(end_year, em, ed),
                )
            except ValueError:
                pass

        return None

    def _infer_transaction_date(self, month: int, day: int, period: StatementPeriod) -> date | None:
        """Infer the correct year for a transaction based on the statement period."""
        # Try the start year first
        try:
            candidate = date(period.start_date.year, month, day)
            if period.start_date <= candidate <= period.end_date:
                return candidate
        except ValueError:
            pass

        # Try the end year if different
        if period.end_date.year != period.start_date.year:
            try:
                candidate = date(period.end_date.year, month, day)
                if period.start_date <= candidate <= period.end_date:
                    return candidate
            except ValueError:
                pass

        return None

    def _parse_transactions(
        self, text: str, tables: list, account_id: str, beginning_balance: Decimal
    ) -> list[Transaction]:
        raw_transactions = []

        # Extract statement period from text
        period = self._parse_statement_period(text)
        if not period:
            # Fallback: if we're early in the year, include previous year
            # to handle statements from late previous year
            today = date.today()
            if today.month <= 2:
                # In Jan/Feb, transactions from Nov/Dec are likely previous year
                period = StatementPeriod(
                    start_date=date(today.year - 1, 1, 1),
                    end_date=date(today.year, 12, 31),
                )
            else:
                period = StatementPeriod(
                    start_date=date(today.year, 1, 1),
                    end_date=date(today.year, 12, 31),
                )

        # Try table-based extraction first
        for table in tables:
            for row in table:
                if not row or len(row) < 3:
                    continue

                txn_data = self._parse_table_row(row, period)
                if txn_data:
                    raw_transactions.append(txn_data)

        # Fall back to text-based extraction if no transactions found
        if not raw_transactions:
            raw_transactions = self._parse_transactions_from_text(text, period)

        # Sort by date and add running balance
        raw_transactions.sort(key=lambda t: t["date"])

        transactions = []
        running_balance = beginning_balance

        for txn_data in raw_transactions:
            previous_balance = running_balance
            new_balance = previous_balance + txn_data["amount"]
            running_balance = new_balance

            txn_id = Transaction.generate_id(
                account_id, txn_data["date"], txn_data["description"], txn_data["amount"]
            )

            transactions.append(Transaction(
                id=txn_id,
                account_id=account_id,
                date=txn_data["date"],
                description=txn_data["description"],
                amount=txn_data["amount"],
                previous_balance=previous_balance,
                new_balance=new_balance,
            ))

        return transactions

    def _parse_table_row(self, row: list, period: StatementPeriod) -> dict | None:
        # Chase tables typically: Date | Description | Amount
        # Clean up None values
        row = [str(cell).strip() if cell else "" for cell in row]

        # Look for date pattern in first column (MM/DD)
        date_match = re.match(r"(\d{1,2})/(\d{1,2})", row[0])
        if not date_match:
            return None

        month, day = int(date_match.group(1)), int(date_match.group(2))
        txn_date = self._infer_transaction_date(month, day, period)
        if not txn_date:
            return None

        # Description is typically middle column(s)
        description = " ".join(row[1:-1]).strip()
        if not description:
            return None

        # Amount is last column
        amount_str = row[-1].replace("$", "").replace(",", "").strip()

        # Handle negative amounts (debits shown as negative or in parentheses)
        is_negative = False
        if amount_str.startswith("(") and amount_str.endswith(")"):
            amount_str = amount_str[1:-1]
            is_negative = True
        elif amount_str.startswith("-"):
            amount_str = amount_str[1:]
            is_negative = True

        try:
            amount = Decimal(amount_str)
            if is_negative:
                amount = -amount
        except Exception:
            return None

        return {
            "date": txn_date,
            "description": description,
            "amount": amount,
        }

    def _parse_transactions_from_text(
        self, text: str, period: StatementPeriod
    ) -> list[dict]:
        """Fallback text-based parsing when tables don't work."""
        transactions = []

        # Pattern: MM/DD description amount
        pattern = r"(\d{1,2}/\d{1,2})\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})\s*$"

        for line in text.split("\n"):
            match = re.match(pattern, line.strip())
            if not match:
                continue

            date_str, description, amount_str = match.groups()
            month, day = map(int, date_str.split("/"))

            txn_date = self._infer_transaction_date(month, day, period)
            if not txn_date:
                continue

            amount_str = amount_str.replace("$", "").replace(",", "")
            try:
                amount = Decimal(amount_str)
            except Exception:
                continue

            transactions.append({
                "date": txn_date,
                "description": description.strip(),
                "amount": amount,
            })

        return transactions
