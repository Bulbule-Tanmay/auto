import json
import os
import time

STATE_PATH = os.environ.get("RADAR_STATE", "state/state.json")
SEEN_DAYS = 30
SENT_DAYS = 60


def load() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        st = {}
    st.setdefault("seen", {})        # post_id -> timestamp
    st.setdefault("sent", {})        # short_id -> lead info (for feedback lookup)
    st.setdefault("feedback", [])    # list of {verdict, service, source, summary, ts}
    st.setdefault("tg_offset", 0)
    return st


def save(st: dict) -> None:
    now = time.time()
    st["seen"] = {k: v for k, v in st["seen"].items() if now - v < SEEN_DAYS * 86400}
    st["sent"] = {k: v for k, v in st["sent"].items() if now - v.get("ts", now) < SENT_DAYS * 86400}
    st["feedback"] = st["feedback"][-200:]
    os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1, ensure_ascii=False, sort_keys=True)
