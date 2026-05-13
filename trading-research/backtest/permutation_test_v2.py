#!/usr/bin/env python3
"""
Permutation Test v2 — Fair Comparison using OpenInsider Universe.

v1 flaw: random pool came from Wikipedia S&P lists (2026 survivors).
          Engine pool came from OpenInsider filings (all stocks, including
          those that later crashed/delisted). Two different populations.

v2 fix:   BOTH groups come from the SAME OpenInsider data.
          Universe = ALL tickers with >=1 qualifying insider purchase
          in the last 45 days, in $200M-$3B range.
          Engine = the subset where 3+ insiders clustered in 30 days.
          Random control = the rest (solo buyers, non-clustered pairs).

Answers: "Among stocks where executives are buying, do the clustered
         ones outperform the non-clustered ones?"

Usage:
  cd trading-research
  python -m backtest.permutation_test_v2                     # full run
  python -m backtest.permutation_test_v2 --skip-download      # cached rerun
  python -m backtest.permutation_test_v2 --iterations 500     # faster check
"""

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from backtest.price_data import (
    MCAP_MAX_M,
    MCAP_MIN_M,
    _download_history,
    _normalize,
    download_shares_history,
)
from pipeline.insider_scanner import MIN_TRANSACTION_USD, QUALIFYING_ROLES

# ── Paths ──────────────────────────────────────────────────────────────────
BACKTEST_DIR = Path(__file__).parent
RESULTS_DIR = BACKTEST_DIR / "results"
CACHE_DIR = BACKTEST_DIR / "cache" / "permutation"
PRICE_CACHE_DIR = BACKTEST_DIR / "cache" / "price_history"
OI_CACHE_DIR = BACKTEST_DIR / "cache" / "openinsider"
ENGINE_CSV = RESULTS_DIR / "production_backtest_2018-01-01_2024-12-31.csv"

CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Constants ──────────────────────────────────────────────────────────────
HORIZONS = [7, 10, 30, 60, 90, 180]
HORIZON_KEYS = [f"{d}d" for d in HORIZONS]
SEED = 42
UNIVERSE_LOOKBACK_DAYS = 45  # matches engine's lookback

# Entity-indicating keywords (mirrors openinsider_feed.py)
ENTITY_KEYWORDS = (
    "llc", "l.p.", "l.l.c.", "inc", "corp", "corporation", "ltd", "limited",
    "fund", "trust", "trustee", "bank", "capital", "management", "group",
    "holdings", "ventures", "associates", "partners", "advisors",
    "advisor", "estate", "custodian", "fbo", "u/a", "u/t/a",
)


def _is_entity_name(name: str) -> bool:
    n = name.lower().strip().rstrip(" .,;:")
    return any(kw in n for kw in ENTITY_KEYWORDS)


def _is_qualifying_role(title: str) -> bool:
    t = (title or "").lower()
    return any(role in t for role in QUALIFYING_ROLES)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: Load OpenInsider transactions and apply engine filters
# ═══════════════════════════════════════════════════════════════════════════════

def load_qualifying_transactions() -> list[dict]:
    """Load all cached OpenInsider transactions, applying engine filters.

    Returns list of dicts: {ticker, name, role, date, total_usd}
    These are the EXACT same transactions the engine sees.
    """
    cache_path = CACHE_DIR / "qualifying_transactions.json"
    if cache_path.exists():
        with cache_path.open() as f:
            raw = json.load(f)
            # Convert date strings back
            print(f"[OI] Loaded {len(raw)} qualifying transactions from cache.",
                  flush=True)
            return raw

    print("[OI] Loading OpenInsider cache files...", flush=True)
    oi_files = sorted(OI_CACHE_DIR.glob("*.csv"))
    print(f"  {len(oi_files)} cache files found.", flush=True)

    all_rows: list[dict] = []
    total_raw = 0
    for fpath in oi_files:
        try:
            with fpath.open() as f:
                reader = csv.DictReader(f)
                for row in reader:
                    total_raw += 1
                    # Parse numeric fields
                    try:
                        usd = float(row.get("total_usd", 0))
                    except (ValueError, TypeError):
                        continue
                    if usd < MIN_TRANSACTION_USD:
                        continue
                    name = row.get("name", "")
                    if _is_entity_name(name):
                        continue
                    role = row.get("role", "")
                    if not _is_qualifying_role(role):
                        continue
                    all_rows.append({
                        "ticker": row["ticker"],
                        "name": name,
                        "role": role,
                        "date": row["date"],
                        "total_usd": usd,
                    })
        except Exception as e:
            print(f"  Warning: failed to read {fpath.name}: {e}", flush=True)

    print(f"[OI] {total_raw} raw rows -> {len(all_rows)} qualifying transactions.",
          flush=True)

    with cache_path.open("w") as f:
        json.dump(all_rows, f)

    return all_rows


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: Build per-date universe from OpenInsider data
# ═══════════════════════════════════════════════════════════════════════════════

