"""
backtest.py — Backtesting Engine with Realistic Transaction Costs
==================================================================

Agent 3: Backtesting & Simulation Engineer
Reviewer: Agent 4 (Statistical Breaker), Agent 5 (Data Breaker)

This module implements a realistic backtesting engine for retail traders.
It supports both cross-sectional and walk-forward backtesting, models
transaction costs realistically (commissions, spreads, slippage, borrow costs),
and enforces retail execution constraints.

Key design decisions:
- Separate gross and net return streams
- Transaction cost model calibrated for retail (Interactive Brokers pricing)
- Spread model differentiates by market cap decile
- Slippage model accounts for trade size relative to ADV
- Short borrow costs for hard-to-borrow stocks
- Capacity-aware position sizing
- Walk-forward and cross-sectional backtesting modes

DESIGN NOTE (Backtesting Engineer):
Transaction costs are NOT an afterthought. Most backtesting failures at
institutional quant funds come from underestimating costs. For retail traders
with smaller capital, commissions and spreads are proportionately larger.

VETO FIX (Data Breaker): Added market-cap-decile-based spread estimation
rather than a flat spread assumption. Small/micro caps have meaningfully
wider spreads that can eliminate apparent alpha.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================================
# Constants — Interactive Brokers Retail Pricing (2024)
# ============================================================================

COMMISSION_PER_SHARE = 0.005       # $0.005 per share (IBKR Pro tiered)
COMMISSION_MIN = 0.35              # $0.35 minimum per trade (was $1.00, IBKR reduced)
COMMISSION_MAX_PCT = 0.01          # 1% of trade value maximum

# Spread estimates by market cap decile (half-spread in bps)
# Conservative estimates based on retail market data
SPREAD_DECILE_TABLE = {
    1: 2,      # Mega cap >$200B
    2: 3,      # $100B-$200B
    3: 5,      # $20B-$100B
    4: 8,      # $5B-$20B
    5: 12,     # $2B-$5B
    6: 20,     # $500M-$2B
    7: 35,     # $200M-$500M
    8: 60,     # $50M-$200M
    9: 100,    # $10M-$50M
    10: 200,   # Sub-$10M
}

# Default borrow costs (annualized)
EASY_TO_BORROW_COST = 0.0025       # 0.25% annualized
HARD_TO_BORROW_COST = 0.05         # 5% annualized
IMPOSSIBLE_TO_BORROW_COST = 0.50   # 50% annualized (effectively unshortable)

# Market cap threshold for hard-to-borrow classification
HARD_TO_BORROW_MCAP_THRESHOLD = 2e9  # Below $2B, assume hard-to-borrow

# Slippage model parameters (Almgren et al. 2005, adapted for retail)
SLIPPAGE_LINEAR_THRESHOLD = 0.01   # 1% of ADV
SLIPPAGE_MODERATE_THRESHOLD = 0.05  # 5% of ADV
SLIPPAGE_LINEAR_BPS_PER_PCT = 2.0  # 2 bps per 1% participation
SLIPPAGE_MODERATE_BPS_PER_PCT = 5.0  # 5 bps per 1% participation
SLIPPAGE_HIGH_BPS_PER_PCT = 25.0   # 25 bps per 1% participation
SLIPPAGE_MIN_BPS = 1.0             # Minimum slippage even for tiny trades


# ============================================================================
# Data Structures
# ============================================================================


class PositionSizingMethod(Enum):
    EQUAL_WEIGHT = "equal_weight"
    SIGNAL_PROPORTIONAL = "signal_proportional"
    RISK_PARITY = "risk_parity"
    KELLY = "kelly"


class Side(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class PositionSizingSpec:
    """Specification of position sizing methodology."""

    method: PositionSizingMethod = PositionSizingMethod.EQUAL_WEIGHT
    max_position_pct: float = 0.05       # Maximum position as fraction of portfolio
    max_positions: int = 50              # Maximum simultaneous positions
    max_sector_pct: float = 0.30         # Maximum sector exposure
    capital: float = 100000.0            # Assumed retail capital in USD
    rebalance_frequency: str = "daily"   # 'daily' | 'weekly' | 'monthly'


@dataclass
class TransactionCostModel:
    """Complete transaction cost model for retail traders."""

    commission_per_share: float = COMMISSION_PER_SHARE
    commission_min: float = COMMISSION_MIN
    commission_max_pct: float = COMMISSION_MAX_PCT
    use_spread_model: bool = True
    use_slippage_model: bool = True
    model_short_borrow: bool = True
    capital: float = 100000.0


@dataclass
class TradeRecord:
    """Record of a single trade."""

    date: str
    ticker: str
    side: Side
    shares: int
    price: float
    notional: float
    commission: float
    spread_cost: float
    slippage: float
    borrow_cost: float
    total_cost: float
    cost_bps: float


@dataclass
class BacktestResult:
    """Complete backtest result."""

    # Return streams
    gross_returns: pd.Series       # Gross of costs
    net_returns: pd.Series         # Net of all costs
    cost_breakdown: pd.DataFrame   # Commission, spread, slippage, borrow by date

    # Position data
    positions: pd.DataFrame        # Position snapshots (date, ticker, shares, weight)

    # Trade log
    trade_log: pd.DataFrame        # Every trade with costs

    # Summary metrics (gross)
    gross_total_return: float
    gross_annualized_return: float
    gross_annualized_volatility: float
    gross_sharpe_ratio: float
    gross_max_drawdown: float

    # Summary metrics (net)
    net_total_return: float
    net_annualized_return: float
    net_annualized_volatility: float
    net_sharpe_ratio: float
    net_max_drawdown: float

    # Cost metrics
    total_costs_bps: float
    average_cost_per_trade_bps: float
    annual_turnover: float
    cost_drag_annualized_bps: float

    # Metadata
    start_date: str
    end_date: str
    n_trades: int
    n_trading_days: int
    warnings: List[str]


# ============================================================================
# Transaction Cost Calculator
# ============================================================================


class TransactionCostCalculator:
    """
    Calculates realistic transaction costs for retail traders.

    Covers:
    - Commissions (Interactive Brokers retail pricing)
    - Bid-ask spread (varies by market cap)
    - Slippage (varies by trade size relative to ADV)
    - Short borrow costs (varies by borrow difficulty)
    """

    def __init__(self, model: Optional[TransactionCostModel] = None):
        self.model = model or TransactionCostModel()

    def estimate_spread_bps(self, market_cap: float) -> float:
        """
        Estimate half-spread in basis points based on market cap decile.

        DESIGN NOTE (Data Breaker review):
        Using a flat 5bps spread for all stocks is a common error.
        Small caps have 10-50x wider spreads than large caps.
        This model uses an exponential decay function of log market cap
        to smoothly interpolate between decile boundary estimates.
        """
        if market_cap <= 0 or np.isnan(market_cap):
            return SPREAD_DECILE_TABLE[10]  # Assume nano cap

        # Continuous decay model
        half_spread_bps = max(2.0, 200.0 * np.exp(-0.55 * np.log10(max(market_cap / 1e6, 1))))

        return half_spread_bps * 2  # Full spread (round trip)

    def estimate_slippage_bps(
        self, trade_value: float, adv: float, market_cap: float
    ) -> float:
        """
        Estimate slippage in basis points.

        Uses a piecewise linear model based on participation rate.
        Small/micro caps have a size penalty.
        """
        if adv <= 0:
            return 100.0  # Extremely illiquid — large slippage

        participation_rate = trade_value / adv

        if participation_rate <= SLIPPAGE_LINEAR_THRESHOLD:
            slippage_bps = (
                SLIPPAGE_LINEAR_BPS_PER_PCT * participation_rate * 100
            )
        elif participation_rate <= SLIPPAGE_MODERATE_THRESHOLD:
            slippage_bps = (
                SLIPPAGE_MODERATE_BPS_PER_PCT * participation_rate * 100
            )
        else:
            slippage_bps = (
                SLIPPAGE_HIGH_BPS_PER_PCT * participation_rate * 100
            )

        # Size penalty: small caps have worse market impact
        size_penalty = max(1.0, 3.0 - 0.3 * np.log10(max(market_cap, 1e6)))

        return max(SLIPPAGE_MIN_BPS, slippage_bps * size_penalty)

    def estimate_borrow_cost_daily(
        self, market_cap: float, short_interest_pct: Optional[float] = None
    ) -> float:
        """
        Estimate daily short borrow cost as a fraction of position value.

        Returns the daily cost rate (e.g., 0.0001 = 1 basis point per day).
        """
        # Classify borrow difficulty
        if market_cap >= 200e9:
            annual_rate = EASY_TO_BORROW_COST
        elif market_cap >= HARD_TO_BORROW_MCAP_THRESHOLD:
            annual_rate = 0.01  # 1% — moderate
        elif short_interest_pct and short_interest_pct > 30:
            annual_rate = IMPOSSIBLE_TO_BORROW_COST
        elif short_interest_pct and short_interest_pct > 10:
            annual_rate = HARD_TO_BORROW_COST
        else:
            annual_rate = HARD_TO_BORROW_COST

        return annual_rate / 252  # Daily rate

    def calculate_trade_cost(
        self,
        ticker: str,
        side: Side,
        shares: int,
        price: float,
        market_cap: float,
        adv: float,
        short_interest_pct: Optional[float] = None,
        holding_period_days: int = 21,
    ) -> TradeRecord:
        """
        Calculate total cost for a single trade.
        """
        notional = shares * price

        # 1. Commission
        commission = shares * self.model.commission_per_share
        commission = max(commission, self.model.commission_min)
        commission = min(commission, notional * self.model.commission_max_pct)

        # 2. Spread cost
        spread_bps = self.estimate_spread_bps(market_cap) if self.model.use_spread_model else 5.0
        spread_cost = notional * spread_bps / 10000.0  # Full round-trip spread from estimate_spread_bps()

        # 3. Slippage
        slippage_bps = (
            self.estimate_slippage_bps(notional, adv, market_cap)
            if self.model.use_slippage_model
            else 5.0
        )
        slippage = notional * slippage_bps / 10000.0

        # 4. Borrow cost (short only)
        borrow_cost = 0.0
        if side == Side.SHORT and self.model.model_short_borrow:
            daily_borrow = self.estimate_borrow_cost_daily(
                market_cap, short_interest_pct
            )
            borrow_cost = notional * daily_borrow * holding_period_days

        total_cost = commission + spread_cost + slippage + borrow_cost
        cost_bps = (total_cost / notional * 10000.0) if notional > 0 else 0.0

        return TradeRecord(
            date="",
            ticker=ticker,
            side=side,
            shares=shares,
            price=price,
            notional=notional,
            commission=commission,
            spread_cost=spread_cost,
            slippage=slippage,
            borrow_cost=borrow_cost,
            total_cost=total_cost,
            cost_bps=cost_bps,
        )


# ============================================================================
# Position Sizer
# ============================================================================


class PositionSizer:
    """
    Determines position sizes based on the specified methodology.

    All position sizes are capacity-aware: no position exceeds 5% of ADV,
    no single position > 5% of portfolio, sector constraints enforced.
    """

    def __init__(self, spec: PositionSizingSpec):
        self.spec = spec

    def size_positions(
        self,
        signals: pd.Series,  # ticker -> signal value
        prices: pd.Series,   # ticker -> price
        market_caps: pd.Series,  # ticker -> market cap
        advs: pd.Series,     # ticker -> average daily volume (dollars)
        sectors: Optional[pd.Series] = None,  # ticker -> sector
        volatilities: Optional[pd.Series] = None,  # ticker -> volatility
    ) -> pd.DataFrame:
        """
        Size positions for all signal stocks.

        Returns DataFrame with columns:
        [ticker, signal, price, shares, notional, weight, sector]
        """
        positions = pd.DataFrame()
        positions["ticker"] = signals.index
        positions["signal"] = signals.values
        positions["price"] = positions["ticker"].map(prices)
        positions["market_cap"] = positions["ticker"].map(market_caps).fillna(1e9)
        positions["adv"] = positions["ticker"].map(advs).fillna(1e7)
        positions["sector"] = (
            positions["ticker"].map(sectors).fillna("Unknown")
            if sectors is not None
            else "Unknown"
        )
        positions["volatility"] = (
            positions["ticker"].map(volatilities).fillna(0.20)
            if volatilities is not None
            else 0.20
        )

        # Filter out zero/negative prices
        positions = positions[positions["price"] > 0].copy()

        if positions.empty:
            return positions

        # Sort by signal (strongest first)
        if signals.name and getattr(signals, "higher_is_better", True):
            positions = positions.sort_values("signal", ascending=False)
        else:
            positions = positions.sort_values("signal", ascending=True)

        # Apply position sizing method
        if self.spec.method == PositionSizingMethod.EQUAL_WEIGHT:
            positions = self._size_equal_weight(positions)
        elif self.spec.method == PositionSizingMethod.SIGNAL_PROPORTIONAL:
            positions = self._size_signal_proportional(positions)
        elif self.spec.method == PositionSizingMethod.RISK_PARITY:
            positions = self._size_risk_parity(positions)
        elif self.spec.method == PositionSizingMethod.KELLY:
            positions = self._size_kelly(positions)

        # Apply constraints
        positions = self._apply_constraints(positions)

        return positions

    def _size_equal_weight(self, positions: pd.DataFrame) -> pd.DataFrame:
        """Equal weight position sizing."""
        n_positions = min(len(positions), self.spec.max_positions)
        positions = positions.head(n_positions).copy()
        positions["target_weight"] = 1.0 / n_positions
        positions["target_notional"] = self.spec.capital * positions["target_weight"]
        positions["shares"] = np.floor(
            positions["target_notional"] / positions["price"]
        )
        positions["notional"] = positions["shares"] * positions["price"]
        positions["weight"] = positions["notional"] / self.spec.capital
        return positions

    def _size_signal_proportional(self, positions: pd.DataFrame) -> pd.DataFrame:
        """Signal-proportional position sizing."""
        positions = positions.head(self.spec.max_positions).copy()
        positions["abs_signal"] = positions["signal"].abs()
        total_signal = positions["abs_signal"].sum()

        if total_signal > 0:
            positions["target_weight"] = (
                positions["abs_signal"] / total_signal * self.spec.max_position_pct
            )
        else:
            positions["target_weight"] = 1.0 / len(positions)

        positions["target_notional"] = self.spec.capital * positions["target_weight"]
        positions["shares"] = np.floor(
            positions["target_notional"] / positions["price"]
        )
        positions["notional"] = positions["shares"] * positions["price"]
        positions["weight"] = positions["notional"] / self.spec.capital
        return positions

    def _size_risk_parity(self, positions: pd.DataFrame) -> pd.DataFrame:
        """Risk parity position sizing (inverse volatility weighted)."""
        positions = positions.head(self.spec.max_positions).copy()
        positions["inv_vol"] = 1.0 / positions["volatility"].clip(lower=0.05)
        total_inv_vol = positions["inv_vol"].sum()

        positions["target_weight"] = positions["inv_vol"] / total_inv_vol
        positions["target_weight"] = positions["target_weight"].clip(
            upper=self.spec.max_position_pct
        )
        positions["target_notional"] = self.spec.capital * positions["target_weight"]
        positions["shares"] = np.floor(
            positions["target_notional"] / positions["price"]
        )
        positions["notional"] = positions["shares"] * positions["price"]
        positions["weight"] = positions["notional"] / self.spec.capital
        return positions

    def _size_kelly(self, positions: pd.DataFrame) -> pd.DataFrame:
        """Kelly criterion position sizing (fractional Kelly, f=0.25)."""
        positions = positions.head(self.spec.max_positions).copy()
        f = 0.25  # Quarter-Kelly for safety

        # Kelly: f* = (p * b - q) / b
        # Simplified: f* ~= expected_return / variance
        positions["kelly_weight"] = f * (
            positions["signal"] / (positions["volatility"] ** 2)
        )

        # Normalize
        total_abs_kelly = positions["kelly_weight"].abs().sum()
        if total_abs_kelly > 0:
            positions["target_weight"] = (
                positions["kelly_weight"].abs() / total_abs_kelly
            )
        else:
            positions["target_weight"] = 1.0 / len(positions)

        positions["target_weight"] = positions["target_weight"].clip(
            upper=self.spec.max_position_pct
        )
        positions["target_notional"] = self.spec.capital * positions["target_weight"]
        positions["shares"] = np.floor(
            positions["target_notional"] / positions["price"]
        )
        positions["notional"] = positions["shares"] * positions["price"]
        positions["weight"] = positions["notional"] / self.spec.capital
        return positions

    def _apply_constraints(self, positions: pd.DataFrame) -> pd.DataFrame:
        """Apply portfolio constraints."""
        # Max position constraint
        positions["weight"] = positions["weight"].clip(
            upper=self.spec.max_position_pct
        )

        # ADV capacity constraint: no position > 5% of ADV
        if "adv" in positions.columns:
            adv_limit_weight = (positions["adv"] * 0.05) / self.spec.capital
            positions["weight"] = pd.concat(
                [positions["weight"], adv_limit_weight], axis=1
            ).min(axis=1)

        # Sector constraint
        if "sector" in positions.columns:
            sector_weights = positions.groupby("sector")["weight"].sum()
            constrained_sectors = sector_weights[sector_weights > self.spec.max_sector_pct]

            for sector in constrained_sectors.index:
                sector_mask = positions["sector"] == sector
                scale_factor = self.spec.max_sector_pct / sector_weights[sector]
                positions.loc[sector_mask, "weight"] *= scale_factor

        # Recompute notionals and shares
        positions["notional"] = positions["weight"] * self.spec.capital
        positions["shares"] = np.floor(positions["notional"] / positions["price"]).astype(int)
        positions["notional"] = positions["shares"] * positions["price"]
        positions["weight"] = positions["notional"] / self.spec.capital

        return positions


# ============================================================================
# Shared Helpers
# ============================================================================


def _compute_holding_period_return(
    positions: "pd.DataFrame",
    price_df: "pd.DataFrame",
    start_date: str,
    holding_period_days: int,
) -> float:
    """Compute equal-weighted forward return for a cohort of stocks.

    Shared by WalkForwardBacktester and CrossSectionalBacktester.
    Entry price is the first available price strictly after start_date.
    Exit price is the last available price at or before end_dt.
    """
    if positions.empty or "ticker" not in positions.columns:
        return 0.0

    start_dt = pd.Timestamp(start_date)
    end_dt = start_dt + pd.tseries.offsets.BusinessDay(n=holding_period_days)

    cohort_return = 0.0
    valid_count = 0

    for _, pos in positions.iterrows():
        ticker = pos["ticker"]
        if ticker not in price_df.columns:
            continue

        ticker_prices = price_df[ticker].dropna()

        entry_prices = ticker_prices[ticker_prices.index > start_dt]
        if entry_prices.empty:
            continue

        entry_price = entry_prices.iloc[0]

        exit_prices = ticker_prices[ticker_prices.index <= end_dt]
        if exit_prices.empty or exit_prices.index[-1] <= entry_prices.index[0]:
            continue

        exit_price = exit_prices.iloc[-1]

        if entry_price > 0:
            ret = (exit_price / entry_price) - 1.0
            cohort_return += ret
            valid_count += 1

    return cohort_return / valid_count if valid_count > 0 else 0.0


# ============================================================================
# Walk-Forward Backtester
# ============================================================================


class WalkForwardBacktester:
    """
    Implements walk-forward backtesting that simulates real-time deployment.

    Walk-forward methodology:
    1. Divide data into rolling windows (e.g., 5 years training, 1 year testing)
    2. For each window, compute the signal using only data available at that time
    3. Test forward performance
    4. Roll forward and repeat

    This is the gold standard for honest backtesting. One-shot backtests
    on the full period are vulnerable to in-sample overfitting.
    """

    def __init__(
        self,
        cost_calculator: Optional[TransactionCostCalculator] = None,
        position_sizer_spec: Optional[PositionSizingSpec] = None,
    ):
        self.cost_calculator = cost_calculator or TransactionCostCalculator()
        self.position_sizer = PositionSizer(position_sizer_spec or PositionSizingSpec())

    def run(
        self,
        signal_df: pd.DataFrame,      # date x ticker matrix of signals
        price_df: pd.DataFrame,       # date x ticker matrix of prices
        market_cap_df: pd.DataFrame,  # date x ticker matrix of market caps
        volume_df: pd.DataFrame,      # date x ticker matrix of dollar volumes
        sector_df: Optional[pd.DataFrame] = None,
        holding_period_days: int = 21,
        train_years: int = 5,
        test_years: int = 1,
    ) -> List[BacktestResult]:
        """
        Run walk-forward backtest.

        Returns:
            List of BacktestResult, one per walk-forward window.
        """
        results = []

        signal_dates = sorted(signal_df.index)
        if len(signal_dates) < 252:
            logger.warning("Insufficient data for walk-forward backtest")
            return results

        start_date = pd.Timestamp(signal_dates[0])
        end_date = pd.Timestamp(signal_dates[-1])

        # Generate windows
        train_duration = pd.Timedelta(days=train_years * 365)
        test_duration = pd.Timedelta(days=test_years * 365)
        step_duration = pd.Timedelta(days=test_years * 365)  # Non-overlapping tests

        current = start_date
        window_idx = 0

        while current + train_duration + test_duration <= end_date:
            train_start = current
            train_end = current + train_duration
            test_start = train_end
            test_end = test_start + test_duration

            train_dates = [
                d for d in signal_dates
                if train_start.strftime("%Y-%m-%d") <= d <= train_end.strftime("%Y-%m-%d")
            ]
            test_dates = [
                d for d in signal_dates
                if test_start.strftime("%Y-%m-%d") < d <= test_end.strftime("%Y-%m-%d")
            ]

            if len(test_dates) < 10:  # Minimum test period
                break

            # Run single window
            window_result = self._run_single_window(
                signal_df=signal_df,
                price_df=price_df,
                market_cap_df=market_cap_df,
                volume_df=volume_df,
                sector_df=sector_df,
                train_dates=train_dates,
                test_dates=test_dates,
                holding_period_days=holding_period_days,
                window_name=f"window_{window_idx}_{test_start.strftime('%Y%m%d')}_{test_end.strftime('%Y%m%d')}",
            )
            results.append(window_result)

            current += step_duration
            window_idx += 1

        return results

    def _run_single_window(
        self,
        signal_df: pd.DataFrame,
        price_df: pd.DataFrame,
        market_cap_df: pd.DataFrame,
        volume_df: pd.DataFrame,
        sector_df: Optional[pd.DataFrame],
        train_dates: List[str],
        test_dates: List[str],
        holding_period_days: int,
        window_name: str,
    ) -> BacktestResult:
        """Backtest a single walk-forward window."""
        trades = []
        portfolio_returns = []

        for date in sorted(test_dates):
            # Get signals for this date
            if date not in signal_df.index:
                continue

            day_signals = signal_df.loc[date].dropna()
            if day_signals.empty:
                continue

            # Size positions
            day_prices = price_df.loc[date] if date in price_df.index else pd.Series(dtype=float)
            day_mcaps = market_cap_df.loc[date] if date in market_cap_df.index else pd.Series(dtype=float)
            day_volumes = volume_df.loc[date] if date in volume_df.index else pd.Series(dtype=float)
            day_sectors = sector_df.loc[date] if sector_df is not None and date in sector_df.index else None

            # Filter to tickers with valid prices
            valid_tickers = set(day_signals.index) & set(day_prices.index) & set(day_mcaps.index)
            valid_tickers = {t for t in valid_tickers if day_prices[t] > 0}

            if not valid_tickers:
                continue

            filtered_signals = day_signals[list(valid_tickers)]
            filtered_prices = day_prices[list(valid_tickers)]
            filtered_mcaps = day_mcaps[list(valid_tickers)]
            filtered_volumes = day_volumes[list(valid_tickers)]

            positions = self.position_sizer.size_positions(
                signals=filtered_signals,
                prices=filtered_prices,
                market_caps=filtered_mcaps,
                advs=filtered_volumes,
                sectors=(
                    day_sectors[list(valid_tickers)]
                    if day_sectors is not None
                    else None
                ),
            )

            # Compute forward return for this cohort
            cohort_ret = _compute_holding_period_return(
                positions=positions,
                price_df=price_df,
                start_date=date,
                holding_period_days=holding_period_days,
            )
            portfolio_returns.append({"date": date, "return": cohort_ret})

            # Record trades with costs
            for _, pos in positions.iterrows():
                cost = self.cost_calculator.calculate_trade_cost(
                    ticker=pos["ticker"],
                    side=Side.LONG,
                    shares=int(pos["shares"]),
                    price=pos["price"],
                    market_cap=pos.get("market_cap", 1e9),
                    adv=pos.get("adv", 1e7),
                    holding_period_days=holding_period_days,
                )

                trades.append({
                    "window": window_name,
                    "date": date,
                    "ticker": pos["ticker"],
                    "side": "LONG",
                    "shares": int(pos["shares"]),
                    "price": pos["price"],
                    "notional": pos["notional"],
                    "weight": pos["weight"],
                    "commission": cost.commission,
                    "spread_cost": cost.spread_cost,
                    "slippage_cost": cost.slippage,
                    "borrow_cost": cost.borrow_cost,
                    "total_cost": cost.total_cost,
                    "cost_bps": cost.cost_bps,
                })

        # Compile results
        trades_df = pd.DataFrame(trades)
        returns_series = (
            pd.DataFrame(portfolio_returns).set_index("date")["return"]
            if portfolio_returns
            else pd.Series(dtype=float)
        )
        return self._compile_result(trades_df, returns_series, window_name, test_dates)

    def _compile_result(
        self,
        trades_df: pd.DataFrame,
        returns_series: pd.Series,
        window_name: str,
        test_dates: List[str],
    ) -> BacktestResult:
        """Compile a backtest result from trade log and return series."""
        if trades_df.empty and returns_series.empty:
            return BacktestResult(
                gross_returns=pd.Series(dtype=float),
                net_returns=pd.Series(dtype=float),
                cost_breakdown=pd.DataFrame(),
                positions=pd.DataFrame(),
                trade_log=trades_df,
                gross_total_return=0.0,
                gross_annualized_return=0.0,
                gross_annualized_volatility=0.0,
                gross_sharpe_ratio=0.0,
                gross_max_drawdown=0.0,
                net_total_return=0.0,
                net_annualized_return=0.0,
                net_annualized_volatility=0.0,
                net_sharpe_ratio=0.0,
                net_max_drawdown=0.0,
                total_costs_bps=0.0,
                average_cost_per_trade_bps=0.0,
                annual_turnover=0.0,
                cost_drag_annualized_bps=0.0,
                start_date=test_dates[0] if test_dates else "",
                end_date=test_dates[-1] if test_dates else "",
                n_trades=0,
                n_trading_days=len(test_dates),
                warnings=[],
            )

        # Aggregate daily trades
        if not trades_df.empty:
            trades_df["date"] = pd.to_datetime(trades_df["date"])
            daily_trades = trades_df.groupby("date").agg({
                "notional": "sum",
                "total_cost": "sum",
            })
            cost_breakdown = trades_df.groupby("date")[["commission", "spread_cost", "slippage_cost", "borrow_cost"]].sum()
        else:
            daily_trades = pd.DataFrame()
            cost_breakdown = pd.DataFrame()

        n_trading_days = len(test_dates)
        n_obs = len(returns_series)

        # Derive n_years from actual calendar span
        if n_obs >= 2:
            try:
                calendar_days = (returns_series.index[-1] - returns_series.index[0]).days
                n_years = max(calendar_days / 365.25, 0.01)
            except (TypeError, AttributeError):
                n_years = max(n_trading_days / 252.0, 0.01)
        else:
            n_years = max(n_trading_days / 252.0, 0.01)

        holding_period_days_est = 21  # default; refined below if possible
        periods_per_year = max(252.0 / holding_period_days_est, 1.0)
        ann_vol_factor = np.sqrt(periods_per_year)

        if returns_series.empty:
            gross_total_return = 0.0
            gross_ann_return = 0.0
            gross_ann_vol = 0.0
            gross_sharpe = 0.0
            gross_max_dd = 0.0
        else:
            gross_total_return = (1 + returns_series).prod() - 1
            gross_ann_return = (1 + gross_total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0
            gross_ann_vol = returns_series.std() * ann_vol_factor
            gross_sharpe = gross_ann_return / gross_ann_vol if gross_ann_vol > 0 else 0.0
            cum_returns = (1 + returns_series).cumprod()
            gross_max_dd = (cum_returns / cum_returns.cummax() - 1).min()

        total_costs = trades_df["total_cost"].sum() if not trades_df.empty else 0.0
        total_notional = trades_df["notional"].sum() if not trades_df.empty else 0.0
        avg_cost_bps = (total_costs / total_notional * 10000) if total_notional > 0 else 0

        cost_drag_annual_bps = (
            total_costs / (self.position_sizer.spec.capital * n_years) * 10000
            if n_years > 0 and self.position_sizer.spec.capital > 0
            else 0.0
        )

        net_total_return = gross_total_return - (
            total_costs / self.position_sizer.spec.capital
            if self.position_sizer.spec.capital > 0
            else 0.0
        )
        net_ann_return = (1 + net_total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0
        net_sharpe = net_ann_return / gross_ann_vol if gross_ann_vol > 0 else 0.0

        return BacktestResult(
            gross_returns=returns_series,
            net_returns=returns_series - (total_costs / self.position_sizer.spec.capital / max(n_obs, 1)),
            cost_breakdown=cost_breakdown,
            positions=pd.DataFrame(),
            trade_log=trades_df,
            gross_total_return=gross_total_return,
            gross_annualized_return=gross_ann_return,
            gross_annualized_volatility=gross_ann_vol,
            gross_sharpe_ratio=gross_sharpe,
            gross_max_drawdown=gross_max_dd,
            net_total_return=net_total_return,
            net_annualized_return=net_ann_return,
            net_annualized_volatility=gross_ann_vol,
            net_sharpe_ratio=net_sharpe,
            net_max_drawdown=gross_max_dd,
            total_costs_bps=total_costs / self.position_sizer.spec.capital * 10000 if self.position_sizer.spec.capital > 0 else 0,
            average_cost_per_trade_bps=avg_cost_bps,
            annual_turnover=total_notional / (self.position_sizer.spec.capital * n_years) if n_years > 0 else 0,
            cost_drag_annualized_bps=cost_drag_annual_bps,
            start_date=test_dates[0] if test_dates else "",
            end_date=test_dates[-1] if test_dates else "",
            n_trades=len(trades_df),
            n_trading_days=n_trading_days,
            warnings=[],
        )


# ============================================================================
# Event-Study Backtester
# ============================================================================


class EventStudyBacktester:
    """
    Implements event-study backtesting for sparse event-driven signals.

    Designed for hypotheses where each stock has exactly one signal value
    on a single event date (e.g., FDA drug approval date, earnings surprise
    announcement date). The signal DataFrame is a sparse date x ticker matrix
    where only event dates have non-NaN values for the affected tickers.

    Methodology:
    1. Extract all (date, ticker, signal_value) tuples from sparse signal matrix.
    2. For each event, compute the forward holding-period return from the
       event date using the price data.
    3. Optionally compute market-adjusted excess returns (equal-weight average
       of all available tickers over the same window).
    4. Return a BacktestResult where the returns series holds the individual
       event returns indexed by event date. This enables the downstream
       statistical tests to assess whether signal values predict returns.
    """

    def __init__(
        self,
        cost_calculator: Optional[TransactionCostCalculator] = None,
        position_sizer_spec: Optional[PositionSizingSpec] = None,
    ):
        self.cost_calculator = cost_calculator or TransactionCostCalculator()
        self.position_sizer = PositionSizer(position_sizer_spec or PositionSizingSpec())

    def run(
        self,
        signal_df: pd.DataFrame,
        price_df: pd.DataFrame,
        market_cap_df: pd.DataFrame,
        volume_df: pd.DataFrame,
        sector_df: Optional[pd.DataFrame] = None,
        holding_period_days: int = 21,
        excess_returns: bool = True,
        min_events: int = 5,
    ) -> BacktestResult:
        """
        Run event-study backtest.

        Args:
            signal_df: Sparse date x ticker matrix of signals (mostly NaN).
            price_df: date x ticker matrix of prices.
            market_cap_df: date x ticker matrix of market caps.
            volume_df: date x ticker matrix of dollar volumes.
            sector_df: Optional date x ticker matrix of sector classifications.
            holding_period_days: Forward holding period for each event.
            excess_returns: If True, compute market-adjusted excess returns.
            min_events: Minimum number of events required.

        Returns:
            BacktestResult with individual event returns.
        """
        # Extract all (date, ticker, signal_value) events
        events = self._extract_events(signal_df)
        if len(events) < min_events:
            logger.warning(
                f"Only {len(events)} events found (need {min_events}). "
                "Insufficient for event study."
            )
            return self._empty_result()

        logger.info(
            f"EventStudyBacktester: {len(events)} events across "
            f"{events['date'].nunique()} dates, {events['ticker'].nunique()} tickers"
        )

        # Compute forward returns for each event
        event_returns = []
        trades = []

        for _, event in events.iterrows():
            event_date = event["date"]
            ticker = event["ticker"]
            signal_value = event["signal"]

            if ticker not in price_df.columns:
                continue

            result = self._compute_event_return(
                ticker=ticker,
                event_date=event_date,
                price_df=price_df,
                holding_period_days=holding_period_days,
            )

            if result is None:
                continue

            ret, exit_price_from_data = result

            # Compute market return for excess return if requested
            market_ret = 0.0
            if excess_returns:
                market_ret = self._compute_market_return(
                    price_df=price_df,
                    event_date=event_date,
                    holding_period_days=holding_period_days,
                    exclude_ticker=ticker,
                )

            excess_ret = ret - market_ret

            # Estimate trade costs for entry and exit
            try:
                entry_date = event["entry_date"]
                entry_price = event["entry_price"]
            except KeyError:
                entry_price = 50.0

            shares = int(self.position_sizer.spec.capital / entry_price) if entry_price > 0 else 100

            entry_cost = self.cost_calculator.calculate_trade_cost(
                ticker=ticker,
                side=Side.LONG,
                shares=shares,
                price=entry_price,
                market_cap=event.get("market_cap", 1e10),
                adv=event.get("adv", 1e7),
                holding_period_days=holding_period_days,
            )

            # Exit trade cost (sell-to-close, no borrow cost)
            exit_cost = self.cost_calculator.calculate_trade_cost(
                ticker=ticker,
                side=Side.LONG,
                shares=shares,
                price=exit_price_from_data,
                market_cap=event.get("market_cap", 1e10),
                adv=event.get("adv", 1e7),
                holding_period_days=0,  # no holding period for exit
            )

            total_trade_cost = entry_cost.total_cost + exit_cost.total_cost
            total_cost_bps = ((entry_cost.cost_bps + exit_cost.cost_bps) / 2.0
                              if entry_cost.cost_bps and exit_cost.cost_bps else 0)

            event_returns.append({
                "date": event_date,
                "ticker": ticker,
                "signal": signal_value,
                "gross_return": ret,
                "market_return": market_ret,
                "excess_return": excess_ret,
                "entry_price": entry_price,
                "exit_price": exit_price_from_data,
                "cost_bps": total_cost_bps,
                "total_cost": total_trade_cost,
            })

            trades.append({
                "date": event_date,
                "ticker": ticker,
                "side": "LONG",
                "shares": shares,
                "price": entry_price,
                "notional": self.position_sizer.spec.capital,
                "weight": 1.0,
                "total_cost": total_trade_cost,
                "cost_bps": total_cost_bps,
            })

        if not event_returns:
            logger.warning("No valid event returns computed.")
            return self._empty_result()

        returns_df = pd.DataFrame(event_returns)
        returns_df["date"] = pd.to_datetime(returns_df["date"])
        returns_df = returns_df.set_index("date")

        # Use excess returns as the primary return series
        return_series = returns_df["excess_return"].copy()
        gross_series = returns_df["gross_return"].copy()

        trades_df = pd.DataFrame(trades)
        if not trades_df.empty:
            trades_df["date"] = pd.to_datetime(trades_df["date"])

        return self._compile_result(
            trades_df=trades_df,
            returns_series=return_series,
            gross_series=gross_series,
            events_df=returns_df,
            holding_period_days=holding_period_days,
        )

    def _extract_events(self, signal_df: pd.DataFrame) -> pd.DataFrame:
        """Extract all (date, ticker, signal_value) events from sparse signal matrix."""
        events = []
        for date in signal_df.index:
            day_signals = signal_df.loc[date].dropna()
            for ticker in day_signals.index:
                events.append({
                    "date": pd.Timestamp(date),
                    "ticker": ticker,
                    "signal": float(day_signals[ticker]),
                })
        return pd.DataFrame(events)

    def _compute_event_return(
        self,
        ticker: str,
        event_date: pd.Timestamp,
        price_df: pd.DataFrame,
        holding_period_days: int,
    ) -> Optional[Tuple[float, float]]:
        """Compute the forward holding-period return for a single event.

        Entry price: first available price strictly after event_date.
        Exit price: last available price on or before event_date + holding_period_days.

        Returns:
            (return, exit_price) or None if insufficient price data.
        """
        ticker_prices = price_df[ticker].dropna()
        if ticker_prices.empty:
            return None

        entry_prices = ticker_prices[ticker_prices.index > event_date]
        if entry_prices.empty:
            return None

        entry_idx = entry_prices.index[0]
        entry_price = entry_prices.iloc[0]

        end_dt = event_date + pd.tseries.offsets.BusinessDay(n=holding_period_days)
        exit_prices = ticker_prices[(ticker_prices.index > entry_idx) & (ticker_prices.index <= end_dt)]
        if exit_prices.empty:
            return None

        exit_price = exit_prices.iloc[-1]

        if entry_price <= 0:
            return None

        return float((exit_price / entry_price) - 1.0), float(exit_price)

    def _compute_market_return(
        self,
        price_df: pd.DataFrame,
        event_date: pd.Timestamp,
        holding_period_days: int,
        exclude_ticker: Optional[str] = None,
    ) -> float:
        """Compute equal-weight market return over the holding period.

        Uses all tickers with valid prices over the window, excluding the
        event ticker to avoid contamination.
        """
        ticker_returns = []
        for ticker in price_df.columns:
            if ticker == exclude_ticker:
                continue

            ticker_prices = price_df[ticker].dropna()
            if ticker_prices.empty:
                continue

            entry_prices = ticker_prices[ticker_prices.index > event_date]
            if entry_prices.empty:
                continue

            entry_idx = entry_prices.index[0]
            entry_price = entry_prices.iloc[0]

            end_dt = event_date + pd.tseries.offsets.BusinessDay(n=holding_period_days)
            exit_prices = ticker_prices[(ticker_prices.index > entry_idx) & (ticker_prices.index <= end_dt)]
            if exit_prices.empty:
                continue

            exit_price = exit_prices.iloc[-1]
            if entry_price > 0:
                ticker_returns.append(float((exit_price / entry_price) - 1.0))

        if not ticker_returns:
            return 0.0

        return float(np.mean(ticker_returns))

    def _empty_result(self) -> BacktestResult:
        """Return an empty BacktestResult."""
        return BacktestResult(
            gross_returns=pd.Series(dtype=float),
            net_returns=pd.Series(dtype=float),
            cost_breakdown=pd.DataFrame(),
            positions=pd.DataFrame(),
            trade_log=pd.DataFrame(),
            gross_total_return=0.0,
            gross_annualized_return=0.0,
            gross_annualized_volatility=0.0,
            gross_sharpe_ratio=0.0,
            gross_max_drawdown=0.0,
            net_total_return=0.0,
            net_annualized_return=0.0,
            net_annualized_volatility=0.0,
            net_sharpe_ratio=0.0,
            net_max_drawdown=0.0,
            total_costs_bps=0.0,
            average_cost_per_trade_bps=0.0,
            annual_turnover=0.0,
            cost_drag_annualized_bps=0.0,
            start_date="",
            end_date="",
            n_trades=0,
            n_trading_days=0,
            warnings=["Insufficient events for event study backtest."],
        )

    def _compile_result(
        self,
        trades_df: pd.DataFrame,
        returns_series: pd.Series,
        gross_series: pd.Series,
        events_df: pd.DataFrame,
        holding_period_days: int = 21,
    ) -> BacktestResult:
        """Compile event-study backtest result.

        For event studies, the "returns" are individual event excess returns.
        Annualization uses the actual calendar span between the first and last
        event, scaled by the holding period.
        """
        n_events = len(returns_series)

        if n_events < 2:
            n_years = holding_period_days / 252.0
        else:
            calendar_days = (returns_series.index[-1] - returns_series.index[0]).days
            n_years = max(calendar_days / 365.25, holding_period_days / 252.0)

        periods_per_year = max(252.0 / holding_period_days, 1.0)
        ann_vol_factor = np.sqrt(periods_per_year)

        if returns_series.empty:
            gross_total_return = 0.0
            gross_ann_return = 0.0
            gross_ann_vol = 0.0
            gross_sharpe = 0.0
            gross_max_dd = 0.0
        else:
            gross_total_return = (1 + returns_series).prod() - 1
            gross_ann_return = (1 + gross_total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0
            gross_ann_vol = returns_series.std() * ann_vol_factor
            gross_sharpe = gross_ann_return / gross_ann_vol if gross_ann_vol > 0 else 0.0
            cum_returns = (1 + returns_series).cumprod()
            gross_max_dd = (cum_returns / cum_returns.cummax() - 1).min()

        total_costs = trades_df["total_cost"].sum() if not trades_df.empty else 0.0
        capital = self.position_sizer.spec.capital
        cost_drag_annual_bps = (
            total_costs / (capital * n_years) * 10000
            if n_years > 0 and capital > 0
            else 0.0
        )

        net_total_return = gross_total_return - (
            total_costs / capital if capital > 0 else 0.0
        )
        net_ann_return = (1 + net_total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0
        net_sharpe = net_ann_return / gross_ann_vol if gross_ann_vol > 0 else 0.0

        start_date = str(returns_series.index[0]) if not returns_series.empty else ""
        end_date = str(returns_series.index[-1]) if not returns_series.empty else ""

        return BacktestResult(
            gross_returns=gross_series if not gross_series.empty else returns_series,
            net_returns=returns_series,
            cost_breakdown=trades_df.groupby("date")["total_cost"].sum() if not trades_df.empty else pd.DataFrame(),
            positions=pd.DataFrame(),
            trade_log=trades_df,
            gross_total_return=gross_total_return,
            gross_annualized_return=gross_ann_return,
            gross_annualized_volatility=gross_ann_vol,
            gross_sharpe_ratio=gross_sharpe,
            gross_max_drawdown=gross_max_dd,
            net_total_return=net_total_return,
            net_annualized_return=net_ann_return,
            net_annualized_volatility=gross_ann_vol,
            net_sharpe_ratio=net_sharpe,
            net_max_drawdown=gross_max_dd,
            total_costs_bps=total_costs / capital * 10000 if capital > 0 else 0.0,
            average_cost_per_trade_bps=trades_df["cost_bps"].mean() if not trades_df.empty else 0.0,
            annual_turnover=0.0,
            cost_drag_annualized_bps=cost_drag_annual_bps,
            start_date=start_date,
            end_date=end_date,
            n_trades=len(trades_df),
            n_trading_days=n_events,
            warnings=[],
        )


# ============================================================================
# Cross-Sectional Backtester
# ============================================================================


class CrossSectionalBacktester:
    """
    Implements cross-sectional backtesting.

    At each rebalance date:
    1. Rank all stocks by signal
    2. Go long the top quantile, short the bottom quantile (if applicable)
    3. Hold for the specified period
    4. Rebalance
    """

    def __init__(
        self,
        cost_calculator: Optional[TransactionCostCalculator] = None,
        position_sizer_spec: Optional[PositionSizingSpec] = None,
    ):
        self.cost_calculator = cost_calculator or TransactionCostCalculator()
        self.position_sizer = PositionSizer(position_sizer_spec or PositionSizingSpec())

    def run(
        self,
        signal_df: pd.DataFrame,
        price_df: pd.DataFrame,
        market_cap_df: pd.DataFrame,
        volume_df: pd.DataFrame,
        sector_df: Optional[pd.DataFrame] = None,
        holding_period_days: int = 21,
        rebalance_frequency: str = "monthly",
        top_quantile: float = 0.2,
        long_only: bool = True,
    ) -> BacktestResult:
        """
        Run cross-sectional backtest.

        Args:
            signal_df: date x ticker matrix of signals
            price_df: date x ticker matrix of prices
            market_cap_df: date x ticker matrix of market caps
            volume_df: date x ticker matrix of dollar volumes
            sector_df: date x ticker matrix of sector classifications
            holding_period_days: How long to hold positions
            rebalance_frequency: 'daily', 'weekly', 'monthly'
            top_quantile: Fraction of stocks to go long (e.g., 0.2 = top quintile)
            long_only: If True, only go long (no short leg)

        Returns:
            BacktestResult
        """
        # Determine rebalance dates
        if rebalance_frequency == "daily":
            rebalance_dates = list(signal_df.index)
        elif rebalance_frequency == "weekly":
            rebalance_dates = [d for d in signal_df.index if pd.Timestamp(d).weekday() == 4]
        elif rebalance_frequency == "monthly":
            # Last trading day of each month
            dates = pd.DatetimeIndex(signal_df.index)
            month_ends = dates.to_series().groupby([dates.year, dates.month]).last()
            rebalance_dates = list(month_ends.values)
        else:
            rebalance_dates = list(signal_df.index)

        rebalance_dates = sorted([d for d in rebalance_dates if d in signal_df.index])

        trades = []
        portfolio_returns = []

        for date in rebalance_dates:
            if date not in signal_df.index:
                continue

            day_signals = signal_df.loc[date].dropna()

            if day_signals.empty:
                continue

            # Select top quantile (long leg)
            n_select = max(1, int(len(day_signals) * top_quantile))
            selected = day_signals.nlargest(n_select)

            # Select bottom quantile (short leg) when long_only=False
            short_selected = None
            if not long_only:
                short_selected = day_signals.nsmallest(n_select)

            # Get prices for selected stocks
            common_tickers = set(selected.index) & set(price_df.columns)
            if not common_tickers:
                continue

            selected = selected[list(common_tickers)]

            # Size positions
            day_prices = price_df.loc[date] if date in price_df.index else pd.Series()
            day_mcaps = market_cap_df.loc[date] if date in market_cap_df.index else pd.Series()
            day_volumes = volume_df.loc[date] if date in volume_df.index else pd.Series()

            positions = self.position_sizer.size_positions(
                signals=selected,
                prices=day_prices,
                market_caps=day_mcaps,
                advs=day_volumes,
                sectors=None,
            )

            # Long leg trade costs & forward return
            long_return = 0.0
            for _, pos in positions.iterrows():
                cost = self.cost_calculator.calculate_trade_cost(
                    ticker=pos["ticker"],
                    side=Side.LONG,
                    shares=int(pos["shares"]),
                    price=pos["price"],
                    market_cap=pos.get("market_cap", 1e9),
                    adv=pos.get("adv", 1e7),
                    holding_period_days=holding_period_days,
                )

                trades.append({
                    "date": date,
                    "ticker": pos["ticker"],
                    "side": "LONG",
                    "shares": int(pos["shares"]),
                    "price": pos["price"],
                    "notional": pos["notional"],
                    "weight": pos["weight"],
                    "total_cost": cost.total_cost,
                    "cost_bps": cost.cost_bps,
                })

            long_return = self._compute_cohort_return(
                positions=positions,
                price_df=price_df,
                start_date=date,
                holding_period_days=holding_period_days,
            )

            # Short leg (only when long_only=False)
            short_return = 0.0
            if not long_only and short_selected is not None:
                short_common = set(short_selected.index) & set(price_df.columns)
                if short_common:
                    short_selected = short_selected[list(short_common)]
                    short_positions = self.position_sizer.size_positions(
                        signals=short_selected,
                        prices=day_prices,
                        market_caps=day_mcaps,
                        advs=day_volumes,
                        sectors=None,
                    )

                    for _, pos in short_positions.iterrows():
                        sc = self.cost_calculator.calculate_trade_cost(
                            ticker=pos["ticker"],
                            side=Side.SHORT,
                            shares=int(pos["shares"]),
                            price=pos["price"],
                            market_cap=pos.get("market_cap", 1e9),
                            adv=pos.get("adv", 1e7),
                            holding_period_days=holding_period_days,
                        )

                        trades.append({
                            "date": date,
                            "ticker": pos["ticker"],
                            "side": "SHORT",
                            "shares": int(pos["shares"]),
                            "price": pos["price"],
                            "notional": pos["notional"],
                            "weight": pos["weight"],
                            "total_cost": sc.total_cost,
                            "cost_bps": sc.cost_bps,
                        })

                    short_return = self._compute_cohort_return(
                        positions=short_positions,
                        price_df=price_df,
                        start_date=date,
                        holding_period_days=holding_period_days,
                    )

            # Portfolio return: long - short (short leg returns are positive
            # when the shorted stocks go down, which is good for the strategy)
            portfolio_return = long_return - short_return
            portfolio_returns.append({
                "date": date,
                "return": portfolio_return,
            })

        trades_df = pd.DataFrame(trades)
        returns_series = (
            pd.DataFrame(portfolio_returns).set_index("date")["return"]
            if portfolio_returns
            else pd.Series(dtype=float)
        )

        return self._compile_result(
            trades_df=trades_df,
            returns_series=returns_series,
            start_date=rebalance_dates[0] if rebalance_dates else "",
            end_date=rebalance_dates[-1] if rebalance_dates else "",
            holding_period_days=holding_period_days,
        )

    def _compute_cohort_return(
        self,
        positions: pd.DataFrame,
        price_df: pd.DataFrame,
        start_date: str,
        holding_period_days: int,
    ) -> float:
        """Compute equal-weighted forward return for a cohort of stocks."""
        return _compute_holding_period_return(positions, price_df, start_date, holding_period_days)

    def _compile_result(
        self,
        trades_df: pd.DataFrame,
        returns_series: pd.Series,
        start_date: str,
        end_date: str,
        holding_period_days: int = 21,
    ) -> BacktestResult:
        """Compile cross-sectional backtest result.

        Annualization is derived from the actual calendar span of the return
        series and the holding period, NOT from the count of observations.
        This is critical when returns are multi-day holding period returns
        rather than daily returns.
        """
        n_trading_days = len(returns_series)

        # Derive n_years from actual calendar span (not observation count)
        if not returns_series.empty and len(returns_series.index) >= 2:
            try:
                calendar_days = (returns_series.index[-1] - returns_series.index[0]).days
                n_years = max(calendar_days / 365.25, 0.01)
            except (TypeError, AttributeError):
                n_years = max(n_trading_days / 252.0, 0.01)
        else:
            n_years = max(n_trading_days / 252.0, 0.01)

        # Annualization factor for holding-period returns:
        # Daily returns: scale by sqrt(252)
        # H-day returns: scale by sqrt(252 / H)
        periods_per_year = max(252.0 / holding_period_days, 1.0)
        ann_vol_factor = np.sqrt(periods_per_year)

        if returns_series.empty:
            gross_total_return = 0.0
            gross_ann_return = 0.0
            gross_ann_vol = 0.0
            gross_sharpe = 0.0
            gross_max_dd = 0.0
        else:
            gross_total_return = (1 + returns_series).prod() - 1
            gross_ann_return = (1 + gross_total_return) ** (1 / n_years) - 1
            gross_ann_vol = returns_series.std() * ann_vol_factor
            gross_sharpe = gross_ann_return / gross_ann_vol if gross_ann_vol > 0 else 0.0
            cum_returns = (1 + returns_series).cumprod()
            gross_max_dd = (cum_returns / cum_returns.cummax() - 1).min()

        # Cost adjustments
        total_costs = trades_df["total_cost"].sum() if not trades_df.empty else 0.0
        cost_drag_annual_bps = (
            total_costs / (self.position_sizer.spec.capital * n_years) * 10000
            if n_years > 0 and self.position_sizer.spec.capital > 0
            else 0.0
        )

        net_total_return = gross_total_return - (
            total_costs / self.position_sizer.spec.capital
            if self.position_sizer.spec.capital > 0
            else 0.0
        )
        net_ann_return = (1 + net_total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0
        net_sharpe = net_ann_return / gross_ann_vol if gross_ann_vol > 0 else 0.0

        return BacktestResult(
            gross_returns=returns_series,
            net_returns=returns_series - (total_costs / self.position_sizer.spec.capital / len(returns_series) if len(returns_series) > 0 else 0),
            cost_breakdown=trades_df.groupby("date")["total_cost"].sum() if not trades_df.empty else pd.DataFrame(),
            positions=pd.DataFrame(),
            trade_log=trades_df,
            gross_total_return=gross_total_return,
            gross_annualized_return=gross_ann_return,
            gross_annualized_volatility=gross_ann_vol,
            gross_sharpe_ratio=gross_sharpe,
            gross_max_drawdown=gross_max_dd,
            net_total_return=net_total_return,
            net_annualized_return=net_ann_return,
            net_annualized_volatility=gross_ann_vol,
            net_sharpe_ratio=net_sharpe,
            net_max_drawdown=gross_max_dd,
            total_costs_bps=total_costs / self.position_sizer.spec.capital * 10000 if self.position_sizer.spec.capital > 0 else 0,
            average_cost_per_trade_bps=trades_df["cost_bps"].mean() if not trades_df.empty else 0,
            annual_turnover=0.0,
            cost_drag_annualized_bps=cost_drag_annual_bps,
            start_date=start_date,
            end_date=end_date,
            n_trades=len(trades_df),
            n_trading_days=n_trading_days,
            warnings=[],
        )
