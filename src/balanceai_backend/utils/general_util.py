import csv
from pathlib import Path

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
