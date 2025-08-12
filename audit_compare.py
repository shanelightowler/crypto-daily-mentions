import os, json, random
from collections import Counter, defaultdict
from daily_mentions import (
    fetch_coins, build_keyword_processor, count_mentions_in_text,
    # We reuse your strict functions and config from daily_mentions.py
)
# Loose-mode helpers
from flashtext import KeywordProcessor

# Symbols to compare
TARGETS = ["BTC","ETH","XRP","SOL","ADA","LINK","USDC","MOON"]

def load_corpus(corpus_path):
    items = []
    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                items.append(json.loads(line))
            except Exception:
                pass
    return items

def build_loose_matcher(coins):
    # Allow bare symbol and full name for all coins; case-insensitive
    kp = KeywordProcessor(case_sensitive=False)
    # aliases map to uppercase symbol
    for c in coins:
        cid = c.get("id","")
        sym = (c.get("symbol") or "").strip()
        name = (c.get("name") or "").strip()
        if not cid or not sym: continue
        sym_low = sym.lower()
        sym_up = sym.upper()
        # $symbol
        kp.add_keyword(f"${sym_low}", sym_up)
        # bare symbol
        kp.add_keyword(sym_low, sym_up)
        # full name as a whole-phrase keyword
        if name and len(name) >= 3:
            kp.add_keyword(name.lower(), sym_up)
    return kp

def count_loose_in_text(kp, text):
    # No stripping, no bot filtering, count every occurrence
    hits = kp.extract_keywords(text or "", span_info=False)
    c = Counter()
    for sym in hits:
        c[sym] += 1
    return c

def run_strict(corpus_items):
    # Use your strict matcher and per-comment unique counting
    coins = fetch_coins()
    kp, id_to_meta, canonical_name_by_symbol = build_keyword_processor(coins)
    total = Counter()
    for item in corpus_items:
        c = count_mentions_in_text(kp, item.get("body",""))
        total.update(c)
    return total

def run_loose(corpus_items):
    # Loose: occurrence counting, full names allowed, bare allowed for all, no stripping
    coins = fetch_coins()
    kp = build_loose_matcher(coins)
    total = Counter()
    for item in corpus_items:
        total.update(count_loose_in_text(kp, item.get("body","")))
    return total

def main():
    date = os.getenv("AUDIT_DATE")  # e.g., 2025-08-11
    if not date:
        raise SystemExit("Set AUDIT_DATE=YYYY-MM-DD and ensure comments-YYYY-MM-DD.jsonl exists")
    corpus_path = f"comments-{date}.jsonl"
    if not os.path.exists(corpus_path):
        raise SystemExit(f"Missing {corpus_path}. Run backfill to generate the corpus first.")
    corpus = load_corpus(corpus_path)

    strict_counts = run_strict(corpus)
    loose_counts = run_loose(corpus)

    print(f"Corpus: {len(corpus)} comments")
    print("Symbol,Strict,Loose")
    for sym in TARGETS:
        print(f"{sym},{strict_counts.get(sym,0)},{loose_counts.get(sym,0)}")

if __name__ == "__main__":
    main()
