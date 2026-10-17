"""Entry point.

    python -m radar run [--dry-run] [--sample] [--mock-ai]
    python -m radar feedback
"""
import argparse
import os
import sys
import time

import yaml

from . import digest, state as state_mod, telegram
from .classify import classify
from .gemini import GeminiError
from .models import Post
from .prefilter import plausible
from .sources import beatapi, discovery, reddit, rss
from .util import clip, log, safe_err, short_id

CONFIG_PATH = os.environ.get("RADAR_CONFIG", "config/services.yaml")

SOURCES = {
    "reddit": reddit.collect,
    "beatapi": beatapi.collect,
    "rss": rss.collect,
    "search_discovery": discovery.collect,
}
STAT_KEY = {"search_discovery": "search"}


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# --------------------------------------------------------------------------- feedback
def process_feedback(st: dict) -> int:
    """Read 👍/👎 button presses from Telegram and store them as memory."""
    owner = str(os.environ.get("TELEGRAM_CHAT_ID", ""))
    handled = 0
    try:
        updates = telegram.get_updates(st["tg_offset"])
    except telegram.TelegramError as e:
        log(f"feedback fetch failed: {e}")
        return 0
    for u in updates:
        st["tg_offset"] = max(st["tg_offset"], u["update_id"] + 1)
        cb = u.get("callback_query")
        if not cb:
            continue
        # Only accept button presses from the owner's chat
        if str(cb.get("from", {}).get("id")) != owner:
            continue
        data = cb.get("data", "")
        if data == "noop" or ":" not in data:
            telegram.answer_callback(cb["id"], "")
            continue
        verdict_key, sid = data.split(":", 1)
        verdict = "good" if verdict_key == "g" else "bad"
        info = st["sent"].get(sid)
        if info:
            st["feedback"].append({
                "verdict": verdict, "service": info.get("service", ""), "source": info.get("source", ""),
                "summary": info.get("summary", ""), "ts": time.time(),
            })
            handled += 1
        telegram.answer_callback(cb["id"], "Saved 👍" if verdict == "good" else "Saved 👎")
        msg = cb.get("message") or {}
        if msg:
            telegram.mark_message(msg["chat"]["id"], msg["message_id"],
                                  "✅ Marked good" if verdict == "good" else "❌ Marked bad",
                                  (info or {}).get("url"))
    return handled


# --------------------------------------------------------------------------- run
def sample_posts() -> list[Post]:
    t = time.time() - 3600
    return [
        Post("reddit:s1", "reddit", "Looking for someone to run Facebook ads for my skincare brand",
             "We sell in India, spending about 50k/month, ROAS is bad. Need an expert, budget flexible.",
             "https://reddit.com/r/test/s1", created_utc=t, meta={"subreddit": "smallbusiness"}),
        Post("reddit:s2", "reddit", "[For Hire] Web developer available for projects",
             "I build WordPress sites. DM me.", "https://reddit.com/r/test/s2", created_utc=t,
             meta={"subreddit": "forhire"}),
        Post("beatapi:s3", "beatapi", "Need a developer to automate WhatsApp lead replies using n8n",
             "Looking for someone who can build a WhatsApp bot that qualifies leads and updates Google Sheets.",
             "https://www.linkedin.com/posts/s3", created_utc=t, meta={"platform": "linkedin.com", "unverified": True}),
        Post("reddit:s4", "reddit", "What is your favourite SEO tool?", "Just curious what everyone uses.",
             "https://reddit.com/r/test/s4", created_utc=t, meta={"subreddit": "SEO"}),
    ]


