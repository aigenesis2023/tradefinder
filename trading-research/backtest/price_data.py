"""
Historical price data — strictly temporally isolated into two sections.

SECTION A  (pre-signal):  all fetches use end_date <= signal_date.
                          Used for: market cap, 52-week low, materiality.
                          MUST NOT reference any data after signal_date.

SECTION B  (outcomes):    all fetches use start_date > signal_date.
                          Used for: 7d / 10d / 30d return measurement.
                          MUST NOT reference any data on or before signal_date.

These sections are enforced at the function-signature level.
The function names make the section explicit: get_pre_signal_data vs get_outcome_data.
Cross-section calls are a bug.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

PRICE_CACHE_DIR = Path(__file__).parent / "cache" / "price_history"

# ── Filters locked to live pipeline ──────────────────────────────────────────
MCAP_MIN_M = 200
MCAP_MAX_M = 5_000
MATERIALITY_PCT = 0.0002   # 0.02% of market cap
NEAR_LOW_PCT = 1.15        # within 15% of 52-week low


@dataclass
class PreSignalData:
    ticker: str
    as_of_date: date
    market_cap_m: float | None
    price_on_date: float | None
    low_52w: float | None
    shares_approximate: bool = False  # True when using current shares (fallback)
    in_market_cap_range: bool = False
    passes_materiality: bool = False
    near_52w_low: bool = False
    mcap_band: str = ""   # "$200M-$500M" or "$500M-$5B"


@dataclass
class OutcomeData:
    ticker: str
    signal_date: date
    entry_price: float | None       # first close strictly after signal_date
    outcome_7d: float | None        # % change at signal_date + 7 calendar days
    outcome_10d: float | None
    outcome_30d: float | None
    outcome_7d_date: str | None     # actual date used for measurement
    outcome_10d_date: str | None
    outcome_30d_date: str | None
    delisted_or_acquired: bool = False
    notes: str = ""


def _download_history(ticker: str, start: date, end: date) -> pd.DataFrame:
    """
    yfinance OHLCV download with local CSV cache.
    Cache key includes both start and end — changing the range invalidates the cache.
    """
    PRICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = PRICE_CACHE_DIR / f"{ticker}_{start}_{end}.csv"

    if cache_file.exists():
        try:
            df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            if not df.empty:
                return df
        except Exception:
            pass

    try:
        df = yf.download(
            ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=True,
            progress=False,
        )
        if df is None or df.empty:
            return pd.DataFrame()
        # Flatten MultiIndex columns (yfinance returns (Close, TICKER) etc.)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.to_csv(cache_file)
        return df
    except Exception:
        return pd.DataFrame()


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten columns and normalize index to naive dates."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


# ── SECTION A: Pre-signal data ────────────────────────────────────────────────

def get_pre_signal_data(
    ticker: str,
    signal_date: date,
    cluster_total_usd: float,
) -> PreSignalData:
    """
    Fetch market cap, 52-week low, and materiality as of signal_date.

    All price/share data has end_date = signal_date.
    Nothing from after signal_date is accessed.
    """
    result = PreSignalData(
        ticker=ticker, as_of_date=signal_date,
        market_cap_m=None, price_on_date=None, low_52w=None,
    )

    # 400 calendar days of history gives 252+ trading days for the 52-week low
    hist_start = signal_date - timedelta(days=400)
    hist_end = signal_date + timedelta(days=1)  # yfinance end is exclusive
    df = _download_history(ticker, hist_start, hist_end)
    if df.empty:
        return result

    df = _normalize(df)
    on_or_before = df[df.index.date <= signal_date]
    if on_or_before.empty:
        return result

    result.price_on_date = float(on_or_before["Close"].iloc[-1])

    # 52-week low = min close over the 252 trading days BEFORE signal_date
    strictly_before = df[df.index.date < signal_date]
    if len(strictly_before) >= 10:
        result.low_52w = float(strictly_before["Close"].tail(252).min())

    # Shares outstanding: try quarterly historical first (no future data)
    shares: float | None = None
    try:
        tk = yf.Ticker(ticker)
        shares_series = tk.get_shares_full(
            start=(signal_date - timedelta(days=120)).isoformat(),
            end=(signal_date + timedelta(days=1)).isoformat(),
        )
        if shares_series is not None and len(shares_series) > 0:
            shares = float(shares_series.iloc[-1])
    except Exception:
        pass

    if shares is None:
        # Fallback: current shares outstanding — acknowledged approximation
        try:
            info = yf.Ticker(ticker).fast_info
            shares = getattr(info, "shares", None)
        except Exception:
            pass
        if shares:
            result.shares_approximate = True

    if shares and result.price_on_date:
        result.market_cap_m = round((result.price_on_date * shares) / 1e6, 1)
        result.in_market_cap_range = MCAP_MIN_M <= result.market_cap_m <= MCAP_MAX_M
        if result.in_market_cap_range:
            result.mcap_band = (
                "$200M-$500M" if result.market_cap_m < 500 else "$500M-$5B"
            )
            floor = result.market_cap_m * 1e6 * MATERIALITY_PCT
            result.passes_materiality = cluster_total_usd >= floor

    if result.low_52w and result.price_on_date:
        result.near_52w_low = result.price_on_date <= result.low_52w * NEAR_LOW_PCT

    return result


# ── SECTION B: Outcome data ───────────────────────────────────────────────────

def get_outcome_data(ticker: str, signal_date: date) -> OutcomeData:
    """
    Measure price outcomes strictly after signal_date.

    start_date = signal_date + 1 day.  No data on or before signal_date is accessed.
    If the stock was delisted/acquired: included as delisted_or_acquired=True, not excluded.
    """
    result = OutcomeData(
        ticker=ticker, signal_date=signal_date,
        entry_price=None,
        outcome_7d=None, outcome_10d=None, outcome_30d=None,
        outcome_7d_date=None, outcome_10d_date=None, outcome_30d_date=None,
    )

    fetch_start = signal_date + timedelta(days=1)   # strictly after signal_date
    fetch_end = signal_date + timedelta(days=35)
    df = _download_history(ticker, fetch_start, fetch_end)

    if df.empty:
        result.delisted_or_acquired = True
        result.notes = "no price data after signal date (delisted/acquired)"
        return result

    df = _normalize(df)
    after = df[df.index.date > signal_date]   # double-enforce strict cutoff
    if after.empty:
        result.delisted_or_acquired = True
        result.notes = "no trading days after signal date"
        return result

    result.entry_price = float(after["Close"].iloc[0])

    def _at_days(calendar_days: int) -> tuple[float | None, str | None]:
        target = signal_date + timedelta(days=calendar_days)
        available = after[after.index.date >= target]
        if available.empty:
            return None, None
        price = float(available["Close"].iloc[0])
        pct = round((price / result.entry_price - 1) * 100, 2)
        return pct, available.index[0].strftime("%Y-%m-%d")

    result.outcome_7d,  result.outcome_7d_date  = _at_days(7)
    result.outcome_10d, result.outcome_10d_date = _at_days(10)
    result.outcome_30d, result.outcome_30d_date = _at_days(30)

    if result.outcome_30d is None:
        result.delisted_or_acquired = True
        result.notes = "insufficient data for 30d outcome (possibly delisted after signal)"

    return result
