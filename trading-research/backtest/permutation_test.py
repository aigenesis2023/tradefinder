#!/usr/bin/env python3
"""
Permutation Test: Insider Cluster Engine vs Random Mid-Cap Selection.

Answers the question: "Do insider clusters predict returns better than
randomly selecting mid-cap stocks on the same dates?"

Method:
  1. Build a broad ticker universe (S&P 500/400/600 from Wikipedia)
  2. For each of the 232 signal dates (2018-2024), construct the $200M-$3B pool
  3. Pre-compute forward returns for every (ticker, date) in the pool
  4. Randomization: 1000 iterations of sampling N mid-caps per date
     (matching the engine's signal count), measuring equal-weighted returns
  5. Compare engine's actual distribution against the random sampling distribution

Outputs:
  - Formatted comparison table to stdout
  - Full distribution data to backtest/results/permutation_test_2018-2024.json

Usage:
  cd trading-research
  python -m backtest.permutation_test                    # full run
  python -m backtest.permutation_test --skip-download     # cached rerun
  python -m backtest.permutation_test --rebuild-universe  # refresh ticker list
  python -m backtest.permutation_test --iterations 500    # faster convergence check
"""

import argparse
import csv
import io
import json
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from backtest.price_data import (
    MCAP_MAX_M,
    MCAP_MIN_M,
    _download_history,
    _normalize,
    download_shares_history,
)

# ── Paths ──────────────────────────────────────────────────────────────────
BACKTEST_DIR = Path(__file__).parent
RESULTS_DIR = BACKTEST_DIR / "results"
CACHE_DIR = BACKTEST_DIR / "cache" / "permutation"
PRICE_CACHE_DIR = BACKTEST_DIR / "cache" / "price_history"
ENGINE_CSV = RESULTS_DIR / "production_backtest_2018-01-01_2024-12-31.csv"

CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Constants ──────────────────────────────────────────────────────────────
HEADERS = {"User-Agent": "tradefinder-research leoduncan.elearning@gmail.com"}
HORIZONS = [7, 10, 30, 60, 90, 180]
HORIZON_KEYS = [f"{d}d" for d in HORIZONS]
SEED = 42
IWM_START = date(2017, 1, 1)
IWM_END = date(2025, 7, 1)

# Wikipedia pages for broad US stock universe
WIKI_SOURCES = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "sp600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: Ticker list assembly
# ═══════════════════════════════════════════════════════════════════════════════

def _clean_ticker(symbol: str) -> str:
    """Convert Wikipedia ticker to yfinance format (BRK.B → BRK-B)."""
    s = str(symbol).strip()
    # Strip Wikipedia footnote markers like [a], [b], [1]
    s = s.split("[")[0].strip()
    return s.replace(".", "-")


