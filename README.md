# AI Lead Radar

Every morning (about 8:30 AM IST) this finds people who are asking for your services
(Meta Ads, SEO, web development, AI automation), has Gemini filter out the noise, writes a
draft reply for each real lead, and sends a ranked digest to your Telegram.
**Nothing is ever sent to anyone automatically.** You review, edit and send each reply yourself.

It runs free on GitHub Actions. There is no server and no PC needs to be on.

## How it works

1. **Collect** posts from the last ~24h: Freelancer.com (API), optional RSS feeds, and
   Gemini + Google Search discovery of public Reddit / LinkedIn / X / Quora / Facebook / Upwork posts.
   No Reddit or other platform API keys are needed.
2. **Pre-filter** with cheap keywords (English + Hinglish) so only plausible posts reach the AI.
3. **AI intent detection** (Gemini free tier): real buyer or not, which service, urgency,
   budget clue, location, score 0-100, and a reply draft in the post's language.
4. **Telegram digest**: top 10 leads, each with the post link, summary, and draft.
5. **Learn**: tap 👍 Good lead / 👎 Bad lead under each lead. Your taps are saved and shown
   to the AI as examples next time, so picks improve.
6. **Never repeats**: seen posts are remembered for 30 days.

## One-time setup (about 10 minutes)

### 1. Make the repo private
Settings -> General -> Danger Zone -> Change visibility -> Private.
The memory file lists the leads you were sent, so keep it private.

### 2. Get your secrets
| Secret | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram -> @BotFather -> `/newbot` |
| `TELEGRAM_CHAT_ID` | Message your bot once (send `/start`), then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `chat.id` |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey |

Optional: `FREELANCER_TOKEN` gives higher limits on the Freelancer.com API (not required).

### 3. Add them to GitHub
Repo -> Settings -> Secrets and variables -> Actions -> **New repository secret**, one per row above.
Never put keys in code or in this README.

### 4. Turn it on
Repo -> Actions tab -> enable workflows if asked -> **Daily Lead Radar** -> **Run workflow**.
Within a couple of minutes your first digest should arrive on Telegram. After that it runs
by itself every day at 03:00 UTC (08:30 IST).

## Customising (no code needed)

Edit `config/services.yaml`:
- **services**: describe each service and your ideal client. The AI uses this to decide what is a lead.
- **owner.reply_style**: tone and rules for drafts.
- **max_leads_per_day / min_score**: digest size and quality bar.
- **sources**: Freelancer search terms, extra RSS feeds, and which sites Google discovery
  searches (`platform_groups`). Direct Reddit fetching exists but is switched off by default.

## Run it on your own computer (optional)

```bash
pip install -r requirements.txt
python -m radar run --sample --mock-ai --dry-run   # offline pipeline test, no keys
export GEMINI_API_KEY=...  TELEGRAM_BOT_TOKEN=...  TELEGRAM_CHAT_ID=...
python -m radar run --dry-run                      # real fetch + AI, prints instead of sending
python -m radar run                                # real run, sends to Telegram
```

## Source coverage (honest notes)

| Source | Status |
|---|---|
| Freelancer.com | Good (official API, no key needed) |
| RSS / forums | Good, add feeds you care about |
| Reddit, LinkedIn, X, Quora, Facebook, Upwork | Partial. Found only via Google-indexed public posts, so very fresh posts may be missed. Flagged "verify the post" in the digest. |

Google discovery costs a few Gemini calls per run (services x platform groups). If you hit the
free-tier limit, trim `platform_groups` in the config.

## Good to know

- GitHub may start scheduled jobs 5-20 minutes late, so the digest lands between 8:30 and 9:00 AM.
- A second small job (`feedback.yml`) collects your 👍/👎 taps every 6 hours, because Telegram
  only keeps them for 24h.
- If all sources fail or the AI is down, you get a Telegram message saying so instead of silence.
- GitHub pauses scheduled workflows after 60 days with no repo activity. The radar's own
  memory commits count as activity, so this normally does not happen.
- The free Gemini tier has rate limits. The radar batches posts and pauses between calls to stay inside them.
