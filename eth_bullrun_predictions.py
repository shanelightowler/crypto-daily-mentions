import os
import re
import json
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime, timedelta
from statistics import median, mean

import praw

# =========================
# Config
# =========================
USER_AGENT = "eth-bullrun-predictions"
SUBREDDIT = "ethereum"
THREAD_SEARCH_QUERY = "Daily General Discussion"
ROLLING_DAYS = int(os.getenv("ROLLING_DAYS", "30"))

# Output
PRED_DIR = os.getenv("PRED_DIR", "predictions")
os.makedirs(PRED_DIR, exist_ok=True)
MANIFEST_PATH = "predictions_manifest.json"
CONSENSUS_PATH = os.path.join(PRED_DIR, "consensus.json")

# Debug: save candidates (all sentences evaluated, accepted/rejected + reason)
DEBUG_SAVE_CANDIDATES = os.getenv("DEBUG_SAVE_CANDIDATES", "true").lower() == "true"

# Reddit credentials
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError("Set CLIENT_ID and CLIENT_SECRET environment variables for Reddit API auth.")

# =========================
# Heuristics and patterns
# =========================

# ETH context terms (we allow comment-level context as well)
ETH_TERMS = re.compile(r"\b(eth|ethereum|\$eth)\b", re.I)

# Forward-looking / cycle-top context
CONTEXT_WORDS = re.compile(
    r"\b("
    r"ath|all[-\s]?time\s?high|top|peak|topp?ing|blow[-\s]?off|"
    r"(this|next)\s+(cycle|bull\s*run)|end\s+of\s+cycle|price\s+target|"
    r"will\s+(go|hit|reach)|to\s+\$?\d"
    r")\b",
    re.I
)

# Exclusions (phrases and authors)
EXCLUDE_AUTHORS = {"automoderator", "tricky_troll"}  # daily doots summary + bots
SHORT_TERM_TIME = re.compile(r"\b(today|tomorrow|this\s+(week|weekend|month)|by\s+(the\s+)?(weekend|eom|eow)|next\s+(week|month)|in\s+\d+\s*(days?|weeks?))\b", re.I)
SHORT_TERM_EXTRA = re.compile(r"\b(next\s+leg|pull\s*back|pullback|bounce|rally|tonight)\b", re.I)
MARKETCAP_TERMS = re.compile(r"\b(market\s?cap|mcap|cap(italization)?)\b", re.I)
HISTORICAL_ONLY = re.compile(r"\b(ath\s+was|hit\s+in\s+20\d{2}|back\s+in\s+20\d{2}|last\s+cycle|previous\s+cycle)\b", re.I)
AVERAGE_SELLING = re.compile(r"\b(avg|average)\b.*\b(price|sold|selling)\b", re.I)
AMOUNT_OF_ETH = re.compile(r"\b\d+(?:\.\d+)?\s*eth\b", re.I)
SHOULD_NOW = re.compile(r"\b(should\s+be\s+at|would\s+be\s+at)\b", re.I)
NEGATED_TOP = re.compile(r"\b(not|won't|cannot|can\'t|unlikely|no\s+way)\b.*\b(top|peak|topp?ing|ath)\b", re.I)
BTC_ONLY = re.compile(r"\b(btc|bitcoin)\b", re.I)

# Bounds guard for ETH cycle top predictions
MIN_PRICE_USD = 1_000
MAX_PRICE_USD = 250_000

# Money patterns
RANGE_PATTERN = re.compile(
    r"""
    (?P<a>\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\$?\s?\d+(?:\.\d+)?)
    \s*(?:-|–|to|TO)\s*
    (?P<b>\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\$?\s?\d+(?:\.\d+)?)
    \s*(?P<suffix>[kKmM])?
    """,
    re.X,
)

BETWEEN_PATTERN = re.compile(
    r"""
    \b(?:between|from)\s+
    (?P<a>\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\$?\s?\d+(?:\.\d+)?)
    \s+(?:and|to)\s+
    (?P<b>\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\$?\s?\d+(?:\.\d+)?)
    \s*(?P<suffix>[kKmM])?
    """,
    re.X | re.I,
)

SINGLE_PATTERN = re.compile(
    r"""
    [~≈]?\s*
    (?P<val>\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\$?\s?\d+(?:\.\d+)?)
    \s*(?P<suffix>[kKmM])?\s*\+?
    """,
    re.X,
)

def to_number_usd(raw: str, suffix: Optional[str]) -> Optional[float]:
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
        else:
            # ignore 'b'/'t' (market cap scale, not ETH price) or unknown suffix
            return None
    val = v * mult
    if val < MIN_PRICE_USD or val > MAX_PRICE_USD:
        return None
    return val