def _scrape_wikipedia(url: str) -> list[str]:
    """Scrape a Wikipedia S&P constituent page for ticker symbols."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
    except Exception as e:
        print(f"  [Wiki] Failed to read {url}: {e}", flush=True)
        return []

    for df in tables:
        for col in df.columns:
            col_lower = str(col).lower()
            if "symbol" in col_lower or "ticker" in col_lower:
                return [_clean_ticker(s) for s in df[col] if str(s).strip()]
    return []


def _scrape_iwm_holdings() -> list[str]:
    """Scrape iShares IWM holdings page for Russell 2000 constituents."""
    # iShares provides a CSV download for ETF holdings
    url = ("https://www.ishares.com/us/products/239710/"
           "ishares-russell-2000-etf/1467271812596.ajax"
           "?fileType=csv&fileName=IWM_holdings&dataType=fund")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        # Parse CSV lines — the format has metadata rows then a table
        lines = resp.text.strip().split("\n")
        tickers = []
        in_data = False
        for line in lines:
            parts = [p.strip().strip('"') for p in line.split(",")]
            if not in_data:
                if parts and parts[0].lower() == "ticker":
                    in_data = True
                continue
            if parts and parts[0] and parts[0] != "":
                tickers.append(_clean_ticker(parts[0]))
            if len(tickers) > 0 and (not parts or parts[0] == ""):
                break
        return tickers
    except Exception as e:
        print(f"  [IWM] Failed to fetch holdings: {e}", flush=True)
        return []


def assemble_ticker_universe(rebuild: bool = False) -> list[str]:
    """Build broad US stock universe from Wikipedia + IWM, cached to JSON."""
    cache_path = CACHE_DIR / "universe_tickers.json"
    if not rebuild and cache_path.exists():
        with cache_path.open() as f:
            tickers = json.load(f)
        print(f"[Universe] Loaded {len(tickers)} tickers from cache.", flush=True)
        return tickers

    print("[Universe] Assembling ticker list...", flush=True)
    all_tickers: set[str] = set()

    for name, url in WIKI_SOURCES.items():
        print(f"  Scraping {name}...", flush=True)
        tickers = _scrape_wikipedia(url)
        print(f"    Got {len(tickers)} tickers", flush=True)
        all_tickers.update(tickers)

    # Supplement with IWM holdings
    print("  Scraping IWM holdings...", flush=True)
    iwm_tickers = _scrape_iwm_holdings()
    print(f"    Got {len(iwm_tickers)} tickers", flush=True)
    all_tickers.update(iwm_tickers)

    # Remove clearly invalid tickers
    tickers_list = sorted(
        t for t in all_tickers
        if t and len(t) >= 2 and len(t) <= 8
        and t[0].isalpha()
        and not any(c in t for c in "()[]{}$\\")
        and t != "-"
    )

    with cache_path.open("w") as f:
        json.dump(tickers_list, f)

    print(f"[Universe] Assembled {len(tickers_list)} unique tickers.", flush=True)
    return tickers_list


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: Data download
# ═══════════════════════════════════════════════════════════════════════════════

def _download_one_ohlcv(ticker: str) -> bool:
    """Download OHLCV for one ticker. Returns True on success."""
    try:
        df = _download_history(ticker, date(2017, 1, 1), date(2025, 7, 1))
        return df is not None and not df.empty
    except Exception:
        return False


def bulk_download_ohlcv(tickers: list[str], max_workers: int = 4) -> set[str]:
    """Download OHLCV history for all universe tickers using thread pool."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Check which tickers already have cached data
    to_download: list[str] = []
    already_have = 0
    for t in tickers:
        cache_file = PRICE_CACHE_DIR / f"{t}_2017-01-01_2025-07-01.csv"
        if cache_file.exists():
            already_have += 1
        else:
            to_download.append(t)

    print(f"[Download] {already_have} tickers already cached, {len(to_download)} to download.",
          flush=True)

    if not to_download:
        return set(tickers)

    print(f"[Download] Fetching OHLCV for {len(to_download)} tickers "
          f"(max {max_workers} workers)...", flush=True)
    successful: set[str] = set(t for t in tickers if t not in to_download)
    start = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_download_one_ohlcv, t): t for t in to_download}
        done = 0
        for fut in as_completed(futures):
            ticker = futures[fut]
            done += 1
            try:
                if fut.result():
                    successful.add(ticker)
            except Exception:
                pass
            if done % 200 == 0:
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(to_download) - done) / rate if rate > 0 else 0
                print(f"  {done}/{len(to_download)} ({rate:.1f}/s, ETA {eta:.0f}s)",
                      flush=True)

    elapsed = time.time() - start
    print(f"[Download] Completed {len(to_download)} downloads in {elapsed:.0f}s. "
          f"{len(successful)} tickers with valid data.", flush=True)
    return successful


