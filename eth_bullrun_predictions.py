import os
import re
import json
from datetime import datetime, timedelta
from statistics import median, mean
from collections import Counter

import praw

USER_AGENT = "eth-bullrun-predictions"
SUBREDDIT = "ethereum"
THREAD_SEARCH_QUERY = "Daily General Discussion"
ROLLING_DAYS = 30  # for consensus

# Reddit credentials
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError("Set CLIENT_ID and CLIENT_SECRET environment variables for Reddit API auth.")

# Output dirs/files
PRED_DIR = os.getenv("PRED_DIR", "predictions")
os.makedirs(PRED_DIR, exist_ok=True)
MANIFEST_PATH = "predictions_manifest.json"
CONSENSUS_PATH = os.path.join(PRED_DIR, "consensus.json")

# Heuristics
ETH_TERMS = re.compile(r"\b(eth|ethereum|ether|\$eth)\b", re.I)

# Context words that suggest “top of bull run” prediction
CONTEXT_WORDS = re.compile(
    r"\b(ath|all[-\s]?time high|top|peak|blow[-\s]?off|this cycle|next cycle|bull run|end of cycle|price target|will (go|hit)|to \$?\d|reach)\b",
    re.I
)

# Money patterns
# Range like: $10k-$15k, 10-15k, 8k to 12k, $10,000 to $15,000
RANGE_PATTERN = re.compile(
    r"""
    (?P<a>\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\$?\s?\d+(?:\.\d+)?)
    \s*(?:-|–|to|TO)\s*
    (?P<b>\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\$?\s?\d+(?:\.\d+)?)
    \s*(?P<suffix>[kKmMbB])?
    """,
    re.X,
)

# Single amount like: $10k, 10k, $15,000, 15000, 15m
SINGLE_PATTERN = re.compile(
    r"""
    (?P<val>\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\$?\s?\d+(?:\.\d+)?)
    \s*(?P<suffix>[kKmMbB])?
    """,
    re.X,
)

def to_number_usd(raw: str, suffix: str | None) -> float | None:
    # raw like "$10,000" or "15000" or "$12.5"
    s = raw.strip().replace("$", "").replace(",", "").lower()
    try:
        v = float(s)
    except ValueError:
        return None
    mult = 1.0
    if suffix:
        suf = suffix.lower()
        if suf == "k":
            mult = 1_000
        elif suf == "m":
            mult = 1_000_000
        elif suf == "b":
            mult = 1_000_000_000
    return v * mult

def sentence_split(text: str):
    # Simple sentence splitter; good enough for Reddit comments
    return re.split(r"(?<=[\.\!\?])\s+|\n+", text)

def looks_like_prediction(sent: str) -> bool:
    # Must have ETH context and prediction context
    return bool(ETH_TERMS.search(sent)) and bool(CONTEXT_WORDS.search(sent))

def extract_predictions_from_sentence(sent: str):
    preds = []

    # Try range first
    for m in RANGE_PATTERN.finditer(sent):
        a_raw = m.group("a")
        b_raw = m.group("b")
        suf = m.group("suffix")
        # If one side already includes k/m/b, RANGE_PATTERN puts suffix in 'suffix' only if it applies to both ends like "10-12k".
        # Handle embedded suffix in a_raw/b_raw too (e.g., "10k - 12k").
        suf_a = None
        suf_b = None

        ma = re.search(r"([kKmMbB])\s*$", a_raw.strip())
        if ma:
            suf_a = ma.group(1)
        mb = re.search(r"([kKmMbB])\s*$", b_raw.strip())
        if mb:
            suf_b = mb.group(1)

        va = to_number_usd(a_raw, suf or suf_a)
        vb = to_number_usd(b_raw, suf or suf_b)
        if va and vb and va > 0 and vb > 0:
            low, high = sorted([va, vb])
            mid = (low + high) / 2.0
            preds.append({
                "type": "range",
                "lower_usd": round(low, 2),
                "upper_usd": round(high, 2),
                "amount_usd": round(mid, 2),
                "raw": m.group(0).strip()
            })

    # Then singles
    # Avoid double-counting values that were part of a range by excluding the exact range text spans is complex; acceptable to allow both, but we can lightly guard:
    if not preds:  # if a range is present, we’ll prefer the range and skip singles in that sentence
        for m in SINGLE_PATTERN.finditer(sent):
            raw = m.group("val")
            suf = m.group("suffix")
            val = to_number_usd(raw, suf)
            # Filter out very small numbers (likely not price predictions)
            if val and val >= 100:  # <$100 likely not "ETH top", adjust as needed
                preds.append({
                    "type": "single",
                    "amount_usd": round(val, 2),
                    "raw": m.group(0).strip()
                })

    return preds

