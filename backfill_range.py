import os
import json
import time
from datetime import datetime, timedelta
from collections import Counter
import praw
from daily_mentions import fetch_coins, build_keyword_processor, count_mentions_in_text

# Bot filter (reuse if present)
try:
    from daily_mentions import EXCLUDE_BOTS as DM_EXCLUDE_BOTS
except Exception:
    DM_EXCLUDE_BOTS = True
try:
    from daily_mentions import BOT_NAME_PATTERNS as DM_BOT_NAME_PATTERNS
except Exception:
    DM_BOT_NAME_PATTERNS = ("automoderator", "bot", "tip", "price", "moon", "giveaway", "airdrop")

EXCLUDE_BOTS = DM_EXCLUDE_BOTS
BOT_NAME_PATTERNS = DM_BOT_NAME_PATTERNS

def should_skip_author(author) -> bool:
    if not EXCLUDE_BOTS:
        return False
    if author is None:
        return False
    name = str(getattr(author, "name", "") or "").lower()
    if name == "automoderator":
        return True
    return any(part in name for part in BOT_NAME_PATTERNS)

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
USER_AGENT = "crypto-mention-counter"
if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError("Set CLIENT_ID and CLIENT_SECRET environment variables for Reddit API auth.")

reddit = praw.Reddit(client_id=CLIENT_ID, client_secret=CLIENT_SECRET, user_agent=USER_AGENT)

DATA_DIR = os.getenv("DATA_DIR", "data")
CORPUS_DIR = os.getenv("CORPUS_DIR", "corpus")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CORPUS_DIR, exist_ok=True)

def find_daily_thread_by_date(reddit, date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Date must be in YYYY-MM-DD format")
    month_name = dt.strftime("%B")
    day_no = dt.day
    year = dt.year
    needle = f"{month_name} {day_no}, {year}"
    for submission in reddit.subreddit("CryptoCurrency").search(
        "Daily Crypto Discussion", sort="new", time_filter="all", limit=None
    ):
        title = submission.title or ""
        if "Daily Crypto Discussion" in title and needle in title:
            return submission
    return None

def ensure_manifest():
    path = "manifest.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_manifest(manifest):
    manifest = sorted(manifest, key=lambda x: x["date"])
    with open("manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

def dump_corpus(comments, date_str: str):
    path = os.path.join(CORPUS_DIR, f"comments-{date_str}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for c in comments:
            author = getattr(c, "author", None)
            author_name = getattr(author, "name", None) if author else None
            obj = {"id": c.id, "author": author_name, "body": c.body or ""}
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(f"📦 Saved corpus to {path}")

def process_one_day(date_str: str, save_corpus: bool = True, force: bool = False, sleep_secs: float = 1.0):
    print(f"\n=== Processing {date_str} ===")
    out_name = f"data-{date_str}.json"
    out_path = os.path.join(DATA_DIR, out_name)
    if not force and os.path.exists(out_path):
        print(f"↪ Skipping {date_str} (already exists). Use force=true to overwrite.")
        return True

    submission = find_daily_thread_by_date(reddit, date_str)
    if not submission:
        print(f"⚠ No Daily Crypto Discussion thread found for {date_str}")
        return False

    print(f"Thread: {submission.title}")
    print(f"URL: https://www.reddit.com{submission.permalink}")
    submission.comments.replace_more(limit=None)
    comments = submission.comments.list()
    print(f"Total comments: {len(comments)}")

    if save_corpus:
        dump_corpus(comments, date_str)

    coins = fetch_coins()
    kp, id_to_meta, canonical_name_by_symbol = build_keyword_processor(coins)

    counts_by_symbol = Counter()
    for c in comments:
        if should_skip_author(getattr(c, "author", None)):
            continue
        counts_by_symbol.update(count_mentions_in_text(kp, c.body or ""))

    results_by_symbol = dict(sorted(counts_by_symbol.items(), key=lambda x: x[1], reverse=True))
    results_list = [{"symbol": sym, "name": canonical_name_by_symbol.get(sym, ""), "count": count}
                    for sym, count in results_by_symbol.items()]
    output = {
        "thread_title": submission.title,
        "thread_url": f"https://www.reddit.com{submission.permalink}",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "results": results_by_symbol,
        "results_list": results_list,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"✅ Saved {out_path}")

    manifest = ensure_manifest()
    manifest = [m for m in manifest if m.get("date") != date_str]
    manifest.append({"date": date_str, "file": os.path.join(DATA_DIR, out_name)})
    save_manifest(manifest)
    print(f"📄 Manifest updated for {date_str}")

    time.sleep(sleep_secs)
    return True

def daterange(start_date: str, end_date: str):
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    d = start
    while d <= end:
        yield d.strftime("%Y-%m-%d")
        d += timedelta(days=1)

def main():
    START_DATE = os.getenv("START_DATE", "").strip()
    END_DATE = os.getenv("END_DATE", "").strip()
    BACKFILL_DAYS = os.getenv("BACKFILL_DAYS", "").strip()
    FORCE = (os.getenv("FORCE", "false").lower() == "true")
    SAVE_CORPUS = (os.getenv("SAVE_CORPUS", "true").lower() != "false")
    SLEEP_SECS = float(os.getenv("SLEEP_SECS", "1.0"))

    dates = []
    if START_DATE and END_DATE:
        dates = list(daterange(START_DATE, END_DATE))
    elif BACKFILL_DAYS:
        n = int(BACKFILL_DAYS)
        today = datetime.utcnow().date()
        # last N days up to yesterday
        dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n, 0, -1)]
    else:
        raise SystemExit("Set either START_DATE and END_DATE (YYYY-MM-DD) or BACKFILL_DAYS (integer)")

    print(f"Planned dates: {dates}")
    ok = 0
    for ds in dates:
        if process_one_day(ds, save_corpus=SAVE_CORPUS, force=FORCE, sleep_secs=SLEEP_SECS):
            ok += 1
    print(f"\nDone. Success: {ok}/{len(dates)}")

if __name__ == "__main__":
    main()
