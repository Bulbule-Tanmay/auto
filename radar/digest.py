"""Formats the Telegram morning digest."""
from datetime import datetime, timedelta, timezone

from .models import Lead
from .util import clip, esc, short_id

IST = timezone(timedelta(hours=5, minutes=30))
URGENCY_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}
SOURCE_LABEL = {"reddit": "Reddit", "freelancer": "Freelancer", "rss": "Forum/RSS", "search": "Web search"}


def header(n_leads: int, scanned: int, stats: dict, notes: list[str]) -> str:
    today = datetime.now(IST).strftime("%a, %d %b %Y")
    per_src = ", ".join(f"{SOURCE_LABEL.get(k, k)} {v}" for k, v in stats.items() if v) or "none"
    lines = [
        f"☀️ <b>AI Lead Radar</b> · {today}",
        f"<b>{n_leads}</b> lead{'s' if n_leads != 1 else ''} today · {scanned} new posts scanned",
        f"Sources: {esc(per_src)}",
    ]
    if notes:
        lines.append("")
        lines.append("⚠️ " + esc("; ".join(notes)))
    if n_leads:
        lines.append("")
        lines.append("Review each draft, edit it, and send it yourself. Tap 👍/👎 so tomorrow's picks get better.")
    return "\n".join(lines)


def lead_message(rank: int, lead: Lead) -> tuple[str, list[list[dict]], str]:
    p = lead.post
    sid = short_id(p.id)
    parts = [
        f"<b>#{rank} · {esc(lead.service_name)}</b> · score {lead.score} · "
        f"{URGENCY_ICON.get(lead.urgency, '🟡')} {esc(lead.urgency)}",
        f"📌 {esc(clip(lead.summary, 300))}",
    ]
    meta = [SOURCE_LABEL.get(p.source, p.source)]
    if p.meta.get("subreddit"):
        meta[0] += f" r/{p.meta['subreddit']}"
    if lead.location:
        meta.append(f"📍 {lead.location}")
    budget = lead.budget_clue or p.meta.get("budget", "")
    if budget:
        meta.append(f"💰 {budget}")
    if p.meta.get("unverified"):
        meta.append("⚠️ from web search, verify the post")
    parts.append(esc(" · ".join(meta)))
    if lead.reason:
        parts.append(f"<i>{esc(clip(lead.reason, 200))}</i>")
    parts.append("")
    parts.append("<b>Draft reply:</b>")
    parts.append(f"<blockquote>{esc(clip(lead.draft, 1400))}</blockquote>")

    buttons = [
        [{"text": "🔗 Open post", "url": p.url}],
        [{"text": "👍 Good lead", "callback_data": f"g:{sid}"},
         {"text": "👎 Bad lead", "callback_data": f"b:{sid}"}],
    ]
    return "\n".join(parts), buttons, sid
