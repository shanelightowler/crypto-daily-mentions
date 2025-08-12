import os
import re
import json
import time
import requests
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import praw
from flashtext import KeywordProcessor

# =========================
# Config
# =========================
USER_AGENT = "crypto-mention-counter"
COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list?include_platform=false"
COIN_CACHE_FILE = "coins_cache.json"
COIN_CACHE_TTL_DAYS = 7

# Heuristics to reduce false positives:
# - For symbols in this set, we will NOT match the bare symbol; we will only match "$symbol".
# - These are common English words or very short tokens frequently used out of crypto context.
AMBIGUOUS_SYMBOLS = {
    "one", "near", "gas", "time", "zen", "pay", "beam", "wave", "waves", "dash", "life",
    "note", "true", "magic", "saga", "rune", "mask", "bone", "cake", "rose", "sushi",
    "star", "flow", "kind", "space", "core", "mint", "move", "hash", "uni", "apt", "op",
    "hook", "spell", "gala", "atlas", "pearl", "ray", "band", "honey", "meme", "solo"
}
# Names that are too generic; only match if $SYMBOL hits:
AMBIGUOUS_NAMES = {
    "near", "one", "time", "waves", "dash", "gas", "beam", "mask", "core", "flow", "magic"
}

# If True, we’ll also add bare ticker symbols of length 2 (e.g., "io", "ai") — usually noisy.
ALLOW_VERY_SHORT_TICKERS = False

# =========================
# Reddit credentials
# =========================
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError("Set CLIENT_ID and CLIENT_SECRET environment variables for Reddit API auth.")

# =========================
# Utilities
# =========================
def load_cached_coins():
    if not os.path.exists(COIN_CACHE_FILE):
        return None
    try:
        with open(COIN_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("_fetched_at")
        if not ts:
            return None
        fetched_at = datetime.fromisoformat(ts)
        if datetime.utcnow() - fetched_at > timedelta(days=COIN_CACHE_TTL_DAYS):
            return None
        return data.get("coins")
    except Exception:
        return None

def fetch_coins():
    coins = load_cached_coins()
    if coins is not None:
        return coins
    # Fetch from CoinGecko
    resp = requests.get(COINGECKO_LIST_URL, timeout=30)
    resp.raise_for_status()
    coins = resp.json()
    with open(COIN_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"_fetched_at": datetime.utcnow().isoformat(), "coins": coins}, f)
    return coins

def normalize_text(s: str) -> str:
    # Lower is handled by flashtext when case_sensitive=False, but we still strip URLs/markdown noise.
    # Remove URLs
    s = re.sub(r"https?://\S+", " ", s)
    # Remove HTML entities noise (optional)
    s = s.replace("&amp;", "&")
    return s

def build_keyword_processor(coins):
    """
    Returns:
      - kp: KeywordProcessor (case-insensitive), mapping alias -> payload {id,symbol,name,alias}
      - id_to_meta: dict id -> {symbol, name}
    """
    kp = KeywordProcessor(case_sensitive=False)
    id_to_meta = {}
    seen_aliases = set()  # avoid duplicate alias entries across coins

    for c in coins:
        # Each coin: { id, symbol, name }
        cid = c.get("id", "")
        sym = (c.get("symbol") or "").strip().lower()
        name = (c.get("name") or "").strip().lower()
        if not cid or not sym or not name:
            continue
        # Filter out obviously bad/unknown entries
        if not sym.isalnum():
            continue
        # Very short tickers are noisy; consider excluding unless $ prefixed
        if len(sym) < 2:
            continue
        if len(sym) == 2 and not ALLOW_VERY_SHORT_TICKERS:
            # We'll add only the $SY alias below
            pass

        id_to_meta[cid] = {"symbol": sym, "name": name}

        # Always add $symbol
        dollar_alias = f"${sym}"
        if dollar_alias not in seen_aliases:
            kp.add_keyword(dollar_alias, {"id": cid, "symbol": sym, "name": name, "alias": dollar_alias})
            seen_aliases.add(dollar_alias)

        # Add bare symbol if:
        # - length >= 3, and
        # - not ambiguous
        if len(sym) >= 3 and sym not in AMBIGUOUS_SYMBOLS:
            if sym not in seen_aliases:
                kp.add_keyword(sym, {"id": cid, "symbol": sym, "name": name, "alias": sym})
                seen_aliases.add(sym)

        # Add full name if not too generic
        # For multi-word names, flashtext will match the full phrase as whole words.
        if name not in AMBIGUOUS_NAMES and len(name) >= 4:
            if name not in seen_aliases:
                kp.add_keyword(name, {"id": cid, "symbol": sym, "name": name, "alias": name})
                seen_aliases.add(name)

    return kp, id_to_meta

