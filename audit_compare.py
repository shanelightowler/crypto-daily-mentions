import os, json
from collections import Counter
from flashtext import KeywordProcessor

# Import your strict logic and config
from daily_mentions import (
    fetch_coins,
    build_keyword_processor,
    count_mentions_in_text,
)

# Try to mirror your bot-filter setting using the same patterns if available
try:
    from daily_mentions import EXCLUDE_BOTS as DM_EXCLUDE_BOTS
except Exception:
    DM_EXCLUDE_BOTS = True
try:
    from daily_mentions import BOT_NAME_PATTERNS as DM_BOT_NAME_PATTERNS
except Exception:
    DM_BOT_NAME_PATTERNS = ("automoderator", "bot", "tip", "price", "moon", "giveaway", "airdrop")

EXCLUDE_BOTS = DM_EXCLUDE_BOTS
BOT_NAME_PATTERNS = DM_BOT_NAME_PATTERNS

TARGETS = ["BTC","ETH","XRP","SOL","ADA","LINK","USDC","MOON"]

def load_corpus(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                items.append(json.loads(line))
            except Exception:
                pass
    return items

def should_skip_author_name(name):
    if not EXCLUDE_BOTS:
        return False
    if not name:
        return False
    name = str(name).lower()
    if name == "automoderator":
        return True
    return any(part in name for part in BOT_NAME_PATTERNS)

# Loose matcher: allow $symbol, bare symbol, and full name for all coins; count every occurrence
def build_loose_matcher(coins):
    kp = KeywordProcessor(case_sensitive=False)
    for c in coins:
        cid = c.get("id", "")
        sym = (c.get("symbol") or "").strip()
        name = (c.get("name") or "").strip()
        if not cid or not sym:
            continue
        sym_low = sym.lower()
        sym_up = sym.upper()
        kp.add_keyword(f"${sym_low}", sym_up)
        kp.add_keyword(sym_low, sym_up)
        if name and len(name) >= 3:
            kp.add_keyword(name.lower(), sym_up)
    return kp

def count_loose_in_text(kp, text):
    hits = kp.extract_keywords(text or "", span_info=False)
    c = Counter()
    for sym in hits:
        c[sym] += 1
    return c

def run_strict(corpus_items):
    coins = fetch_coins()
    kp, id_to_meta, canonical_name_by_symbol = build_keyword_processor(coins)
    total = Counter()
    for item in corpus_items:
        if should_skip_author_name(item.get("author")):
            continue
        total.update(count_mentions_in_text(kp, item.get("body", "")))
    return total

def run_loose(corpus_items):
    coins = fetch_coins()
    kp = build_loose_matcher(coins)
    total = Counter()
    for item in corpus_items:
        # loose mode: do NOT skip bots; count every occurrence; no text stripping
        total.update(count_loose_in_text(kp, item.get("body", "")))
    return total

def main():
    date = os.getenv("AUDIT_DATE", "").strip()
    if not date:
        raise SystemExit("Set AUDIT_DATE=YYYY-MM-DD (and ensure comments-YYYY-MM-DD.jsonl exists).")
    corpus_path = f"comments-{date}.jsonl"
    if not os.path.exists(corpus_path):
        raise SystemExit(f"Missing {corpus_path}. Run the Backfill One Thread workflow first to create it.")

    corpus = load_corpus(corpus_path)
    strict_counts = run_strict(corpus)
    loose_counts = run_loose(corpus)

    print(f"Corpus: {len(corpus)} comments")
    print("Symbol,Strict,Loose")
    for sym in TARGETS:
        print(f"{sym},{strict_counts.get(sym,0)},{loose_counts.get(sym,0)}")

    # Also show top 15 by each mode for a broader view
    def topn(counter, n=15):
        return sorted(counter.items(), key=lambda x: x[1], reverse=True)[:n]

    print("\nTop 15 (Strict):")
    for sym, n in topn(strict_counts):
        print(f"{sym}: {n}")

    print("\nTop 15 (Loose):")
    for sym, n in topn(loose_counts):
        print(f"{sym}: {n}")

if __name__ == "__main__":
    main()
