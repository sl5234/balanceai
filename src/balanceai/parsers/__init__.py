from abc import ABC, abstractmethod

from balanceai.models import Account, Transaction, Bank


class StatementParser(ABC):
    """Base class for bank statement parsers."""

    @abstractmethod
    def parse(self, file_path: str) -> tuple[Account, list[Transaction]]:
        """
        Parse a bank statement PDF.

        Args:
            file_path: Path to the PDF file

        Returns:
            Tuple of (Account, list of Transactions)
        """
        pass


_parsers: dict[Bank, type[StatementParser]] = {}


def register_parser(bank: Bank):
    """Decorator to register a parser for a bank."""

    def decorator(cls: type[StatementParser]):
        _parsers[bank] = cls
        return cls

    return decorator


def get_parser(bank: Bank) -> StatementParser:
    """Get a parser instance for the given bank."""
    if bank not in _parsers:
        raise ValueError(f"No parser registered for {bank.value}")
    return _parsers[bank]()
