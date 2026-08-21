import datetime
import json
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
    plaid_account_ids: list[str] = field(default_factory=list)
    our_account_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "access_token": self.access_token,
            "institution_id": self.institution_id,
            "institution_name": self.institution_name,
            "plaid_account_ids": self.plaid_account_ids,
            "our_account_ids": self.our_account_ids,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlaidItem":
        d = dict(d)
        for key in ("plaid_account_ids", "our_account_ids"):
            if isinstance(d.get(key), str):
                d[key] = json.loads(d[key])
            elif d.get(key) is None:
                d[key] = []
        return cls(**d)
