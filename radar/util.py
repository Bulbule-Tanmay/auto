import hashlib
import html
import sys
import time

import requests

USER_AGENT = "Mozilla/5.0 (compatible; AILeadRadar/1.0; personal lead research)"


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def safe_err(e: Exception) -> str:
    """Describe an exception WITHOUT leaking URLs (Telegram URLs contain the bot token)."""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code}"
    return type(e).__name__


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def short_id(post_id: str) -> str:
    return hashlib.sha1(post_id.encode()).hexdigest()[:10]


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def now() -> float:
    return time.time()
