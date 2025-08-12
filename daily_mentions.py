import praw
import re
import json
from collections import Counter
import os

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

# Save results
output = {
    "thread_title": daily_thread.title,
    "thread_url": f"https://www.reddit.com{daily_thread.permalink}",
    "results": counts
}

with open("data.json", "w") as f:
    json.dump(output, f, indent=2)

print("✅ Data saved to data.json")
