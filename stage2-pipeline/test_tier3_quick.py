#!/usr/bin/env python3
"""Quick Tier 3 verification — negative controls must BROKEN."""
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "implementation"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("yfinance").setLevel(logging.WARNING)
logging.getLogger("peewee").setLevel(logging.WARNING)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "signal_builder", "_cache", "yahoo")

TICKERS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "JNJ", "JPM", "PG",
    "HD", "BAC", "KO", "DIS", "CVX", "PEP", "MRK", "NVDA", "NFLX",
    "COST", "ORCL", "ADBE", "CRM", "INTC", "AMD", "NKE", "MCD",
    "LOW", "GS", "IBM", "CAT", "GE",
]


def build_price_df(tickers, start="2022-01-01", end="2024-12-31"):
    frames = {}
    for t in tickers:
        candidates = sorted([
            f for f in os.listdir(CACHE_DIR)
            if f.startswith(f"{t}_") and f.endswith(".parquet")
        ])
        if not candidates:
            continue
        path = os.path.join(CACHE_DIR, candidates[0])
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        prices = df["Close"].dropna()
        prices = prices.loc[start:end]
        if len(prices) < 100:
            continue
        frames[t] = prices
    if not frames:
        raise ValueError("No tickers with cached data!")
    return pd.DataFrame(frames)


def main():
    print("=" * 70)
    print("QUICK TIER 3 VERIFICATION — Negative Controls")
    print("=" * 70)

    from calibration import (
        _build_factor_signal_df, _save_signal_parquet, _make_hypothesis_spec,
        _run_single_pipeline, _build_random_signal_df,
    )

    print("\n[1] Building price DataFrame...")
    price_df = build_price_df(TICKERS)
    print(f"    {price_df.shape[0]} dates x {price_df.shape[1]} tickers")

    from factors import FactorConstructor
    fc = FactorConstructor(seed=42)

    print("\n[2] Building baseline momentum signal...")
    baseline = _build_factor_signal_df(fc, price_df, "construct_momentum_12_1")
    print(f"    Shape: {baseline.shape}")

    output_dir = "/tmp/tier3_quick_test"

    # --- Random uniform signal ---
    print("\n[3] Testing RANDOM UNIFORM (must BROKEN)...")
    rng = np.random.RandomState(99)
    tickers = list(baseline.columns)
    dates_list = list(baseline.index)
    random_signal = pd.DataFrame(
        rng.uniform(0, 1, size=(len(dates_list), len(tickers))),
        index=dates_list, columns=tickers,
    )
    # Add NaNs matching baseline for realistic missingness
    random_signal = random_signal.where(baseline.notna())

    signal_path = _save_signal_parquet(random_signal, output_dir, "random_uniform")
    hyp = _make_hypothesis_spec(
        name="calibration_tier3_random",
        signal_path=signal_path,
        start_date="2022-01-01",
        end_date="2024-12-31",
    )
    result1 = _run_single_pipeline(hyp, output_dir, verbose=False)
    print(f"    Verdict: {result1.verdict}")
    print(f"    Reason:  {result1.verdict_reason}")
    print(f"    P-value: {result1.p_value}")

    # --- Shuffled momentum ---
    print("\n[4] Testing SHUFFLED MOMENTUM (must BROKEN)...")
    rng2 = np.random.RandomState(100)
    shuffled = baseline.copy()
    for date_idx in range(shuffled.shape[0]):
        row = shuffled.iloc[date_idx].values.copy()
        nan_mask = np.isnan(row)
        valid_vals = row[~nan_mask]
        rng2.shuffle(valid_vals)
        row[~nan_mask] = valid_vals
        shuffled.iloc[date_idx] = row

    signal_path = _save_signal_parquet(shuffled, output_dir, "shuffled_momentum")
    hyp = _make_hypothesis_spec(
        name="calibration_tier3_shuffled",
        signal_path=signal_path,
        start_date="2022-01-01",
        end_date="2024-12-31",
    )
    result2 = _run_single_pipeline(hyp, output_dir, verbose=False)
    print(f"    Verdict: {result2.verdict}")
    print(f"    Reason:  {result2.verdict_reason}")
    print(f"    P-value: {result2.p_value}")

    # --- Summary ---
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    results = {
        "random_uniform": result1,
        "shuffled_momentum": result2,
    }
    all_ok = True
    for name, r in results.items():
        ok = r.verdict in ("BROKEN", "UNTESTABLE")
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"  {status}: {name} → {r.verdict}")

    if all_ok:
        print("\nSUCCESS: All negative controls BROKEN — Tier 3 passes.")
        return 0
    else:
        print("\nFAILED: At least one negative control SURVIVED — FPR defect.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
