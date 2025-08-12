import os
import re
import json
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

# Only allow bare (no $) mentions for these symbols, and only when typed in ALL CAPS.
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

# Map canonical symbols to the preferred CoinGecko id and display name
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

def normalize_text(s: str) -> str:
    s = re.sub(r"https?://\S+", " ", s)  # remove URLs
    s = s.replace("&amp;", "&")
    return s

def build_keyword_processor(coins):
    """
    Returns:
      - kp: KeywordProcessor
      - id_to_meta: dict id -> {symbol, name}
      - canonical_name_by_symbol: dict SYMBOL -> display name
    Strategy:
      - Always add $symbol for all coins.
      - Add bare symbol only for UNAMBIGUOUS_BARE_SYMBOLS.
      - Do NOT add full names (reduces false positives).
      - Ensure canonical symbols (BTC, ETH, …) claim their aliases first.
    """
    kp = KeywordProcessor(case_sensitive=False)
    id_to_meta = {}
    canonical_name_by_symbol = {sym: name for sym, (_, name) in CANONICAL_SYMBOLS.items()}
    seen_aliases = set()

    # Build a quick lookup: id -> coin dict and symbol -> list of ids
    coins_by_id = {c.get("id",""): c for c in coins if c.get("id")}
    def add_aliases_for_coin(coin, allow_bare=False, preferred=False):
      # add $symbol; optionally bare symbol
      cid = coin.get("id")
      sym = (coin.get("symbol") or "").strip().lower()
      name = (coin.get("name") or "").strip()
      if not cid or not sym: return
      if not sym.isalnum() or len(sym) < 2: return

      # Save meta
      if cid not in id_to_meta:
          id_to_meta[cid] = {"symbol": sym, "name": name}

      # $symbol alias
      dollar_alias = f"${sym}"
      if dollar_alias not in seen_aliases:
          kp.add_keyword(dollar_alias, {"id": cid, "symbol": sym.upper(), "alias": dollar_alias})
          seen_aliases.add(dollar_alias)

      # Bare symbol alias (only for whitelisted)
      if allow_bare:
          if sym not in seen_aliases:
              kp.add_keyword(sym, {"id": cid, "symbol": sym.upper(), "alias": sym})
              seen_aliases.add(sym)

    # 1) Add canonical symbols first so they own $BTC, BTC, etc.
    for sym, (cid_pref, _disp) in CANONICAL_SYMBOLS.items():
        coin = coins_by_id.get(cid_pref)
        if coin:
            allow_bare = sym in UNAMBIGUOUS_BARE_SYMBOLS
            add_aliases_for_coin(coin, allow_bare=allow_bare, preferred=True)

    # 2) Add remaining coins: $symbol only; bare only for whitelist (if not already taken)
    for c in coins:
        cid = c.get("id","")
        sym = (c.get("symbol") or "").strip().upper()
        if not cid or not sym: continue
        allow_bare = sym in UNAMBIGUOUS_BARE_SYMBOLS
        add_aliases_for_coin(c, allow_bare=allow_bare, preferred=False)

    return kp, id_to_meta, canonical_name_by_symbol

def count_mentions_in_text(kp: KeywordProcessor, text: str):
    """
    Extract matches and apply acceptance rules:
      - Always accept $SYMBOL matches.
      - For bare SYMBOL, accept only if the matched text is ALL CAPS (e.g., BTC), to avoid 'the', 'for', 'you', etc.
    Returns Counter of SYMBOL -> count.
    """
    text = normalize_text(text)
    hits = kp.extract_keywords(text, span_info=True)  # returns (payload, start, end)
    counts = Counter()
    for payload, start, end in hits:
        sym = payload["symbol"]  # already uppercased
        alias = payload["alias"] # e.g., '$eth' or 'eth'
        matched = text[start:end]
        if alias.startswith("$"):
            counts[sym] += 1
        else:
            # bare symbol: require ALL CAPS in the original text
            if matched.strip().upper() == matched.strip() and len(matched.strip()) >= 3:
                counts[sym] += 1
            # else ignore
    return counts

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
    kp, id_to_meta, canonical_name_by_symbol = build_keyword_processor(coins)
    print("Keyword processor ready.")

    # Fetch all comments
    print("Fetching comments...")
    daily_thread.comments.replace_more(limit=None)
    comments = daily_thread.comments.list()
    print(f"Total comments: {len(comments)}")

    # Count mentions by SYMBOL
    counts_by_symbol = Counter()
    for c in comments:
        c_counts = count_mentions_in_text(kp, c.body)
        counts_by_symbol.update(c_counts)

    # Prepare output: dict for site + list for richer data
    results_by_symbol = dict(sorted(counts_by_symbol.items(), key=lambda x: x[1], reverse=True))
    results_list = []
    for sym, count in results_by_symbol.items():
        # Pick a friendly name for known symbols; otherwise leave blank to avoid mislabeling
        name = canonical_name_by_symbol.get(sym, "")
        results_list.append({"symbol": sym, "name": name, "count": count})

    output = {
        "thread_title": daily_thread.title,
        "thread_url": f"https://www.reddit.com{daily_thread.permalink}",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "results": results_by_symbol,   # dict: SYMBOL -> count
        "results_list": results_list    # list for display
    }

    # Date-stamped filename
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    daily_filename = f"data-{today_str}.json"

    # Save files
    with open(daily_filename, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    # Update manifest.json
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
