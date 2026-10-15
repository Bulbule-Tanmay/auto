"""Generic RSS/Atom collector for forums, communities and job boards."""
import calendar
import time

import feedparser

from ..models import Post
from ..util import log, safe_err


def collect(cfg: dict, since_ts: float) -> tuple[list[Post], list[str]]:
    feeds = cfg["sources"]["rss"].get("feeds") or []
    posts: list[Post] = []
    notes: list[str] = []
    for url in feeds:
        try:
            d = feedparser.parse(url, agent="Mozilla/5.0 (AILeadRadar)")
            if d.bozo and not d.entries:
                raise ValueError("unreadable feed")
        except Exception as e:  # noqa: BLE001
            notes.append(f"rss feed failed: {url} ({safe_err(e)})")
            log(f"rss {url}: {safe_err(e)}")
            continue
        for e in d.entries:
            t = e.get("published_parsed") or e.get("updated_parsed")
            created = calendar.timegm(t) if t else time.time()
            if created < since_ts:
                continue
            link = e.get("link", "")
            posts.append(Post(
                id=f"rss:{e.get('id') or link}",
                source="rss",
                title=e.get("title", ""),
                text=e.get("summary", ""),
                url=link,
                author=e.get("author", ""),
                created_utc=created,
                meta={"feed": d.feed.get("title", url)},
            ))
    return posts, notes