def run(args) -> int:
    cfg = load_config()
    st = state_mod.load()
    owner_chat_ok = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))
    sending = owner_chat_ok and not args.dry_run

    if sending:
        n = process_feedback(st)
        log(f"feedback processed: {n}")

    since = time.time() - cfg.get("lookback_hours", 26) * 3600
    stats: dict[str, int] = {}
    notes: list[str] = []
    posts: list[Post] = []

    if args.sample:
        posts = sample_posts()
        stats = {"reddit": 3, "beatapi": 1}
    else:
        for name, fn in SOURCES.items():
            if not cfg["sources"].get(name, {}).get("enabled"):
                continue
            try:
                got, n = fn(cfg, since)
            except Exception as e:  # noqa: BLE001
                notes.append(f"{name} failed ({safe_err(e)})")
                log(f"{name} failed: {safe_err(e)}")
                continue
            notes += n
            stats[STAT_KEY.get(name, name)] = len(got)
            posts += got
            log(f"{name}: {len(got)} posts")

    # dedupe: against memory and within this batch (by id and url)
    uniq: dict[str, Post] = {}
    seen_urls: set[str] = set()
    for p in sorted(posts, key=lambda x: -x.created_utc):
        if p.id in st["seen"] or p.id in uniq or p.url in seen_urls:
            continue
        uniq[p.id] = p
        seen_urls.add(p.url)
    fresh = list(uniq.values())

    candidates = [p for p in fresh if plausible(p)][: cfg.get("max_posts_to_ai", 120)]
    log(f"fresh={len(fresh)} candidates={len(candidates)}")

    try:
        leads = classify(candidates, cfg, st, mock=args.mock_ai) if candidates else []
    except (GeminiError, Exception) as e:  # noqa: BLE001
        msg = f"❌ <b>AI Lead Radar</b>: AI step failed ({safe_err(e)}: {str(e)[:200]}). Will retry next run."
        log(msg)
        if sending:
            try:
                telegram.send(msg)
            except telegram.TelegramError:
                pass
            state_mod.save(st)
        return 1

    leads = [l for l in leads if l.score >= cfg.get("min_score", 55)]
    leads.sort(key=lambda l: (-l.score, {"high": 0, "medium": 1, "low": 2}.get(l.urgency, 1)))
    leads = leads[: cfg.get("max_leads_per_day", 10)]

    # ---- deliver
    head = digest.header(len(leads), len(fresh), stats, notes)
    messages = [digest.lead_message(i, l) for i, l in enumerate(leads, 1)]

    if args.dry_run or not owner_chat_ok:
        print(head, "\n")
        for text, _, sid in messages:
            print(text, f"\n[buttons: open / good:{sid} / bad:{sid}]\n" + "-" * 60)
        if not args.dry_run:
            log("Telegram secrets missing: printed instead of sending.")
        return 0

    try:
        telegram.send(head)
        for lead, (text, buttons, sid) in zip(leads, messages):
            telegram.send(text, buttons)
            st["sent"][sid] = {
                "service": lead.service_name, "source": lead.post.source,
                "summary": clip(lead.summary, 200), "url": lead.post.url, "ts": time.time(),
            }
            time.sleep(0.5)
    except telegram.TelegramError as e:
        log(f"telegram send failed: {e}")
        state_mod.save(st)   # keep feedback progress; posts stay unseen so they retry
        return 1

    # everything we evaluated is now "seen" so it is never processed twice
    now = time.time()
    for p in fresh:
        st["seen"][p.id] = now
    state_mod.save(st)
    return 0


def feedback_only() -> int:
    st = state_mod.load()
    n = process_feedback(st)
    state_mod.save(st)
    log(f"feedback processed: {n}")
    return 0


def cli() -> None:
    ap = argparse.ArgumentParser(prog="radar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="collect, classify and send the digest")
    r.add_argument("--dry-run", action="store_true", help="print instead of sending to Telegram")
    r.add_argument("--sample", action="store_true", help="use built-in sample posts (no network)")
    r.add_argument("--mock-ai", action="store_true", help="skip Gemini, use a dumb local stand-in")
    sub.add_parser("feedback", help="only collect 👍/👎 button presses")
    args = ap.parse_args()
    sys.exit(run(args) if args.cmd == "run" else feedback_only())
