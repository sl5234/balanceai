"""Where the backend keeps its secrets and local data: outside this package
folder, so tools that scan it (black, mypy, pytest) never touch them."""

from pathlib import Path

SECRETS_DIR = Path(__file__).parent.parent / "balanceai_backend_secrets"
