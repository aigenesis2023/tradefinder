"""
measure_absolute_returns.py — Pre-paper-trade measurement script.

Answers the questions that all four external reviewers (Gemini, GPT, two anonymous)
agreed are non-negotiable before live paper-trading begins:

  1. What is the ABSOLUTE (cash, not alpha) return distribution on n=93?
  2. Is the mean driven by a few outliers, or is the distribution well-behaved?
  3. Do sub-cohorts differ meaningfully (cluster size, 52w-low flag, year, mcap)?
  4. What is the absolute win rate? Drawdown? Median return?

No engine changes. No trading. Just measurement on the existing validated cohort.

Run:
    python -m backtest.measure_absolute_returns
"""

from pathlib import Path
import sys
import pandas as pd
import numpy as np


PROD_CSV = Path(__file__).parent / "results" / "openinsider_prod_with_extended_horizons.csv"
BROAD_CSV = Path(__file__).parent / "results" / "openinsider_clusters_with_alpha.csv"
OUT_PATH = Path(__file__).parent / "results" / "absolute_returns_measurement.md"

HORIZONS = ["outcome_7d", "outcome_10d", "outcome_30d", "outcome_60d", "outcome_90d", "outcome_180d"]
HORIZON_LABELS = {
    "outcome_7d": "7d", "outcome_10d": "10d", "outcome_30d": "30d",
    "outcome_60d": "60d", "outcome_90d": "90d", "outcome_180d": "180d",
}


def fmt(x, dp=2):
    if pd.isna(x):
        return "—"
    return f"{x:.{dp}f}"


def horizon_stats(series: pd.Series) -> dict:
    s = series.dropna()
    if len(s) == 0:
        return {"n": 0}
    return {
        "n": len(s),
        "mean": s.mean(),
        "median": s.median(),
        "std": s.std(),
        "win_rate": (s > 0).mean() * 100,
        "min": s.min(),
        "max": s.max(),
        "p10": s.quantile(0.10),
        "p25": s.quantile(0.25),
        "p75": s.quantile(0.75),
        "p90": s.quantile(0.90),
        "max_drawdown_trade": s.min(),  # worst single trade
    }


