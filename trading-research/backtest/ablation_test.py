"""
LLM Ablation Test

Question this answers: does the LLM filter stack add edge over the raw
mechanical signal? If Agent 1 / 1B / 1C / 1D judgments correlate with
actual outcomes, we have evidence the LLM stack contributes lift. If not,
the LLM is theater and we should cut it.

Design:
    - Read backtest CSV signals (mechanical-filter-only, no LLM applied)
    - For each signal, send a structured prompt to Claude with ONLY
      the cluster metadata that would have been visible at signal_date
    - Hide actual outcomes (entry/exit prices, returns)
    - Ask for conviction score (1-5) and a binary act/skip decision
    - Tabulate: outcomes for "act" vs "skip"

Leakage controls:
    - Outcome columns are NOT included in the prompt
    - Signal date is included (the LLM needs temporal context to reason)
    - Caveat: the LLM may have training-data knowledge of what happened to
      specific tickers post-signal. To control for this, run on signals from
      AFTER the model's training cutoff (2024 backtest, when available).
    - To stress-test, also run a "ticker-blinded" variant that hides ticker
      and company name (only sector + cluster details remain).

Usage:
    python -m backtest.ablation_test backtest/results/backtest_2023-01-01_2023-12-31.csv
    python -m backtest.ablation_test --blinded <csv>   # ticker-blinded variant
"""

import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

from orchestrator.llm_client import call_claude


PROMPT_BASE = """You are evaluating whether to act on a single insider buying cluster signal.

Use only the data below. Do not search for the outcome. Reason as if it is the
day after the signal fired and you must decide whether to take the trade.

— Signal —
Ticker:           {ticker_field}
Company:          {company_field}
Signal date:      {signal_date}
Cluster window:   {cluster_start} to {cluster_end}
Insiders:         {unique_insiders} unique buyers
Total purchased:  ${total_usd:,.0f}
Market cap:       ${market_cap_m:.0f}M  ({mcap_band})
Within 15% of 52-week low: {near_52w_low}

— Decision framework —
We are looking for high-conviction insider clusters where:
  - The buying is a credible signal of management seeing undervaluation
  - The company is sufficiently neglected that the signal isn't priced in
  - The cluster size and dollar amount are material vs the float
{empirical_block}
Output STRICTLY this JSON, no commentary:
{{
  "conviction_score": <integer 1-5; 5 = strongest>,
  "action": "<one of: ACT, SKIP, DISQUALIFY>",
  "primary_reason": "<one sentence>"
}}

ACT = take the trade. SKIP = pass for now. DISQUALIFY = signal is structurally weak.
"""

EMPIRICAL_PRIORS_BLOCK = """
— Empirical priors (from 2023 backtest, n=25; trust this over intuition) —
  - Near 52-week low UNDERPERFORMS: -2.71%/-3.70% avg vs +5.01%/+3.62% (7d/10d).
    "Buying the bottom" is actually catching a falling knife at 1-2 week horizon.
  - 3+ insider clusters UNDERPERFORM 2-insider clusters at 30d (-10.6% vs +5.5% avg).
    Larger clusters may signal panic or "everyone's getting in" tops, not conviction.
  - Sub-$500M cap clusters underperform $500M-$5B clusters across all windows.
  - Override your default intuition that "more insiders + bottom = stronger signal".
"""


def build_prompt(row: dict, blinded: bool = False, empirical: bool = False) -> str:
    """Construct the LLM prompt from a CSV row."""
    if blinded:
        ticker_field = "[REDACTED]"
        company_field = "[REDACTED]"
    else:
        ticker_field = row["ticker"]
        company_field = row["company_name"]

    return PROMPT_BASE.format(
        ticker_field=ticker_field,
        company_field=company_field,
        signal_date=row["signal_date"],
        cluster_start=row["cluster_start"],
        cluster_end=row["cluster_end"],
        unique_insiders=int(row["unique_insiders"]),
        total_usd=float(row["total_usd"]),
        market_cap_m=float(row["market_cap_m"]),
        mcap_band=row["mcap_band"],
        near_52w_low=row["near_52w_low"],
        empirical_block=EMPIRICAL_PRIORS_BLOCK if empirical else "",
    )