def parse_comment_for_predictions(comment_body: str):
    out = []
    for sent in sentence_split(comment_body or ""):
        s = sent.strip()
        if not s:
            continue
        if looks_like_prediction(s):
            preds = extract_predictions_from_sentence(s)
            # Light guard: require $ or k/m/b in the matched raw to reduce TPS/TVL confusions
            for p in preds:
                raw = p["raw"].lower()
                if "$" in raw or any(x in raw for x in ["k", "m", "b"]):
                    out.append({"sentence": s, "prediction": p})
    return out

def find_latest_eth_daily_thread(reddit):
    for submission in reddit.subreddit(SUBREDDIT).search(THREAD_SEARCH_QUERY, sort="new", time_filter="day"):
        title = submission.title or ""
        if "daily general discussion" in title.lower():
            return submission
    return None

def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def summarize(amounts):
    if not amounts:
        return {
            "count": 0,
            "mean_usd": None,
            "median_usd": None,
            "min_usd": None,
            "max_usd": None
        }
    return {
        "count": len(amounts),
        "mean_usd": round(mean(amounts), 2),
        "median_usd": round(median(amounts), 2),
        "min_usd": round(min(amounts), 2),
        "max_usd": round(max(amounts), 2)
    }

def compute_consensus(manifest, days=30):
    # Pool all predictions across last N days and compute median/mean
    # Manifest entries are { date, file }
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    pooled = []
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
        "pooled_predictions": s
    }

def main():
    reddit = praw.Reddit(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        user_agent=USER_AGENT,
    )

    sub = find_latest_eth_daily_thread(reddit)
    if not sub:
        print("No Daily General Discussion thread found today on r/ethereum.")
        return

    print(f"Thread: {sub.title}")
    print(f"URL: https://www.reddit.com{sub.permalink}")

    sub.comments.replace_more(limit=None)
    comments = sub.comments.list()
    print(f"Total comments: {len(comments)}")

    # Extract predictions
    records = []
    for c in comments:
        body = getattr(c, "body", "") or ""
        # Skip obvious bot or automod to reduce noise
        author = getattr(c, "author", None)
        author_name = getattr(author, "name", None) if author else None
        if author_name and author_name.lower() == "automoderator":
            continue
        hits = parse_comment_for_predictions(body)
        for h in hits:
            p = h["prediction"]
            # Normalize a single amount for aggregation; ranges use midpoint
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

    # Aggregate
    amounts = [r["amount_usd"] for r in records if isinstance(r["amount_usd"], (int, float)) and r["amount_usd"] > 0]
    summary = summarize(amounts)

    # Date stamp: infer from title if possible; else UTC today
    date_str = None
    try:
        # Title example: "Daily General Discussion - August 20, 2025"
        parts = (sub.title or "").split(" - ", 1)
        if len(parts) == 2:
            date_part = parts[1].strip()
            # Drop anything after the date (rare)
            date_part = date_part.split("(")[0].strip()
            dt = datetime.strptime(date_part, "%B %d, %Y")
            date_str = dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

    # Build output
    output = {
        "thread_title": sub.title,
        "thread_url": f"https://www.reddit.com{sub.permalink}",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "date": date_str,
        "summary": summary,
        "predictions": records
    }

    # Save per-day file
    day_file = os.path.join(PRED_DIR, f"eth-preds-{date_str}.json")
    save_json(day_file, output)
    print(f"✅ Saved {day_file}")

    # Update manifest
    manifest = load_json(MANIFEST_PATH, [])
    manifest = [m for m in manifest if m.get("date") != date_str]
    manifest.append({"date": date_str, "file": day_file})
    manifest = sorted(manifest, key=lambda x: x["date"])
    save_json(MANIFEST_PATH, manifest)
    print("📄 Manifest updated")

    # Update rolling consensus
    consensus = compute_consensus(manifest, days=ROLLING_DAYS)
    save_json(CONSENSUS_PATH, consensus)
    print(f"📈 Consensus updated ({ROLLING_DAYS}d window)")

if __name__ == "__main__":
    main()
