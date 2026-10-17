"""BeatAPI web-search collector.

Uses BeatAPI's Web Search endpoint (POST https://api.beatapi.io/v1/web/search) to find
recent public posts where someone asks for one of your services, limited to the
platforms listed in config (Reddit, LinkedIn, X, Quora, Facebook, Upwork...).

Needs one secret: BEATAPI_API_KEY (https://beatapi.io/dashboard/apikeys).
Cost: $0.005 per successful search call. One call = one service x one platform group.

Search results are leads, not evidence, so every post is flagged "unverified" and
still goes through the normal AI filter.
"""
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from ..models import Post
from ..util import clip, log, session

API = "https://api.beatapi.io/v1/web/search"
FATAL_STATUSES = {400, 401, 402, 403}   # fix the request / key / balance: retrying cannot help
RETRY_STATUSES = {429, 500, 503}


class BeatAPIError(Exception):
    def __init__(self, msg: str, fatal: bool = False):
        super().__init__(msg)
        self.fatal = fatal


def _parse_time(value) -> float | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _error_text(r: requests.Response) -> str:
    """Short description of an API error body. Never includes the key (it is only in a header)."""
    try:
        err = r.json().get("error", {})
        return f"{err.get('code', '')} {err.get('message', '')}".strip()[:200]
    except Exception:  # noqa: BLE001
        return " ".join(r.text.split())[:200]


def _search(s: requests.Session, body: dict, retries: int = 3) -> dict:
    delay = 3.0
    last = "unknown error"
    for attempt in range(retries):
        try:
            r = s.post(API, json=body, timeout=40)
        except requests.RequestException as e:
            last = type(e).__name__
        else:
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    last = "invalid JSON in response"
            elif r.status_code in FATAL_STATUSES:
                raise BeatAPIError(f"HTTP {r.status_code} {_error_text(r)}", fatal=True)
            else:
                last = f"HTTP {r.status_code} {_error_text(r)}"
                if r.status_code == 429:
                    try:
                        delay = min(float(r.json().get("error", {}).get("retry_after_seconds", delay)), 30)
                    except Exception:  # noqa: BLE001
                        pass
        if attempt < retries - 1:
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise BeatAPIError(f"failed after {retries} tries ({last})")


def collect(cfg: dict, since_ts: float) -> tuple[list[Post], list[str]]:
    bcfg = cfg["sources"]["beatapi"]
    key = os.environ.get("BEATAPI_API_KEY", "").strip()
    if not key:
        return [], ["beatapi skipped: BEATAPI_API_KEY secret is not set"]

    s = session()
    s.headers.update({"Authorization": f"Bearer {key}", "Content-Type": "application/json"})

    groups = bcfg.get("platform_groups") or [["reddit.com"]]
    allowed = {d.lower() for g in groups for d in g} | {"twitter.com"}
    time_range = bcfg.get("time_range", "week")
    max_results = int(bcfg.get("max_results", 10))

    posts: dict[str, Post] = {}
    notes: list[str] = []
    calls = failed = streak = 0
    last_reason = ""
    stop = False

    for svc in cfg["services"]:
        if stop:
            break
        queries = svc.get("beatapi_queries") or [f"looking for {svc['name']} expert"]
        for q in queries:
            if stop:
                break
            for group in groups:
                calls += 1
                body = {
                    "query": clip(q, 400),
                    "type": "web",
                    "max_results": max(1, min(max_results, 10)),
                    "time_range": time_range,
                    "include_domains": group[:10],
                }
                try:
                    data = _search(s, body)
                    streak = 0
                except BeatAPIError as e:
                    failed += 1
                    streak += 1
                    last_reason = str(e)
                    log(f"beatapi {svc['id']} {group}: {last_reason}")
                    if e.fatal or streak >= 3:   # bad key / no balance / outage: stop spending time
                        stop = True
                        break
                    continue

                for it in data.get("results") or []:
                    if not isinstance(it, dict):
                        continue
                    url = (it.get("url") or "").strip()
                    host = (urlparse(url).hostname or "").lower()
                    if not url.startswith("http") or not any(host == a or host.endswith("." + a) for a in allowed):
                        continue
                    published = _parse_time(it.get("published_at"))
                    if published is not None and published < since_ts:
                        continue   # clearly older than the lookback window
                    posts[f"beatapi:{url}"] = Post(
                        id=f"beatapi:{url}",
                        source="beatapi",
                        title=clip(it.get("title", ""), 200),
                        text=it.get("snippet", "") or "",
                        url=url,
                        created_utc=published or time.time(),
                        meta={"platform": host.removeprefix("www."), "service_hint": svc["id"],
                              "unverified": True},
                    )
                time.sleep(0.5)

    if failed:
        skipped = "stopped early; " if stop else ""
        notes.append(f"beatapi: {failed}/{calls} searches failed, {skipped}last error: {last_reason}")
    return list(posts.values()), notes
