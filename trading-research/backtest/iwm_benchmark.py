"""
IWM Benchmark — measures alpha vs. small-cap beta.

For each signal in the n=383 measured CSV, computes IWM's return over the
same 30-day holding window, then reports:
  - Alpha = signal_return_30d - iwm_return_30d
  - Whether we have real alpha or just small-cap beta exposure

Usage:
    cd trading-research
    python -m backtest.iwm_benchmark
"""

import pandas as pd
import yfinance as yf
from pathlib import Path

CSV = Path(__file__).parent / "results" / "openinsider_clusters_2018-01-01_2024-12-31_measured.csv"


def load_iwm_prices() -> pd.Series:
    """Download IWM closes for the full backtest window in one shot."""
    print("Downloading IWM 2017-2025...")
    data = yf.download("IWM", start="2017-01-01", end="2025-01-01",
                       progress=False, auto_adjust=True)
    closes = data["Close"]
    if isinstance(closes, pd.DataFrame):
        closes = closes.iloc[:, 0]
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    return closes.dropna()


def nearest_price(series: pd.Series, date: pd.Timestamp) -> float:
    """Return closing price on date, or nearest prior trading day."""
    idx = series.index.searchsorted(date)
    if idx >= len(series):
        idx = len(series) - 1
    # Walk back if the exact date is missing (weekend / holiday)
    while idx > 0 and series.index[idx] > date:
        idx -= 1
    return float(series.iloc[idx])


def iwm_return(series: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float:
    p0 = nearest_price(series, start)
    p1 = nearest_price(series, end)
    return round((p1 - p0) / p0 * 100, 4)


def main():
    df = pd.read_csv(CSV, parse_dates=["signal_date", "outcome_30d_date"])
    df = df[df["outcome_30d"].notna() & df["outcome_30d_date"].notna()].copy()
    print(f"Rows with 30d outcome: {len(df)}")

    iwm = load_iwm_prices()

    df["iwm_30d"] = df.apply(
        lambda r: iwm_return(iwm, r["signal_date"], r["outcome_30d_date"]), axis=1
    )
    df["alpha_30d"] = df["outcome_30d"] - df["iwm_30d"]
    df["alpha_win"] = df["alpha_30d"] > 0

    # ── Overall ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("OVERALL (n={})".format(len(df)))
    print("=" * 60)
    print(f"  Raw signal avg 30d:    {df['outcome_30d'].mean():.2f}%")
    print(f"  IWM avg 30d (same win):{df['iwm_30d'].mean():.2f}%")
    print(f"  Alpha avg 30d:         {df['alpha_30d'].mean():.2f}%")
    print(f"  Alpha median 30d:      {df['alpha_30d'].median():.2f}%")
    print(f"  Alpha > 0 rate:        {df['alpha_win'].mean()*100:.1f}%")
    print(f"  Signal win rate:       {(df['outcome_30d']>0).mean()*100:.1f}%")

    # ── Cluster size ─────────────────────────────────────────────────────────
    print("\n── By cluster size ─────────────────────────────────")
    for label, sub in [("2 insiders", df[df["unique_insiders"] == 2]),
                        ("3+ insiders", df[df["unique_insiders"] >= 3])]:
        if len(sub) == 0:
            continue
        print(f"  {label} (n={len(sub)})")
        print(f"    Raw avg:   {sub['outcome_30d'].mean():.2f}%  "
              f"win={( sub['outcome_30d']>0).mean()*100:.1f}%")
        print(f"    IWM avg:   {sub['iwm_30d'].mean():.2f}%")
        print(f"    Alpha avg: {sub['alpha_30d'].mean():.2f}%  "
              f"alpha_win={sub['alpha_win'].mean()*100:.1f}%")

    # ── Market cap band ───────────────────────────────────────────────────────
    print("\n── By market cap band ──────────────────────────────")
    for band in sorted(df["mcap_band"].unique()):
        sub = df[df["mcap_band"] == band]
        print(f"  {band} (n={len(sub)})")
        print(f"    Raw avg:   {sub['outcome_30d'].mean():.2f}%  "
              f"win={(sub['outcome_30d']>0).mean()*100:.1f}%")
        print(f"    IWM avg:   {sub['iwm_30d'].mean():.2f}%")
        print(f"    Alpha avg: {sub['alpha_30d'].mean():.2f}%  "
              f"alpha_win={sub['alpha_win'].mean()*100:.1f}%")

    # ── By year ───────────────────────────────────────────────────────────────
    print("\n── By year ─────────────────────────────────────────")
    df["year"] = df["signal_date"].dt.year
    for yr in sorted(df["year"].unique()):
        sub = df[df["year"] == yr]
        print(f"  {yr} (n={len(sub)})")
        print(f"    Raw avg:   {sub['outcome_30d'].mean():.2f}%  "
              f"win={(sub['outcome_30d']>0).mean()*100:.1f}%")
        print(f"    IWM avg:   {sub['iwm_30d'].mean():.2f}%")
        print(f"    Alpha avg: {sub['alpha_30d'].mean():.2f}%  "
              f"alpha_win={sub['alpha_win'].mean()*100:.1f}%")

    # ── Combined high-quality filter ──────────────────────────────────────────
    print("\n── BEST-CASE FILTER: 3+ insiders + $500M-$5B ───────")
    hq = df[(df["unique_insiders"] >= 3) & (df["mcap_band"] == "$500M-$5B")]
    print(f"  n={len(hq)}")
    if len(hq) > 0:
        print(f"  Raw avg:   {hq['outcome_30d'].mean():.2f}%  "
              f"win={(hq['outcome_30d']>0).mean()*100:.1f}%")
        print(f"  IWM avg:   {hq['iwm_30d'].mean():.2f}%")
        print(f"  Alpha avg: {hq['alpha_30d'].mean():.2f}%  "
              f"alpha_win={hq['alpha_win'].mean()*100:.1f}%")

    # ── Save enriched CSV ─────────────────────────────────────────────────────
    out = CSV.parent / "openinsider_clusters_with_alpha.csv"
    df.to_csv(out, index=False)
    print(f"\nSaved enriched CSV → {out}")


if __name__ == "__main__":
    main()
