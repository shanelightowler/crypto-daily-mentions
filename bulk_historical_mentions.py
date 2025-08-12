import praw
import re
import json
import os
from collections import Counter
from datetime import datetime, timedelta

# Reddit credentials from environment variables
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
USER_AGENT = "crypto-mention-counter-bulk"

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

def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)

def get_daily_thread_for_date(target_date_str):
    # Search posts with "Daily Crypto Discussion" and find the one matching target date string
    for submission in reddit.subreddit("CryptoCurrency").search("Daily Crypto Discussion", sort="new", time_filter="all"):
        if f"Daily Crypto Discussion – {target_date_str}" in submission.title:
            return submission
    return None

def count_mentions(submission):
    submission.comments.replace_more(limit=None)
    counts = Counter()
    for comment in submission.comments.list():
        text = comment.body.lower()
        for coin, aliases in keyword_aliases.items():
            for alias in aliases:
                pattern = r"\b" + re.escape(alias.lower()) + r"\b"
                matches = re.findall(pattern, text)
                counts[coin] += len(matches)
    return counts

def main():
    start_date = datetime.strptime("2025-08-01", "%Y-%m-%d")
    end_date = datetime.strptime("2025-08-11", "%Y-%m-%d")

    for single_date in daterange(start_date, end_date):
        date_str_formatted = single_date.strftime("%B %d, %Y")  # e.g., August 11, 2025
        file_date = single_date.strftime("%Y-%m-%d")
        print(f"Processing {date_str_formatted} ...")

        thread = get_daily_thread_for_date(date_str_formatted)
        if not thread:
            print(f"  No thread found for {date_str_formatted}")
            continue

        counts = count_mentions(thread)

        output = {
            "thread_title": thread.title,
            "thread_url": f"https://www.reddit.com{thread.permalink}",
            "results": counts,
            "date": file_date
        }

        filename = f"data-{file_date}.json"
        with open(filename, "w") as f:
            json.dump(output, f, indent=2)

        print(f"  Saved data to {filename}")

if __name__ == "__main__":
    main()
