"""
run_pipeline.py — Insider cluster screener (daily script).

Fetches all open-market insider purchases (SEC Form 4, code "P") from OpenInsider
for the last 45 days, detects clusters of 3+ unique insiders within any rolling
30-day window, filters by market cap $200M-$3B, and outputs a simple report.

This is a STEP-1 SCREENING TOOL, not a complete trading strategy. It surfaces
structurally meaningful insider-cluster events for the operator to research further
(fundamentals, news, valuation, sector context) before deciding whether to take a
position.

Rules (literature-anchored):
  1. Fetch all open-market insider purchases from OpenInsider (last 45 days)
  2. Filter: transaction value >= $100K, qualifying roles only (CEO/CFO/COO/Chairman/
     Director/President/EVP/SVP), exclude entity names (LLC, LP, Fund, etc.)
  3. Market cap $200M-$3B (via yfinance, with caching)
  4. Detect clusters: 3+ unique insiders at the same ticker within any rolling 30-day
     window (Lakonishok-Lee 2001; Alldredge-Blank 2019; Kang et al. 2018)
  5. Opportunistic soft gate: require at least one insider in the cluster NOT to be a
     routine trader (Cohen-Malloy-Pomorski 2012). Routine = bought in the same calendar
     month for 3 consecutive prior years.
  6. Output a simple report: ticker, insider names, roles, purchase dates, total value,
     opportunistic count
  7. Hold horizon: 180 days (informational note only)

Usage:
  python run_pipeline.py
  python run_pipeline.py --dry-run
"""

import argparse
import json
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import yfinance as yf

from pipeline.state_manager import init_db, log_signal
from pipeline.openinsider_feed import scan as scan_openinsider
from pipeline.insider_scanner import InsiderCluster


# ── Thresholds ────────────────────────────────────────────────────────────
MARKET_CAP_MIN_M = 200
MARKET_CAP_MAX_M = 3000
RECOMMENDED_HOLD_DAYS = 180
CMP_MIN_HISTORY_DAYS = 1095  # 3 years needed for valid routine/opportunistic classification

# OpenInsider feed parameters
RECENT_WINDOW_DAYS = 45
HISTORY_DAYS = 1100  # ~3 years for routine/opportunistic classification

# Ticker enrichment cache
ENRICH_CACHE_PATH = Path(__file__).parent / "cache" / "enrich_cache.json"
ENRICH_CACHE_TTL_SECONDS = 24 * 3600  # 1 day


