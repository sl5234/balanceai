from datetime import date
from decimal import Decimal

from balanceai_backend.models.receipt import PaymentMethod, ReceiptExtraction, ReceiptKind


def test_parses_a_full_receipt():
    receipt = ReceiptExtraction.model_validate_json(
        '{"date": "2026-11-08", "counterparty": "Blue Bottle Coffee", "kind": "purchase",'
        ' "total": "12.50", "tax": "1.02", "tip": null, "payment_method": "card",'
        ' "card_last4": "1234", "items": ["Latte", "Croissant"], "category": "dining"}'
    )
    assert receipt.date == date(2026, 11, 8)
    assert receipt.total == Decimal("12.50")
    assert receipt.kind is ReceiptKind.PURCHASE
    assert receipt.payment_method is PaymentMethod.CARD


def test_optional_fields_default_to_empty():
    receipt = ReceiptExtraction.model_validate_json(
        '{"date": "2026-11-08", "counterparty": "Corner Store", "kind": "purchase",'
        ' "total": 4.0, "payment_method": "cash"}'
    )
    assert receipt.tax is None and receipt.card_last4 is None
    assert receipt.items == [] and receipt.category is None


def test_parses_a_refund():
    receipt = ReceiptExtraction.model_validate_json(
        '{"date": "2026-11-08", "counterparty": "Acme Outfitters", "kind": "refund",'
        ' "total": "29.81", "payment_method": "card", "card_last4": "1234"}'
    )
    assert receipt.kind is ReceiptKind.REFUND
    assert receipt.total == Decimal("29.81")
