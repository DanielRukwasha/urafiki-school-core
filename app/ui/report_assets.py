"""Embed trusted local images; PDF generation never fetches arbitrary URLs."""

import base64
from pathlib import Path

from flask import current_app

from app.ui.theming import safe_asset_url


def inline_report_logo(url):
    url = safe_asset_url(url)
    prefix = (current_app.static_url_path or "/static").rstrip("/") + "/"
    if not url or not url.startswith(prefix):
        return None
    root = Path(current_app.static_folder).resolve()
    path = (root / url[len(prefix) :]).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 2_000_000:
        return None
    content = path.read_bytes()
    mime = None
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif content.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        mime = "image/webp"
    if mime is None:
        return None
    return "data:" + mime + ";base64," + base64.b64encode(content).decode("ascii")
