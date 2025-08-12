import os
import re
import json
import requests
from datetime import datetime, timedelta
from collections import Counter
import praw
from flashtext import KeywordProcessor

# =========================
# Config (semi-loose profile + top-coin full names)
# =========================
USER_AGENT = "crypto-mention-counter"
COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list?include_platform=false"
COIN_CACHE_FILE = "coins_cache.json"
COIN_CACHE_TTL_DAYS = 7

# Count every occurrence (semi-loose). Change to "per_comment" for strict mode.
COUNT_MODE = "occurrence"  # "occurrence" or "per_comment"

# Skip typical bots/moderators
EXCLUDE_BOTS = True
BOT_NAME_PATTERNS = ("automoderator", "bot", "tip", "price", "moon", "giveaway", "airdrop")

# Clean text before matching
STRIP_QUOTES_AND_CODE = True  # remove > quotes and code blocks
# We always strip URLs in normalize_text()

# Bare (no $) matches allowed for these symbols, in ANY case (semi-loose).
UNAMBIGUOUS_BARE_SYMBOLS = {
    "BTC","ETH","BNB","SOL","ADA","XRP","DOGE","TRX","TON","AVAX",
    "DOT","MATIC","LTC","BCH","XLM","SHIB","LINK","ATOM","ETC","XMR",
    "FIL","ICP","APT","SUI","ARB","OP","INJ","NEAR","ALGO","HBAR",
    "AAVE","UNI","LDO","RPL","MKR","COMP","SNX","CRV","CVX","GMX",
    "DYDX","IMX","SAND","MANA","APE","GRT","FET","RNDR","KAS","TIA",
    "SEI","PEPE","FLOKI","BONK","WIF","JUP","PYTH","JTO","STRK","BLUR",
    "CHZ","ENJ","ZRX","BAT","ZEC","DASH","KAVA","KDA","KSM","ROSE",
    "RUNE","EGLD","NEO","GALA","SFP","CAKE","STX","MINA","AR","ASTR",
    "OSMO","SKL","CFX","XDC","TFUEL","THETA","BTT","OKB","HT","CRO",
    "QNT","RSR","NEXO"
}

# In semi-loose mode, allow the whole whitelist to match in any case.
RELAXED_COINS = UNAMBIGUOUS_BARE_SYMBOLS

# Allow full-name matching ONLY for these top coins (safe names that won't collide with ordinary words).
ALLOW_FULL_NAMES_FOR = {
    "BTC","ETH","SOL","ADA","XRP","DOGE","LINK","BNB","LTC","DOT",
    "AVAX","MATIC","TRX","ATOM","XLM","BCH","ETC","SHIB"
}

# Optional extra full-name aliases (safe synonyms/brands)
EXTRA_FULLNAME_ALIASES = {
    "BTC": ["bitcoin"],
    "ETH": ["ethereum"],
    "SOL": ["solana"],
    "ADA": ["cardano"],
    "XRP": ["ripple"],
    "DOGE": ["dogecoin"],
    "LINK": ["chainlink"],
    "BNB": ["binance coin","binancecoin"],
    "LTC": ["litecoin"],
    "DOT": ["polkadot"],
    "AVAX": ["avalanche"],
    "MATIC": ["polygon"],  # CoinGecko's name includes "(MATIC)"; this ensures "polygon" matches
    "TRX": ["tron"],
    "ATOM": ["cosmos"],
    "XLM": ["stellar"],
    "BCH": ["bitcoin cash"],
    "ETC": ["ethereum classic"],
    "SHIB": ["shiba inu"]
    # Note: we intentionally avoid generic/ambiguous words like "ton", "near", "flow", etc.
}

