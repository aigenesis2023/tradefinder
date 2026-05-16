#!/usr/bin/env python3
"""Quick Tier 1 verification using cached Yahoo data (no downloads)."""
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "implementation"))

# Set up verbose logging to see gate details
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# Keep external libraries quieter
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("yfinance").setLevel(logging.WARNING)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "signal_builder", "_cache", "yahoo")

# Pick 15 large-cap tickers with cached 2020-2025 data
TICKERS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "JNJ", "JPM", "PG",
    "HD", "BAC", "KO", "DIS", "CVX", "PEP", "MRK", "NVDA", "NFLX",
    "COST", "ORCL", "ADBE", "CRM", "INTC", "AMD", "NKE", "MCD",
    "LOW", "GS", "IBM", "CAT", "GE",
]


def build_price_df(tickers, start="2022-01-01", end="2024-12-31"):
    """Build price DataFrame from cached parquet files."""
    frames = {}
    for t in tickers:
        # Find the best matching cache file
        candidates = sorted([
            f for f in os.listdir(CACHE_DIR)
            if f.startswith(f"{t}_") and f.endswith(".parquet")
        ])
        if not candidates:
            print(f"  SKIP {t}: no cached data")
            continue
        path = os.path.join(CACHE_DIR, candidates[0])
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        # Use Close price (adjusted close not available in these cached files)
        prices = df["Close"].dropna()
        # Filter to requested date range
        prices = prices.loc[start:end]
        if len(prices) < 100:
            print(f"  SKIP {t}: only {len(prices)} data points in range")
            continue
        frames[t] = prices

    if not frames:
        raise ValueError("No tickers with cached data found!")

    price_df = pd.DataFrame(frames)
    print(f"\nPrice DataFrame: {price_df.shape[0]} dates x {price_df.shape[1]} tickers")
    print(f"Date range: {price_df.index[0]} to {price_df.index[-1]}")
    return price_df


def main():
    print("=" * 70)
    print("QUICK TIER 1 VERIFICATION (from cache, no downloads)")
    print("=" * 70)

    print("\n[1] Building price DataFrame from cached data...")
    price_df = build_price_df(TICKERS)
    print(f"    Tickers: {list(price_df.columns)}")

    print("\n[2] Building momentum signal via FactorConstructor...")
    from factors import FactorConstructor
    fc = FactorConstructor(seed=42)
    from calibration import _build_factor_signal_df, _make_hypothesis_spec, _save_signal_parquet, _run_single_pipeline

    signal_df = _build_factor_signal_df(fc, price_df, "construct_momentum_12_1")
    print(f"    Signal shape: {signal_df.shape[0]} dates x {signal_df.shape[1]} tickers")
    if signal_df.empty:
        print("    ERROR: Empty signal DataFrame!")
        return 1

    # Show some stats about the signal
    n_valid = signal_df.notna().sum().sum()
    print(f"    Valid signal values: {n_valid}")

    print("\n[3] Saving signal and running pipeline...")
    output_dir = "/tmp/tier1_quick_test"
    os.makedirs(output_dir, exist_ok=True)
    signal_path = _save_signal_parquet(signal_df, output_dir, "momentum_12_1")

    hyp = _make_hypothesis_spec(
        name="quick_tier1_momentum",
        signal_path=signal_path,
        holding_period_days=21,
        start_date="2022-01-01",
        end_date="2024-12-31",
    )

    print(f"    Hypothesis: {hyp.name}")
    print(f"    Holding period: {hyp.holding_period_days}d")
    print(f"    Rebalance: {hyp.position_sizing.rebalance_frequency}")
    print(f"    Time period: {hyp.time_period.start_date} to {hyp.time_period.end_date}")
    print()

    result = _run_single_pipeline(hyp, output_dir, verbose=True)

    print("\n" + "=" * 70)
    print("RESULT")
    print("=" * 70)
    print(f"Verdict:        {result.verdict}")
    print(f"Reason:         {result.verdict_reason}")
    print(f"Sharpe:         {result.sharpe_ratio}")
    print(f"Alpha (bps):    {result.annualized_alpha_bps}")
    print(f"GT-Score:       {result.gt_score}")
    print(f"P-value:        {result.p_value}")
    print(f"Elapsed:        {result.elapsed_seconds:.0f}s")
    print(f"Warnings:       {result.warnings}")
    print()

    if result.verdict in ("SURVIVED", "SURVIVED_WARNING"):
        print("SUCCESS: Momentum survived the pipeline — Tier 1 passes.")
        return 0
    elif result.verdict == "BROKEN":
        print("FAILED: Momentum broke. Adversarial test may still have issues.")
        print("Check the verbose log above for which gates failed.")
        return 1
    else:
        print(f"UNEXPECTED: {result.verdict}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
