"""
Neglect Screen — Gate 2 of the Dual Entry Gate.

Lightened rules (3 of 4 must pass):
  1. Analyst coverage: fewer than 8 active analyst ratings
  2. News volume: fewer than 3 meaningful news events in prior 30 days
  3. Institutional ownership: below 30% of free float
  4. Trading volume: persistently below 6-month average (flat neglect, not distress)

All thresholds are enforced here in Python. Agent prompts never make these decisions.

Data sources (all free):
  - yfinance: institutional holders, volume, analyst count
  - Finviz scrape: analyst count fallback, short interest, institutional %
"""

from dataclasses import dataclass, field
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import re

# Thresholds
MAX_ANALYST_RATINGS = 8
MAX_NEWS_EVENTS_30D = 3
MAX_INSTITUTIONAL_OWNERSHIP_PCT = 30.0
CONDITIONS_REQUIRED = 3  # of 4 must pass

FINVIZ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)"
}


@dataclass
class NeglectResult:
    ticker: str
    passes: bool
    conditions_passed: int
    analyst_count: int
    analyst_pass: bool
    news_count_30d: int
    news_pass: bool
    institutional_pct: float
    institutional_pass: bool
    volume_ratio: float
    volume_pass: bool
    missing_data: list = field(default_factory=list)
    notes: str = ""


def _get_analyst_count_yfinance(ticker_obj) -> int | None:
    """
    Use numberOfAnalystOpinions from .info — this is standing analyst coverage,
    not recommendation changes. Much more accurate for coverage-gap detection.
    Falls back to recommendation-change count only if info field is missing.
    """
    try:
        info = ticker_obj.info or {}
        count = info.get("numberOfAnalystOpinions")
        if count is not None:
            return int(count)
        # Fallback: count distinct firms in recent recommendation changes
        recs = ticker_obj.recommendations
        if recs is None or recs.empty:
            return None
        # Count distinct analyst firms in last 90 rows, not just row count
        if "Firm" in recs.columns:
            return recs.tail(90)["Firm"].nunique()
        return len(recs.tail(90))
    except Exception:
        return None


