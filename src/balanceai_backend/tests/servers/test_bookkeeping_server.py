import datetime
import sqlite3
from decimal import Decimal
from unittest.mock import patch

import pytest
from balanceai_backend.db.connection import conn, create_schema
from balanceai_backend.models.journal import (
    GeneratedJournalEntry,
    GeneratedJournalEntrySet,
    Journal,
    JournalAccount,
    JournalEntry,
)
from balanceai_backend.servers.bookkeeping_server import (
    create_journal,
    delete_journal,
    list_journal_entries,
    list_journals,
    sync_journal_entries_from_receipt,
    update_journal,
)


@pytest.fixture
def sample_entry():
    return JournalEntry(
        journal_entry_id="entry-1",
        date=datetime.date(2026, 1, 27),
        account=JournalAccount.CASH,
        description="Trader Joe's purchase",
        debit=Decimal("32.02"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def sample_entry_2():
    return JournalEntry(
        journal_entry_id="entry-2",
        date=datetime.date(2026, 1, 28),
        account=JournalAccount.CASH,
        description="Whole Foods purchase",
        debit=Decimal("54.10"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def journal_with_no_entries():
    return Journal(
        journal_id="journal-1",
        name="January journal",
        entries=[],
    )


@pytest.fixture
def journal_with_entries(sample_entry, sample_entry_2):
    return Journal(
        journal_id="journal-1",
        name="January journal",
        entries=[sample_entry, sample_entry_2],
    )


class TestListJournalEntries:
    def test_returns_empty_list_when_journal_has_no_entries(self):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_entries", return_value=[]
        ):
            result = list_journal_entries("journal-1")
        assert result == []

    def test_returns_all_entries(self, sample_entry, sample_entry_2):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_entries",
            return_value=[sample_entry, sample_entry_2],
        ):
            result = list_journal_entries("journal-1")
        assert len(result) == 2

    def test_returns_entries_in_order(self, sample_entry, sample_entry_2):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_entries",
            return_value=[sample_entry, sample_entry_2],
        ):
            result = list_journal_entries("journal-1")
        assert result[0]["journal_entry_id"] == sample_entry.journal_entry_id
        assert result[1]["journal_entry_id"] == sample_entry_2.journal_entry_id

    def test_entries_are_returned_as_dicts(self, sample_entry, sample_entry_2):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_entries",
            return_value=[sample_entry, sample_entry_2],
        ):
            result = list_journal_entries("journal-1")
        for entry in result:
            assert isinstance(entry, dict)

    def test_entry_dict_contains_expected_fields(self, sample_entry):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_entries",
            return_value=[sample_entry],
        ):
            result = list_journal_entries("journal-1")
        entry = result[0]
        assert entry["journal_entry_id"] == sample_entry.journal_entry_id
        assert entry["date"] == sample_entry.date.isoformat()
        assert entry["description"] is None
        assert entry["debit"] == str(sample_entry.debit)
        assert entry["credit"] == str(sample_entry.credit)

    def test_entry_dict_includes_tax_field(self, sample_entry):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_entries",
            return_value=[sample_entry],
        ):
            result = list_journal_entries("journal-1")
        for entry in result:
            assert "tax" in entry
            assert entry["tax"] == "0"

    def test_raises_value_error_when_journal_not_found(self):
        with (
            patch(
                "balanceai_backend.servers.bookkeeping_server.db_find_journal_entries",
                side_effect=ValueError("journal-999"),
            ),
            pytest.raises(ValueError, match="journal-999"),
        ):
            list_journal_entries("journal-999")

    def test_filters_entries_by_date(self, sample_entry):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_entries",
            return_value=[sample_entry],
        ) as mock:
            result = list_journal_entries("journal-1", date=sample_entry.date)
        mock.assert_called_once_with("journal-1", date=sample_entry.date, conn=conn)
        assert len(result) == 1
        assert result[0]["journal_entry_id"] == sample_entry.journal_entry_id

    def test_returns_empty_list_when_no_entries_match_date(self):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_entries", return_value=[]
        ):
            result = list_journal_entries("journal-1", date=datetime.date(2020, 1, 1))
        assert result == []

    def test_returns_all_entries_when_date_not_provided(self, sample_entry, sample_entry_2):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_entries",
            return_value=[sample_entry, sample_entry_2],
        ):
            result = list_journal_entries("journal-1")
        assert len(result) == 2