def _load_enrich_cache() -> dict:
    """Load the enrichment cache from disk. Returns {} if missing or corrupt."""
    if not ENRICH_CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(ENRICH_CACHE_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_enrich_cache(cache: dict) -> None:
    """Persist the enrichment cache to disk."""
    ENRICH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENRICH_CACHE_PATH.write_text(json.dumps(cache, indent=2))


def _enrich_ticker(ticker: str) -> dict:
    """Fetch market cap, price, and listing date from yfinance, with 24h JSON caching."""
    cache = _load_enrich_cache()
    entry = cache.get(ticker)
    now = time.time()
    if entry and (now - entry.get("ts", 0)) < ENRICH_CACHE_TTL_SECONDS:
        return {
            "market_cap_m": entry["mcap_m"],
            "company_name": entry.get("name", ticker),
            "price": entry.get("price"),
            "high_52w": entry.get("high_52w"),
            "trading_history_days": entry.get("history_days"),
        }

    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        market_cap_m = (info.get("marketCap") or 0) / 1e6
        company_name = info.get("longName") or ticker
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        high_52w = info.get("fiftyTwoWeekHigh")

        # Compute days since first trade. If yfinance lacks the epoch field (common for
        # recent ticker changes or newly listed stocks), fall back to counting trading
        # days in the full price history.
        first_trade_epoch = info.get("firstTradeDateEpochUtc")
        trading_history_days = None
        if first_trade_epoch:
            trading_history_days = (now - first_trade_epoch) / 86400
        else:
            try:
                hist = t.history(period="max")
                if not hist.empty:
                    trading_history_days = (now - hist.index[0].timestamp()) / 86400
            except Exception:
                pass

        result = {
            "market_cap_m": round(market_cap_m, 2),
            "company_name": company_name,
            "price": price,
            "high_52w": high_52w,
            "trading_history_days": round(trading_history_days) if trading_history_days else None,
        }
        cache[ticker] = {
            "mcap_m": result["market_cap_m"],
            "name": company_name,
            "price": price,
            "high_52w": high_52w,
            "history_days": result["trading_history_days"],
            "ts": now,
        }
        _save_enrich_cache(cache)
        return result
    except Exception as e:
        print(f"  [yfinance] Warning: enrich failed for {ticker}: {e}", flush=True)
        return {}


def _get_pre_cluster_close(ticker: str, cluster_start: str) -> float | None:
    """Return the highest close in the 10 trading days before cluster_start.

    Using the max (rather than the last close) surfaces the pre-event price even when
    the cluster_start date immediately follows a crash — e.g., EFOR crashed -52% on
    Apr 23 and insiders bought Apr 24. The last close before cluster_start is the
    crashed price ($19.53); the max ($40.43) tells the real story.
    """
    try:
        t = yf.Ticker(ticker)
        end_dt = datetime.strptime(cluster_start, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=10)
        hist = t.history(start=start_dt.strftime("%Y-%m-%d"),
                         end=end_dt.strftime("%Y-%m-%d"))
        if not hist.empty:
            return float(hist["Close"].max())
    except Exception:
        pass
    return None


def _format_report(run_id: str, signals: list, candidates_evaluated: int,
                   discarded_log: list) -> str:
    """Format a clean, readable report of detected clusters."""
    lines = []
    today = date.today().strftime("%Y-%m-%d")
    lines.append(f"=== INSIDER CLUSTER SCREENING — {today} ===")
    lines.append(f"Run ID: {run_id} | Clusters evaluated: {candidates_evaluated} | "
                 f"Signals surfaced: {len(signals)}")
    lines.append("")
    lines.append("STEP-1 SCREENING TOOL. Research each candidate before trading.")
    lines.append("")
    lines.append("─" * 70)
    lines.append("INSIDER CLUSTER SIGNALS")
    lines.append("─" * 70)

    if not signals:
        lines.append("")
        lines.append("NO QUALIFYING CLUSTERS TODAY. THIS IS A VALID RESULT.")
        lines.append(f"(OpenInsider feed evaluated {candidates_evaluated} cluster "
                     f"candidates; none passed all filters.)")
    else:
        # Sort: most opportunistic first, then most insiders, then largest total value
        signals.sort(
            key=lambda s: (s["opportunistic_count"], s["unique_insiders"], s["total_usd"]),
            reverse=True,
        )
        for i, s in enumerate(signals, start=1):
            # CMP quality label — honest about insufficient history
            if not s.get("cmp_reliable"):
                quality = "DATA INSUFFICIENT (limited trading history)"
            elif s["opportunistic_count"] == s["unique_insiders"]:
                quality = "ALL OPPORTUNISTIC"
            else:
                quality = f"{s['opportunistic_count']}/{s['unique_insiders']} opportunistic"

            # Staleness: days since last insider purchase
            days_since = (date.today() - datetime.strptime(s["cluster_end"], "%Y-%m-%d").date()).days

            lines.append("")
            lines.append(f"{i}. {s['ticker']} — {s['company_name']}")
            lines.append(f"   Cluster: {s['unique_insiders']} insiders | "
                         f"${s['total_usd']:,.0f} total | Quality: {quality}")
            if s["routine_insiders"]:
                lines.append(f"   Routine traders (low signal value): "
                             f"{', '.join(s['routine_insiders'])}")
            lines.append(f"   Market cap: ${s['market_cap_m']:,.0f}M")

            # Price context + insider VWAP comparison
            price = s.get("price")
            high_52w = s.get("high_52w")
            insider_vwap = s.get("insider_vwap")
            if price is not None and high_52w is not None and high_52w > 0:
                drawdown = ((price - high_52w) / high_52w) * 100
                dd_part = f" ({drawdown:+.1f}% from 52w high)"
            else:
                dd_part = ""
            if price is not None:
                price_str = f"${price:.2f}{dd_part}"
                if insider_vwap and insider_vwap > 0:
                    vwap_delta = ((price - insider_vwap) / insider_vwap) * 100
                    direction = "above" if vwap_delta >= 0 else "below"
                    price_str += f" | Insider avg: ${insider_vwap:.2f} (current {abs(vwap_delta):.1f}% {direction})"
                lines.append(f"   Price: {price_str}")
            elif price is not None:
                lines.append(f"   Price: ${price:.2f}")

            lines.append(f"   Cluster window: {s['cluster_start']} -> {s['cluster_end']} ({days_since}d ago)")
            if s.get("insider_details"):
                purchases = ", ".join(
                    f"{d['name']} ({d['role']}, {d['date']} @ ${d['price']:.2f}, ${d['value']:,.0f})"
                    for d in s["insider_details"]
                )
                lines.append(f"   Purchases: {purchases}")

            # Pre-cluster price context — flag post-crash clusters
            pre_close = s.get("pre_cluster_close")
            if pre_close and insider_vwap and pre_close > 0:
                pre_delta = ((insider_vwap - pre_close) / pre_close) * 100
                if pre_delta < -20:
                    lines.append(f"   ⚠  Pre-cluster: ${pre_close:.2f} — insiders bought "
                                 f"after {abs(pre_delta):.0f}% crash")
                elif pre_delta < -5:
                    lines.append(f"   Pre-cluster: ${pre_close:.2f} — insiders bought "
                                 f"into {abs(pre_delta):.0f}% decline")

            lines.append(f"   Recommended hold: {RECOMMENDED_HOLD_DAYS} days")

        # Show education note if any signal has insufficient history
        if any(not s.get("cmp_reliable") for s in signals):
            lines.append("")
            lines.append("   ⚠  DATA INSUFFICIENT: Limited trading history (<3 years).")
            lines.append("      IPO-period insider purchases are often pre-arranged allocations,")
            lines.append("      not discretionary conviction buys. Research accordingly.")

    lines.append("")
    lines.append("─" * 70)
    if discarded_log:
        lines.append(f"DISCARDED ({len(discarded_log)}):")
        for entry in discarded_log[:30]:
            lines.append(f"  {entry['ticker']} — {entry['reason']}")
        if len(discarded_log) > 30:
            lines.append(f"  ... and {len(discarded_log) - 30} more")
    else:
        lines.append("DISCARDED: none")
    lines.append("")
    lines.append("─" * 70)
    lines.append("REFERENCE")
    lines.append(f"  Discovery:            OpenInsider feed (full-market scan)")
    lines.append(f"  Recommended hold:     {RECOMMENDED_HOLD_DAYS} days "
                 f"(Jeng-Metrick-Zeckhauser 2003; Cohen-Malloy-Pomorski 2012)")
    lines.append(f"  Opportunistic gate:   cluster discarded if 0 opportunistic insiders "
                 f"(CMP 2012)")
    lines.append("")
    lines.append("DO YOUR OWN RESEARCH ON EACH SURFACED TICKER BEFORE TRADING.")
    return "\n".join(lines)


def _save_report(report: str, run_id: str) -> Path:
    """Save the report to the research_logs directory."""
    logs_dir = Path(__file__).parent / "research_logs"
    logs_dir.mkdir(exist_ok=True)
    ts = datetime.now(tz=None).strftime("%Y%m%d_%H%M%S")
    path = logs_dir / f"report_{ts}_{run_id}.md"
    path.write_text(report)
    return path


def main(dry_run: bool = False):
    init_db()
    run_id = str(uuid.uuid4())[:8]
    print(f"\n[Pipeline] Starting run {run_id} {'(DRY RUN)' if dry_run else ''}")

    if dry_run:
        print(f"[Pipeline] DRY RUN — would scrape OpenInsider for last "
              f"{RECENT_WINDOW_DAYS}d and classify against {HISTORY_DAYS}d history.")
        return

    # Phase 1: full-market discovery via OpenInsider
    clusters = scan_openinsider(
        recent_window_days=RECENT_WINDOW_DAYS,
        history_days=HISTORY_DAYS,
    )

    signals: list[dict] = []
    discarded_log: list[dict] = []

    # Phase 2: per-cluster enrichment + filtering
    for cluster in clusters:
        ticker = cluster.ticker

        # Opportunistic soft gate (CMP 2012): discard if 0 opportunistic insiders
        if cluster.opportunistic_count < 1:
            discarded_log.append({
                "ticker": ticker,
                "reason": "all insiders classified routine (no opportunistic signal)",
            })
            continue

        enriched = _enrich_ticker(ticker)
        if not enriched:
            discarded_log.append({"ticker": ticker, "reason": "yfinance enrichment failed"})
            continue

        market_cap_m = enriched.get("market_cap_m", 0)
        if market_cap_m < MARKET_CAP_MIN_M or market_cap_m > MARKET_CAP_MAX_M:
            discarded_log.append({
                "ticker": ticker,
                "reason": f"mcap ${market_cap_m:.0f}M outside "
                          f"${MARKET_CAP_MIN_M}M-${MARKET_CAP_MAX_M}M",
            })
            continue

        # Build per-insider detail: name, role, date, price paid, size
        sorted_txns = sorted(cluster.transactions, key=lambda x: x.date)
        insider_details = [
            {"name": t.name, "role": t.role, "date": t.date,
             "price": t.price_per_share, "value": t.total_usd}
            for t in sorted_txns
        ]

        # Insider volume-weighted average price
        total_txn_value = sum(t.shares * t.price_per_share for t in cluster.transactions)
        total_shares = sum(t.shares for t in cluster.transactions)
        insider_vwap = total_txn_value / total_shares if total_shares else 0

        # Pre-cluster price context — what was the stock trading at before insiders bought?
        pre_cluster_close = _get_pre_cluster_close(ticker, cluster.cluster_start)

        # CMP reliability: need 3+ years of trading history for valid classification.
        # Only flag as unreliable when we have positive evidence of a recent listing.
        # Missing data (None) means yfinance doesn't know — not that the stock is new.
        history_days = enriched.get("trading_history_days")
        cmp_reliable = not (history_days is not None and history_days < CMP_MIN_HISTORY_DAYS)

        signal = {
            "ticker": ticker,
            "company_name": enriched.get("company_name", ticker),
            "cluster_start": cluster.cluster_start,
            "cluster_end": cluster.cluster_end,
            "unique_insiders": cluster.unique_insiders,
            "opportunistic_count": cluster.opportunistic_count,
            "routine_insiders": cluster.routine_insiders,
            "total_usd": cluster.total_usd,
            "market_cap_m": market_cap_m,
            "insider_names": sorted({t.name for t in cluster.transactions}),
            "insider_roles": sorted({t.role for t in cluster.transactions if t.role}),
            "insider_details": insider_details,
            "insider_vwap": round(insider_vwap, 2),
            "price": enriched.get("price"),
            "high_52w": enriched.get("high_52w"),
            "pre_cluster_close": round(pre_cluster_close, 2) if pre_cluster_close else None,
            "cmp_reliable": cmp_reliable,
        }
        signals.append(signal)

        # Log to SQLite for record-keeping
        log_signal(run_id, {
            "ticker": signal["ticker"],
            "signal_date": signal["cluster_end"],
            "cluster_start": signal["cluster_start"],
            "cluster_end": signal["cluster_end"],
            "unique_insiders": signal["unique_insiders"],
            "opportunistic_count": signal["opportunistic_count"],
            "total_usd": signal["total_usd"],
            "insider_names": json.dumps(signal["insider_names"]),
            "insider_roles": json.dumps(signal["insider_roles"]),
            "company_name": signal["company_name"],
            "market_cap_m": signal["market_cap_m"],
        })

    report = _format_report(run_id, signals, len(clusters), discarded_log)
    path = _save_report(report, run_id)
    print(report)
    print(f"\n[Pipeline] Report saved to {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show plan without scraping")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
