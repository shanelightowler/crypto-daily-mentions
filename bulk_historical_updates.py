import os
import sys
import json
from datetime import datetime
from collections import Counter, defaultdict
import praw

# Reuse helpers from your daily script (must be in repo root)
from daily_mentions import fetch_coins, build_keyword_processor, count_mentions_in_text

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

def scrape_single_thread(url: str):
    submission = reddit.submission(url=url)
    submission.comments.replace_more(limit=None)
    comments = submission.comments.list()

    print(f"Thread: {submission.title}")
    print(f"URL: {url}")
    print(f"Total comments: {len(comments)}")

    # Build keyword processor (same as daily script)
    coins = fetch_coins()
    kp, id_to_meta = build_keyword_processor(coins)

    # Count mentions
    counts_by_id = Counter()
    for c in comments:
        c_counts = count_mentions_in_text(kp, c.body)
        counts_by_id.update(c_counts)

    # Convert to symbol-level
    results_list = []
    results_by_symbol = defaultdict(int)
    for cid, count in counts_by_id.items():
        meta = id_to_meta.get(cid)
        if not meta:
            continue
        sym = meta["symbol"].upper()
        name = meta["name"].title()
        results_list.append({"id": cid, "symbol": sym, "name": name, "count": count})
        results_by_symbol[sym] += count

    results_list.sort(key=lambda x: x["count"], reverse=True)

    output = {
        "thread_title": submission.title,
        "thread_url": url,
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "results": dict(sorted(results_by_symbol.items(), key=lambda x: x[1], reverse=True)),
        "results_list": results_list,
    }

    # Filenames: new standard by date + backward-compat by submission id
    date_str = parse_date_from_title(submission.title) or datetime.utcnow().strftime("%Y-%m-%d")
    new_name = f"data-{date_str}.json"
    legacy_name = f"data_{submission.id}.json"  # for old pages that still reference this

    with open(new_name, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    with open(legacy_name, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Saved {new_name} and {legacy_name}")

    # Update manifest.json
    manifest_path = "manifest.json"
    manifest = []
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    manifest = [m for m in manifest if m.get("date") != date_str]
    manifest.append({"date": date_str, "file": new_name})
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