def sentence_split(text: str) -> List[str]:
    return re.split(r"(?<=[\.\!\?])\s+|\n+", text)

def strip_quotes(text: str) -> str:
    # Remove fenced/inline code and quoted replies
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)
    lines = [ln for ln in (text or "").splitlines() if not ln.lstrip().startswith(">")]
    return "\n".join(lines)

def extract_predictions_from_sentence(s: str) -> List[Dict[str, Any]]:
    # Exclude obvious non-predictions
    if MARKETCAP_TERMS.search(s) or AMOUNT_OF_ETH.search(s) or AVERAGE_SELLING.search(s):
        return []
    # Historical facts w/o forward cue
    if HISTORICAL_ONLY.search(s) and not re.search(r"\b(will|should|could|target|this cycle|next cycle|top|peak|topp?ing|bull run)\b", s, re.I):
        return []
    # Short-term timing / local move phrasing
    if SHORT_TERM_TIME.search(s) or SHORT_TERM_EXTRA.search(s):
        return []
    # Present commentary like "should be at"
    if SHOULD_NOW.search(s):
        return []
    # Negated top/peak statements
    if NEGATED_TOP.search(s):
        return []

    preds: List[Dict[str, Any]] = []

    # Try "between X and Y"
    for m in BETWEEN_PATTERN.finditer(s):
        a_raw = m.group("a")
        b_raw = m.group("b")
        suf = m.group("suffix")
        va = to_number_usd(a_raw, suf)
        vb = to_number_usd(b_raw, suf)
        if va and vb:
            low, high = sorted([va, vb])
            mid = (low + high) / 2.0
            preds.append({
                "type": "range",
                "lower_usd": round(low, 2),
                "upper_usd": round(high, 2),
                "amount_usd": round(mid, 2),
                "raw": m.group(0).strip()
            })

    # Standard ranges like "10-12k"
    for m in RANGE_PATTERN.finditer(s):
        a_raw = m.group("a")
        b_raw = m.group("b")
        suf = m.group("suffix")
        # Support embedded suffixes
        suf_a = None
        suf_b = None
        ma = re.search(r"([kKmM])\s*$", a_raw.strip())
        if ma:
            suf_a = ma.group(1)
        mb = re.search(r"([kKmM])\s*$", b_raw.strip())
        if mb:
            suf_b = mb.group(1)

        va = to_number_usd(a_raw, suf or suf_a)
        vb = to_number_usd(b_raw, suf or suf_b)
        if va and vb:
            low, high = sorted([va, vb])
            mid = (low + high) / 2.0
            preds.append({
                "type": "range",
                "lower_usd": round(low, 2),
                "upper_usd": round(high, 2),
                "amount_usd": round(mid, 2),
                "raw": m.group(0).strip()
            })

    # Singles (only if no ranges found in the sentence)
    if not preds:
        for m in SINGLE_PATTERN.finditer(s):
            raw = m.group("val")
            suf = m.group("suffix")
            val = to_number_usd(raw, suf)
            if not val:
                continue
            # Require a money marker in the raw chunk
            raw_chunk = m.group(0).lower()
            if "$" not in raw_chunk and not re.search(r"\b[km]\b", raw_chunk):
                continue
            preds.append({
                "type": "single",
                "amount_usd": round(val, 2),
                "raw": m.group(0).strip()
            })

    # If the sentence names multiple amounts and uses "at least / possibly / up to / could reach", keep the highest as "top"
    if len(preds) > 1 and re.search(r"\b(at\s+least|possibly|up\s+to|could\s+reach)\b", s, re.I):
        best = None
        for p in preds:
            amt = p.get("amount_usd")
            if isinstance(amt, (int, float)):
                if not best or amt > best.get("amount_usd", 0):
                    best = p
        if best:
            return [best]

    return preds