# Canonical symbol -> (coingecko id, display name) for cleaner names in UI
CANONICAL_SYMBOLS = {
    "BTC": ("bitcoin", "Bitcoin"),
    "ETH": ("ethereum", "Ethereum"),
    "SOL": ("solana", "Solana"),
    "ADA": ("cardano", "Cardano"),
    "DOGE": ("dogecoin", "Dogecoin"),
    "LINK": ("chainlink", "Chainlink"),
    "XRP": ("ripple", "XRP"),
    "LTC": ("litecoin", "Litecoin"),
    "BCH": ("bitcoin-cash", "Bitcoin Cash"),
    "XLM": ("stellar", "Stellar"),
    "DOT": ("polkadot", "Polkadot"),
    "AVAX": ("avalanche-2", "Avalanche"),
    "MATIC": ("matic-network", "Polygon (MATIC)"),
    "TRX": ("tron", "TRON"),
    "ATOM": ("cosmos", "Cosmos"),
    "ETC": ("ethereum-classic", "Ethereum Classic"),
    "UNI": ("uniswap", "Uniswap"),
    "AAVE": ("aave", "Aave"),
    "ARB": ("arbitrum", "Arbitrum"),
    "OP": ("optimism", "Optimism"),
    "INJ": ("injective-protocol", "Injective"),
    "SUI": ("sui", "Sui"),
    "APT": ("aptos", "Aptos"),
    "TON": ("toncoin", "Toncoin"),
    "FTM": ("fantom", "Fantom"),
    "ALGO": ("algorand", "Algorand"),
    "HBAR": ("hedera-hashgraph", "Hedera"),
    "RUNE": ("thorchain", "THORChain"),
    "NEO": ("neo", "NEO"),
    "EGLD": ("elrond-erd-2", "MultiversX (EGLD)"),
    "KAS": ("kaspa", "Kaspa"),
    "TIA": ("celestia", "Celestia"),
    "SEI": ("sei-network", "Sei"),
    "NEAR": ("near", "NEAR"),
    "BNB": ("binancecoin", "BNB"),
    "SHIB": ("shiba-inu", "Shiba Inu"),
    "XMR": ("monero", "Monero"),
    "FIL": ("filecoin", "Filecoin"),
    "ICP": ("internet-computer", "Internet Computer"),
    "GRT": ("the-graph", "The Graph"),
    "FET": ("fetch-ai", "Fetch.ai"),
    "LDO": ("lido-dao", "Lido DAO"),
    "RPL": ("rocket-pool", "Rocket Pool"),
    "MKR": ("maker", "Maker"),
    "COMP": ("compound-governance-token", "Compound"),
    "SNX": ("synthetix-network-token", "Synthetix"),
    "CRV": ("curve-dao-token", "Curve DAO"),
    "CVX": ("convex-finance", "Convex Finance"),
    "GMX": ("gmx", "GMX"),
    "DYDX": ("dydx", "dYdX"),
    "IMX": ("immutable-x", "Immutable"),
    "SAND": ("the-sandbox", "The Sandbox"),
    "MANA": ("decentraland", "Decentraland"),
    "APE": ("apecoin", "ApeCoin"),
    "RNDR": ("render-token", "Render"),
    "PEPE": ("pepe", "PEPE"),
    "FLOKI": ("floki", "Floki"),
    "BONK": ("bonk", "BONK"),
    "WIF": ("dogwifcoin", "dogwifhat"),
    "JUP": ("jupiter-exchange-solana", "Jupiter"),
    "PYTH": ("pyth-network", "Pyth Network"),
    "JTO": ("jito-governance-token", "Jito"),
    "STRK": ("starknet", "Starknet"),
    "BLUR": ("blur", "Blur"),
    "CHZ": ("chiliz", "Chiliz"),
    "ENJ": ("enjincoin", "Enjin"),
    "ZRX": ("0x", "0x"),
    "BAT": ("basic-attention-token", "Basic Attention Token"),
    "ZEC": ("zcash", "Zcash"),
    "DASH": ("dash", "Dash"),
    "KAVA": ("kava", "Kava"),
    "KDA": ("kadena", "Kadena"),
    "KSM": ("kusama", "Kusama"),
    "ROSE": ("oasis-network", "Oasis Network"),
    "STX": ("stacks", "Stacks"),
    "MINA": ("mina-protocol", "Mina"),
    "AR": ("arweave", "Arweave"),
    "ASTR": ("astar", "Astar"),
    "OSMO": ("osmosis", "Osmosis"),
    "SKL": ("skale", "SKALE"),
    "CFX": ("conflux-token", "Conflux"),
    "XDC": ("xinfin-network", "XDC Network"),
    "TFUEL": ("theta-fuel", "Theta Fuel"),
    "THETA": ("theta-token", "Theta Network"),
    "BTT": ("bittorrent", "BitTorrent"),
    "OKB": ("okb", "OKB"),
    "HT": ("huobi-token", "HT"),
    "CRO": ("crypto-com-chain", "Cronos"),
    "QNT": ("quant-network", "Quant"),
    "RSR": ("reserve-rights-token", "Reserve Rights"),
    "NEXO": ("nexo", "Nexo")
}

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
    resp = requests.get(COINGECKO_LIST_URL, timeout=30)
    resp.raise_for_status()
    coins = resp.json()
    with open(COIN_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"_fetched_at": datetime.utcnow().isoformat(), "coins": coins}, f)
    return coins