def stats_table(df: pd.DataFrame, label: str) -> list[str]:
    lines = [f"### {label} (n={len(df)})", ""]
    lines.append("| Horizon | n | Mean % | Median % | Win % | Std % | Min % | p10 | p25 | p75 | p90 | Max % |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for col in HORIZONS:
        if col not in df.columns:
            continue
        s = horizon_stats(df[col])
        if s["n"] == 0:
            continue
        lines.append(
            f"| **{HORIZON_LABELS[col]}** | {s['n']} | "
            f"{fmt(s['mean'])} | {fmt(s['median'])} | {fmt(s['win_rate'], 1)} | "
            f"{fmt(s['std'])} | {fmt(s['min'])} | {fmt(s['p10'])} | "
            f"{fmt(s['p25'])} | {fmt(s['p75'])} | {fmt(s['p90'])} | {fmt(s['max'])} |"
        )
    lines.append("")
    return lines


def outlier_check(df: pd.DataFrame, horizon: str = "outcome_10d", k: int = 5) -> list[str]:
    """Show top-k winners and losers and re-compute mean excluding them."""
    lines = []
    if horizon not in df.columns:
        return lines
    sub = df.dropna(subset=[horizon]).copy()
    if len(sub) == 0:
        return lines
    sub = sub.sort_values(horizon, ascending=False)
    n = len(sub)
    mean_full = sub[horizon].mean()
    win_full = (sub[horizon] > 0).mean() * 100

    top = sub.head(k)
    bot = sub.tail(k)
    middle = sub.iloc[k:-k] if n > 2 * k else pd.DataFrame(columns=sub.columns)
    mean_trimmed = middle[horizon].mean() if len(middle) > 0 else float("nan")
    win_trimmed = (middle[horizon] > 0).mean() * 100 if len(middle) > 0 else float("nan")

    label = HORIZON_LABELS.get(horizon, horizon)
    lines.append(f"### Outlier sensitivity — {label} returns")
    lines.append("")
    lines.append(f"- Full mean: **{fmt(mean_full)}%** | Full win rate: **{fmt(win_full, 1)}%** (n={n})")
    if not np.isnan(mean_trimmed):
        lines.append(
            f"- Trimmed mean (drop top {k} + bottom {k}): **{fmt(mean_trimmed)}%** | "
            f"Trimmed win rate: **{fmt(win_trimmed, 1)}%** (n={len(middle)})"
        )
    lines.append("")
    lines.append(f"**Top {k} winners ({label}):**")
    for _, r in top.iterrows():
        lines.append(
            f"- {r['ticker']} {r['signal_date']} | cluster={int(r['unique_insiders'])} | "
            f"mcap=${r['market_cap_m']:.0f}M | return={fmt(r[horizon])}%"
        )
    lines.append("")
    lines.append(f"**Bottom {k} losers ({label}):**")
    for _, r in bot.iterrows():
        lines.append(
            f"- {r['ticker']} {r['signal_date']} | cluster={int(r['unique_insiders'])} | "
            f"mcap=${r['market_cap_m']:.0f}M | return={fmt(r[horizon])}%"
        )
    lines.append("")
    return lines


def cluster_size_breakdown(df: pd.DataFrame) -> list[str]:
    lines = ["## Slice — Cluster size", ""]
    bins = [(3, "3 insiders", df[df["unique_insiders"] == 3]),
            (4, "4 insiders", df[df["unique_insiders"] == 4]),
            (5, "5+ insiders (ELITE)", df[df["unique_insiders"] >= 5])]
    for _, label, sub in bins:
        lines += stats_table(sub, label)
    return lines


def near_52w_low_breakdown(df: pd.DataFrame) -> list[str]:
    """Distress-vs-conviction proxy. near_52w_low=True is the distress flag."""
    lines = ["## Slice — Distress proxy (near 52w low at signal)", ""]
    lines.append("Distress-vs-conviction question: insiders buying near 52-week lows may be supporting")
    lines.append("a falling stock (defensive); insiders buying away from lows may signal genuine informational")
    lines.append("advantage. This compares the two sub-cohorts on the same horizons.")
    lines.append("")
    distress = df[df["near_52w_low"].astype(str).str.lower() == "true"]
    not_distress = df[df["near_52w_low"].astype(str).str.lower() != "true"]
    lines += stats_table(distress, "Near 52w low = TRUE (potential distress)")
    lines += stats_table(not_distress, "Near 52w low = FALSE (potential conviction)")
    return lines


def year_breakdown(df: pd.DataFrame) -> list[str]:
    lines = ["## Slice — By year", ""]
    df = df.copy()
    df["year"] = pd.to_datetime(df["signal_date"]).dt.year
    for year in sorted(df["year"].unique()):
        sub = df[df["year"] == year]
        lines += stats_table(sub, f"Year {year}")
    return lines


def mcap_quartile_breakdown(df: pd.DataFrame) -> list[str]:
    lines = ["## Slice — Market cap quartile", ""]
    df = df.copy()
    df["mcap_q"] = pd.qcut(df["market_cap_m"], 4, labels=["Q1 (smallest)", "Q2", "Q3", "Q4 (largest)"])
    for q in df["mcap_q"].cat.categories:
        sub = df[df["mcap_q"] == q]
        if len(sub) == 0:
            continue
        min_mcap = sub["market_cap_m"].min()
        max_mcap = sub["market_cap_m"].max()
        lines += stats_table(sub, f"{q} (${min_mcap:.0f}M – ${max_mcap:.0f}M)")
    return lines


def delisted_breakdown(df: pd.DataFrame) -> list[str]:
    lines = ["## Slice — Delisted / acquired flag", ""]
    delisted = df[df["delisted_or_acquired"].astype(str).str.lower() == "true"]
    live = df[df["delisted_or_acquired"].astype(str).str.lower() != "true"]
    lines += stats_table(delisted, "Delisted or acquired during measurement window")
    lines += stats_table(live, "Still trading")
    return lines


def breakeven_math(df: pd.DataFrame) -> list[str]:
    """
    For a 10-day +8%/-6% target/stop framework, compute what win rate is needed to break even
    AFTER 0.6% round-trip costs, and compare against actual.
    """
    lines = ["## Break-even math (10d horizon, +8%/-6% framework, 60bps round-trip costs)", ""]
    s = df["outcome_10d"].dropna()
    if len(s) == 0:
        return lines
    actual_win = (s > 0).mean() * 100
    actual_mean = s.mean()

    # Hit target = +8%, stop = -6%, costs = -0.6%. Solve for breakeven p.
    # 8p - 6(1-p) - 0.6 = 0 => 14p = 6.6 => p = 0.4714
    breakeven_p = (6 + 0.6) / 14 * 100

    # Realistic expectancy assuming actual_win % hits target, rest hit stop, minus costs
    expectancy_naive = (actual_win / 100) * 8 + (1 - actual_win / 100) * (-6) - 0.6

    lines.append(f"- Actual 10d win rate (any positive return): **{fmt(actual_win, 1)}%**")
    lines.append(f"- Actual 10d mean return: **{fmt(actual_mean)}%**")
    lines.append(f"- Break-even win rate needed for +8%/-6% framework after 60bps costs: **{fmt(breakeven_p, 1)}%**")
    lines.append(
        f"- Naive expectancy if every win = +8% and every loss = -6%, after costs: "
        f"**{fmt(expectancy_naive)}%** per trade"
    )
    lines.append("")
    lines.append("Caveats: actual fills rarely hit exactly +8% or -6%. Above is a sanity check, not an estimate.")
    lines.append("The 'mean return' line is the actual measurement and is more reliable.")
    lines.append("")
    return lines


def compare_to_alpha(prod_df: pd.DataFrame, broad_df: pd.DataFrame) -> list[str]:
    """Compare absolute vs alpha returns at 30d on the production cohort."""
    lines = ["## Absolute vs Alpha — production cohort at 30d", ""]
    # Match prod rows in the broad CSV by ticker + signal_date
    if "alpha_30d" not in broad_df.columns:
        return lines
    merged = prod_df.merge(
        broad_df[["ticker", "signal_date", "alpha_30d", "alpha_win", "iwm_30d"]],
        on=["ticker", "signal_date"], how="left"
    )
    s_abs = merged["outcome_30d"].dropna()
    s_alpha = merged["alpha_30d"].dropna()
    s_iwm = merged["iwm_30d"].dropna()
    abs_win = (s_abs > 0).mean() * 100
    alpha_win = (s_alpha > 0).mean() * 100
    lines.append(f"- 30d **absolute** mean: {fmt(s_abs.mean())}%  | absolute win rate: {fmt(abs_win, 1)}%")
    lines.append(f"- 30d **alpha** mean:    {fmt(s_alpha.mean())}% | alpha win rate:    {fmt(alpha_win, 1)}%")
    lines.append(f"- 30d **IWM** mean:      {fmt(s_iwm.mean())}% (the benchmark drag/lift)")
    lines.append("")
    lines.append("If absolute win rate < alpha win rate, beating IWM is masking absolute losses during weak markets.")
    lines.append("")
    return lines


def main():
    if not PROD_CSV.exists():
        print(f"Missing: {PROD_CSV}", file=sys.stderr)
        sys.exit(1)
    prod = pd.read_csv(PROD_CSV)
    broad = pd.read_csv(BROAD_CSV) if BROAD_CSV.exists() else pd.DataFrame()

    lines = []
    lines.append("# Absolute Returns Measurement — Production Cohort (n=93)")
    lines.append("")
    lines.append("Source: `openinsider_prod_with_extended_horizons.csv` — 3+ unique insiders, $500M-$5B, 2018-2024.")
    lines.append("All return numbers are **absolute** (raw price change %), NOT alpha-adjusted.")
    lines.append("Entry = next close after `signal_date` (Form 4 filing date). No transaction costs deducted.")
    lines.append("")
    lines.append("## Headline distribution (whole cohort)")
    lines.append("")
    lines += stats_table(prod, f"Full production cohort")

    lines += outlier_check(prod, "outcome_10d", k=5)
    lines += outlier_check(prod, "outcome_30d", k=5)

    lines += breakeven_math(prod)

    if not broad.empty:
        lines += compare_to_alpha(prod, broad)

    lines += cluster_size_breakdown(prod)
    lines += near_52w_low_breakdown(prod)
    lines += year_breakdown(prod)
    lines += mcap_quartile_breakdown(prod)
    lines += delisted_breakdown(prod)

    lines.append("---")
    lines.append("")
    lines.append("## Reading guide")
    lines.append("")
    lines.append("- **Mean vs Median**: if mean >> median, distribution is right-skewed (driven by big winners). Concerning for retail because you cannot rely on the mean.")
    lines.append("- **Win rate**: % of trades where absolute return > 0. The number that matters for cash P&L.")
    lines.append("- **Trimmed mean vs Full mean**: if removing 5 best + 5 worst trades collapses the mean, the edge is concentrated in outliers, not a robust effect.")
    lines.append("- **p10**: 10th percentile — the typical bad trade. If p10 is very negative, a single losing streak does heavy damage.")
    lines.append("- **near_52w_low slice**: if distress sub-cohort underperforms, the engine should add a distress/conviction tag in v2.")
    lines.append("- **Cluster size slice**: if 5+ (elite) sample is too small (n<10), it cannot support a sizing multiplier.")
    lines.append("- **Year slice**: if results are concentrated in 1-2 years, out-of-sample stability is suspect.")

    out = "\n".join(lines)
    OUT_PATH.write_text(out)
    print(out)
    print(f"\n\n[Saved to {OUT_PATH}]", file=sys.stderr)


if __name__ == "__main__":
    main()
