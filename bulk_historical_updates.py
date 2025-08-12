import os
import sys
import json
from datetime import datetime
from collections import Counter

import praw

# Reuse helpers from your daily script
from daily_mentions import (
    fetch_coins,
    build_keyword_processor,
    count_mentions_in_text,
)

# Try to reuse bot filtering config from daily_mentions; otherwise defaults
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

# Reddit credentials
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
USER_AGENT = "crypto-mention-counter"
if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError("Set CLIENT_ID and CLIENT_SECRET environment variables for Reddit API auth.")

reddit = praw.Reddit(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    user_agent=USER_AGENT
)

# New: subfolders
DATA_DIR = os.getenv("DATA_DIR", "data")
CORPUS_DIR = os.getenv("CORPUS_DIR", "corpus")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CORPUS_DIR, exist_ok=True)

def parse_date_from_title(title: str) -> str | None:
    try:
        parts = title.split(" - ", 1)
        if len(parts) != 2:
            return None
        date_part = parts[1].split(" (")[0].strip()
        dt = datetime.strptime(date_part, "%B %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None

def dump_corpus(comments, date_str: str):
    path = os.path.join(CORPUS_DIR, f"comments-{date_str}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for c in comments:
            author = getattr(c, "author", None)
            author_name = getattr(author, "name", None) if author else None
            obj = {"id": c.id, "author": author_name, "body": c.body or ""}
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(f"📦 Saved corpus to {path}")

def scrape_single_thread(url: str):
    submission = reddit.submission(url=url)
    submission.comments.replace_more(limit=None)
    comments = submission.comments.list()

    print(f"Thread: {submission.title}")
    print(f"URL: {url}")
    print(f"Total comments: {len(comments)}")

    date_str = parse_date_from_title(submission.title) or datetime.utcnow().strftime("%Y-%m-%d")
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
        "thread_url": url,
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "results": results_by_symbol,
        "results_list": results_list,
    }

    # Save into data/ subfolder
    filename = f"data-{date_str}.json"
    out_path = os.path.join(DATA_DIR, filename)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"✅ Saved {out_path}")

    # Update manifest at root
    manifest_path = "manifest.json"
    manifest = []
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    manifest = [m for m in manifest if m.get("date") != date_str]
    manifest.append({"date": date_str, "file": os.path.join(DATA_DIR, filename)})
    manifest.sort(key=lambda x: x["date"])
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"📄 Manifest updated for {date_str}")

def main():
    if len(sys.argv) == 2:
        url = sys.argv[1]
        scrape_single_thread(url)
    else:
        print("Usage: python bulk_historical_updates.py <reddit_thread_url>")
        sys.exit(1)

if __name__ == "__main__":
    main()
