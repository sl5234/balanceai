import logging
import re
from datetime import date
from decimal import Decimal
from typing import NamedTuple

import pdfplumber
from appdevcommons.hash_generator import HashGenerator

from balanceai.models import Account, AccountType, Transaction, Bank
from balanceai.parsers import StatementParser, register_parser

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="/Users/sl5234/Workspace/BalanceAI/logs/chase_parser.log",
    filemode="a",
)
logger = logging.getLogger(__name__)


class StatementPeriod(NamedTuple):
    start_date: date
    end_date: date


MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
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
            for page in pdf.pages:
                all_text += page.extract_text() or ""

        logger.debug("\nExtracted text:\n%s", all_text)

        account = self._parse_account_info(all_text)
        account.id = HashGenerator.generate_hash(account.id)
        beginning_balance, ending_balance = self._parse_balances(all_text)
        transactions = self._parse_transactions(all_text, account.id)
        self._validate_balances(beginning_balance, transactions, ending_balance)

        return account, transactions

    def _parse_account_info(self, text: str) -> Account:
        # Extract account number (may be on next line after "Account Number:")
        account_match = re.search(r"Account\s*Number[:\s]*(\d+)", text, re.IGNORECASE)
        if not account_match:
            raise ValueError("Could not parse account number from statement")
        account_id = account_match.group(1)

        # Determine account type
        if "credit card" in text.lower():
            account_type = AccountType.CREDIT
        elif "saving" in text.lower():
            account_type = AccountType.SAVING
        else:
            account_type = AccountType.DEBIT

        return Account(
            id=account_id,
            bank=Bank.CHASE,
            account_type=account_type,
        )

    def _parse_balances(self, text: str) -> tuple[Decimal, Decimal]:
        # Extract beginning balance
        beginning_match = re.search(
            r"(?:Beginning|Opening|Starting)\s*Balance[:\s]*\$?([\d,]+\.?\d*)", text, re.IGNORECASE
        )
        if not beginning_match:
            raise ValueError("Could not parse beginning balance from statement")
        beginning_balance = Decimal(beginning_match.group(1).replace(",", ""))

        # Extract ending balance
        ending_match = re.search(
            r"(?:Ending|Closing|Final)\s*Balance[:\s]*\$?([\d,]+\.?\d*)", text, re.IGNORECASE
        )
        if not ending_match:
            raise ValueError("Could not parse ending balance from statement")
        ending_balance = Decimal(ending_match.group(1).replace(",", ""))

        return beginning_balance, ending_balance

    def _parse_statement_period(self, text: str) -> StatementPeriod:
        """Parse statement period from various formats Chase might use."""

        # Format: "November 25, 2025 through December 19, 2025" (spaces around "through" optional)
        pattern = r"(\w+)\s+(\d{1,2}),\s*(\d{4})\s*through\s*(\w+)\s+(\d{1,2}),\s*(\d{4})"
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            raise ValueError("Could not parse statement period from statement")

        start_month_name, start_day, start_year, end_month_name, end_day, end_year = match.groups()
        start_month = MONTH_NAMES.get(start_month_name.lower())
        end_month = MONTH_NAMES.get(end_month_name.lower())

        if not start_month:
            raise ValueError(f"Invalid start month name: {start_month_name}")
        if not end_month:
            raise ValueError(f"Invalid end month name: {end_month_name}")

        period = StatementPeriod(
            start_date=date(int(start_year), start_month, int(start_day)),
            end_date=date(int(end_year), end_month, int(end_day)),
        )
        logger.debug("\nStatement period: %s to %s", period.start_date, period.end_date)

        return period

    def _infer_transaction_date(self, month: int, day: int, period: StatementPeriod) -> date:
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

        raise ValueError(
            f"Could not infer year for {month}/{day} within statement period "
            f"{period.start_date} to {period.end_date}"
        )

    def _parse_transactions_from_text(self, text: str, period: StatementPeriod) -> list[dict]:
        """Parse transactions from extracted text."""
        transactions = []

        # Clean up malformed markers from PDF extraction (e.g., "*end*transac1tion detail2/01" -> "12/01")
        # These occur at page boundaries where markers merge with transaction lines
        # The first digit of the date gets embedded in the word, second digit follows "detail"
        text = re.sub(r"\*(?:start|end)\*\w*(\d)\w*\s*detail(\d)", r"\1\2", text)

        # Pattern: MM/DD description amount new_balance
        pattern = r"(\d{1,2}/\d{1,2})\s+(.+?)\s+(-?[\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*$"

        for line in text.split("\n"):
            match = re.match(pattern, line.strip())
            if not match:
                continue

            date_str, description, amount_str, new_balance_str = match.groups()
            month, day = map(int, date_str.split("/"))

            txn_date = self._infer_transaction_date(month, day, period)

            amount = Decimal(amount_str.replace(",", ""))
            new_balance = Decimal(new_balance_str.replace(",", ""))
            previous_balance = new_balance - amount

            transactions.append(
                {
                    "date": txn_date,
                    "description": description.strip(),
                    "amount": amount,
                    "previous_balance": previous_balance,
                    "new_balance": new_balance,
                }
            )

        if not transactions:
            raise ValueError("Could not parse any transactions from statement")

        return transactions

    def _parse_transactions(self, text: str, account_id: str) -> list[Transaction]:
        period = self._parse_statement_period(text)
        raw_transactions = self._parse_transactions_from_text(text, period)

        # Sort by date
        raw_transactions.sort(key=lambda t: t["date"])

        transactions = []
        for txn_data in raw_transactions:
            txn_id = Transaction.generate_id(
                account_id, txn_data["date"], txn_data["description"], txn_data["amount"]
            )

            transactions.append(
                Transaction(
                    id=txn_id,
                    account_id=account_id,
                    date=txn_data["date"],
                    description=txn_data["description"],
                    amount=txn_data["amount"],
                    previous_balance=txn_data["previous_balance"],
                    new_balance=txn_data["new_balance"],
                )
            )

        logger.debug("\nExtracted transactions:\n%s", transactions)
        return transactions

    def _validate_balances(
        self, beginning_balance: Decimal, transactions: list[Transaction], ending_balance: Decimal
    ) -> None:
        logger.debug("\nBeginning balance: \n%s", beginning_balance)
        logger.debug("\nEnding balance: \n%s", ending_balance)

        total_amount = sum(t.amount for t in transactions)
        logger.debug("\nTransactions total amount: \n%s", total_amount)
        calculated_ending = beginning_balance + total_amount

        if calculated_ending != ending_balance:
            raise ValueError(
                f"Balance mismatch: beginning ({beginning_balance}) + transactions ({total_amount}) "
                f"= {calculated_ending}, but ending balance is {ending_balance}"
            )
