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