# ---------------------------------------------------------------------------
# create_or_update_journal_entries
# ---------------------------------------------------------------------------


@pytest.fixture
def journal():
    return Journal(
        journal_id="journal-1",
        name="January journal",
        entries=[],
    )


@pytest.fixture
def receipt_path(tmp_path):
    # File must exist so read_bytes() succeeds; contents are irrelevant because
    # OcrUtil.executeWithAnthropic is mocked in every test.
    img = tmp_path / "receipt.jpg"
    img.write_bytes(b"fake-image-data")
    return str(img)


@pytest.fixture
def ocr_entry_data():
    return GeneratedJournalEntry(
        date=datetime.date(2026, 1, 27),
        account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        description="Grocery purchase at Trader Joe's",
        debit=Decimal("32.02"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def ocr_result(ocr_entry_data):
    return GeneratedJournalEntrySet(
        entries=[
            ocr_entry_data,
            GeneratedJournalEntry(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.CASH,
                description="Grocery purchase at Trader Joe's",
                debit=Decimal("0.00"),
                credit=Decimal("32.02"),
            ),
        ]
    )


class TestCreateOrUpdateJournalEntriesForReceipt:
    def test_raises_when_journal_not_found(self, receipt_path):
        with (
            patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[]),
            pytest.raises(ValueError, match="journal-999"),
        ):
            sync_journal_entries_from_receipt("journal-999", receipt_path)

    def test_creates_new_entry_when_no_match(self, journal, receipt_path, ocr_result):
        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=ocr_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry",
                return_value=None,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 2
        descriptions = {e["description"] for e in result["entries"]}
        assert "Grocery purchase at Trader Joe's" in descriptions

    def test_new_entry_gets_fresh_id(self, journal, receipt_path, ocr_result):
        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=ocr_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry",
                return_value=None,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        entry_id = result["entries"][0]["journal_entry_id"]
        assert entry_id is not None
        assert entry_id != ""

    def test_updates_existing_entry_preserving_id(self, receipt_path, ocr_result):
        existing_entry = JournalEntry(
            journal_entry_id="original-id",
            date=datetime.date(2026, 1, 27),
            account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            description="Old description",
            debit=Decimal("30.00"),
            credit=Decimal("0.00"),
        )
        journal = Journal(
            journal_id="journal-1",
            name="January journal",
            entries=[existing_entry],
        )

        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=ocr_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry",
                side_effect=[existing_entry, None],
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 2
        expense = next(
            e
            for e in result["entries"]
            if e["account"] == JournalAccount.NON_ESSENTIALS_EXPENSE.value
        )
        assert expense["journal_entry_id"] == "original-id"
        assert expense["description"] == "Grocery purchase at Trader Joe's"
        assert expense["debit"] == "32.02"

    def test_adds_multiple_entries_from_ocr(self, journal, receipt_path):
        # Double-entry: one debit line and one credit line from the same receipt
        double_entry_result = GeneratedJournalEntrySet(
            entries=[
                GeneratedJournalEntry(
                    date=datetime.date(2026, 1, 27),
                    account=JournalAccount.NON_ESSENTIALS_EXPENSE,
                    description="Grocery purchase at Trader Joe's",
                    debit=Decimal("32.02"),
                    credit=Decimal("0.00"),
                ),
                GeneratedJournalEntry(
                    date=datetime.date(2026, 1, 27),
                    account=JournalAccount.CASH,
                    description="Payment via Visa",
                    debit=Decimal("0.00"),
                    credit=Decimal("32.02"),
                ),
            ]
        )

        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=double_entry_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry",
                return_value=None,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 2

    def test_no_entries_from_ocr_leaves_journal_unchanged(self, journal, receipt_path):
        empty_ocr_result = GeneratedJournalEntrySet(entries=[])

        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=empty_ocr_result,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert result["entries"] == []

    def test_storage_update_called_once(self, journal, receipt_path, ocr_result):
        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=ocr_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry",
                return_value=None,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal") as mock_save,
        ):
            sync_journal_entries_from_receipt("journal-1", receipt_path)

        mock_save.assert_called_once_with(journal, conn)

    def test_returns_journal_as_dict(self, journal, receipt_path, ocr_result):
        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=ocr_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry",
                return_value=None,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert isinstance(result, dict)
        assert "journal_id" in result
        assert "entries" in result

    def test_mixed_new_and_updated_entries(self, receipt_path):
        # The journal already has a GENERAL entry. OCR returns two entries:
        # one GENERAL (matches the existing entry → update, preserve ID) and
        # one CASH (no match → create, gets a new ID).
        existing_entry = JournalEntry(
            journal_entry_id="existing-id",
            date=datetime.date(2026, 1, 27),
            account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            description="Old grocery description",
            debit=Decimal("30.00"),
            credit=Decimal("0.00"),
        )
        journal = Journal(
            journal_id="journal-1",
            name="January journal",
            entries=[existing_entry],
        )
        ocr_result = GeneratedJournalEntrySet(
            entries=[
                GeneratedJournalEntry(
                    date=datetime.date(2026, 1, 27),
                    account=JournalAccount.NON_ESSENTIALS_EXPENSE,
                    description="Grocery purchase at Trader Joe's",
                    debit=Decimal("32.02"),
                    credit=Decimal("0.00"),
                ),
                GeneratedJournalEntry(
                    date=datetime.date(2026, 1, 27),
                    account=JournalAccount.CASH,
                    description="Payment via Visa",
                    debit=Decimal("0.00"),
                    credit=Decimal("32.02"),
                ),
            ]
        )

        def fake_finder(journal_id, entry):
            # Only the GENERAL entry matches the pre-existing journal entry
            return (
                existing_entry if entry.account == JournalAccount.NON_ESSENTIALS_EXPENSE else None
            )

        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=ocr_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry",
                side_effect=fake_finder,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 2
        ids = {e["journal_entry_id"] for e in result["entries"]}
        assert "existing-id" in ids


