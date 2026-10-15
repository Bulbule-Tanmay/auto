"""Discovery of public posts via Google Search (through Gemini grounding).

Reddit, LinkedIn, X, Quora, Facebook and Upwork either block scraping or need
paid/approved API access, so instead we ask Gemini (with Google Search) to find
recent public posts where someone asks for a service. Coverage is partial: only
content Google has indexed. Results are flagged as unverified and still pass
through the normal AI filter.

Each service is searched once per platform group in config (one call each).
"""
import time
from urllib.parse import urlparse

from ..gemini import generate, parse_json
from ..models import Post
from ..util import clip, log, safe_err

PROMPT = """Use Google Search to find PUBLIC posts from roughly the last 24-48 hours
where a business owner or founder is asking to HIRE or get recommendations for:
{service_name} ({description}).

Only look on these sites: {platforms}. (For example, use the site: operator.)
Prefer posts from India but include global ones if clearly a real buyer request.
Posts may be in English or Hinglish. Ignore freelancers advertising themselves,
job seekers, and promotional posts.

Return ONLY a JSON array (max 8 items). Each item:
{{"title": "...", "snippet": "what the person is asking for", "url": "direct URL to the post", "platform": "site name", "posted": "approx date or 'unknown'"}}

Rules: only include items you actually found in search results, with their real
URL. Never invent posts or URLs. If you find nothing, return [].
"""


def _groups(scfg: dict) -> list[list[str]]:
    groups = scfg.get("platform_groups")
    if groups:
        return groups
    return [scfg.get("platforms", ["linkedin.com", "x.com"])]   # old config format


def collect(cfg: dict, since_ts: float) -> tuple[list[Post], list[str]]:
    scfg = cfg["sources"]["search_discovery"]
    groups = _groups(scfg)
    allowed = tuple({d for g in groups for d in g} | {"twitter.com"})
    posts: dict[str, Post] = {}
    notes: list[str] = []
    total = failed = 0

    for svc in cfg["services"]:
        for group in groups:
            total += 1
            prompt = PROMPT.format(
                service_name=svc["name"],
                description=" ".join(svc["description"].split()),
                platforms=", ".join(group),
            )
            try:
                items = parse_json(generate(prompt, search=True, temperature=0.2))
                if not isinstance(items, list):
                    items = []
            except Exception as e:  # noqa: BLE001
                failed += 1
                log(f"discovery {svc['id']} {group}: {safe_err(e)}")
                time.sleep(5)
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                url = (it.get("url") or "").strip()
                host = (urlparse(url).hostname or "").lower()
                if not url.startswith("http") or not any(host == a or host.endswith("." + a) for a in allowed):
                    continue
                platform = host.removeprefix("www.")
                posts[f"search:{url}"] = Post(
                    id=f"search:{url}",
                    source="search",
                    title=clip(it.get("title", ""), 200),
                    text=it.get("snippet", ""),
                    url=url,
                    created_utc=time.time(),   # real post time unknown
                    meta={"platform": platform, "posted": it.get("posted", "unknown"),
                          "unverified": True},
                )
            time.sleep(6)  # stay under free-tier rate limits
    if failed:
        notes.append(f"search discovery: {failed}/{total} queries failed")
    return list(posts.values()), notes
