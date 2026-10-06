import datetime
from dataclasses import dataclass, field


@dataclass
class PlaidItem:
    """A linked bank connection's identity: which institution, and the credential
    to call Plaid with. Sync progress (the cursor) is tracked separately in
    PlaidSyncCursor, since it changes on every sync call while this stays static."""

    item_id: str
    access_token: str
    institution_id: str | None = None
    institution_name: str | None = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "access_token": self.access_token,
            "institution_id": self.institution_id,
            "institution_name": self.institution_name,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlaidItem":
        return cls(**d)
