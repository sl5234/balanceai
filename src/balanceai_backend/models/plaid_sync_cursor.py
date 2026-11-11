import datetime
from dataclasses import dataclass, field


@dataclass
class PlaidSyncCursor:
    """Sync progress for one Plaid item — a bookmark into that item's
    /transactions/sync change stream. Written on every sync call, unlike
    PlaidItem which is set once at link time and rarely changes."""

    item_id: str
    cursor: str
    last_synced_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat()
    )
    # Set by the database when saved (UTC ISO 8601); ignored when saving.
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "cursor": self.cursor,
            "last_synced_at": self.last_synced_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlaidSyncCursor":
        return cls(**d)