def parse_comment_for_predictions(comment_body: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    out: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []

    raw = strip_quotes(comment_body or "")
    sentences = [t.strip() for t in sentence_split(raw) if t.strip()]
    if not sentences:
        return out, candidates

    comment_has_eth = any(ETH_TERMS.search(x) for x in sentences)
    comment_has_btc_only = (not comment_has_eth) and any(BTC_ONLY.search(x) for x in sentences)
    if comment_has_btc_only:
        # BTC-only comments: skip fully
        return out, candidates

    prev_had_eth = False

    for sent in sentences:
        s = sent.strip()
        has_eth = bool(ETH_TERMS.search(s)) or prev_had_eth or comment_has_eth
        has_ctx = bool(CONTEXT_WORDS.search(s))

        accepted = False
        reason = ''
        amounts_found: List[float] = []

        if has_eth and has_ctx:
            preds = extract_predictions_from_sentence(s)
            filtered = []
            for p in preds:
                raw_match = p["raw"].lower()
                if "$" in raw_match or re.search(r"\b[km]\b", raw_match):
                    filtered.append(p)
            if filtered:
                for p in filtered:
                    out.append({"sentence": s, "prediction": p})
                    if "amount_usd" in p and isinstance(p["amount_usd"], (int, float)):
                        amounts_found.append(p["amount_usd"])
                accepted = True
            else:
                reason = 'no_money_marker'
        else:
            reason = 'missing_eth_or_context'

        candidates.append({
            "sentence": s,
            "has_eth": has_eth,
            "has_context": has_ctx,
            "amounts_found": amounts_found,
            "accepted": accepted,
            "reason": reason
        })

        prev_had_eth = bool(ETH_TERMS.search(s))

    return out, candidates

# =========================
# Utilities
# =========================
def save_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def summarize(amounts: List[float]) -> Dict[str, Any]:
    if not amounts:
        return {"count": 0, "mean_usd": None, "median_usd": None, "min_usd": None, "max_usd": None}
    return {
        "count": len(amounts),
        "mean_usd": round(mean(amounts), 2),
        "median_usd": round(median(amounts), 2),
        "min_usd": round(min(amounts), 2),
        "max_usd": round(max(amounts), 2),
    }

def compute_consensus(manifest: List[Dict[str, str]], days: int = ROLLING_DAYS) -> Dict[str, Any]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    pooled: List[float] = []
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

def find_latest_eth_daily_thread(reddit: praw.Reddit):
    for submission in reddit.subreddit(SUBREDDIT).search(THREAD_SEARCH_QUERY, sort="new", time_filter="day"):
        title = submission.title or ""
        if "daily general discussion" in title.lower():
            return submission
    return None

# =========================
# Main
# =========================
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

    records: List[Dict[str, Any]] = []
    all_candidates: List[Dict[str, Any]] = []
    seen = set()  # de-dup per comment

    for c in comments:
        author = getattr(c, "author", None)
        author_name = (getattr(author, "name", None) or "").lower()
        if author_name in EXCLUDE_AUTHORS:
            continue
        body = getattr(c, "body", "") or ""
        hits, cand = parse_comment_for_predictions(body)
        all_candidates.extend(cand)
        for h in hits:
            p = h["prediction"]
            if p["type"] == "range":
                amt = p["amount_usd"]
                lower = p["lower_usd"]
                upper = p["upper_usd"]
            else:
                amt = p["amount_usd"]
                lower = None
                upper = None
            # De-dup key: (comment_id, approx amount bucket, start of sentence)
            key = (getattr(c, "id", None), round((amt or 0), -1), (h["sentence"] or "")[:160])
            if key in seen:
                continue
            seen.add(key)

            records.append({
                "amount_usd": amt,
                "lower_usd": lower,
                "upper_usd": upper,
                "raw_match": p["raw"],
                "sentence": h["sentence"],
                "comment_id": getattr(c, "id", None),
                "author": getattr(author, "name", None) if author else None,
                "accept_reason": p["type"],  # 'single' or 'range'
            })

    amounts = [r["amount_usd"] for r in records if isinstance(r["amount_usd"], (int, float)) and r["amount_usd"] > 0]
    summary = summarize(amounts)

    # Date from title if possible
    date_str = None
    try:
        parts = (sub.title or "").split(" - ", 1)
        if len(parts) == 2:
            date_part = parts[1].strip()
            date_part = date_part.split("(")[0].strip()
            dt = datetime.strptime(date_part, "%B %d, %Y")
            date_str = dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

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

    # Save candidates (debug)
    if DEBUG_SAVE_CANDIDATES:
        cand_path = os.path.join(PRED_DIR, f"eth-preds-candidates-{date_str}.jsonl")
        with open(cand_path, "w", encoding="utf-8") as f:
            for item in all_candidates:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"🕵️ Saved candidate log to {cand_path}")

    # Update manifest
    manifest = load_json(MANIFEST_PATH, [])
    manifest = [m for m in manifest if m.get("date") != date_str]
    manifest.append({"date": date_str, "file": day_file})
    manifest = sorted(manifest, key=lambda x: x["date"])
    save_json(MANIFEST_PATH, manifest)
    print("📄 Manifest updated")

    # Update consensus
    consensus = compute_consensus(manifest, days=ROLLING_DAYS)
    save_json(CONSENSUS_PATH, consensus)
    print(f"📈 Consensus updated ({ROLLING_DAYS}d window)")

if __name__ == "__main__":
    main()
