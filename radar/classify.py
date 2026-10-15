"""AI intent detection: decides which posts are real buyers, scores them, drafts replies."""
import time

from .gemini import GeminiError, generate, parse_json
from .models import Lead, Post
from .prefilter import INTENT
from .util import clip, log

BATCH = 8
PAUSE_SECONDS = 7   # keeps us under free-tier requests-per-minute

PROMPT = """You are the lead-qualification engine for {owner_name}'s digital services business.

ABOUT THE BUSINESS
{about}

SERVICES (only these count):
{services}

TASK
For each post below, decide whether the author is a REAL potential client looking to
hire someone / get a quote / get a recommendation for one of the services above.
Posts may be in English or Hinglish (Hindi written in English letters).

REJECT (is_lead=false) when the post is:
- a freelancer or agency advertising themselves, or a job seeker
- asking how to DIY, a tutorial, or general advice with no intent to hire
- a student/learner question, a rant, news, or discussion
- spam, promotion, or about a service we do not offer
- an employment offer for a full-time salaried role (project/contract work is fine)
Be strict. Fewer, better leads. Posts marked "unverified" came from web search;
judge only by the snippet and be conservative.

SCORING (0-100): clear buying intent + fit with a service + urgency + budget signals + recency.
90+ = explicit ask with budget/urgency; 70-89 = clear ask; 55-69 = plausible; below 55 = weak.

DRAFT REPLY (only when is_lead=true)
Style: {reply_style}
Write in the same language as the post (English, or Hinglish if the post is Hinglish).
Plain text, no markdown, no emojis, no placeholders like [Name]. Never invent claims,
case studies or numbers about us.
{memory}
Return ONLY a JSON array with one object per post, in the same order:
{{"id": "<post id as given>", "is_lead": true|false, "service_id": "<one of: {service_ids}>",
 "summary": "<one line: what they need>", "urgency": "high|medium|low",
 "budget_clue": "<budget if mentioned, else ''>", "location": "<city/country if known, else ''>",
 "score": <0-100>, "reason": "<short reason for the score or rejection>",
 "draft": "<reply draft, or '' if not a lead>"}}

POSTS
{posts}
"""


def _services_block(cfg: dict) -> str:
    out = []
    for s in cfg["services"]:
        out.append(f"- id={s['id']} | {s['name']}: {' '.join(s['description'].split())} "
                   f"Ideal client: {' '.join(s['ideal_client'].split())}")
    return "\n".join(out)


def _memory_block(state: dict) -> str:
    fb = state.get("feedback", [])
    good = [f for f in fb if f["verdict"] == "good"][-6:]
    bad = [f for f in fb if f["verdict"] == "bad"][-6:]
    if not good and not bad:
        return ""
    lines = ["\nOWNER FEEDBACK FROM PAST LEADS (learn from this):"]
    if good:
        lines.append("Leads the owner LIKED:")
        lines += [f"- [{f.get('service', '')}] {clip(f.get('summary', ''), 140)}" for f in good]
    if bad:
        lines.append("Leads the owner DISLIKED (avoid similar ones):")
        lines += [f"- [{f.get('service', '')}] {clip(f.get('summary', ''), 140)}" for f in bad]
    return "\n".join(lines) + "\n"


def _post_block(posts: list[Post]) -> str:
    chunks = []
    for p in posts:
        extra = ", ".join(f"{k}={v}" for k, v in p.meta.items() if v not in ("", None))
        chunks.append(
            f"--- POST id={p.id}\nsource: {p.source} {('(' + extra + ')') if extra else ''}\n"
            f"title: {clip(p.title, 200)}\ntext: {clip(p.text, 1200)}"
        )
    return "\n".join(chunks)


def _mock(posts: list[Post], cfg: dict) -> list[Lead]:
    """Offline stand-in for the AI, used only by --mock-ai for testing the pipeline."""
    leads = []
    for p in posts:
        if not INTENT.search(f"{p.title} {p.text}"):
            continue
        blob = f"{p.title} {p.text}".lower()
        svc = next((s for s in cfg["services"]
                    if any(w in blob for w in s["name"].lower().split())), cfg["services"][0])
        leads.append(Lead(p, svc["id"], svc["name"], clip(p.title, 120), "medium", "", "", 70,
                          "mock classifier", "Hi, saw your post and would be glad to help. Happy to chat quickly?"))
    return leads


def classify(posts: list[Post], cfg: dict, state: dict, mock: bool = False) -> list[Lead]:
    if mock:
        return _mock(posts, cfg)

    svc_by_id = {s["id"]: s for s in cfg["services"]}
    by_id = {p.id: p for p in posts}
    leads: list[Lead] = []

    for i in range(0, len(posts), BATCH):
        batch = posts[i:i + BATCH]
        prompt = PROMPT.format(
            owner_name=cfg["owner"]["name"],
            about=" ".join(cfg["owner"]["about"].split()),
            services=_services_block(cfg),
            reply_style=" ".join(cfg["owner"]["reply_style"].split()),
            memory=_memory_block(state),
            service_ids=", ".join(svc_by_id),
            posts=_post_block(batch),
        )
        raw = generate(prompt, json_mode=True, temperature=0.2)
        results = parse_json(raw)
        if isinstance(results, dict):
            results = results.get("results", [])
        for r in results:
            p = by_id.get(r.get("id"))
            if not p or not r.get("is_lead"):
                continue
            sid = r.get("service_id")
            if sid not in svc_by_id:
                continue
            try:
                score = int(r.get("score", 0))
            except (TypeError, ValueError):
                score = 0
            leads.append(Lead(
                post=p,
                service_id=sid,
                service_name=svc_by_id[sid]["name"],
                summary=str(r.get("summary", "")).strip(),
                urgency=str(r.get("urgency", "medium")).lower(),
                budget_clue=str(r.get("budget_clue", "")).strip(),
                location=str(r.get("location", "")).strip(),
                score=max(0, min(100, score)),
                reason=str(r.get("reason", "")).strip(),
                draft=str(r.get("draft", "")).strip(),
            ))
        log(f"classified {min(i + BATCH, len(posts))}/{len(posts)}")
        if i + BATCH < len(posts):
            time.sleep(PAUSE_SECONDS)
    return leads