def strip_quotes_and_code(s: str) -> str:
    # Remove fenced code blocks ```...```
    s = re.sub(r"```.*?```", " ", s, flags=re.DOTALL)
    # Remove inline code `...`
    s = re.sub(r"`[^`]*`", " ", s)
    # Remove quoted lines starting with >
    s = "\n".join([line for line in s.splitlines() if not line.lstrip().startswith(">")])
    return s

def normalize_text(s: str) -> str:
    if STRIP_QUOTES_AND_CODE:
        s = strip_quotes_and_code(s)
    s = re.sub(r"https?://\S+", " ", s)  # remove URLs
    s = s.replace("&amp;", "&")
    return s

def build_keyword_processor(coins):
    """
    Returns:
      - kp: KeywordProcessor (case-insensitive)
      - id_to_meta: dict id -> {symbol, name}
      - canonical_name_by_symbol: dict SYMBOL -> display name
    Strategy:
      - Add $symbol for all coins.
      - Add bare symbol only for UNAMBIGUOUS_BARE_SYMBOLS (whitelist).
      - Add full names ONLY for ALLOW_FULL_NAMES_FOR (plus safe synonyms).
      - Canonical symbols are registered first, so they claim $BTC, BTC, and names.
    """
    kp = KeywordProcessor(case_sensitive=False)
    id_to_meta = {}
    canonical_name_by_symbol = {sym: name for sym, (_, name) in CANONICAL_SYMBOLS.items()}
    seen_aliases = set()

    coins_by_id = {c.get("id", ""): c for c in coins if c.get("id")}

    def add_keyword(alias, cid, sym_up):
        if alias in seen_aliases:
            return
        kp.add_keyword(alias, {"id": cid, "symbol": sym_up, "alias": alias})
        seen_aliases.add(alias)

    def add_coin_aliases(coin, allow_bare=False, allow_names=False, extras=None):
        cid = coin.get("id")
        sym = (coin.get("symbol") or "").strip().lower()
        name = (coin.get("name") or "").strip()
        if not cid or not sym:
            return
        if not sym.isalnum() or len(sym) < 2:
            return

        id_to_meta.setdefault(cid, {"symbol": sym, "name": name})
        sym_up = sym.upper()

        # $symbol
        add_keyword(f"${sym}", cid, sym_up)

        # bare symbol
        if allow_bare:
            add_keyword(sym, cid, sym_up)

        # full name(s) for selected top coins only
        if allow_names:
            base = name.lower()
            if base and len(base) >= 3:
                add_keyword(base, cid, sym_up)
            for extra in (extras or []):
                ex = extra.strip().lower()
                if ex and len(ex) >= 3:
                    add_keyword(ex, cid, sym_up)

    # Canonical coins first (so they own their aliases)
    for sym, (cid, _disp) in CANONICAL_SYMBOLS.items():
        coin = coins_by_id.get(cid)
        if coin:
            allow_bare = sym in UNAMBIGUOUS_BARE_SYMBOLS
            allow_names = sym in ALLOW_FULL_NAMES_FOR
            extras = EXTRA_FULLNAME_ALIASES.get(sym, [])
            add_coin_aliases(coin, allow_bare=allow_bare, allow_names=allow_names, extras=extras)

    # Then the rest
    for c in coins:
        sym_up = (c.get("symbol") or "").strip().upper()
        if not sym_up:
            continue
        allow_bare = sym_up in UNAMBIGUOUS_BARE_SYMBOLS
        allow_names = sym_up in ALLOW_FULL_NAMES_FOR
        extras = EXTRA_FULLNAME_ALIASES.get(sym_up, [])
        add_coin_aliases(c, allow_bare=allow_bare, allow_names=allow_names, extras=extras)

    return kp, id_to_meta, canonical_name_by_symbol