def bulk_download_shares(tickers: list[str], max_workers: int = 4) -> set[str]:
    """Download shares-outstanding history for all universe tickers."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Check existing caches
    to_download: list[str] = []
    for t in tickers:
        cache_file = PRICE_CACHE_DIR / "shares" / f"{t}.csv"
        if not cache_file.exists():
            to_download.append(t)

    print(f"[Shares] {len(tickers) - len(to_download)} cached, {len(to_download)} to download.",
          flush=True)

    if not to_download:
        return set(tickers)

    print(f"[Shares] Fetching shares for {len(to_download)} tickers...", flush=True)
    successful: set[str] = set(t for t in tickers if t not in to_download)
    start = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(download_shares_history, t): t for t in to_download}
        done = 0
        for fut in as_completed(futures):
            ticker = futures[fut]
            done += 1
            try:
                result = fut.result()
                if result is not None and len(result) > 0:
                    successful.add(ticker)
            except Exception:
                pass
            if done % 200 == 0:
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(to_download) - done) / rate if rate > 0 else 0
                print(f"  {done}/{len(to_download)} ({rate:.1f}/s, ETA {eta:.0f}s)",
                      flush=True)

    elapsed = time.time() - start
    print(f"[Shares] Completed {len(to_download)} downloads in {elapsed:.0f}s. "
          f"{len(successful)} tickers with valid shares data.", flush=True)
    return successful


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3: IWM benchmark
# ═══════════════════════════════════════════════════════════════════════════════

def load_iwm_series() -> pd.Series:
    """Download IWM close prices for the full window, cached."""
    cache_path = CACHE_DIR / "iwm_prices.csv"
    if cache_path.exists():
        iwm = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        # Handle both column naming conventions
        if "Close" in iwm.columns:
            return iwm["Close"]
        else:
            return iwm.iloc[:, 0]

    print("[IWM] Downloading benchmark data...", flush=True)
    data = yf.download("IWM", start="2017-01-01", end="2025-07-01",
                       progress=False, auto_adjust=True)
    closes = data["Close"]
    if isinstance(closes, pd.DataFrame):
        closes = closes.iloc[:, 0]
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    closes = closes.dropna()
    closes.to_csv(cache_path)
    return closes


def iwm_return_for_window(
    iwm_series: pd.Series,
    signal_date: date,
    outcome_date_str: str | None,
) -> float | None:
    """IWM return over the same calendar window as the signal."""
    if outcome_date_str is None:
        return None
    try:
        outcome_dt = pd.Timestamp(outcome_date_str)
    except (ValueError, TypeError):
        return None

    signal_ts = pd.Timestamp(signal_date)
    after = iwm_series[iwm_series.index > signal_ts]
    if after.empty:
        return None
    entry = float(after.iloc[0])

    exit_data = iwm_series[iwm_series.index >= outcome_dt]
    if exit_data.empty:
        return None
    exit_price = float(exit_data.iloc[0])

    return round((exit_price / entry - 1) * 100, 4)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4: Per-date universe construction
# ═══════════════════════════════════════════════════════════════════════════════

def _load_shares_cache(ticker: str) -> pd.Series | None:
    """Load shares-outstanding series for a ticker. Returns None if unavailable."""
    shares_file = PRICE_CACHE_DIR / "shares" / f"{ticker}.csv"
    if not shares_file.exists():
        return None
    try:
        s = pd.read_csv(shares_file, index_col=0)
        if s.empty or len(s.columns) < 1:
            return None
        series = s.iloc[:, 0]
        # Handle mixed timezone dates from yfinance
        series.index = pd.to_datetime(series.index, utc=True).tz_localize(None)
        return series.sort_index()
    except Exception:
        return None


def _get_market_cap(
    ticker: str,
    signal_date: date,
    price_df: pd.DataFrame,
    shares_series: pd.Series | None,
) -> float | None:
    """Compute market cap in $M from pre-loaded price+shares data.

    Args:
        price_df: already-normalized price DataFrame
        shares_series: pre-loaded shares Series (or None)
    """
    on_or_before = price_df[price_df.index.date <= signal_date]
    if on_or_before.empty:
        return None
    price = float(on_or_before["Close"].iloc[-1])

    if shares_series is None or shares_series.empty:
        return None

    on_or_before_s = shares_series[shares_series.index <= pd.Timestamp(signal_date)]
    if on_or_before_s.empty:
        return None

    shares = float(on_or_before_s.iloc[-1])
    if shares and shares > 0:
        return (price * shares) / 1e6
    return None


def build_universe_by_date(
    all_tickers: list[str],
    signal_dates: list[date],
    skip_download: bool = False,
) -> dict[str, list[str]]:
    """For each signal date, find which universe tickers are in $200M-$3B range."""
    cache_path = CACHE_DIR / "universe_by_date.json"

    if not skip_download and cache_path.exists():
        with cache_path.open() as f:
            raw = json.load(f)
        print(f"[Universe-by-date] Loaded {len(raw)} dates from cache.", flush=True)
        return raw

    # Load and normalize all price DataFrames once
    print("[Universe-by-date] Loading price data...", flush=True)
    price_cache: dict[str, pd.DataFrame] = {}
    missing_price = 0
    for t in all_tickers:
        cache_file = PRICE_CACHE_DIR / f"{t}_2017-01-01_2025-07-01.csv"
        if not cache_file.exists():
            missing_price += 1
            continue
        try:
            df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            if df.empty:
                missing_price += 1
                continue
            df = _normalize(df)
            price_cache[t] = df
        except Exception:
            missing_price += 1
    print(f"  {len(price_cache)} tickers loaded, {missing_price} missing.",
          flush=True)

    # Pre-load all shares series once
    print("[Universe-by-date] Loading shares data...", flush=True)
    shares_cache: dict[str, pd.Series | None] = {}
    for t in all_tickers:
        shares_cache[t] = _load_shares_cache(t)
    n_with_shares = sum(1 for v in shares_cache.values() if v is not None)
    print(f"  {n_with_shares} tickers with shares data.", flush=True)

    print(f"[Universe-by-date] Filtering $200M-$3B on {len(signal_dates)} dates...",
          flush=True)
    universe_by_date: dict[str, list[str]] = {}
    start = time.time()

    for i, sd in enumerate(signal_dates):
        eligible = []
        for t in all_tickers:
            pdf = price_cache.get(t)
            if pdf is None:
                continue
            mcap = _get_market_cap(t, sd, pdf, shares_cache.get(t))
            if mcap is not None and MCAP_MIN_M <= mcap <= MCAP_MAX_M:
                eligible.append(t)
        universe_by_date[sd.isoformat()] = eligible

        if (i + 1) % 50 == 0:
            elapsed = time.time() - start
            avg_size = sum(len(v) for v in universe_by_date.values()) / len(universe_by_date)
            print(f"  {i + 1}/{len(signal_dates)} dates processed. "
                  f"Avg pool size: {avg_size:.0f} tickers.", flush=True)

    elapsed = time.time() - start
    avg_size = sum(len(v) for v in universe_by_date.values()) / len(universe_by_date)
    print(f"[Universe-by-date] Built in {elapsed:.0f}s. "
          f"Avg {avg_size:.0f} eligible tickers per date.", flush=True)

    with cache_path.open("w") as f:
        json.dump(universe_by_date, f)

    return universe_by_date


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5: Outcome pre-computation
# ═══════════════════════════════════════════════════════════════════════════════

def precompute_outcomes(
    universe_by_date: dict[str, list[str]],
    signal_dates: list[date],
    iwm_series: pd.Series,
) -> dict:
    """Pre-compute forward returns + IWM alpha for all (ticker, date) pairs.

    Returns a dict keyed by (ticker, iso_date) with outcome arrays.
    """
    cache_path = CACHE_DIR / "precomputed_outcomes.json"
    if cache_path.exists():
        with cache_path.open() as f:
            print("[Outcomes] Loaded pre-computed outcomes from cache.", flush=True)
            return json.load(f)

    print("[Outcomes] Pre-computing forward returns...", flush=True)

    # Build a set of all (ticker, date) pairs we need
    pairs = set()
    for sd_str, tickers in universe_by_date.items():
        for t in tickers:
            pairs.add((t, sd_str))

    print(f"  {len(pairs)} (ticker, date) pairs to compute.", flush=True)

    outcomes: dict[str, dict] = {}  # key: "TICKER|DATE"
    price_frames: dict[str, pd.DataFrame] = {}
    missing = 0
    start = time.time()
    done = 0

    for ticker, sd_str in pairs:
        done += 1
        sd = date.fromisoformat(sd_str)

        # Load price data lazily
        if ticker not in price_frames:
            cache_file = PRICE_CACHE_DIR / f"{ticker}_2017-01-01_2025-07-01.csv"
            if cache_file.exists():
                try:
                    df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                    df = _normalize(df)
                    price_frames[ticker] = df
                except Exception:
                    missing += 1
                    continue
            else:
                missing += 1
                continue

        df = price_frames[ticker]
        after = df[df.index.date > sd]
        if after.empty:
            missing += 1
            continue

        entry = float(after["Close"].iloc[0])
        key = f"{ticker}|{sd_str}"
        outcomes[key] = {"entry": entry}

        for d in HORIZONS:
            target = sd + timedelta(days=d)
            available = after[after.index.date >= target]
            if available.empty:
                outcomes[key][f"ret_{d}d"] = None
                outcomes[key][f"ret_{d}d_date"] = None
                outcomes[key][f"alpha_{d}d"] = None
            else:
                px = float(available["Close"].iloc[0])
                ret = round((px / entry - 1) * 100, 2)
                ret_date = available.index[0].strftime("%Y-%m-%d")
                outcomes[key][f"ret_{d}d"] = ret
                outcomes[key][f"ret_{d}d_date"] = ret_date

                iwm_ret = iwm_return_for_window(iwm_series, sd, ret_date)
                outcomes[key][f"alpha_{d}d"] = round(ret - iwm_ret, 4) if iwm_ret is not None else None

        if done % 20000 == 0:
            elapsed = time.time() - start
            rate = done / elapsed
            eta = (len(pairs) - done) / rate if rate > 0 else 0
            print(f"  {done}/{len(pairs)} ({rate:.0f}/s, ETA {eta:.0f}s)", flush=True)

    elapsed = time.time() - start
    print(f"[Outcomes] Computed {len(outcomes)} entries in {elapsed:.0f}s. "
          f"{missing} pairs skipped (no data).", flush=True)

    with cache_path.open("w") as f:
        json.dump(outcomes, f)

    return outcomes


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 6: Engine results loading
# ═══════════════════════════════════════════════════════════════════════════════

def load_engine_results() -> dict:
    """Load engine backtest results grouped by signal date."""
    print("[Engine] Loading backtest results...", flush=True)

    by_date: dict[str, dict] = defaultdict(lambda: {
        "tickers": [],
        "ret": {k: [] for k in HORIZON_KEYS},
        "alpha": {k: [] for k in HORIZON_KEYS},
    })

    with ENGINE_CSV.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            sd = row["signal_date"]
            by_date[sd]["tickers"].append(row["ticker"])
            for hk in HORIZON_KEYS:
                val = row.get(f"outcome_{hk}")
                if val and val.strip():
                    try:
                        by_date[sd]["ret"][hk].append(float(val))
                    except ValueError:
                        pass
                aval = row.get(f"alpha_{hk}")
                if aval and aval.strip():
                    try:
                        by_date[sd]["alpha"][hk].append(float(aval))
                    except ValueError:
                        pass

    # Compute per-date equal-weighted mean
    result = {
        "dates": [],
        "ret": {k: [] for k in HORIZON_KEYS},
        "alpha": {k: [] for k in HORIZON_KEYS},
        "n_signals": {},
        "tickers_by_date": {},
    }

    for sd, data in sorted(by_date.items()):
        result["dates"].append(sd)
        result["n_signals"][sd] = len(data["tickers"])
        result["tickers_by_date"][sd] = data["tickers"]
        for hk in HORIZON_KEYS:
            vals = [v for v in data["ret"][hk] if v is not None]
            if vals:
                result["ret"][hk].append(sum(vals) / len(vals))
            avals = [v for v in data["alpha"][hk] if v is not None]
            if avals:
                result["alpha"][hk].append(sum(avals) / len(avals))

    print(f"[Engine] {len(result['dates'])} signal dates, "
          f"{sum(result['n_signals'].values())} total signals.", flush=True)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 7: Randomization loop
# ═══════════════════════════════════════════════════════════════════════════════

def run_randomization(
    engine: dict,
    universe_by_date: dict[str, list[str]],
    outcomes: dict,
    n_iterations: int = 1000,
    seed: int = 42,
) -> dict:
    """Run the permutation test: random mid-cap sampling vs engine."""
    rng = np.random.default_rng(seed)

    print(f"[Randomization] Running {n_iterations} iterations...", flush=True)

    # Pre-build index for fast lookup: ticker|date -> horizons
    # (already a dict, just use direct lookup)

    # Storage: iterations × horizons
    random_raw = {hk: np.zeros(n_iterations) for hk in HORIZON_KEYS}
    random_alpha = {hk: np.zeros(n_iterations) for hk in HORIZON_KEYS}
    random_winrate = {hk: np.zeros(n_iterations) for hk in HORIZON_KEYS}

    # Pre-collect engine tickers per date for exclusion
    engine_tickers_by_date = engine["tickers_by_date"]
    date_signal_counts = engine["n_signals"]
    signal_dates = engine["dates"]

    start = time.time()

    for it in range(n_iterations):
        iter_ret: dict[str, list[float]] = {hk: [] for hk in HORIZON_KEYS}
        iter_alpha: dict[str, list[float]] = {hk: [] for hk in HORIZON_KEYS}

        for sd in signal_dates:
            n_signals = date_signal_counts[sd]
            pool = universe_by_date.get(sd, [])
            if not pool:
                continue

            # Exclude engine tickers for a stricter test
            engine_tickers = set(engine_tickers_by_date.get(sd, []))
            clean_pool = [t for t in pool if t not in engine_tickers]

            if len(clean_pool) >= n_signals:
                sampled = rng.choice(clean_pool, size=n_signals, replace=False)
            else:
                # Not enough clean tickers, use full pool
                sampled = rng.choice(pool, size=n_signals, replace=False)

            for ticker in sampled:
                key = f"{ticker}|{sd}"
                entry = outcomes.get(key)
                if entry is None:
                    continue
                for hk in HORIZON_KEYS:
                    ret_val = entry.get(f"ret_{hk}")
                    if ret_val is not None:
                        iter_ret[hk].append(ret_val)
                    alpha_val = entry.get(f"alpha_{hk}")
                    if alpha_val is not None:
                        iter_alpha[hk].append(alpha_val)

        # Equal-weighted basket mean for this iteration
        for hk in HORIZON_KEYS:
            if iter_ret[hk]:
                random_raw[hk][it] = np.mean(iter_ret[hk])
                # Win rate for this iteration
                wins = sum(1 for v in iter_ret[hk] if v > 0)
                random_winrate[hk][it] = wins / len(iter_ret[hk]) * 100
            else:
                random_raw[hk][it] = np.nan
                random_winrate[hk][it] = np.nan

            if iter_alpha[hk]:
                random_alpha[hk][it] = np.mean(iter_alpha[hk])
            else:
                random_alpha[hk][it] = np.nan

        if (it + 1) % 250 == 0:
            elapsed = time.time() - start
            print(f"  Iteration {it + 1}/{n_iterations} ({elapsed:.0f}s)", flush=True)

    elapsed = time.time() - start
    print(f"[Randomization] Completed in {elapsed:.0f}s.", flush=True)

    return {
        "raw": random_raw,
        "alpha": random_alpha,
        "winrate": random_winrate,
        "n_iterations": n_iterations,
        "seed": seed,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 8: Statistics and output
# ═══════════════════════════════════════════════════════════════════════════════

def _engine_stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": 0, "median": 0, "std": 0, "win_pct": 0, "skew": 0}
    arr = np.array(values)
    wins = (arr > 0).sum()
    return {
        "n": len(arr),
        "mean": round(float(np.mean(arr)), 2),
        "median": round(float(np.median(arr)), 2),
        "std": round(float(np.std(arr, ddof=1)), 2),
        "sem": round(float(np.std(arr, ddof=1) / np.sqrt(len(arr))), 2),
        "win_pct": round(wins / len(arr) * 100, 1),
        "skew": round(float(pd.Series(arr).skew()), 2),
    }


def _random_stats(random_arr: np.ndarray) -> dict:
    valid = random_arr[~np.isnan(random_arr)]
    if len(valid) == 0:
        return {"mean_of_means": 0, "median_of_means": 0, "std_of_means": 0,
                "p2_5": 0, "p5": 0, "p25": 0, "p75": 0, "p95": 0, "p97_5": 0}
    return {
        "mean_of_means": round(float(np.mean(valid)), 2),
        "median_of_means": round(float(np.median(valid)), 2),
        "std_of_means": round(float(np.std(valid, ddof=1)), 2),
        "p2_5": round(float(np.percentile(valid, 2.5)), 2),
        "p5": round(float(np.percentile(valid, 5)), 2),
        "p25": round(float(np.percentile(valid, 25)), 2),
        "p75": round(float(np.percentile(valid, 75)), 2),
        "p95": round(float(np.percentile(valid, 95)), 2),
        "p97_5": round(float(np.percentile(valid, 97.5)), 2),
    }


def _comparison(engine_mean: float, random_arr: np.ndarray) -> dict:
    valid = random_arr[~np.isnan(random_arr)]
    if len(valid) == 0:
        return {"p_1tail": 1.0, "p_2tail": 1.0, "cohens_d": 0, "z_score": 0, "percentile": 50}

    rand_mean = float(np.mean(valid))
    rand_std = float(np.std(valid, ddof=1))

    # One-tailed: P(random >= engine)
    p_1tail = (valid >= engine_mean).sum() / len(valid)

    # Two-tailed
    p_2tail = (np.abs(valid - rand_mean) >= np.abs(engine_mean - rand_mean)).sum() / len(valid)

    # Cohen's d
    cohens_d = (engine_mean - rand_mean) / rand_std if rand_std > 0 else 0

    # Z-score
    z_score = (engine_mean - rand_mean) / rand_std if rand_std > 0 else 0

    # Engine percentile in random distribution
    percentile = (valid < engine_mean).sum() / len(valid) * 100

    return {
        "p_1tail": round(p_1tail, 4),
        "p_2tail": round(p_2tail, 4),
        "cohens_d": round(cohens_d, 4),
        "z_score": round(z_score, 4),
        "percentile": round(percentile, 1),
    }


def print_results(engine: dict, random: dict, universe_by_date: dict) -> None:
    """Print formatted comparison table and interpretation."""
    pool_sizes = [len(v) for v in universe_by_date.values()]
    avg_pool = sum(pool_sizes) / len(pool_sizes) if pool_sizes else 0

    print()
    print("=" * 80)
    print("PERMUTATION TEST — Insider Cluster Engine vs Random Mid-Cap Selection")
    print("=" * 80)
    print(f"Signal dates: {len(engine['dates'])}    "
          f"Total engine signals: {sum(engine['n_signals'].values())}")
    print(f"Universe pool: ~{avg_pool:.0f} mid-cap tickers per date ($200M-$3B)")
    print(f"Iterations: {random['n_iterations']}    Random seed: {random['seed']}")
    print("=" * 80)

    for label, metric_key in [("RAW RETURNS", "ret"), ("IWM ALPHA", "alpha")]:
        print(f"\n{label}")
        print("-" * 80)
        header = (f"{'Horizon':>7s}  {'Engine':>8s}  {'Engine':>7s}  "
                  f"{'Random':>8s}  {'Random':>7s}  "
                  f"{'95% CI':>20s}  {'p-value':>8s}  "
                  f"{'Cohen':>6s}  {'Engine':>7s}")
        print(header)
        header2 = (f"{'':7s}  {'Mean':>8s}  {'Win%':>7s}  "
                   f"{'Mean':>8s}  {'Median':>7s}  "
                   f"{'[Low  , High]':>20s}  {'(1-tail)':>8s}  "
                   f"{'d':>6s}  {'%ile':>7s}")
        print(header2)
        print("-" * 80)

        for hk in HORIZON_KEYS:
            eng_vals = engine[metric_key][hk]
            eng = _engine_stats(eng_vals)
            rnd_arr = random["raw" if metric_key == "ret" else "alpha"][hk]
            rnd = _random_stats(rnd_arr)
            cmp = _comparison(eng["mean"], rnd_arr)

            ci = f"[{rnd['p2_5']:>+5.1f}%, {rnd['p97_5']:>+5.1f}%]"

            # Significance markers
            sig = ""
            if cmp["p_1tail"] < 0.05:
                sig = " *"
            elif cmp["p_1tail"] < 0.10:
                sig = " ."

            print(f"{hk:>7s}  {eng['mean']:>+7.2f}%  {eng['win_pct']:>6.1f}%  "
                  f"{rnd['mean_of_means']:>+7.2f}%  {rnd['median_of_means']:>+6.2f}%  "
                  f"{ci:>20s}  {cmp['p_1tail']:>7.4f}{sig}  "
                  f"{cmp['cohens_d']:>+6.2f}  {cmp['percentile']:>6.1f}%")

        print("-" * 80)

    # Interpretation
    print("\nINTERPRETATION")
    print("-" * 80)

    # Find the most favorable horizon for the engine
    best_h = "30d"
    best_p = 1.0
    for hk in HORIZON_KEYS:
        eng_mean = _engine_stats(engine["alpha"][hk])["mean"]
        rnd_arr = random["alpha"][hk]
        cmp = _comparison(eng_mean, rnd_arr)
        if cmp["p_1tail"] < best_p:
            best_p = cmp["p_1tail"]
            best_h = hk

    eng_best = _engine_stats(engine["alpha"][best_h])
    rnd_best = _random_stats(random["alpha"][best_h])
    cmp_best = _comparison(eng_best["mean"], random["alpha"][best_h])
    diff = eng_best["mean"] - rnd_best["mean_of_means"]

    if cmp_best["p_1tail"] < 0.05:
        verdict = (
            f"STATISTICALLY SIGNIFICANT (p = {cmp_best['p_1tail']:.4f}). "
            f"The engine's alpha advantage of {diff:+.2f}pp at {best_h} is unlikely "
            f"to arise by chance. The insider-cluster filter appears to add value "
            f"beyond random mid-cap selection."
        )
    elif cmp_best["p_1tail"] < 0.10:
        verdict = (
            f"MARGINALLY SIGNIFICANT (p = {cmp_best['p_1tail']:.4f}). "
            f"The engine's alpha advantage of {diff:+.2f}pp at {best_h} is suggestive "
            f"but does not reach conventional significance (p < 0.05). A larger sample "
            f"or additional out-of-sample testing is recommended before attributing "
            f"predictive value to the insider-cluster pattern."
        )
    else:
        verdict = (
            f"NOT STATISTICALLY SIGNIFICANT (p = {cmp_best['p_1tail']:.4f}). "
            f"The engine's alpha advantage of {diff:+.2f}pp at {best_h} is within "
            f"the range of what random mid-cap selection produces {cmp_best['p_1tail']:.0%} "
            f"of the time. We CANNOT reject the null hypothesis that insider clusters "
            f"add no predictive value beyond random selection from the same universe."
        )

    print(f"  {verdict}")

    print()
    print("  CAVEATS:")
    print("  - Random pool has survivorship bias (S&P index constituents as of 2026).")
    print("  - Companies that went bankrupt or were delisted 2018-2024 are excluded,")
    print("    making the random benchmark CONSERVATIVE (harder to beat).")
    print("  - Random alpha should center near zero; a systematic positive bias suggests")
    print("    survivorship bias is material or mid-caps had a secular up-trend.")
    print("  - This test compares DISTRIBUTIONS. It does not test whether specific")
    print("    signals are predictive — only whether the aggregate screening rule")
    print("    outperforms random selection from the same market-cap band.")

    # Random alpha sanity check
    for hk in HORIZON_KEYS:
        rnd_alpha_mean = _random_stats(random["alpha"][hk])["mean_of_means"]
        print(f"  Random alpha sanity ({hk}): mean = {rnd_alpha_mean:+.2f}% "
              f"{'(PASS — near zero)' if abs(rnd_alpha_mean) < 0.5 else '(CHECK — bias suspected)'}")

    print("=" * 80)


def save_results(engine: dict, random: dict, filepath: Path) -> None:
    """Save full results as JSON for later analysis."""
    output = {
        "engine": {
            "dates": engine["dates"],
            "n_signals": engine["n_signals"],
            "raw_returns": {hk: engine["ret"][hk] for hk in HORIZON_KEYS},
            "alpha": {hk: engine["alpha"][hk] for hk in HORIZON_KEYS},
        },
        "random": {
            "n_iterations": random["n_iterations"],
            "seed": random["seed"],
            "raw_returns": {hk: random["raw"][hk].tolist() for hk in HORIZON_KEYS},
            "alpha": {hk: random["alpha"][hk].tolist() for hk in HORIZON_KEYS},
        },
        "horizons": HORIZON_KEYS,
    }
    with filepath.open("w") as f:
        json.dump(output, f)
    print(f"\nFull results saved to {filepath}", flush=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Permutation test: engine vs random mid-cap selection")
    parser.add_argument("--iterations", type=int, default=1000,
                       help="Number of randomization iterations (default: 1000)")
    parser.add_argument("--seed", type=int, default=SEED,
                       help=f"Random seed (default: {SEED})")
    parser.add_argument("--skip-download", action="store_true",
                       help="Skip OHLCV and shares download (use cached data)")
    parser.add_argument("--rebuild-universe", action="store_true",
                       help="Rebuild ticker universe from Wikipedia")
    parser.add_argument("--max-tickers", type=int, default=0,
                       help="Cap universe size for faster test runs")
    parser.add_argument("--workers", type=int, default=4,
                       help="Max download threads (default: 4)")
    args = parser.parse_args()

    # Use args.seed directly where needed instead of module-level SEED
    seed = args.seed

    # ── Phase 1: Ticker universe ──
    all_tickers = assemble_ticker_universe(rebuild=args.rebuild_universe)
    if args.max_tickers and args.max_tickers < len(all_tickers):
        rng = np.random.default_rng(seed)
        all_tickers = sorted(rng.choice(all_tickers, size=args.max_tickers, replace=False))
        print(f"[Universe] Randomly sampled {len(all_tickers)} tickers.", flush=True)

    # ── Phase 2: Download data ──
    if not args.skip_download:
        valid_tickers = bulk_download_ohlcv(all_tickers, max_workers=args.workers)
        valid_tickers = bulk_download_shares(list(valid_tickers), max_workers=args.workers)
        all_tickers = sorted(valid_tickers)
        print(f"[Download] {len(all_tickers)} tickers with complete data.", flush=True)
    else:
        # Filter to tickers with existing caches
        with_cache = []
        for t in all_tickers:
            cache_file = PRICE_CACHE_DIR / f"{t}_2017-01-01_2025-07-01.csv"
            if cache_file.exists():
                with_cache.append(t)
        print(f"[Skip-download] {len(with_cache)}/{len(all_tickers)} tickers have cached data.",
              flush=True)
        all_tickers = with_cache

    # ── Phase 3: Load engine results ──
    engine = load_engine_results()
    signal_dates = [date.fromisoformat(d) for d in engine["dates"]]

    # ── Phase 4: IWM benchmark ──
    iwm_series = load_iwm_series()

    # ── Phase 5: Build per-date universe ──
    universe_by_date = build_universe_by_date(
        all_tickers, signal_dates, skip_download=args.skip_download)

    # ── Phase 6: Pre-compute outcomes ──
    outcomes = precompute_outcomes(universe_by_date, signal_dates, iwm_series)

    # ── Phase 7: Randomization ──
    random = run_randomization(
        engine, universe_by_date, outcomes,
        n_iterations=args.iterations, seed=seed)

    # ── Phase 8: Results ──
    print_results(engine, random, universe_by_date)
    save_results(engine, random,
                 RESULTS_DIR / "permutation_test_2018-2024.json")


if __name__ == "__main__":
    main()