def parse_response(text: str) -> Optional[dict]:
    """Extract JSON from the LLM response. Tolerant of code fences."""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = cleaned.replace("```", "").strip()
    match = re.search(r"\{.*?\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    score = data.get("conviction_score")
    action = data.get("action", "").upper().strip()
    if action not in {"ACT", "SKIP", "DISQUALIFY"}:
        return None
    if not isinstance(score, int) or not (1 <= score <= 5):
        return None
    return {
        "conviction_score": score,
        "action": action,
        "primary_reason": data.get("primary_reason", "")[:200],
    }


def run_ablation(csv_path: Path, blinded: bool = False, empirical: bool = False) -> list[dict]:
    """Run LLM judgment on every signal in the CSV. Returns enriched rows."""
    print(f"[Ablation] Loading {csv_path}")
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    print(f"[Ablation] {len(rows)} signals to evaluate "
          f"(blinded={blinded}, empirical={empirical})")

    enriched = []
    for i, row in enumerate(rows, 1):
        ticker = row["ticker"] if not blinded else "[REDACTED]"
        print(f"[Ablation] [{i:>3}/{len(rows)}] {ticker} ...", end=" ", flush=True)

        prompt = build_prompt(row, blinded=blinded, empirical=empirical)
        response = call_claude(prompt, timeout=180)
        parsed = parse_response(response) if response else None

        if not parsed:
            print("PARSE FAILED")
            enriched.append({**row, "llm_action": "PARSE_FAILED",
                             "llm_conviction": None, "llm_reason": ""})
            time.sleep(1)
            continue

        print(f"{parsed['action']} (conviction={parsed['conviction_score']})")
        enriched.append({
            **row,
            "llm_action":     parsed["action"],
            "llm_conviction": parsed["conviction_score"],
            "llm_reason":     parsed["primary_reason"],
        })
        time.sleep(1)

    return enriched


def summarize(rows: list[dict]):
    """Tabulate outcomes by LLM decision."""
    print("\n" + "=" * 72)
    print("ABLATION RESULTS — does LLM judgment correlate with outcomes?")
    print("=" * 72)

    by_action: dict[str, list[dict]] = {}
    for r in rows:
        by_action.setdefault(r["llm_action"], []).append(r)

    print(f"\nDecision distribution (n={len(rows)}):")
    for action, group in sorted(by_action.items()):
        print(f"  {action:<14} n={len(group):>3}")

    def stats(vals):
        if not vals: return None
        wins = [v for v in vals if v > 0]
        return {
            "n": len(vals),
            "win%": round(len(wins) / len(vals) * 100, 1),
            "avg":  round(sum(vals) / len(vals), 2),
        }

    print("\nOutcomes by LLM action:")
    for window, key in [("7d", "outcome_7d"), ("10d", "outcome_10d"), ("30d", "outcome_30d")]:
        print(f"\n── {window}")
        for action, group in sorted(by_action.items()):
            vals = [float(r[key]) for r in group if r[key] not in ("", None)]
            s = stats(vals)
            if s:
                print(f"  {action:<14} n={s['n']:>3}  win={s['win%']:>5.1f}%  avg={s['avg']:>+6.2f}%")

    print("\nKey question: does ACT outperform SKIP / DISQUALIFY?")
    for window, key in [("7d", "outcome_7d"), ("10d", "outcome_10d"), ("30d", "outcome_30d")]:
        act_vals = [float(r[key]) for r in by_action.get("ACT", []) if r[key] not in ("", None)]
        non_act = [float(r[key]) for r in rows
                   if r["llm_action"] in ("SKIP", "DISQUALIFY") and r[key] not in ("", None)]
        a = stats(act_vals); n = stats(non_act)
        if a and n:
            lift = a["avg"] - n["avg"]
            print(f"  {window:<4}  ACT avg={a['avg']:+.2f}% (n={a['n']})  "
                  f"NON-ACT avg={n['avg']:+.2f}% (n={n['n']})  "
                  f"lift={lift:+.2f}%")


def write_csv(rows: list[dict], src: Path, blinded: bool, empirical: bool = False):
    suffix = ""
    if blinded: suffix += "_blinded"
    if empirical: suffix += "_empirical"
    out = src.parent / (src.stem + f"_ablation{suffix}.csv")
    if not rows:
        return
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n[Output] {out}")


def main():
    args = sys.argv[1:]
    blinded = "--blinded" in args
    empirical = "--empirical" in args
    args = [a for a in args if not a.startswith("--")]
    if not args:
        print("Usage: python -m backtest.ablation_test [--blinded] [--empirical] <csv>")
        sys.exit(1)

    csv_path = Path(args[0])
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        sys.exit(1)

    rows = run_ablation(csv_path, blinded=blinded, empirical=empirical)
    write_csv(rows, csv_path, blinded, empirical)
    summarize(rows)


if __name__ == "__main__":
    main()
