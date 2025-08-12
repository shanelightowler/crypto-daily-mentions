import praw
import re
import json
from collections import Counter
import os
from datetime import datetime

# Get credentials from environment variables
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
USER_AGENT = "crypto-mention-counter"

# Coin aliases
keyword_aliases = {
    "bitcoin": ["btc", "bitcoin"],
    "ethereum": ["eth", "ethereum"],
    "cardano": ["ada", "cardano"],
    "solana": ["sol", "solana"],
    "dogecoin": ["doge", "dogecoin"]
}

# Connect to Reddit
reddit = praw.Reddit(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    user_agent=USER_AGENT
)

# Find the latest Daily Crypto Discussion thread
daily_thread = None
for submission in reddit.subreddit("CryptoCurrency").search("Daily Crypto Discussion", sort="new", time_filter="day"):
    if "Daily Crypto Discussion" in submission.title:
        daily_thread = submission
        break

if not daily_thread:
    raise Exception("No Daily Crypto Discussion thread found.")

# Fetch and count mentions
daily_thread.comments.replace_more(limit=None)
counts = Counter()

for comment in daily_thread.comments.list():
    text = comment.body.lower()
    for coin, aliases in keyword_aliases.items():
        for alias in aliases:
            pattern = r"\b" + re.escape(alias.lower()) + r"\b"
            matches = re.findall(pattern, text)
            counts[coin] += len(matches)

# Prepare output
output = {
    "thread_title": daily_thread.title,
    "thread_url": f"https://www.reddit.com{daily_thread.permalink}",
    "results": counts
}

# Date-stamped filename
today_str = datetime.utcnow().strftime("%Y-%m-%d")
daily_filename = f"data-{today_str}.json"

# Save daily file
with open(daily_filename, "w") as f:
    json.dump(output, f, indent=2)

# Also save as latest data.json
with open("data.json", "w") as f:
    json.dump(output, f, indent=2)

# Update manifest.json
manifest = []
if os.path.exists("manifest.json"):
    with open("manifest.json", "r") as f:
        manifest = json.load(f)

# Avoid duplicates if rerunning same day
manifest = [m for m in manifest if m["date"] != today_str]
manifest.append({"date": today_str, "file": daily_filename})

with open("manifest.json", "w") as f:
    json.dump(sorted(manifest, key=lambda x: x["date"]), f, indent=2)

print(f"✅ Data saved to {daily_filename} and data.json")
print(f"📄 Manifest updated with {today_str}")
