import csv
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from appdevcommons.unique_id import UniqueIdGenerator

MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".pdf": "application/pdf",
}


def get_mime_type(extension: str) -> str:
    """Map a file extension (e.g. '.png') to its MIME type."""
    ext = extension.lower()
    if ext not in MIME_TYPES:
        raise ValueError(f"Unsupported file type: {ext}")
    return MIME_TYPES[ext]


def publish_data(rows: list[dict], local_path: str) -> str:
    """Write a list of row dicts to a CSV file. Returns the resolved path."""
    out = Path(local_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        out.write_text("")
        return str(out)
    headers = list(rows[0].keys())
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return str(out)


def utc_now_iso() -> str:
    """Now, in UTC, as ISO 8601 text, e.g. '2026-11-11T05:04:00.123456+00:00'.
    Used for created_at / updated_at."""
    return datetime.now(UTC).isoformat()


class IdPrefix(StrEnum):
    """What an id belongs to, shown as its prefix, e.g. 'plaid-3f9c…'."""

    PLAID = "plaid"  # source transaction from Plaid
    RECEIPT = "receipt"  # source transaction from a receipt
    STATEMENT = "statement"  # source transaction from a bank statement
    TRANSACTION = "txn"


def generate_id(prefix: IdPrefix) -> str:
    """A new unique id with a type prefix, e.g. generate_id(IdPrefix.RECEIPT)
    -> 'receipt-3f9c1a…' (UniqueIdGenerator's 32 hex characters)."""
    return f"{prefix.value}-{UniqueIdGenerator.generate_id()}"
