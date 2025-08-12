import os
import sys
import json
from datetime import datetime
from collections import Counter

import praw

# Reuse helpers and rules from your daily script (must be in repo root)
from daily_mentions import (
    fetch_coins,
    build_keyword_processor,
    count_mentions_in_text,
    should_skip_author,  # uses the EXCLUDE_BOTS settings from daily_mentions.py
)

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

def parse_date_from_title(title: str) -> str | None:
    # Example: "Daily Crypto Discussion - August 11, 2025 (GMT+0)"
    try:
        parts = title.split(" - ", 1)
        if len(parts) != 2:
            return None
        date_part = parts[1].split(" (")[0].strip()  # "August 11, 2025"
        dt = datetime.strptime(date_part, "%B %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None

def dump_corpus(comments, date_str: str):
    # Save every comment as one JSON object per line for auditing
    path = f"comments-{date_str}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for c in comments:
            author = getattr(c, "author", None)
            author_name = getattr(author, "name", None) if author else None
            obj = {
                "id": c.id,
                "author": author_name,
                "body": c.body or ""
            }
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(f"📦 Saved corpus to {path}")

def scrape_single_thread(url: str):
    submission = reddit.submission(url=url)
    submission.comments.replace_more(limit=None)
    comments = submission.comments.list()

    print(f"Thread: {submission.title}")
    print(f"URL: {url}")
    print(f"Total comments: {len(comments)}")

    # Determine date for filenames
    date_str = parse_date_from_title(submission.title) or datetime.utcnow().strftime("%Y-%m-%d")

    # Save corpus for auditing
    dump_corpus(comments, date_str)

    # Build matcher (same as daily script)
    coins = fetch_coins()
    kp, id_to_meta, canonical_name_by_symbol = build_keyword_processor(coins)

    # Count mentions by SYMBOL using the same logic as daily_mentions.py
    counts_by_symbol = Counter()
    for c in comments:
        if should_skip_author(getattr(c, "author", None)):
            continue
        counts_by_symbol.update(count_mentions_in_text(kp, c.body or ""))

    # Sort and build outputs
    results_by_symbol = dict(sorted(counts_by_symbol.items(), key=lambda x: x[1], reverse=True))
    results_list = [
        {"symbol": sym, "name": canonical_name_by_symbol.get(sym, ""), "count": count}
        for sym, count in results_by_symbol.items()
    ]

    output = {
        "thread_title": submission.title,
        "thread_url": url,
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "results": results_by_symbol,
        "results_list": results_list,
    }

    # Filename by date
    filename = f"data-{date_str}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"✅ Saved {filename}")

    # Update manifest.json
    manifest_path = "manifest.json"
    manifest = []
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    manifest = [m for m in manifest if m.get("date") != date_str]
    manifest.append({"date": date_str, "file": filename})
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