def count_mentions_in_text(kp: KeywordProcessor, text: str):
    text = normalize_text(text)
    hits = kp.extract_keywords(text, span_info=False)  # we only need payloads
    counts = Counter()
    for payload in hits:
        cid = payload["id"]
        counts[cid] += 1
    return counts

# =========================
# Main: fetch thread, count, save
# =========================
def find_latest_daily_thread(reddit):
    # Search the sub for the latest "Daily Crypto Discussion" thread today
    for submission in reddit.subreddit("CryptoCurrency").search(
        "Daily Crypto Discussion", sort="new", time_filter="day"
    ):
        if "Daily Crypto Discussion" in submission.title:
            return submission
    return None

def main():
    # Connect to Reddit
    reddit = praw.Reddit(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        user_agent=USER_AGENT,
    )

    daily_thread = find_latest_daily_thread(reddit)
    if not daily_thread:
        raise Exception("No Daily Crypto Discussion thread found.")

    print(f"Thread: {daily_thread.title}")
    print(f"URL: https://www.reddit.com{daily_thread.permalink}")

    # Load coins and build matcher
    print("Fetching coin list...")
    coins = fetch_coins()
    print(f"Total coins from CoinGecko: {len(coins)}")

    print("Building keyword processor...")
    kp, id_to_meta = build_keyword_processor(coins)
    print("Keyword processor ready.")

    # Fetch all comments
    print("Fetching comments...")
    daily_thread.comments.replace_more(limit=None)
    comments = daily_thread.comments.list()
    print(f"Total comments: {len(comments)}")

    # Count mentions
    counts_by_id = Counter()
    for c in comments:
        text = c.body
        c_counts = count_mentions_in_text(kp, text)
        counts_by_id.update(c_counts)

    # Prepare results: dict for site + list for richer data
    results_list = []
    results_by_symbol = defaultdict(int)

    for cid, count in counts_by_id.items():
        meta = id_to_meta.get(cid)
        if not meta:
            continue
        sym = meta["symbol"]
        name = meta["name"]
        results_list.append(
            {"id": cid, "symbol": sym.upper(), "name": name.title(), "count": count}
        )
        results_by_symbol[sym.upper()] += count

    # Sort results list by count desc
    results_list.sort(key=lambda x: x["count"], reverse=True)

    output = {
        "thread_title": daily_thread.title,
        "thread_url": f"https://www.reddit.com{daily_thread.permalink}",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        # Keep 'results' as a dict for your frontend
        "results": dict(sorted(results_by_symbol.items(), key=lambda x: x[1], reverse=True)),
        # Provide a richer list (optional for UI)
        "results_list": results_list,
    }

    # Date-stamped filename
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    daily_filename = f"data-{today_str}.json"

    # Save daily file
    with open(daily_filename, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    # Also save as latest data.json
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    # Update manifest.json
    manifest = []
    if os.path.exists("manifest.json"):
        with open("manifest.json", "r", encoding="utf-8") as f:
            manifest = json.load(f)

    # Avoid duplicates if rerunning same day
    manifest = [m for m in manifest if m.get("date") != today_str]
    manifest.append({"date": today_str, "file": daily_filename})
    with open("manifest.json", "w", encoding="utf-8") as f:
        json.dump(sorted(manifest, key=lambda x: x["date"]), f, indent=2)

    print(f"✅ Data saved to {daily_filename} and data.json")
    print(f"📄 Manifest updated with {today_str}")
    if results_list:
        print("Top 10 mentions:")
        for row in results_list[:10]:
            print(f"- {row['symbol']}: {row['count']}")

if __name__ == "__main__":
    main()
