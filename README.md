# crypto-daily-mentions
Tracking crypto daily mentions

Daily Crypto Mentions — How counts are calculated (semi-loose profile)

What this site does
- It reads the Daily Crypto Discussion thread from r/CryptoCurrency.
- It counts how many times each coin’s ticker is mentioned in the comments.
- Data files are published to this repo and displayed on the website.

Data files we publish
- data.json — latest day
- data-YYYY-MM-DD.json — a specific day
- manifest.json — a list of all dates/files (used by the date dropdown)
- comments-YYYY-MM-DD.jsonl — the raw comment text for that day (only produced by the Backfill workflow so we can audit)

What “semi-loose” counting means
- We count every occurrence. If a comment says “BTC BTC ETH”, that adds 2 for BTC and 1 for ETH.
- $SYMBOL always counts (for example $btc, $ETH).
- Bare symbol without $:
  - We allow it for a large whitelist of well-known tickers (see list below), in any case (btc, BTC, Btc).
  - For tickers not on the whitelist, you must type the $ (e.g., $ONE, $GAS) for it to count.
- We do NOT count full names (“bitcoin”, “ethereum”, “safe”, “home”, etc.) to avoid false positives.
- We clean the text before counting:
  - Remove quoted lines (those that start with “>”) and code blocks/backticks.
  - Remove URLs.
- We skip typical bot/automoderator comments.

Why this approach
- It captures real mentions (including repeated mentions).
- It avoids noise from common English words.
- It prevents quoted text and bots from inflating numbers.

Whitelist (tickers allowed without $)
BTC, ETH, BNB, SOL, ADA, XRP, DOGE, TRX, TON, AVAX,
DOT, MATIC, LTC, BCH, XLM, SHIB, LINK, ATOM, ETC, XMR,
FIL, ICP, APT, SUI, ARB, OP, INJ, NEAR, ALGO, HBAR,
AAVE, UNI, LDO, RPL, MKR, COMP, SNX, CRV, CVX, GMX,
DYDX, IMX, SAND, MANA, APE, GRT, FET, RNDR, KAS, TIA,
SEI, PEPE, FLOKI, BONK, WIF, JUP, PYTH, JTO, STRK, BLUR,
CHZ, ENJ, ZRX, BAT, ZEC, DASH, KAVA, KDA, KSM, ROSE,
RUNE, EGLD, NEO, GALA, SFP, CAKE, STX, MINA, AR, ASTR,
OSMO, SKL, CFX, XDC, TFUEL, THETA, BTT, OKB, HT, CRO,
QNT, RSR, NEXO

What each JSON file contains
- thread_title: the title of the Reddit thread
- thread_url: a link to the thread
- generated_at_utc: when the data file was generated (UTC)
- results: a dictionary of SYMBOL -> total mentions
- results_list: a list of {symbol, name, count} rows, sorted by mentions

How the site updates
- Daily Mentions Update workflow: runs every day; fetches the latest thread; writes data.json and data-YYYY-MM-DD.json; updates manifest.json.
- Backfill One Thread workflow (manual):
  1) In GitHub, go to the Actions tab.
  2) Click “Backfill One Thread”.
  3) Click “Run workflow” and paste the Reddit Daily thread URL.
  4) It writes data-YYYY-MM-DD.json and comments-YYYY-MM-DD.jsonl (for auditing) and updates manifest.json.

FAQ
- Why don’t you count full names like “bitcoin”?
  Full names often collide with ordinary words (e.g., “safe”, “flow”, “core”). To keep data clean, we require $SYMBOL (or a whitelisted ticker) instead.

- Why are my counts lower/higher than other sites?
  Sites differ on whether they count every occurrence vs. once per comment, whether they allow full names, and whether they skip bots/quotes. This site uses “semi-loose” settings to balance coverage and quality.

- Can I change the rules?
  Yes. In daily_mentions.py:
    COUNT_MODE = "occurrence" or "per_comment"
    EXCLUDE_BOTS = True/False
    STRIP_QUOTES_AND_CODE = True/False
    UNAMBIGUOUS_BARE_SYMBOLS = { ... } (edit whitelist)
  After editing, run the daily workflow (or backfill) to regenerate the data.
