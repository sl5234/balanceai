"""Where the backend keeps its secrets and local data: outside this package
folder, so tools that scan it (black, mypy, pytest) never touch them."""

import os
from pathlib import Path

SECRETS_DIR = Path(__file__).parent.parent / "balanceai_backend_secrets"

# Receipt images for upload_receipt. Inside the secrets folder by default, which
# Claude Code is denied, so the assistant can't open them; upload_receipt reads
# only from here. BALANCEAI_RECEIPTS_DIR points elsewhere, e.g. for tests.
RECEIPTS_DIR = Path(os.environ.get("BALANCEAI_RECEIPTS_DIR") or SECRETS_DIR / "receipts")
