import re
from datetime import date
from decimal import Decimal

import pdfplumber

from balanceai.models import Account, Transaction, Bank
from balanceai.parsers import StatementParser, register_parser


@register_parser(Bank.CHASE)
class ChaseParser(StatementParser):
    """Parser for Chase bank statements."""

    def parse(self, file_path: str) -> tuple[Account, list[Transaction]]:
        with pdfplumber.open(file_path) as pdf:
            all_text = ""
            all_tables = []

            for page in pdf.pages:
                all_text += page.extract_text() or ""
                tables = page.extract_tables()
                all_tables.extend(tables)

        account = self._parse_account_info(all_text)
        transactions = self._parse_transactions(all_text, all_tables, account.id)

        return account, transactions

    def _parse_account_info(self, text: str) -> Account:
        # Extract account number (last 4 digits typically shown)
        account_match = re.search(r"Account\s*(?:Number|#)?[:\s]*[X\*]*(\d{4})", text, re.IGNORECASE)
        account_id = account_match.group(1) if account_match else "0000"

        # Determine account type
        if "credit card" in text.lower():
            account_type = "credit_card"
        elif "savings" in text.lower():
            account_type = "savings"
        else:
            account_type = "checking"

        # Extract ending balance
        balance_match = re.search(
            r"(?:Ending|Closing)\s*Balance[:\s]*\$?([\d,]+\.?\d*)",
            text,
            re.IGNORECASE
        )
        balance = Decimal(balance_match.group(1).replace(",", "")) if balance_match else Decimal("0")

        return Account(
            id=f"chase_{account_id}",
            name=f"Chase {account_type.replace('_', ' ').title()} ...{account_id}",
            bank=Bank.CHASE,
            account_type=account_type,
            balance_current=balance,
        )

    def _parse_transactions(
        self, text: str, tables: list, account_id: str
    ) -> list[Transaction]:
        transactions = []

        # Extract statement year from text
        year_match = re.search(r"(?:Statement\s*Period|through)[:\s]*\w+\s*\d+,?\s*(\d{4})", text, re.IGNORECASE)
        statement_year = int(year_match.group(1)) if year_match else date.today().year

        # Try table-based extraction first
        for table in tables:
            for row in table:
                if not row or len(row) < 3:
                    continue

                txn = self._parse_table_row(row, statement_year, account_id)
                if txn:
                    transactions.append(txn)

        # Fall back to text-based extraction if no transactions found
        if not transactions:
            transactions = self._parse_transactions_from_text(text, statement_year, account_id)

        return transactions

    def _parse_table_row(
        self, row: list, year: int, account_id: str
    ) -> Transaction | None:
        # Chase tables typically: Date | Description | Amount
        # Clean up None values
        row = [str(cell).strip() if cell else "" for cell in row]

        # Look for date pattern in first column (MM/DD)
        date_match = re.match(r"(\d{1,2})/(\d{1,2})", row[0])
        if not date_match:
            return None

        month, day = int(date_match.group(1)), int(date_match.group(2))

        try:
            txn_date = date(year, month, day)
        except ValueError:
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

        txn_id = Transaction.generate_id(account_id, txn_date, description, amount)

        return Transaction(
            id=txn_id,
            account_id=account_id,
            date=txn_date,
            description=description,
            amount=amount,
        )

    def _parse_transactions_from_text(
        self, text: str, year: int, account_id: str
    ) -> list[Transaction]:
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

            try:
                txn_date = date(year, month, day)
            except ValueError:
                continue

            amount_str = amount_str.replace("$", "").replace(",", "")
            try:
                amount = Decimal(amount_str)
            except Exception:
                continue

            txn_id = Transaction.generate_id(account_id, txn_date, description.strip(), amount)

            transactions.append(Transaction(
                id=txn_id,
                account_id=account_id,
                date=txn_date,
                description=description.strip(),
                amount=amount,
            ))

        return transactions