def _get_analyst_count_finviz(ticker: str) -> int | None:
    try:
        url = f"https://finviz.com/quote.ashx?t={ticker}"
        resp = requests.get(url, headers=FINVIZ_HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        # Finviz shows analyst recom count in the ratings table
        ratings_table = soup.find("table", class_="fullview-ratings-outer")
        if ratings_table:
            rows = ratings_table.find_all("tr")
            return len(rows)
        return None
    except Exception:
        return None


def _get_news_count_30d(ticker_obj) -> int | None:
    try:
        news = ticker_obj.news
        if not news:
            return 0
        import time
        cutoff = time.time() - (30 * 24 * 3600)
        recent = [n for n in news if n.get("providerPublishTime", 0) >= cutoff]
        return len(recent)
    except Exception:
        return None


def _get_institutional_pct_yfinance(ticker_obj) -> float | None:
    try:
        info = ticker_obj.info
        pct = info.get("heldPercentInstitutions")
        if pct is None:
            return None
        val = round(float(pct) * 100, 2)
        # yfinance double-counts short-loaned shares, producing values >100% that
        # are data artifacts, not real ownership. Treat anything above 100 as
        # an unreliable read and fall back to other sources.
        if val > 100:
            return None
        return val
    except Exception:
        return None


def _get_institutional_pct_finviz(ticker: str) -> float | None:
    try:
        url = f"https://finviz.com/quote.ashx?t={ticker}"
        resp = requests.get(url, headers=FINVIZ_HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        cells = soup.find_all("td", class_="snapshot-td2")
        labels = soup.find_all("td", class_="snapshot-td2-cp")
        for label, cell in zip(labels, cells):
            if "Inst Own" in label.text:
                val = cell.text.strip().replace("%", "")
                return float(val)
        return None
    except Exception:
        return None


def _get_volume_ratio(ticker_obj) -> float | None:
    """Returns ratio of recent 20d avg volume to 6-month avg volume. <1.0 means below average."""
    try:
        hist = ticker_obj.history(period="6mo")
        if hist.empty or len(hist) < 20:
            return None
        avg_6mo = hist["Volume"].mean()
        avg_20d = hist["Volume"].tail(20).mean()
        if avg_6mo == 0:
            return None
        return round(float(avg_20d / avg_6mo), 3)
    except Exception:
        return None


def screen_ticker(ticker: str) -> NeglectResult:
    missing = []
    ticker_obj = yf.Ticker(ticker)

    # 1. Analyst count
    analyst_count = _get_analyst_count_yfinance(ticker_obj)
    if analyst_count is None:
        analyst_count = _get_analyst_count_finviz(ticker)
    if analyst_count is None:
        missing.append("analyst_count")
        analyst_count = 0
        analyst_pass = True  # missing data → assume neglected, penalise score elsewhere
    else:
        analyst_pass = analyst_count < MAX_ANALYST_RATINGS

    # 2. News count
    news_count = _get_news_count_30d(ticker_obj)
    if news_count is None:
        missing.append("news_count")
        news_count = 0
        news_pass = True
    else:
        news_pass = news_count < MAX_NEWS_EVENTS_30D

    # 3. Institutional ownership
    inst_pct = _get_institutional_pct_yfinance(ticker_obj)
    if inst_pct is None:
        inst_pct = _get_institutional_pct_finviz(ticker)
    if inst_pct is None:
        missing.append("institutional_pct")
        inst_pct = 0.0
        institutional_pass = True
    else:
        institutional_pass = inst_pct < MAX_INSTITUTIONAL_OWNERSHIP_PCT

    # 4. Volume ratio
    volume_ratio = _get_volume_ratio(ticker_obj)
    if volume_ratio is None:
        missing.append("volume_ratio")
        volume_ratio = 1.0
        volume_pass = True
    else:
        volume_pass = volume_ratio < 1.0

    conditions_passed = sum([analyst_pass, news_pass, institutional_pass, volume_pass])
    passes = conditions_passed >= CONDITIONS_REQUIRED

    notes_parts = []
    if missing:
        notes_parts.append(f"missing data: {', '.join(missing)}")
    if not passes:
        failed = []
        if not analyst_pass:
            failed.append(f"analysts={analyst_count}>={MAX_ANALYST_RATINGS}")
        if not news_pass:
            failed.append(f"news={news_count}>={MAX_NEWS_EVENTS_30D}")
        if not institutional_pass:
            failed.append(f"inst={inst_pct:.1f}%>={MAX_INSTITUTIONAL_OWNERSHIP_PCT}%")
        if not volume_pass:
            failed.append(f"volume_ratio={volume_ratio:.2f}>=1.0")
        notes_parts.append(f"failed: {'; '.join(failed)}")

    return NeglectResult(
        ticker=ticker,
        passes=passes,
        conditions_passed=conditions_passed,
        analyst_count=analyst_count,
        analyst_pass=analyst_pass,
        news_count_30d=news_count,
        news_pass=news_pass,
        institutional_pct=inst_pct,
        institutional_pass=institutional_pass,
        volume_ratio=volume_ratio,
        volume_pass=volume_pass,
        missing_data=missing,
        notes=" | ".join(notes_parts),
    )


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "KTOS"
    result = screen_ticker(ticker)
    print(f"\nNeglect screen: {ticker}")
    print(f"  Pass: {result.passes} ({result.conditions_passed}/4 conditions met)")
    print(f"  Analysts: {result.analyst_count} {'✓' if result.analyst_pass else '✗'}")
    print(f"  News 30d: {result.news_count_30d} {'✓' if result.news_pass else '✗'}")
    print(f"  Inst own: {result.institutional_pct:.1f}% {'✓' if result.institutional_pass else '✗'}")
    print(f"  Vol ratio: {result.volume_ratio:.2f} {'✓' if result.volume_pass else '✗'}")
    if result.notes:
        print(f"  Notes: {result.notes}")