class TestJournalTools:
    """create/update/list/delete journal tools, against an in-memory database."""

    @pytest.fixture
    def db(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        create_schema(connection)
        with patch("balanceai_backend.servers.bookkeeping_server.conn", connection):
            yield connection
        connection.close()

    def test_create_journal_returns_and_saves_journal(self, db):
        result = create_journal(name="Personal", description="Household books")

        assert result["name"] == "Personal"
        assert result["description"] == "Household books"
        assert result["entries"] == []
        [row] = db.execute("SELECT * FROM journals").fetchall()
        assert row["journal_id"] == result["journal_id"]
        assert row["name"] == "Personal"

    def test_create_journal_description_defaults_to_empty(self, db):
        assert create_journal(name="Personal")["description"] == ""

    def test_create_journal_rejects_duplicate_name_case_insensitively(self, db):
        create_journal(name="Personal")

        with pytest.raises(ValueError, match="already exists"):
            create_journal(name="personal")

        assert len(list_journals()) == 1

    def test_update_journal_changes_only_given_fields(self, db):
        journal_id = create_journal(name="Personal", description="Household books")["journal_id"]

        result = update_journal(journal_id, name="Home")

        assert result["name"] == "Home"
        assert result["description"] == "Household books"

    def test_update_journal_rejects_name_used_by_another_journal(self, db):
        create_journal(name="Personal")
        journal_id = create_journal(name="My LLC")["journal_id"]

        with pytest.raises(ValueError, match="already exists"):
            update_journal(journal_id, name="PERSONAL")

    def test_update_journal_allows_keeping_its_own_name(self, db):
        journal_id = create_journal(name="Personal")["journal_id"]

        result = update_journal(journal_id, name="Personal", description="Household")

        assert result["description"] == "Household"

    def test_update_journal_raises_when_not_found(self, db):
        with pytest.raises(ValueError, match="not found"):
            update_journal("missing", name="Home")

    def test_list_journals_returns_all_without_entries(self, db):
        create_journal(name="Personal")
        create_journal(name="My LLC")

        result = list_journals()

        assert {j["name"] for j in result} == {"Personal", "My LLC"}
        assert all(j["entries"] == [] for j in result)

    def test_delete_journal_removes_it(self, db):
        journal_id = create_journal(name="Personal")["journal_id"]

        assert delete_journal(journal_id) == {"journal_id": journal_id}
        assert list_journals() == []
