"""Reddit collector.

Preferred: official API with an app-only token (set REDDIT_CLIENT_ID and
REDDIT_CLIENT_SECRET). Fallback: public JSON endpoints, which Reddit often
blocks from cloud IPs such as GitHub Actions, so failures are tolerated.
"""
import os
import time

import requests

from ..models import Post
from ..util import log, safe_err, session

UA = "script:ai-lead-radar:v1.0 (personal lead research)"


def _token(s: requests.Session):
    cid = os.environ.get("REDDIT_CLIENT_ID")
    secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return None
    r = s.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(cid, secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": UA},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def collect(cfg: dict, since_ts: float) -> tuple[list[Post], list[str]]:
    rcfg = cfg["sources"]["reddit"]
    s = session()
    s.headers["User-Agent"] = UA
    notes: list[str] = []
    posts: list[Post] = []

    token = None
    try:
        token = _token(s)
    except Exception as e:  # noqa: BLE001
        notes.append(f"reddit token failed ({safe_err(e)}), using public endpoints")

    base = "https://oauth.reddit.com" if token else "https://www.reddit.com"
    if token:
        s.headers["Authorization"] = f"bearer {token}"

    failed = 0
    for sub in rcfg["subreddits"]:
        url = f"{base}/r/{sub}/new" + ("" if token else ".json")
        try:
            r = s.get(url, params={"limit": rcfg.get("per_subreddit_limit", 60), "raw_json": 1}, timeout=30)
            r.raise_for_status()
            children = r.json()["data"]["children"]
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"reddit r/{sub}: {safe_err(e)}")
            time.sleep(1)
            continue
        for c in children:
            d = c["data"]
            created = float(d.get("created_utc", 0))
            if created < since_ts:
                continue
            posts.append(Post(
                id=f"reddit:{d['id']}",
                source="reddit",
                title=d.get("title", ""),
                text=d.get("selftext", ""),
                url="https://www.reddit.com" + d.get("permalink", ""),
                author=d.get("author", ""),
                created_utc=created,
                meta={"subreddit": sub, "flair": d.get("link_flair_text") or ""},
            ))
        time.sleep(1)  # be polite

    if failed:
        notes.append(f"reddit: {failed}/{len(rcfg['subreddits'])} subreddits failed"
                     + ("" if token else " (add REDDIT_CLIENT_ID/SECRET to fix blocking)"))
    return posts, notes
