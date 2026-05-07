"""
Scrapes US Congressional stock trade disclosures from https://www.capitoltrades.com/trades.

Pivot history (2026-04-20):
- jeremiak/* GitHub JSON repos: 404
- timothycarambat/senate-stock-watcher-data: abandoned 2021-03, data only through 2020-12
- house-stock-watcher-data S3 + housestockwatcher.com API: 403 / connection refused
- Capitol Trades: fresh (updated daily), both chambers, robots.txt Allow: /

Parsing strategy:
  Each <tr>...</tr> trade row, after stripping <svg>, contains ~16 text tokens in fixed order:
    [0] politician name, [1] party, [2] chamber, [3] state,
    [4] issuer name, [5] ticker ("VZ:US" or "N/A"),
    [6] pub_date_dm ("17 Apr"), [7] pub_date_year ("2026"),
    [8] tx_date_dm ("7 Apr"), [9] tx_date_year ("2026"),
    [10] filing_delay ("10 days"), [11] owner ("Undisclosed"/"Spouse"/...),
    [12] tx_type ("buy"/"sell"/"receive"/"exchange"), [13] amount_range ("100K–250K"),
    [14] price ("$48.62"), [15] link label.

Behavior:
  - Iterates /trades?page=N from newest, stops when tx_date < today - window_days
  - Caches to history/politician_trades_raw.json
  - Graceful degradation: any exception keeps prior cache and returns 0
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _log(msg: str) -> None:
    print(msg, flush=True)


CAPITOL_TRADES_URL = "https://www.capitoltrades.com/trades"
USER_AGENT = "Mozilla/5.0 (compatible; AI-Trading-Assistant-v2/politician-trades-fetcher)"
DEFAULT_WINDOW_DAYS = 90
POLITE_DELAY_SECONDS = 1.0
MAX_PAGES_SAFETY = 400

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_CACHE_PATH = os.path.join(PROJECT_DIR, "history", "politician_trades_raw.json")

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
_SVG_RE = re.compile(r"<svg.*?</svg>", re.DOTALL)
_TEXT_TOKEN_RE = re.compile(r">([^<]{2,})<")
_TRADE_ID_RE = re.compile(r"/trades/(\d+)")
_POLITICIAN_ID_RE = re.compile(r"/politicians/([A-Z]\d+)")
_ISSUER_ID_RE = re.compile(r"/issuers/(\d+)")

_MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _parse_amount(raw: str) -> tuple[int | None, int | None]:
    """Parse '100K–250K', '<1K', '1K–15K', 'over 50M' into (min_usd, max_usd)."""
    if not raw:
        return None, None
    r = raw.replace(",", "").replace("$", "").strip()

    def to_usd(tok: str) -> int | None:
        tok = tok.strip().replace("<", "").replace(">", "")
        m = re.match(r"([0-9.]+)\s*([KMB]?)", tok, re.IGNORECASE)
        if not m:
            return None
        try:
            num = float(m.group(1))
        except ValueError:
            return None
        mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "": 1}.get(m.group(2).upper(), 1)
        return int(num * mult)

    if re.match(r"<\s*1\s*k", r, re.IGNORECASE):
        return 0, 1_000
    if re.search(r"over\s*50m", r, re.IGNORECASE):
        return 50_000_000, None

    parts = re.split(r"[\u2013\u2014\-]", r, maxsplit=1)
    if len(parts) == 2:
        return to_usd(parts[0]), to_usd(parts[1])
    single = to_usd(r)
    return single, single


def _parse_date(day_month: str, year: str) -> str | None:
    """Convert ('17 Apr', '2026') → '2026-04-17' ISO. Return None on failure."""
    if not day_month or not year:
        return None
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3})", day_month.strip())
    if not m:
        return None
    day = int(m.group(1))
    month = _MONTH_MAP.get(m.group(2).title())
    if not month:
        return None
    try:
        yr = int(year.strip())
    except ValueError:
        return None
    try:
        return f"{yr:04d}-{month:02d}-{day:02d}"
    except Exception:
        return None


def _parse_row(row_html: str) -> dict | None:
    # Skip header row (no trade id)
    trade_ids = _TRADE_ID_RE.findall(row_html)
    if not trade_ids:
        return None
    trade_id = trade_ids[0]

    politician_match = _POLITICIAN_ID_RE.search(row_html)
    issuer_match = _ISSUER_ID_RE.search(row_html)
    if not politician_match:
        return None

    # Strip SVGs and extract visible text tokens in order (keep single-char for robustness)
    clean = _SVG_RE.sub("", row_html)
    raw_tokens = [html_lib.unescape(t.strip()) for t in _TEXT_TOKEN_RE.findall(clean)]
    tokens = [t for t in raw_tokens if t and not t.startswith("Goto trade")]

    if len(tokens) < 10:
        return None

    # Positions 0-9 are stable (politician/party/chamber/state/issuer/ticker/pub_date x2/tx_date x2).
    # From position 10 onward the order shifts (filing delay number may or may not be a separate token),
    # so we match by content.
    _OWNER_SET = {"Undisclosed", "Spouse", "Dependent", "Joint", "Self", "Child"}
    _TXTYPE_SET = {"buy", "sell", "receive", "exchange"}
    _PARTY_SET = {"Democrat", "Republican", "Independent", "Other"}
    _CHAMBER_SET = {"House", "Senate"}
    _AMOUNT_PAT = re.compile(r"^(<\s*1\s*K|[0-9.,]+[KMB]?[\u2013\u2014\-][0-9.,]+[KMB]?|over\s*50M)$", re.IGNORECASE)
    _PRICE_PAT = re.compile(r"^\$[0-9.,]+$")

    try:
        politician_name = re.sub(r"\s+", " ", tokens[0]).strip()
        party = tokens[1] if tokens[1] in _PARTY_SET else None
        chamber = tokens[2] if tokens[2] in _CHAMBER_SET else None
        state = tokens[3] if len(tokens[3]) == 2 and tokens[3].isupper() else None
        issuer_name = tokens[4]

        ticker_raw = tokens[5]
        if ":" in ticker_raw:
            ticker, country = ticker_raw.split(":", 1)
        elif ticker_raw == "N/A":
            ticker, country = None, None
        else:
            ticker, country = ticker_raw, None

        pub_date = _parse_date(tokens[6], tokens[7])
        tx_date = _parse_date(tokens[8], tokens[9])
    except IndexError:
        return None

    # Scan tail for owner/tx_type/amount/price by content
    owner = None
    tx_type = None
    amount_range_str = None
    price_str = None
    for tok in tokens[10:]:
        if not owner and tok in _OWNER_SET:
            owner = tok
            continue
        tl = tok.lower() if isinstance(tok, str) else ""
        if not tx_type and tl in _TXTYPE_SET:
            tx_type = tl
            continue
        if not amount_range_str and _AMOUNT_PAT.match(tok):
            amount_range_str = tok
            continue
        if not price_str and _PRICE_PAT.match(tok):
            price_str = tok
            continue

    amount_min, amount_max = _parse_amount(amount_range_str) if amount_range_str else (None, None)

    if not (tx_type and tx_date):
        return None

    return {
        "trade_id": trade_id,
        "politician_id": politician_match.group(1),
        "politician_name": politician_name,
        "party": party,
        "chamber": chamber,
        "state": state,
        "issuer_id": issuer_match.group(1) if issuer_match else None,
        "issuer_name": issuer_name,
        "ticker": ticker,
        "ticker_country": country,
        "pub_date": pub_date,
        "tx_date": tx_date,
        "tx_type": tx_type,
        "owner": owner,
        "amount_range": amount_range_str,
        "amount_min": amount_min,
        "amount_max": amount_max,
    }


_STOCK_ACT_MAX_LAG_DAYS = 45  # Senate PTR law: file within 45 days of tx
_INCREMENTAL_STOP_CONSECUTIVE_SEEN = 24  # 2 full pages of already-known IDs → stop


def _load_cached_trades() -> list[dict]:
    """Return prior cache's trades list, or empty list if missing/invalid."""
    if not os.path.exists(RAW_CACHE_PATH):
        return []
    try:
        with open(RAW_CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    trades = data.get("trades")
    return trades if isinstance(trades, list) else []


def incremental_scrape(
    window_days: int,
    cached_trades: list[dict],
    verbose: bool = False,
) -> tuple[list[dict], int, int]:
    """Fetches only new trades not in cached_trades, stops when we consistently see
    already-known trade_ids. Returns (merged_trades_within_window, new_count, pruned_count).

    Merge rule: union of new + cached, dedup on trade_id, drop trades with tx_date < tx_cutoff.
    """
    today = datetime.now(timezone.utc).date()
    tx_cutoff = today - timedelta(days=window_days)
    seen_ids = {t["trade_id"] for t in cached_trades if t.get("trade_id")}

    if verbose:
        _log(f"  seeded with {len(seen_ids)} existing trade_ids")

    new_trades: list[dict] = []
    consecutive_seen = 0
    hit_stop = False

    for page in range(1, MAX_PAGES_SAFETY + 1):
        url = f"{CAPITOL_TRADES_URL}?page={page}"
        try:
            html = _fetch(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            _log(f"WARN: page {page} fetch failed ({type(e).__name__}: {e}); stopping incremental")
            break

        rows = _ROW_RE.findall(html)
        if not rows:
            if verbose:
                _log(f"  page {page}: no rows; stopping")
            break

        page_new = 0
        page_seen = 0
        for row in rows:
            parsed = _parse_row(row)
            if not parsed:
                continue
            tid = parsed["trade_id"]
            if tid in seen_ids:
                page_seen += 1
                consecutive_seen += 1
                if consecutive_seen >= _INCREMENTAL_STOP_CONSECUTIVE_SEEN:
                    hit_stop = True
                    break
                continue

            # New trade
            try:
                tx_dt = datetime.strptime(parsed["tx_date"], "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            consecutive_seen = 0  # reset on any new id
            seen_ids.add(tid)
            if tx_dt >= tx_cutoff:
                new_trades.append(parsed)
                page_new += 1

        if verbose:
            _log(
                f"  page {page}: new={page_new} seen={page_seen} "
                f"consecutive_seen={consecutive_seen} total_new={len(new_trades)}"
            )

        if hit_stop:
            if verbose:
                _log(
                    f"  stop: {_INCREMENTAL_STOP_CONSECUTIVE_SEEN} consecutive already-seen IDs at page {page}"
                )
            break

        time.sleep(POLITE_DELAY_SECONDS)

    # Merge with cache and prune
    merged: dict[str, dict] = {}
    pruned = 0
    for t in cached_trades + new_trades:
        tid = t.get("trade_id")
        if not tid:
            continue
        try:
            tx_dt = datetime.strptime(t["tx_date"], "%Y-%m-%d").date()
        except (TypeError, ValueError, KeyError):
            continue
        if tx_dt < tx_cutoff:
            pruned += 1
            continue
        # new trades win over cached duplicates (data corrections)
        if tid in merged and t not in new_trades:
            continue
        merged[tid] = t

    return list(merged.values()), len(new_trades), pruned


def scrape(window_days: int = DEFAULT_WINDOW_DAYS, verbose: bool = False) -> list[dict]:
    """Pages are sorted by pub_date desc on Capitol Trades; tx_date within a page is NOT monotonic
    (STOCK Act allows up to 45-day reporting lag). So we stop based on pub_date crossing
    (today - window - 45d), which guarantees all trades with tx_date in our window are collected.
    Then filter by tx_date for the final list."""
    today = datetime.now(timezone.utc).date()
    tx_cutoff = today - timedelta(days=window_days)
    pub_cutoff = today - timedelta(days=window_days + _STOCK_ACT_MAX_LAG_DAYS)

    trades: list[dict] = []
    seen_trade_ids: set[str] = set()

    for page in range(1, MAX_PAGES_SAFETY + 1):
        url = f"{CAPITOL_TRADES_URL}?page={page}"
        try:
            html = _fetch(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            _log(f"WARN: page {page} fetch failed ({type(e).__name__}: {e}); stopping")
            break

        rows = _ROW_RE.findall(html)
        if not rows:
            if verbose:
                _log(f"  page {page}: no rows; stopping")
            break

        page_oldest_pub = None
        parsed_ok = 0
        added_on_page = 0
        for row in rows:
            parsed = _parse_row(row)
            if not parsed:
                continue
            parsed_ok += 1
            if parsed["trade_id"] in seen_trade_ids:
                continue
            seen_trade_ids.add(parsed["trade_id"])

            try:
                pub_dt = datetime.strptime(parsed["pub_date"], "%Y-%m-%d").date() if parsed.get("pub_date") else None
                tx_dt = datetime.strptime(parsed["tx_date"], "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue

            if pub_dt and (page_oldest_pub is None or pub_dt < page_oldest_pub):
                page_oldest_pub = pub_dt

            if tx_dt >= tx_cutoff:
                trades.append(parsed)
                added_on_page += 1

        if verbose:
            _log(
                f"  page {page}: rows={len(rows)} parsed={parsed_ok} added={added_on_page} "
                f"oldest_pub={page_oldest_pub} total_kept={len(trades)}"
            )

        if page_oldest_pub and page_oldest_pub < pub_cutoff:
            if verbose:
                _log(f"  pub_cutoff {pub_cutoff} reached at page {page}; stopping")
            break

        time.sleep(POLITE_DELAY_SECONDS)

    return trades


def save_raw_cache(trades: list[dict], window_days: int) -> None:
    os.makedirs(os.path.dirname(RAW_CACHE_PATH), exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "capitoltrades.com",
        "window_days": window_days,
        "trade_count": len(trades),
        "trades": trades,
    }
    tmp = RAW_CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, RAW_CACHE_PATH)


def probe(trades: list[dict]) -> None:
    _log(f"\n=== Capitol Trades — Probe Report ===")
    _log(f"Total trades parsed in window: {len(trades)}")
    if not trades:
        return

    dates = sorted({t["tx_date"] for t in trades if t.get("tx_date")})
    _log(f"Tx date range: {dates[0]} → {dates[-1]}")

    chambers = Counter(t.get("chamber") for t in trades)
    _log(f"Chambers: {dict(chambers)}")

    parties = Counter(t.get("party") for t in trades)
    _log(f"Parties: {dict(parties)}")

    tx_types = Counter(t.get("tx_type") for t in trades)
    _log(f"Transaction types: {dict(tx_types)}")

    us_only = [t for t in trades if t.get("ticker_country") == "US" and t.get("ticker")]
    _log(f"US tickers: {len(us_only)} / {len(trades)}")

    tkr_counter = Counter(t["ticker"] for t in us_only)
    _log(f"Unique US tickers: {len(tkr_counter)}")
    _log(f"Top 20 tickers by trade count:")
    for t, c in tkr_counter.most_common(20):
        _log(f"  {t:8s}  {c:4d}")

    pol_counter = Counter((t["politician_id"], t.get("politician_name")) for t in trades)
    _log(f"\nDistinct politicians: {len(pol_counter)}")
    _log(f"Top 10 most active:")
    for (pid, name), c in pol_counter.most_common(10):
        _log(f"  {pid:8s}  {c:4d}  {name}")

    amounts_parsed = sum(1 for t in trades if t.get("amount_min") is not None)
    _log(f"\nAmount ranges parsed: {amounts_parsed}/{len(trades)}")
    uniq_amounts = Counter(t.get("amount_range") for t in trades if t.get("amount_range"))
    _log(f"Unique amount strings ({len(uniq_amounts)}):")
    for a, c in uniq_amounts.most_common(15):
        _log(f"  {a!r:30s}  {c:4d}")

    try:
        from market_scanner import SP100_TICKERS, ETF_TICKERS  # type: ignore
        us_universe = set(SP100_TICKERS) | set(ETF_TICKERS)
        present = {t for t in us_universe if t in tkr_counter}
        _log(
            f"\nCoverage vs SP100+ETF ({len(us_universe)} tickers in scope): "
            f"{len(present)} with activity, {len(us_universe) - len(present)} empty"
        )
        for t in sorted(present, key=lambda x: -tkr_counter[x])[:15]:
            _log(f"  {t:8s}  {tkr_counter[t]:4d}")
    except ImportError as e:
        _log(f"\nCould not import SP100/ETF lists: {e}")


def _should_force_full_refresh() -> bool:
    """Weekly full rescrape on Sundays (UTC) — catches amendments, deletions, reclassifications
    that incremental mode can't detect. Override via POLITICIAN_TRADES_FULL_REFRESH=1."""
    if os.environ.get("POLITICIAN_TRADES_FULL_REFRESH") == "1":
        return True
    return datetime.now(timezone.utc).weekday() == 6  # Sunday


def main() -> int:
    window = int(os.environ.get("POLITICIAN_TRADES_WINDOW_DAYS", DEFAULT_WINDOW_DAYS))
    verbose = os.environ.get("POLITICIAN_TRADES_VERBOSE") == "1"
    full_refresh = _should_force_full_refresh()
    cached = _load_cached_trades()

    mode_reason = []
    if full_refresh:
        mode_reason.append("forced full refresh (env or Sunday)")
    elif not cached:
        mode_reason.append("no existing cache")
    mode = "full" if (full_refresh or not cached) else "incremental"

    _log(
        f"Scraping Capitol Trades (mode={mode}{' · ' + '; '.join(mode_reason) if mode_reason else ''}, "
        f"window={window}d, polite={POLITE_DELAY_SECONDS}s)..."
    )

    try:
        if mode == "full":
            trades = scrape(window_days=window, verbose=verbose)
            new_count = len(trades)
            pruned = 0
        else:
            trades, new_count, pruned = incremental_scrape(
                window_days=window, cached_trades=cached, verbose=verbose
            )
    except Exception as e:
        _log(f"WARN: scrape failed ({type(e).__name__}: {e}); keeping existing cache")
        return 0

    try:
        save_raw_cache(trades, window)
        _log(
            f"Cached {len(trades)} trades → {RAW_CACHE_PATH} "
            f"(mode={mode}, new={new_count}, pruned={pruned})"
        )
    except OSError as e:
        _log(f"WARN: cache write failed: {e}")
        return 0

    probe(trades)
    return 0


if __name__ == "__main__":
    sys.exit(main())
