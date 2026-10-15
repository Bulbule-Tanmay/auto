"""Freelancer.com collector using the public projects API.

Works without a token for active projects. If you have a token, set
FREELANCER_TOKEN to raise limits.
"""
import os
import time

from ..models import Post
from ..util import log, safe_err, session

API = "https://www.freelancer.com/api/projects/0.1/projects/active/"


def collect(cfg: dict, since_ts: float) -> tuple[list[Post], list[str]]:
    fcfg = cfg["sources"]["freelancer"]
    s = session()
    token = os.environ.get("FREELANCER_TOKEN")
    if token:
        s.headers["freelancer-oauth-v1"] = token

    posts: dict[str, Post] = {}
    notes: list[str] = []
    failed = 0
    for q in fcfg["queries"]:
        try:
            r = s.get(API, params={
                "query": q,
                "limit": fcfg.get("limit_per_query", 30),
                "full_description": "true",
                "compact": "true",
                "sort_field": "time_submitted",
            }, timeout=30)
            r.raise_for_status()
            projects = r.json()["result"]["projects"]
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"freelancer '{q}': {safe_err(e)}")
            continue
        for p in projects:
            created = float(p.get("time_submitted", 0))
            if created < since_ts:
                continue
            pid = p["id"]
            budget = p.get("budget") or {}
            cur = (p.get("currency") or {}).get("code", "")
            budget_txt = ""
            if budget.get("minimum") or budget.get("maximum"):
                budget_txt = f"{budget.get('minimum', '?')}-{budget.get('maximum', '?')} {cur}".strip()
            posts[f"freelancer:{pid}"] = Post(
                id=f"freelancer:{pid}",
                source="freelancer",
                title=p.get("title", ""),
                text=p.get("description", "") or p.get("preview_description", ""),
                url=f"https://www.freelancer.com/projects/{p.get('seo_url', pid)}",
                created_utc=created,
                meta={"budget": budget_txt, "bids": (p.get("bid_stats") or {}).get("bid_count", "")},
            )
        time.sleep(0.5)
    if failed:
        notes.append(f"freelancer: {failed}/{len(fcfg['queries'])} queries failed")
    return list(posts.values()), notes
