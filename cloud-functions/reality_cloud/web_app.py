"""Static application pages for the administrator workflow."""

from __future__ import annotations

from html import escape
from pathlib import Path

_WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def render_app_page(page: str, resource_id: str = "") -> str:
    if page not in {"home", "start", "session", "proof"}:
        raise ValueError("unsupported application page")
    titles = {
        "home": "Reality Authenticator",
        "start": "証明を開始",
        "session": "セッション状態",
        "proof": "証明書",
    }
    template = (_WEB_ROOT / "app.html").read_text(encoding="utf-8")
    return (
        template.replace("$title", escape(titles[page]))
        .replace("$page", escape(page, quote=True))
        .replace("$resource_id", escape(resource_id, quote=True))
    )


def load_app_asset(filename: str) -> str:
    if filename not in {"app.css", "app.js"}:
        raise ValueError("unsupported application asset")
    return (_WEB_ROOT / filename).read_text(encoding="utf-8")
