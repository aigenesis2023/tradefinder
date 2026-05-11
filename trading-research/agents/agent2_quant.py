"""
Agent 2 — Quantitative Filter

Fully deterministic. No LLM calls. Score and narrative summary derived from
VSA proxies and relative-strength data.

VSA proxies (attempted, not mandatory):
  1. Volume percentile vs 30-day distribution
  2. True range compression vs ATR
  3. Close position within candle range
  4. Multi-day absorption: high volume flat VWAP 3+ consecutive days
  5. RVOL filter: flag VSA divergence only if RVOL > 2.0 within 1-ATR range
  6. Relative strength vs IWM (additional proxy)

Hard rules:
  - Fewer than 3 of 5 proxies computable: cap quant_confirmation_score at 2.5
  - Short interest > 20% of float: always flagged
  - $100M-$200M + avg daily dollar volume < $500K: liquidity flag
  - Stale OHLCV (> 2 trading days): stale_data_flag
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import yfinance as yf
import pandas as pd
from orchestrator.request_budget import BudgetManager

RVOL_VSA_THRESHOLD = 2.0
SHORT_INTEREST_FLAG_THRESHOLD = 0.20
DAILY_DOLLAR_VOLUME_MIN = 500_000
STALE_DATA_DAYS = 2
MIN_PROXIES_FOR_FULL_SCORE = 3
QUANT_SCORE_CAP_INSUFFICIENT_PROXIES = 2.5
IWM_TICKER = "IWM"


@dataclass
class Agent2Result:
    ticker: str
    quant_confirmation_score: float
    proxies_computed: int
    proxies_available: int
    volume_percentile: Optional[float]
    atr_compression: Optional[float]
    close_position_ratio: Optional[float]
    absorption_detected: bool
    rvol: Optional[float]
    rvol_flag: bool
    rs_vs_iwm: Optional[float]
    short_interest_pct: Optional[float]
    short_interest_flag: bool
    float_risk_flag: bool
    stale_data_flag: bool
    sector_beta_flag: bool
    liquidity_warning: bool
    avg_daily_dollar_volume: float
    trend_context: str
    missing_data: list = field(default_factory=list)
    quant_notes: str = ""


def _fetch_ohlcv(ticker: str, period: str = "3mo") -> Optional[pd.DataFrame]:
    try:
        df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        if df.empty:
            return None
        # yfinance ≥0.2.x returns MultiIndex columns (field, ticker) for single tickers too
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return None


def _is_stale(df: pd.DataFrame) -> bool:
    if df is None or df.empty:
        return True
    last_date = df.index[-1]
    if hasattr(last_date, 'date'):
        last_date = last_date.date()
    delta = (datetime.utcnow().date() - last_date).days
    trading_days_missed = max(0, delta - (delta // 7) * 2)
    return trading_days_missed > STALE_DATA_DAYS


def _compute_rvol(df: pd.DataFrame, window: int = 20) -> Optional[float]:
    try:
        avg_vol = df["Volume"].tail(window + 1).iloc[:-1].mean()
        last_vol = float(df["Volume"].iloc[-1])
        return round(last_vol / avg_vol, 3) if avg_vol > 0 else None
    except Exception:
        return None


def _compute_atr(df: pd.DataFrame, window: int = 14) -> Optional[float]:
    try:
        high, low, close = df["High"], df["Low"], df["Close"]
        prev_close = close.shift(1)
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        return float(tr.tail(window).mean())
    except Exception:
        return None


def _compute_proxies(ticker: str, df: pd.DataFrame, market_cap_m: float) -> dict:
    missing, computed, proxies = [], 0, {}

    # Proxy 1: Volume percentile
    try:
        vol_series = df["Volume"].tail(30)
        last_vol = float(df["Volume"].iloc[-1])
        proxies["volume_percentile"] = round(float((vol_series < last_vol).mean() * 100), 1)
        computed += 1
    except Exception:
        proxies["volume_percentile"] = None
        missing.append("volume_percentile")

    # Proxy 2: ATR compression
    try:
        atr = _compute_atr(df)
        recent_tr_avg = float((df["High"] - df["Low"]).tail(5).mean())
        if atr and atr > 0:
            proxies["atr_compression"] = round(recent_tr_avg / atr, 3)
            computed += 1
        else:
            proxies["atr_compression"] = None
            missing.append("atr_compression")
    except Exception:
        proxies["atr_compression"] = None
        missing.append("atr_compression")

    # Proxy 3: Close position within candle
    try:
        row = df.iloc[-1]
        candle_range = float(row["High"]) - float(row["Low"])
        if candle_range > 0:
            proxies["close_position_ratio"] = round((float(row["Close"]) - float(row["Low"])) / candle_range, 3)
            computed += 1
        else:
            proxies["close_position_ratio"] = None
            missing.append("close_position_ratio")
    except Exception:
        proxies["close_position_ratio"] = None
        missing.append("close_position_ratio")

    # Proxy 4: Multi-day absorption
    try:
        recent = df.tail(5)
        vwap = (recent["Close"] * recent["Volume"]).cumsum() / recent["Volume"].cumsum()
        vwap_range = float(vwap.max() - vwap.min())
        atr_val = _compute_atr(df) or 1.0
        high_vol_days = int((recent["Volume"] > df["Volume"].mean() * 1.5).sum())
        proxies["absorption_detected"] = bool((vwap_range < atr_val * 0.5) and (high_vol_days >= 3))
        computed += 1
    except Exception:
        proxies["absorption_detected"] = False
        missing.append("absorption")

    # Proxy 5: RVOL flag
    rvol = _compute_rvol(df)
    proxies["rvol"] = rvol
    if rvol is not None:
        atr_val = _compute_atr(df) or 0
        price = float(df["Close"].iloc[-1])
        price_20d = float(df["Close"].tail(20).mean())
        proxies["rvol_flag"] = rvol > RVOL_VSA_THRESHOLD and abs(price - price_20d) <= atr_val
        computed += 1
    else:
        proxies["rvol_flag"] = False
        missing.append("rvol")

    proxies["proxies_computed"] = computed
    proxies["missing_data"] = missing
    return proxies


def _fetch_short_interest(ticker: str) -> Optional[float]:
    try:
        info = yf.Ticker(ticker).info or {}
        val = info.get("shortPercentOfFloat")
        return float(val) if val is not None else None
    except Exception:
        return None


def _compute_rs_vs_iwm(ticker_df: pd.DataFrame, window: int = 20) -> Optional[float]:
    try:
        iwm_df = _fetch_ohlcv(IWM_TICKER, period="3mo")
        if iwm_df is None or iwm_df.empty:
            return None
        ticker_ret = float(ticker_df["Close"].iloc[-1] / ticker_df["Close"].iloc[-window] - 1)
        iwm_ret = float(iwm_df["Close"].iloc[-1] / iwm_df["Close"].iloc[-window] - 1)
        return round(ticker_ret - iwm_ret, 4)
    except Exception:
        return None


def _check_sector_beta(ticker: str, rvol: Optional[float]) -> bool:
    if rvol is None or rvol < RVOL_VSA_THRESHOLD:
        return False
    try:
        sector = (yf.Ticker(ticker).info or {}).get("sector", "")
        etf_map = {
            "Technology": "XLK", "Healthcare": "XLV", "Industrials": "XLI",
            "Financial Services": "XLF", "Consumer Cyclical": "XLY",
            "Energy": "XLE", "Basic Materials": "XLB", "Utilities": "XLU",
        }
        etf = etf_map.get(sector)
        if not etf:
            return False
        etf_df = _fetch_ohlcv(etf, period="2mo")
        if etf_df is None:
            return False
        etf_rvol = _compute_rvol(etf_df)
        return etf_rvol is not None and etf_rvol > RVOL_VSA_THRESHOLD
    except Exception:
        return False


def _deterministic_quant_score(proxies: dict, rs_vs_iwm: Optional[float]) -> tuple[float, str, str]:
    """
    Compute quant_confirmation deterministically from VSA proxies.
    Returns (score 0.5-5.0, trend_context, quant_notes).
    """
    score = 2.5
    contribs: list[str] = []

    vp = proxies.get("volume_percentile")
    if vp is not None:
        if vp >= 80:
            score += 0.6; contribs.append(f"vol pct {vp:.0f} (top quintile)")
        elif vp >= 60:
            score += 0.3; contribs.append(f"vol pct {vp:.0f} (above median)")
        elif vp <= 20:
            score -= 0.3; contribs.append(f"vol pct {vp:.0f} (bottom quintile)")

    atr_c = proxies.get("atr_compression")
    if atr_c is not None:
        if atr_c < 0.7:
            score += 0.4; contribs.append(f"ATR compression {atr_c:.2f}")
        elif atr_c > 1.3:
            score -= 0.2; contribs.append(f"ATR expansion {atr_c:.2f}")

    cp = proxies.get("close_position_ratio")
    if cp is not None:
        if cp >= 0.7:
            score += 0.3; contribs.append(f"close near high ({cp:.2f})")
        elif cp <= 0.3:
            score -= 0.3; contribs.append(f"close near low ({cp:.2f})")

    if proxies.get("absorption_detected"):
        score += 0.5
        contribs.append("absorption detected")

    if rs_vs_iwm is not None:
        if rs_vs_iwm > 0.02:
            score += 0.4; contribs.append(f"RS vs IWM +{rs_vs_iwm:.2%}")
        elif rs_vs_iwm < -0.02:
            score -= 0.4; contribs.append(f"RS vs IWM {rs_vs_iwm:.2%}")

    score = round(max(0.5, min(5.0, score)), 2)
    trend_context = "; ".join(contribs) if contribs else "no signal contributions"
    quant_notes = f"deterministic quant {score:.2f}/5"
    return score, trend_context, quant_notes


def run_agent2(ticker: str, market_cap_m: float, budget: BudgetManager) -> Agent2Result:
    df = _fetch_ohlcv(ticker)
    stale = _is_stale(df) if df is not None else True

    if df is None:
        return Agent2Result(
            ticker=ticker, quant_confirmation_score=1.0, proxies_computed=0, proxies_available=6,
            volume_percentile=None, atr_compression=None, close_position_ratio=None,
            absorption_detected=False, rvol=None, rvol_flag=False, rs_vs_iwm=None,
            short_interest_pct=None, short_interest_flag=False, float_risk_flag=False,
            stale_data_flag=True, sector_beta_flag=False, liquidity_warning=False,
            avg_daily_dollar_volume=0.0, trend_context="No data", missing_data=["ohlcv"],
        )

    proxies = _compute_proxies(ticker, df, market_cap_m)
    rs_vs_iwm = _compute_rs_vs_iwm(df)
    if rs_vs_iwm is not None:
        proxies["proxies_computed"] = proxies.get("proxies_computed", 0) + 1

    short_pct = _fetch_short_interest(ticker)
    short_flag = short_pct is not None and short_pct > SHORT_INTEREST_FLAG_THRESHOLD
    price = float(df["Close"].iloc[-1])
    avg_vol = float(df["Volume"].mean())
    avg_dollar_vol = avg_vol * price
    liquidity_flag = market_cap_m < 200 and avg_dollar_vol < DAILY_DOLLAR_VOLUME_MIN
    sector_beta = _check_sector_beta(ticker, proxies.get("rvol"))

    raw_score, trend_context, quant_notes = _deterministic_quant_score(proxies, rs_vs_iwm)

    if proxies.get("proxies_computed", 0) < MIN_PROXIES_FOR_FULL_SCORE:
        raw_score = min(raw_score, QUANT_SCORE_CAP_INSUFFICIENT_PROXIES)
    if sector_beta:
        raw_score = max(0.0, raw_score - 0.5)

    return Agent2Result(
        ticker=ticker, quant_confirmation_score=round(raw_score, 3),
        proxies_computed=proxies.get("proxies_computed", 0), proxies_available=6,
        volume_percentile=proxies.get("volume_percentile"), atr_compression=proxies.get("atr_compression"),
        close_position_ratio=proxies.get("close_position_ratio"), absorption_detected=bool(proxies.get("absorption_detected", False)),
        rvol=proxies.get("rvol"), rvol_flag=bool(proxies.get("rvol_flag", False)),
        rs_vs_iwm=rs_vs_iwm, short_interest_pct=short_pct, short_interest_flag=short_flag,
        float_risk_flag=False, stale_data_flag=stale, sector_beta_flag=sector_beta,
        liquidity_warning=liquidity_flag, avg_daily_dollar_volume=round(avg_dollar_vol, 2),
        trend_context=trend_context, missing_data=proxies.get("missing_data", []),
        quant_notes=quant_notes,
    )