def should_skip_author(author) -> bool:
    if not EXCLUDE_BOTS:
        return False
    if author is None:
        return False
    name = str(getattr(author, "name", "") or "").lower()
    if name == "automoderator":
        return True
    return any(part in name for part in BOT_NAME_PATTERNS)

def count_mentions_in_text(kp: KeywordProcessor, text: str):
    """
    Semi-loose acceptance:
      - Always accept $SYMBOL.
      - For bare matches (symbol or name):
          - Accept if symbol is in RELAXED_COINS (any case).
          - Else (not typical) accept only ALL-CAPS words len>=3.
    Returns Counter of SYMBOL -> count for this comment (occurrences or per-comment unique).
    """
    text = normalize_text(text)
    hits = kp.extract_keywords(text, span_info=True)
    per_hit_counts = Counter()
    for payload, start, end in hits:
        sym = payload["symbol"]  # uppercased
        alias = payload["alias"] # e.g., '$eth', 'eth', 'bitcoin', 'polygon'
        matched = text[start:end]
        if alias.startswith("$"):
            per_hit_counts[sym] += 1
        else:
            if sym in RELAXED_COINS:
                per_hit_counts[sym] += 1
            else:
                token = matched.strip()
                if token and token.upper() == token and len(token) >= 3:
                    per_hit_counts[sym] += 1

    if COUNT_MODE == "per_comment":
        collapsed = Counter({sym: 1 for sym in per_hit_counts})
        return collapsed
    else:
        return per_hit_counts

# =========================
# Main: fetch thread, count, save
# =========================
def find_latest_daily_thread(reddit):
    for submission in reddit.subreddit("CryptoCurrency").search(
        "Daily Crypto Discussion", sort="new", time_filter="day"
    ):
        if "Daily Crypto Discussion" in submission.title:
            return submission
    return None

def main():
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

    # Build matcher
    print("Fetching coin list...")
    coins = fetch_coins()
    kp, id_to_meta, canonical_name_by_symbol = build_keyword_processor(coins)

    # Fetch comments
    print("Fetching comments...")
    daily_thread.comments.replace_more(limit=None)
    comments = daily_thread.comments.list()
    print(f"Total comments: {len(comments)}")

    # Count
    counts_by_symbol = Counter()
    for c in comments:
        if should_skip_author(getattr(c, "author", None)):
            continue
        counts_by_symbol.update(count_mentions_in_text(kp, c.body or ""))

    # Output
    results_by_symbol = dict(sorted(counts_by_symbol.items(), key=lambda x: x[1], reverse=True))
    results_list = [
        {"symbol": sym, "name": canonical_name_by_symbol.get(sym, ""), "count": count}
        for sym, count in results_by_symbol.items()
    ]

    output = {
        "thread_title": daily_thread.title,
        "thread_url": f"https://www.reddit.com{daily_thread.permalink}",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "results": results_by_symbol,
        "results_list": results_list
    }

    # Save with today's date and as latest
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    daily_filename = f"data-{today_str}.json"
    with open(daily_filename, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    # Update manifest
    manifest = []
    if os.path.exists("manifest.json"):
        with open("manifest.json", "r", encoding="utf-8") as f:
            manifest = json.load(f)
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
