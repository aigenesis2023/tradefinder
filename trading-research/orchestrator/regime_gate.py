"""
Regime Gate — Gate 1 of the Dual Entry Gate.

Rules (BOTH must be TRUE or hard stop):
  - VIX/VIX3M ratio is BELOW 1.0  (contango term structure = calm market)
  - IWM (Russell 2000 ETF) is ABOVE its 20-day simple moving average

VIX/VIX3M < 1.0 means near-term fear is lower than 3-month fear — a stable,
risk-on environment. Ratio >= 1.0 signals acute stress (backwardation).
This replaces the old 60-day SMA check, which lagged by weeks.

If either fails: no agents are called, regime state is logged, run terminates.
"""

from dataclasses import dataclass
import yfinance as yf
import pandas as pd
from orchestrator.state_manager import log_regime

VIX_TICKER = "^VIX"
VIX3M_TICKER = "^VIX3M"
IWM_TICKER = "IWM"
IWM_MA_DAYS = 20
FETCH_DAYS = IWM_MA_DAYS + 10


@dataclass
class RegimeResult:
    gate_pass: bool
    elite_only: bool   # True when gate fails — engine still runs but only top-decile signals surface
    vix_value: float
    vix3m_value: float
    vix_ratio: float
    vix_pass: bool
    iwm_value: float
    iwm_ma20: float
    iwm_pass: bool
    reason: str


def _fetch_closes(ticker: str, period_days: int) -> pd.Series:
    data = yf.download(ticker, period=f"{period_days}d", progress=False, auto_adjust=True)
    if data.empty:
        raise ValueError(f"No data returned for {ticker}")
    closes = data["Close"]
    if isinstance(closes, pd.DataFrame):
        closes = closes.iloc[:, 0]
    return closes.dropna()


def check_regime() -> RegimeResult:
    try:
        vix_closes = _fetch_closes(VIX_TICKER, FETCH_DAYS)
        vix3m_closes = _fetch_closes(VIX3M_TICKER, FETCH_DAYS)
        iwm_closes = _fetch_closes(IWM_TICKER, FETCH_DAYS)
    except Exception as e:
        # Fetch failure is hard-fail: no override, terminate. We can't decide on
        # elite-only mode without the data.
        result = RegimeResult(
            gate_pass=False, elite_only=False,
            vix_value=None, vix3m_value=None, vix_ratio=None, vix_pass=False,
            iwm_value=None, iwm_ma20=None, iwm_pass=False,
            reason=f"Data fetch failed: {e}"
        )
        log_regime(None, None, None, None, False)
        return result

    vix_value = float(vix_closes.iloc[-1])
    vix3m_value = float(vix3m_closes.iloc[-1])
    vix_ratio = vix_value / vix3m_value
    vix_pass = vix_ratio < 1.0

    iwm_value = float(iwm_closes.iloc[-1])
    iwm_ma20 = float(iwm_closes.tail(IWM_MA_DAYS).mean())
    iwm_pass = iwm_value > iwm_ma20

    gate_pass = vix_pass and iwm_pass

    if gate_pass:
        reason = "PASS"
    elif not vix_pass and not iwm_pass:
        reason = f"VIX/VIX3M {vix_ratio:.3f} >= 1.0 (stress); IWM {iwm_value:.2f} below 20d MA {iwm_ma20:.2f}"
    elif not vix_pass:
        reason = f"VIX/VIX3M {vix_ratio:.3f} >= 1.0 (backwardation — acute stress)"
    else:
        reason = f"IWM {iwm_value:.2f} below 20d MA {iwm_ma20:.2f}"

    # vix3m_value stored in vix_sma60 column for backward compat — ratio < 1.0 ≡ vix < vix3m
    log_regime(vix_value, vix3m_value, iwm_value, iwm_ma20, gate_pass)

    return RegimeResult(
        gate_pass=gate_pass,
        elite_only=not gate_pass,
        vix_value=vix_value,
        vix3m_value=vix3m_value,
        vix_ratio=vix_ratio,
        vix_pass=vix_pass,
        iwm_value=iwm_value,
        iwm_ma20=iwm_ma20,
        iwm_pass=iwm_pass,
        reason=reason,
    )


def regime_gate_header(result: RegimeResult) -> str:
    if result.gate_pass:
        status = "PASS"
    elif result.elite_only:
        status = "ELITE-OVERRIDE MODE — only top-decile signals will surface"
    else:
        status = "ACTIVE — no new ideas"
    vix_line = f"VIX/VIX3M {result.vix_ratio:.3f} ({result.vix_value:.2f}/{result.vix3m_value:.2f}) ({'✓' if result.vix_pass else '✗'})"
    iwm_line = f"IWM {result.iwm_value:.2f} vs 20d MA {result.iwm_ma20:.2f} ({'✓' if result.iwm_pass else '✗'})"
    return f"REGIME GATE: {status}\n{vix_line} | {iwm_line}"


if __name__ == "__main__":
    from orchestrator.state_manager import init_db
    init_db()
    result = check_regime()
    print(regime_gate_header(result))
    print(f"Gate pass: {result.gate_pass}")
