import sys
import praw
import re
import json
from collections import Counter
import os

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
USER_AGENT = "crypto-mention-counter"

keyword_aliases = {
    "bitcoin": ["btc", "bitcoin"],
    "ethereum": ["eth", "ethereum"],
    "cardano": ["ada", "cardano"],
    "solana": ["sol", "solana"],
    "dogecoin": ["doge", "dogecoin"]
}

reddit = praw.Reddit(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    user_agent=USER_AGENT
)

def scrape_single_thread(url):
    submission_id = url.split("/comments/")[1].split("/")[0]
    submission = reddit.submission(id=submission_id)

    submission.comments.replace_more(limit=None)
    counts = Counter()

    for comment in submission.comments.list():
        text = comment.body.lower()
        for coin, aliases in keyword_aliases.items():
            for alias in aliases:
                pattern = r"\b" + re.escape(alias.lower()) + r"\b"
                matches = re.findall(pattern, text)
                counts[coin] += len(matches)

    output = {
        "thread_title": submission.title,
        "thread_url": url,
        "results": dict(counts)
    }

    filename = f"data_{submission_id}.json"
    with open(filename, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Saved mentions to {filename}")

if __name__ == "__main__":
    if len(sys.argv) == 2:
        url = sys.argv[1]
        scrape_single_thread(url)
    else:
        print("Usage: python bulk_historical_mentions.py <reddit_thread_url>")