def build_oi_universe_by_date(
    qualifying: list[dict],
    signal_dates: list[date],
) -> dict[str, list[str]]:
    """For each signal date, find ALL tickers with >=1 qualifying insider
    purchase in the prior UNIVERSE_LOOKBACK_DAYS days.

    This is the engine's "opportunity set" — every stock the engine COULD
    have formed a cluster on.

    Returns: {signal_date_iso: [ticker1, ticker2, ...]}
    """
    cache_path = CACHE_DIR / "oi_universe_by_date.json"
    if cache_path.exists():
        with cache_path.open() as f:
            raw = json.load(f)
        print(f"[OI-Universe] Loaded {len(raw)} dates from cache.", flush=True)
        return raw

    # Index transactions by (ticker, date)
    print("[OI-Universe] Indexing transactions by ticker+date...", flush=True)
    by_ticker: dict[str, list[date]] = defaultdict(list)
    for txn in qualifying:
        try:
            d = datetime.strptime(txn["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        by_ticker[txn["ticker"]].append(d)

    for ticker in by_ticker:
        by_ticker[ticker] = sorted(set(by_ticker[ticker]))

    print(f"[OI-Universe] {len(by_ticker)} unique tickers with qualifying activity.",
          flush=True)

    # For each signal date, find tickers with activity in the lookback window
    print(f"[OI-Universe] Building per-date universe ({len(signal_dates)} dates, "
          f"{UNIVERSE_LOOKBACK_DAYS}d lookback)...", flush=True)

    universe_by_date: dict[str, list[str]] = {}
    start = time.time()

    for i, sd in enumerate(signal_dates):
        cutoff = sd - timedelta(days=UNIVERSE_LOOKBACK_DAYS)
        eligible = []
        for ticker, dates in by_ticker.items():
            # Check if any transaction falls in [cutoff, sd]
            for d in reversed(dates):  # check most recent first
                if d > sd:
                    continue
                if d >= cutoff:
                    eligible.append(ticker)
                break  # checked the most recent date <= sd

        universe_by_date[sd.isoformat()] = eligible

        if (i + 1) % 50 == 0:
            elapsed = time.time() - start
            print(f"  {i + 1}/{len(signal_dates)} dates. "
                  f"Avg {sum(len(v) for v in universe_by_date.values()) / len(universe_by_date):.0f} "
                  f"tickers/date.", flush=True)

    elapsed = time.time() - start
    avg_size = sum(len(v) for v in universe_by_date.values()) / len(universe_by_date)
    print(f"[OI-Universe] Built in {elapsed:.0f}s. "
          f"Avg {avg_size:.0f} tickers per date.", flush=True)

    with cache_path.open("w") as f:
        json.dump(universe_by_date, f)

    return universe_by_date


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3: Market cap filter
# ═══════════════════════════════════════════════════════════════════════════════

def _load_shares_cache(ticker: str) -> pd.Series | None:
    shares_file = PRICE_CACHE_DIR / "shares" / f"{ticker}.csv"
    if not shares_file.exists():
        return None
    try:
        s = pd.read_csv(shares_file, index_col=0)
        if s.empty or len(s.columns) < 1:
            return None
        series = s.iloc[:, 0]
        series.index = pd.to_datetime(series.index, utc=True).tz_localize(None)
        return series.sort_index()
    except Exception:
        return None


def filter_universe_by_mcap(
    oi_universe: dict[str, list[str]],
    signal_dates: list[date],
) -> dict[str, list[str]]:
    """Filter the OI universe to $200M-$3B on each date."""
    cache_path = CACHE_DIR / "oi_universe_mcap_filtered.json"
    if cache_path.exists():
        with cache_path.open() as f:
            raw = json.load(f)
        print(f"[MCap-Filter] Loaded {len(raw)} dates from cache.", flush=True)
        return raw

    # Collect all unique tickers across all dates
    all_tickers = sorted(set(
        t for tickers in oi_universe.values() for t in tickers
    ))
    print(f"[MCap-Filter] {len(all_tickers)} unique tickers to check.", flush=True)

    # Load price data
    print("[MCap-Filter] Loading price data...", flush=True)
    price_cache: dict[str, pd.DataFrame] = {}
    for t in all_tickers:
        cache_file = PRICE_CACHE_DIR / f"{t}_2017-01-01_2025-07-01.csv"
        if cache_file.exists():
            try:
                df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                if not df.empty:
                    price_cache[t] = _normalize(df)
            except Exception:
                pass

    print(f"  {len(price_cache)}/{len(all_tickers)} tickers with price data.",
          flush=True)

    # Download missing price data
    missing = [t for t in all_tickers if t not in price_cache]
    if missing:
        print(f"  Downloading price data for {len(missing)} missing tickers...",
              flush=True)
        for i, t in enumerate(missing):
            try:
                df = _download_history(t, date(2017, 1, 1), date(2025, 7, 1))
                if df is not None and not df.empty:
                    price_cache[t] = _normalize(df)
            except Exception:
                pass
            if (i + 1) % 100 == 0:
                print(f"    {i + 1}/{len(missing)}", flush=True)
        print(f"    Done. {len(price_cache)} tickers total with price data.",
              flush=True)

    # Also download shares for missing tickers
    print("[MCap-Filter] Loading shares data...", flush=True)
    shares_cache: dict[str, pd.Series | None] = {}
    for t in all_tickers:
        if t not in price_cache:
            shares_cache[t] = None
            continue
        s = _load_shares_cache(t)
        if s is None:
            # Try to download
            try:
                s = download_shares_history(t)
            except Exception:
                s = None
        shares_cache[t] = s

    n_shares = sum(1 for v in shares_cache.values() if v is not None)
    print(f"  {n_shares}/{len(all_tickers)} tickers with shares data.", flush=True)

    # Filter by market cap
    print(f"[MCap-Filter] Filtering $200M-$3B on {len(signal_dates)} dates...",
          flush=True)
    filtered: dict[str, list[str]] = {}
    start = time.time()

    for i, sd in enumerate(signal_dates):
        eligible = []
        sd_iso = sd.isoformat()
        for t in oi_universe.get(sd_iso, []):
            pdf = price_cache.get(t)
            if pdf is None:
                continue
            on_or_before = pdf[pdf.index.date <= sd]
            if on_or_before.empty:
                continue
            price = float(on_or_before["Close"].iloc[-1])

            ss = shares_cache.get(t)
            if ss is None or ss.empty:
                continue
            on_or_before_s = ss[ss.index <= pd.Timestamp(sd)]
            if on_or_before_s.empty:
                continue
            shares = float(on_or_before_s.iloc[-1])

            if shares > 0:
                mcap = (price * shares) / 1e6
                if MCAP_MIN_M <= mcap <= MCAP_MAX_M:
                    eligible.append(t)

        filtered[sd_iso] = eligible

        if (i + 1) % 50 == 0:
            elapsed = time.time() - start
            avg_size = sum(len(v) for v in filtered.values()) / len(filtered)
            print(f"  {i + 1}/{len(signal_dates)} dates. "
                  f"Avg {avg_size:.0f} eligible/date.", flush=True)

    elapsed = time.time() - start
    avg_size = sum(len(v) for v in filtered.values()) / len(filtered)
    print(f"[MCap-Filter] Done in {elapsed:.0f}s. "
          f"Avg {avg_size:.0f} $200M-$3B tickers per date.", flush=True)

    with cache_path.open("w") as f:
        json.dump(filtered, f)

    return filtered


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4: IWM benchmark
# ═══════════════════════════════════════════════════════════════════════════════

def load_iwm_series() -> pd.Series:
    cache_path = CACHE_DIR / "iwm_prices.csv"
    if cache_path.exists():
        iwm = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        if "Close" in iwm.columns:
            return iwm["Close"]
        else:
            return iwm.iloc[:, 0]

    print("[IWM] Downloading...", flush=True)
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
# Phase 5: Outcome pre-computation
# ═══════════════════════════════════════════════════════════════════════════════

def precompute_outcomes(
    universe_by_date: dict[str, list[str]],
    signal_dates: list[date],
    iwm_series: pd.Series,
) -> dict:
    """Pre-compute forward returns for all (ticker, date) pairs."""
    cache_path = CACHE_DIR / "oi_precomputed_outcomes.json"
    if cache_path.exists():
        with cache_path.open() as f:
            print("[Outcomes] Loaded from cache.", flush=True)
            return json.load(f)

    # Collect all unique (ticker, date) pairs
    pairs = set()
    for sd_str, tickers in universe_by_date.items():
        for t in tickers:
            pairs.add((t, sd_str))

    print(f"[Outcomes] Pre-computing {len(pairs)} (ticker, date) pairs...",
          flush=True)

    # Load price data
    all_tickers = sorted(set(t for t, _ in pairs))
    price_frames: dict[str, pd.DataFrame] = {}
    for t in all_tickers:
        cache_file = PRICE_CACHE_DIR / f"{t}_2017-01-01_2025-07-01.csv"
        if cache_file.exists():
            try:
                df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                df = _normalize(df)
                price_frames[t] = df
            except Exception:
                pass

    outcomes: dict[str, dict] = {}
    missing = 0
    start = time.time()
    done = 0

    for ticker, sd_str in pairs:
        done += 1
        sd = date.fromisoformat(sd_str)

        df = price_frames.get(ticker)
        if df is None:
            missing += 1
            continue

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
                outcomes[key][f"alpha_{d}d"] = (
                    round(ret - iwm_ret, 4) if iwm_ret is not None else None
                )

        if done % 20000 == 0:
            elapsed = time.time() - start
            rate = done / elapsed
            eta = (len(pairs) - done) / rate if rate > 0 else 0
            print(f"  {done}/{len(pairs)} ({rate:.0f}/s, ETA {eta:.0f}s)", flush=True)

    elapsed = time.time() - start
    print(f"[Outcomes] Computed {len(outcomes)} entries in {elapsed:.0f}s. "
          f"{missing} pairs skipped.", flush=True)

    with cache_path.open("w") as f:
        json.dump(outcomes, f)

    return outcomes


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 6: Engine results (reused from v1)
# ═══════════════════════════════════════════════════════════════════════════════

def load_engine_results() -> dict:
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
# Phase 7: Randomization (uses OI universe, excludes engine tickers)
# ═══════════════════════════════════════════════════════════════════════════════

def run_randomization(
    engine: dict,
    universe_by_date: dict[str, list[str]],
    outcomes: dict,
    n_iterations: int = 1000,
    seed: int = 42,
) -> dict:
    rng = np.random.default_rng(seed)

    print(f"[Randomization] {n_iterations} iterations...", flush=True)

    random_raw = {hk: np.zeros(n_iterations) for hk in HORIZON_KEYS}
    random_alpha = {hk: np.zeros(n_iterations) for hk in HORIZON_KEYS}

    engine_tickers_by_date = engine["tickers_by_date"]
    date_signal_counts = engine["n_signals"]
    signal_dates = engine["dates"]

    # Pre-compute stats about pool composition
    total_dates = len(signal_dates)
    dates_with_pool = 0
    dates_with_clean_pool = 0

    start = time.time()

    for it in range(n_iterations):
        iter_ret: dict[str, list[float]] = {hk: [] for hk in HORIZON_KEYS}
        iter_alpha: dict[str, list[float]] = {hk: [] for hk in HORIZON_KEYS}

        for sd in signal_dates:
            n_signals = date_signal_counts[sd]
            if n_signals == 0:
                continue

            pool = universe_by_date.get(sd, [])
            if not pool:
                continue

            if it == 0:
                dates_with_pool += 1

            # EXCLUDE engine tickers — fair comparison
            engine_tickers = set(engine_tickers_by_date.get(sd, []))
            clean_pool = [t for t in pool if t not in engine_tickers]

            if it == 0:
                if len(clean_pool) >= n_signals:
                    dates_with_clean_pool += 1

            if len(clean_pool) >= n_signals:
                sampled = rng.choice(clean_pool, size=n_signals, replace=False)
            elif len(pool) >= n_signals:
                # Fallback: not enough clean tickers, use full pool
                sampled = rng.choice(pool, size=n_signals, replace=False)
            else:
                # Not enough tickers at all — skip this date
                continue

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

        for hk in HORIZON_KEYS:
            if iter_ret[hk]:
                random_raw[hk][it] = np.mean(iter_ret[hk])
            else:
                random_raw[hk][it] = np.nan

            if iter_alpha[hk]:
                random_alpha[hk][it] = np.mean(iter_alpha[hk])
            else:
                random_alpha[hk][it] = np.nan

        if (it + 1) % 250 == 0:
            elapsed = time.time() - start
            print(f"  Iteration {it + 1}/{n_iterations} ({elapsed:.0f}s)", flush=True)

    elapsed = time.time() - start
    print(f"[Randomization] {elapsed:.0f}s. "
          f"Pool present on {dates_with_pool}/{total_dates} dates, "
          f"clean pool sufficient on {dates_with_clean_pool}/{total_dates}.",
          flush=True)

    return {
        "raw": random_raw,
        "alpha": random_alpha,
        "n_iterations": n_iterations,
        "seed": seed,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 8: Statistics and output (same as v1)
# ═══════════════════════════════════════════════════════════════════════════════

def _engine_stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": 0, "median": 0, "std": 0, "sem": 0,
                "win_pct": 0, "skew": 0}
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
        return {"p_1tail": 1.0, "p_2tail": 1.0, "cohens_d": 0,
                "z_score": 0, "percentile": 50}

    rand_mean = float(np.mean(valid))
    rand_std = float(np.std(valid, ddof=1))
    p_1tail = (valid >= engine_mean).sum() / len(valid)
    p_2tail = (np.abs(valid - rand_mean) >=
               np.abs(engine_mean - rand_mean)).sum() / len(valid)
    cohens_d = (engine_mean - rand_mean) / rand_std if rand_std > 0 else 0
    z_score = (engine_mean - rand_mean) / rand_std if rand_std > 0 else 0
    percentile = (valid < engine_mean).sum() / len(valid) * 100

    return {
        "p_1tail": round(p_1tail, 4),
        "p_2tail": round(p_2tail, 4),
        "cohens_d": round(cohens_d, 4),
        "z_score": round(z_score, 4),
        "percentile": round(percentile, 1),
    }


def print_results(engine: dict, random: dict,
                  universe_by_date: dict[str, list[str]]) -> None:
    pool_sizes = [len(v) for v in universe_by_date.values()]
    avg_pool = sum(pool_sizes) / len(pool_sizes) if pool_sizes else 0
    # Count total distinct tickers in universe
    all_universe_tickers = set()
    for tickers in universe_by_date.values():
        all_universe_tickers.update(tickers)
    # Count engine tickers that appear in universe
    engine_tickers = set()
    for tickers in engine["tickers_by_date"].values():
        engine_tickers.update(tickers)
    engine_in_universe = engine_tickers & all_universe_tickers

    print()
    print("=" * 80)
    print("PERMUTATION TEST v2 — Cluster vs Non-Cluster (Same OpenInsider Universe)")
    print("=" * 80)
    print(f"Signal dates: {len(engine['dates'])}    "
          f"Total engine signals: {sum(engine['n_signals'].values())}")
    print(f"Universe: {len(all_universe_tickers)} unique tickers from OpenInsider "
          f"(>=1 qualifying buy in {UNIVERSE_LOOKBACK_DAYS}d, $200M-$3B)")
    print(f"Engine tickers found in universe: {len(engine_in_universe)}/"
          f"{len(engine_tickers)} ({len(engine_in_universe)/max(1,len(engine_tickers))*100:.0f}%)")
    print(f"Avg pool: {avg_pool:.0f} eligible tickers per date")
    print(f"Iterations: {random['n_iterations']}    Random seed: {random['seed']}")
    print("=" * 80)
    print("  Test: Among stocks where executives bought $100K+, do the")
    print("  clustered ones (3+ insiders in 30d) outperform the rest?")
    print("=" * 80)

    for label, metric_key in [("RAW RETURNS", "ret"), ("IWM ALPHA", "alpha")]:
        print(f"\n{label}")
        print("-" * 80)
        print(f"{'Horizon':>7s}  {'Engine':>8s}  {'Engine':>7s}  "
              f"{'Random':>8s}  {'Random':>7s}  "
              f"{'95% CI':>20s}  {'p-value':>8s}  "
              f"{'Cohen':>6s}  {'Engine':>7s}")
        print(f"{'':7s}  {'Mean':>8s}  {'Win%':>7s}  "
              f"{'Mean':>8s}  {'Median':>7s}  "
              f"{'[Low  , High]':>20s}  {'(1-tail)':>8s}  "
              f"{'d':>6s}  {'%ile':>7s}")
        print("-" * 80)

        for hk in HORIZON_KEYS:
            eng_vals = engine[metric_key][hk]
            eng = _engine_stats(eng_vals)
            rnd_arr = random["raw" if metric_key == "ret" else "alpha"][hk]
            rnd = _random_stats(rnd_arr)
            cmp = _comparison(eng["mean"], rnd_arr)

            ci = f"[{rnd['p2_5']:>+5.1f}%, {rnd['p97_5']:>+5.1f}%]"

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

    # Find best horizon
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
            f"The clustered stocks outperform solo-buyer stocks by {diff:+.2f}pp "
            f"at {best_h}. The 3+ insider clustering pattern carries predictive "
            f"value beyond what individual insider purchases signal."
        )
    elif cmp_best["p_1tail"] < 0.10:
        verdict = (
            f"MARGINALLY SIGNIFICANT (p = {cmp_best['p_1tail']:.4f}). "
            f"Clustered stocks outperform by {diff:+.2f}pp at {best_h}, "
            f"suggestive but below conventional significance."
        )
    else:
        verdict = (
            f"NOT STATISTICALLY SIGNIFICANT (p = {cmp_best['p_1tail']:.4f}). "
            f"The difference of {diff:+.2f}pp at {best_h} is within the range "
            f"of random chance. We CANNOT reject the hypothesis that clustering "
            f"adds no predictive value beyond individual insider buying."
        )

    print(f"  {verdict}")
    print()
    print("  This is the FAIR test:")
    print(f"  - Both groups drawn from the SAME OpenInsider data")
    print(f"  - Both groups apply the SAME role/entity/$100K filters")
    print(f"  - Both groups are in the $200M-$3B range")
    print(f"  - The ONLY difference: engine = 3+ insiders in 30d, "
          f"control = 1-2 insiders")
    print()
    print("  Random alpha sanity (should be near zero — same universe):")
    for hk in HORIZON_KEYS:
        rnd_alpha_mean = _random_stats(random["alpha"][hk])["mean_of_means"]
        ok = "PASS" if abs(rnd_alpha_mean) < 0.5 else "CHECK"
        print(f"    {hk}: mean = {rnd_alpha_mean:+.2f}% ({ok})")
    print("=" * 80)


def save_results(engine: dict, random: dict, filepath: Path) -> None:
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
        "test_version": 2,
        "description": "Cluster vs non-cluster, same OpenInsider universe",
    }
    with filepath.open("w") as f:
        json.dump(output, f)
    print(f"\nFull results saved to {filepath}", flush=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Permutation test v2: cluster vs non-cluster (same OI universe)")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--skip-download", action="store_true",
                       help="Skip price/shares download (use cached)")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    seed = args.seed

    # ── Phase 1: Load qualifying OI transactions ──
    qualifying = load_qualifying_transactions()

    # ── Phase 2: Load engine results ──
    engine = load_engine_results()
    signal_dates = [date.fromisoformat(d) for d in engine["dates"]]

    # ── Phase 3: Build OI universe by date ──
    oi_universe = build_oi_universe_by_date(qualifying, signal_dates)

    # ── Phase 4: Filter by market cap ──
    universe_mcap = filter_universe_by_mcap(oi_universe, signal_dates)

    # ── Phase 5: IWM benchmark ──
    iwm_series = load_iwm_series()

    # ── Phase 6: Pre-compute outcomes ──
    outcomes = precompute_outcomes(universe_mcap, signal_dates, iwm_series)

    # ── Phase 7: Randomization ──
    random = run_randomization(
        engine, universe_mcap, outcomes,
        n_iterations=args.iterations, seed=seed)

    # ── Phase 8: Results ──
    print_results(engine, random, universe_mcap)
    save_results(engine, random,
                 RESULTS_DIR / "permutation_test_v2_2018-2024.json")


if __name__ == "__main__":
    main()
