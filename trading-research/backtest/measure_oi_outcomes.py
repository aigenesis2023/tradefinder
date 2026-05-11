"""
Take an OpenInsider clusters CSV and add outcome columns matching our
backtest schema, so the existing ablation tooling works unchanged.

Adds: market_cap_m, mcap_band, near_52w_low, entry_price,
      outcome_7d, outcome_10d, outcome_30d, outcome_*_date,
      delisted_or_acquired, notes, shares_approximate

Reuses backtest/price_data.py — same temporal isolation as the EDGAR backtest.

Usage:
    python -m backtest.measure_oi_outcomes openinsider_clusters_2018-01-01_2024-12-31.csv
"""

import csv
import sys
import time
from datetime import date
from pathlib import Path

from backtest.price_data import get_pre_signal_data, get_outcome_data


def measure(csv_in: Path) -> Path:
    with open(csv_in) as f:
        rows = list(csv.DictReader(f))
    print(f"[Measure] {len(rows)} clusters from {csv_in.name}")

    out_rows = []
    skipped_mcap = skipped_range = skipped_mat = 0

    for i, r in enumerate(rows, 1):
        if i % 25 == 0:
            print(f"  [{i:>4}/{len(rows)}] processed | "
                  f"passing={len(out_rows)} skip_mcap={skipped_mcap} "
                  f"skip_range={skipped_range} skip_mat={skipped_mat}")

        ticker = r["ticker"]
        try:
            signal_date = date.fromisoformat(r["signal_date"])
        except ValueError:
            continue
        total_usd = float(r["total_usd"])

        pre = get_pre_signal_data(ticker, signal_date, total_usd)
        if pre.market_cap_m is None:
            skipped_mcap += 1; continue
        if not pre.in_market_cap_range:
            skipped_range += 1; continue
        if not pre.passes_materiality:
            skipped_mat += 1; continue

        outcome = get_outcome_data(ticker, signal_date)

        out_rows.append({
            "ticker":             ticker,
            "company_name":       r["company_name"],
            "signal_date":        r["signal_date"],
            "cluster_start":      r["cluster_start"],
            "cluster_end":        r["cluster_end"],
            "total_usd":          int(round(total_usd)),
            "unique_insiders":    int(r["unique_insiders"]),
            "market_cap_m":       round(pre.market_cap_m, 1),
            "mcap_band":          pre.mcap_band,
            "near_52w_low":       pre.near_52w_low,
            "shares_approximate": pre.shares_approximate,
            "entry_price":        outcome.entry_price,
            "outcome_7d":         outcome.outcome_7d,
            "outcome_10d":        outcome.outcome_10d,
            "outcome_30d":        outcome.outcome_30d,
            "outcome_7d_date":    outcome.outcome_7d_date,
            "outcome_10d_date":   outcome.outcome_10d_date,
            "outcome_30d_date":   outcome.outcome_30d_date,
            "delisted_or_acquired": outcome.delisted_or_acquired,
            "notes":              outcome.notes,
        })
        time.sleep(0.05)

    print(f"\n[Result] {len(out_rows)} clusters passed all filters")
    print(f"  skipped no_mcap        : {skipped_mcap}")
    print(f"  skipped outside_range  : {skipped_range}")
    print(f"  skipped below_material : {skipped_mat}")

    out_path = csv_in.parent / csv_in.name.replace(".csv", "_measured.csv")
    if out_rows:
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=out_rows[0].keys())
            w.writeheader()
            w.writerows(out_rows)
        print(f"[Output] {out_path}")
    return out_path


def main():
    if len(sys.argv) != 2:
        print("Usage: python -m backtest.measure_oi_outcomes <clusters.csv>")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.is_absolute():
        csv_path = Path(__file__).parent / "results" / csv_path.name
    if not csv_path.exists():
        print(f"Not found: {csv_path}")
        sys.exit(1)

    measure(csv_path)


if __name__ == "__main__":
    main()
