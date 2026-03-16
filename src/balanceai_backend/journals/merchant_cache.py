import json
from pathlib import Path

_CACHE_PATH = Path(__file__).parent.parent / "data" / "merchant_cache.json"


def load_merchant_context_cache() -> dict:
    if not _CACHE_PATH.exists():
        return {}
    with open(_CACHE_PATH) as f:
        return json.load(f)


def save_merchant_context_cache(data: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CACHE_PATH, "w") as f:
        json.dump(data, f, indent=2)
