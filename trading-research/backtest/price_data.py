"""
Historical price data with strict temporal isolation.

SECTION A  (pre-signal):  all fetches use end_date <= signal_date.
                          Used for: market cap, 52-week high/low, pre-cluster close.
                          MUST NOT reference any data after signal_date.

SECTION B  (outcomes):    all fetches use start_date > signal_date.
                          Used for: 7d / 10d / 30d / 60d / 90d / 180d return measurement.
                          MUST NOT reference any data on or before signal_date.

SECTION C  (benchmark):   IWM returns over the exact same calendar windows.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

PRICE_CACHE_DIR = Path(__file__).parent / "cache" / "price_history"
SHARES_CACHE_DIR = PRICE_CACHE_DIR / "shares"

MCAP_MIN_M = 200
MCAP_MAX_M = 3000
NEAR_LOW_PCT = 1.15  # within 15% of 52-week low


@dataclass
class PreSignalData:
    ticker: str
    as_of_date: date
    market_cap_m: float | None = None
    price: float | None = None
    low_52w: float | None = None
    high_52w: float | None = None
    pre_cluster_close: float | None = None  # max close in 10d before cluster_start
    shares_approximate: bool = False
    in_market_cap_range: bool = False
    near_52w_low: bool = False
    mcap_band: str = ""
    company_name: str = ""
    trading_history_days: float | None = None


@dataclass
class OutcomeData:
    ticker: str
    signal_date: date
    entry_price: float | None = None
    outcome_7d: float | None = None
    outcome_10d: float | None = None
    outcome_30d: float | None = None
    outcome_60d: float | None = None
    outcome_90d: float | None = None
    outcome_180d: float | None = None
    outcome_7d_date: str | None = None
    outcome_10d_date: str | None = None
    outcome_30d_date: str | None = None
    outcome_60d_date: str | None = None
    outcome_90d_date: str | None = None
    outcome_180d_date: str | None = None
    delisted_or_acquired: bool = False
    notes: str = ""


def _download_history(ticker: str, start: date, end: date) -> pd.DataFrame:
    """yfinance OHLCV download with local CSV cache, temporal-invariant."""
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
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.to_csv(cache_file)
        return df
    except Exception:
        return pd.DataFrame()


def download_shares_history(ticker: str) -> pd.Series | None:
    """Download full shares-outstanding history and cache as CSV.

    Called once per ticker during universe construction. The existing
    get_pre_signal_data() calls get_shares_full() with a narrow date range
    on every invocation, which is too slow for 2000+ tickers.
    """
    SHARES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = SHARES_CACHE_DIR / f"{ticker}.csv"

    if cache_file.exists():
        try:
            s = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            if not s.empty and len(s.columns) >= 1:
                return s.iloc[:, 0]
        except Exception:
            pass

    try:
        tk = yf.Ticker(ticker)
        shares = tk.get_shares_full(start="2017-01-01", end="2025-07-01")
        if shares is not None and len(shares) > 0:
            # Strip timezone info to avoid mixed-timezone parsing errors
            shares.index = pd.to_datetime(shares.index).tz_localize(None)
            shares.to_csv(cache_file)
            return shares
    except Exception:
        pass
    return None


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION A: Pre-signal data — everything on or before signal_date
# ═══════════════════════════════════════════════════════════════════════════════

def get_pre_signal_data(
    ticker: str,
    signal_date: date,
    cluster_start: date | None = None,
) -> PreSignalData:
    """Fetch market cap, 52w high/low, and company name as of signal_date."""
    result = PreSignalData(ticker=ticker, as_of_date=signal_date)

    hist_start = signal_date - timedelta(days=400)
    hist_end = signal_date + timedelta(days=1)
    df = _download_history(ticker, hist_start, hist_end)
    if df.empty:
        return result

    df = _normalize(df)
    on_or_before = df[df.index.date <= signal_date]
    if on_or_before.empty:
        return result

    result.price = float(on_or_before["Close"].iloc[-1])

    strictly_before = df[df.index.date < signal_date]
    if len(strictly_before) >= 10:
        result.low_52w = float(strictly_before["Close"].tail(252).min())
        result.high_52w = float(strictly_before["Close"].tail(252).max())

    # Pre-cluster crash detection: max close in 10 trading days before cluster_start
    if cluster_start:
        pre_end = cluster_start
        pre_start = cluster_start - timedelta(days=12)
        pre_df = df[(df.index.date >= pre_start) & (df.index.date < pre_end)]
        if not pre_df.empty:
            result.pre_cluster_close = float(pre_df["Close"].max())

    # Shares outstanding: historical first, fallback to current
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
        try:
            info = yf.Ticker(ticker).fast_info
            shares = getattr(info, "shares", None)
        except Exception:
            pass
        if shares:
            result.shares_approximate = True

    if shares and result.price:
        result.market_cap_m = round((result.price * shares) / 1e6, 1)
        result.in_market_cap_range = MCAP_MIN_M <= result.market_cap_m <= MCAP_MAX_M
        result.mcap_band = (
            "$200M-$500M" if result.market_cap_m < 500 else "$500M-$3B"
        )

    if result.low_52w and result.price:
        result.near_52w_low = result.price <= result.low_52w * NEAR_LOW_PCT

    # Company name + trading history from yfinance info
    try:
        info = yf.Ticker(ticker).info or {}
        result.company_name = info.get("longName") or ticker
        first_trade_epoch = info.get("firstTradeDateEpochUtc")
        if first_trade_epoch:
            result.trading_history_days = (pd.Timestamp.now().timestamp() - first_trade_epoch) / 86400
    except Exception:
        result.company_name = ticker

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION B: Outcome data — everything strictly after signal_date
# ═══════════════════════════════════════════════════════════════════════════════

def get_outcome_data(ticker: str, signal_date: date) -> OutcomeData:
    """Measure price outcomes strictly after signal_date."""
    result = OutcomeData(ticker=ticker, signal_date=signal_date)

    fetch_start = signal_date + timedelta(days=1)
    fetch_end = signal_date + timedelta(days=200)
    df = _download_history(ticker, fetch_start, fetch_end)

    if df.empty:
        result.delisted_or_acquired = True
        result.notes = "no price data after signal date (delisted/acquired)"
        return result

    df = _normalize(df)
    after = df[df.index.date > signal_date]
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

    result.outcome_7d, result.outcome_7d_date = _at_days(7)
    result.outcome_10d, result.outcome_10d_date = _at_days(10)
    result.outcome_30d, result.outcome_30d_date = _at_days(30)
    result.outcome_60d, result.outcome_60d_date = _at_days(60)
    result.outcome_90d, result.outcome_90d_date = _at_days(90)
    result.outcome_180d, result.outcome_180d_date = _at_days(180)

    if result.outcome_30d is None:
        result.delisted_or_acquired = True
        result.notes = "insufficient data for 30d outcome"

    return result
