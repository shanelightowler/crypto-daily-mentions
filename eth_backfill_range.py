import os
import json
import time
from datetime import datetime, timedelta
from statistics import median, mean
from typing import Any, Dict, List

import praw

# Reuse the parser from the daily script
from eth_bullrun_predictions import parse_comment_for_predictions  # type: ignore

USER_AGENT = "eth-bullrun-predictions-backfill"
SUBREDDIT = "ethereum"
THREAD_SEARCH_QUERY = "Daily General Discussion"

# Output/manifest
PRED_DIR = os.getenv("PRED_DIR", "predictions")
MANIFEST_PATH = "predictions_manifest.json"
CONSENSUS_PATH = os.path.join(PRED_DIR, "consensus.json")
ROLLING_DAYS = int(os.getenv("ROLLING_DAYS", "30"))
DEBUG_SAVE_CANDIDATES = os.getenv("DEBUG_SAVE_CANDIDATES", "true").lower() == "true"

os.makedirs(PRED_DIR, exist_ok=True)

# Reddit credentials
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError("Set CLIENT_ID and CLIENT_SECRET environment variables for Reddit API auth.")

reddit = praw.Reddit(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    user_agent=USER_AGENT,
)

# ---------------- Utilities ----------------

def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

def summarize(amounts: List[float]) -> Dict[str, Any]:
    if not amounts:
        return {"count": 0, "mean_usd": None, "median_usd": None, "min_usd": None, "max_usd": None}
    return {
        "count": len(amounts),
        "mean_usd": round(mean(amounts), 2),
        "median_usd": round(median(amounts), 2),
        "min_usd": round(min(amounts), 2),
        "max_usd": round(max(amounts), 2),
    }

def compute_consensus(manifest: List[Dict[str, str]], days: int = ROLLING_DAYS) -> Dict[str, Any]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    pooled: List[float] = []
    for entry in manifest:
        d = entry.get("date")
        if not d or d < cutoff:
            continue
        path = entry.get("file")
        if not path or not os.path.exists(path):
            continue
        data = load_json(path, {})
        for item in data.get("predictions", []):
            amt = item.get("amount_usd")
            if isinstance(amt, (int, float)) and amt > 0:
                pooled.append(amt)
    s = summarize(pooled)
    return {
        "window_days": days,
        "as_of_utc": datetime.utcnow().isoformat() + "Z",
        "pooled_predictions": s,
    }

def find_daily_thread_by_date(reddit: praw.Reddit, date_str: str):
    """
    date_str: 'YYYY-MM-DD'
    Title format: 'Daily General Discussion - Month D, YYYY'
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Date must be in YYYY-MM-DD format")

    month_name = dt.strftime("%B")
    day_no = dt.day
    year = dt.year
    needle = f"{month_name} {day_no}, {year}".lower()

    for sub in reddit.subreddit(SUBREDDIT).search(THREAD_SEARCH_QUERY, sort="new", time_filter="all", limit=None):
        title = (sub.title or "").lower()
        if "daily general discussion" in title and needle in title:
            return sub
    return None

def daterange(start_date: str, end_date: str):
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    d = start
    while d <= end:
        yield d.strftime("%Y-%m-%d")
        d += timedelta(days=1)

# ---------------- Main processing ----------------

def process_one_day(date_str: str, force: bool = False, sleep_secs: float = 0.8) -> bool:
    print(f"\n=== ETH backfill {date_str} ===")
    out_path = os.path.join(PRED_DIR, f"eth-preds-{date_str}.json")
    if os.path.exists(out_path) and not force:
        print("↪ Skipping (already exists). Use force=true to overwrite.")
        return True

    sub = find_daily_thread_by_date(reddit, date_str)
    if not sub:
        print("⚠ No r/ethereum Daily General Discussion thread found for this date.")
        return False

    print(f"Thread: {sub.title}")
    print(f"URL: https://www.reddit.com{sub.permalink}")

    sub.comments.replace_more(limit=None)
    comments = sub.comments.list()
    print(f"Total comments: {len(comments)}")

    records: List[Dict[str, Any]] = []
    all_candidates: List[Dict[str, Any]] = []

    for c in comments:
        author = getattr(c, "author", None)
        author_name = getattr(author, "name", None) if author else None
        if author_name and author_name.lower() in {"automoderator", "tricky_troll"}:
            continue
        body = getattr(c, "body", "") or ""
        hits, cand = parse_comment_for_predictions(body)
        all_candidates.extend(cand)
        for h in hits:
            p = h["prediction"]
            if p["type"] == "range":
                amt = p["amount_usd"]
                lower = p["lower_usd"]
                upper = p["upper_usd"]
            else:
                amt = p["amount_usd"]
                lower = None
                upper = None
            records.append({
                "amount_usd": amt,
                "lower_usd": lower,
                "upper_usd": upper,
                "raw_match": p["raw"],
                "sentence": h["sentence"],
                "comment_id": getattr(c, "id", None),
                "author": author_name,
            })

    amounts = [r["amount_usd"] for r in records if isinstance(r["amount_usd"], (int, float)) and r["amount_usd"] > 0]
    summary = summarize(amounts)

    output = {
        "thread_title": sub.title,
        "thread_url": f"https://www.reddit.com{sub.permalink}",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "date": date_str,
        "summary": summary,
        "predictions": records,
    }

    save_json(out_path, output)
    print(f"✅ Saved {out_path}")

    # Save candidates (debug)
    if DEBUG_SAVE_CANDIDATES:
        cand_path = os.path.join(PRED_DIR, f"eth-preds-candidates-{date_str}.jsonl")
        with open(cand_path, "w", encoding="utf-8") as f:
            for item in all_candidates:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"🕵️ Saved candidate log to {cand_path}")

    # Update manifest
    manifest = load_json(MANIFEST_PATH, [])
    manifest = [m for m in manifest if m.get("date") != date_str]
    manifest.append({"date": date_str, "file": out_path})
    manifest = sorted(manifest, key=lambda x: x["date"])
    save_json(MANIFEST_PATH, manifest)
    print("📄 Manifest updated")

    time.sleep(sleep_secs)
    return True

def main():
    START_DATE = os.getenv("START_DATE", "").strip()
    END_DATE = os.getenv("END_DATE", "").strip()
    BACKFILL_DAYS = os.getenv("BACKFILL_DAYS", "").strip()
    FORCE = (os.getenv("FORCE", "false").lower() == "true")

    dates: List[str] = []
    if START_DATE and END_DATE:
        dates = list(daterange(START_DATE, END_DATE))
    elif BACKFILL_DAYS:
        n = int(BACKFILL_DAYS)
        today = datetime.utcnow().date()
        dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n, 0, -1)]
    else:
        raise SystemExit("Set either START_DATE and END_DATE (YYYY-MM-DD) or BACKFILL_DAYS (integer)")

    print(f"Planned dates: {dates}")

    ok = 0
    for ds in dates:
        if process_one_day(ds, force=FORCE):
            ok += 1

    # Recompute consensus after the batch
    manifest = load_json(MANIFEST_PATH, [])
    consensus = compute_consensus(manifest, days=ROLLING_DAYS)
    save_json(CONSENSUS_PATH, consensus)
    print(f"\n📈 Consensus updated (window {ROLLING_DAYS}d)")
    print(f"Done. Success: {ok}/{len(dates)}")

if __name__ == "__main__":
    main()
