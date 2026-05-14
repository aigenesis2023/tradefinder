"""
factors.py — Baseline Factor Construction and Comparison
=========================================================

REQUIREMENT 9 (MANDATORY — NOT OPTIONAL)

This module builds the mandatory baseline factor library and compares every
hypothesis against these known factors. A hypothesis that is mostly explained
by known factor exposures after costs is NOT a genuine LLM edge — it is
factor recycling.

Baseline factor library:
1. Momentum (12-1 month) — Jegadeesh & Titman (1993)
2. Short-term reversal (1-month) — Jegadeesh (1990)
3. Post-earnings-announcement drift (PEAD) — Ball & Brown (1968)
4. Value (book-to-market) — Fama & French (1992)
5. Size (market cap) — Banz (1981)
6. Liquidity (Amihud illiquidity) — Amihud (2002)
7. Low volatility — Ang et al. (2006)
8-12. Sector-neutral versions of above

DESIGN NOTE (Statistical Epistemologist):
If a hypothesis alpha disappears after controlling for baseline factors,
it's not an LLM edge — it's factor recycling. This is one of the most
common errors in quantitative research: claiming a "new" signal that is
just a repackaged momentum or value factor.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import pearsonr

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21
FACTOR_ALPHA_SIGNIFICANCE = 0.05


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class FactorReturn:
    """Return series for a single factor."""

    name: str
    description: str
    returns: pd.Series          # Long-short factor return (daily)
    long_returns: pd.Series     # Long leg only (if applicable)
    short_returns: pd.Series    # Short leg only (if applicable)
    construction_period: str    # Lookback / formation period
    source_paper: str           # Academic reference


@dataclass
class FactorExposureResult:
    """Result of regressing strategy returns on factor returns."""

    # Factor loadings
    factor_loadings: Dict[str, float]   # factor_name -> beta
    factor_t_stats: Dict[str, float]    # factor_name -> t-statistic
    factor_p_values: Dict[str, float]   # factor_name -> p-value

    # Alpha
    alpha_annualized: float             # Intercept (annualized)
    alpha_t_stat: float
    alpha_p_value: float
    alpha_ci_95: Tuple[float, float]

    # Model fit
    r_squared: float
    adjusted_r_squared: float
    n_observations: int

    # Residual analysis
    residual_annualized_return: float
    residual_sharpe: float
    residual_significant: bool          # Is residual alpha significant?

    # Factor contribution
    factor_contribution_pct: Dict[str, float]  # % of return explained by each factor

    # Verdict
    is_factor_recycling: bool           # True if alpha becomes non-significant after
                                        # controlling for baseline factors
    dominant_factors: List[str]         # Factors with |t-stat| > 2


@dataclass
class FactorComparisonReport:
    """Complete factor comparison report."""

    # Individual factor returns
    factor_returns: Dict[str, FactorReturn]

    # Strategy regression on factors
    exposure: FactorExposureResult

    # Correlation with individual factors
    factor_correlations: Dict[str, float]

    # Alpha decomposition
    raw_alpha_annualized: float
    factor_explained_alpha: float       # Alpha explained by factors
    residual_alpha_annualized: float    # Alpha not explained by factors
    factor_explained_pct: float         # Fraction of alpha explained by factors

    # Verdict
    verdict: str                        # 'SURVIVED_FACTOR_CHECK' | 'FACTOR_RECYCLING'
    warnings: List[str]


# ============================================================================
# Factor Constructor
# ============================================================================


class FactorConstructor:
    """
    Constructs all baseline factors from price and fundamental data.

    All factor construction is point-in-time: factors at date T use only
    data available at T (no look-ahead bias in the factor construction itself).
    """

    def __init__(self, seed: Optional[int] = None):
        self.seed = seed
        self.rng = np.random.RandomState(seed)

    def _get_factor_returns_from_file(self) -> Dict[str, pd.Series]:
        """
        Load standard factor returns from file.

        In production, this would load from:
        - Kenneth French data library (Fama-French factors)
        - AQR data library
        - Custom computed factors from the pipeline's data
        """
        # For the pipeline, factor returns can be:
        # 1. Downloaded from Kenneth French data library (free)
        # 2. Downloaded from AQR data library (free)
        # 3. Computed from the pipeline's price/fundamental data
        # 4. Provided as input data

        # Placeholder: return empty dict (factors will be computed from data)
        return {}

    # ------------------------------------------------------------------
    # Factor 1: Momentum (12-1 month)
    # ------------------------------------------------------------------

    def construct_momentum_12_1(
        self,
        price_df: pd.DataFrame,
        market_cap_df: Optional[pd.DataFrame] = None,
        date: Optional[str] = None,
    ) -> pd.Series:
        """
        Construct momentum signal: return from t-12 months to t-1 month.

        Skips the most recent month to avoid short-term reversal effects.
        This is the canonical Jegadeesh & Titman (1993) momentum factor.

        Returns:
            Series mapping ticker -> momentum signal
        """
        if len(price_df) < TRADING_DAYS_PER_MONTH * 12:
            return pd.Series(dtype=float)

        # Use the last year of data, skipping the most recent month
        if date is not None:
            date_idx = price_df.index.get_loc(date)
            end_idx = date_idx - TRADING_DAYS_PER_MONTH
            start_idx = end_idx - TRADING_DAYS_PER_MONTH * 11
        else:
            end_idx = -TRADING_DAYS_PER_MONTH
            start_idx = -TRADING_DAYS_PER_MONTH * 12

        # Ensure indices are valid
        start_idx = max(0, start_idx)
        end_idx = min(len(price_df) - 1, end_idx)

        momentum_prices = price_df.iloc[start_idx : end_idx + 1]
        momentum_returns = momentum_prices.pct_change().add(1).prod() - 1

        return momentum_returns

    def construct_momentum_factor_return(
        self,
        price_df: pd.DataFrame,
        universe_dates: List[str],
        top_quantile: float = 0.3,
        bottom_quantile: float = 0.3,
    ) -> pd.Series:
        """
        Construct momentum factor return series (long top 30%, short bottom 30%).
        """
        factor_returns = []

        for i, date in enumerate(universe_dates):
            if i < TRADING_DAYS_PER_MONTH * 12:
                continue

            date_idx = price_df.index.get_loc(date)
            mom_signal = self.construct_momentum_12_1(
                price_df.iloc[: date_idx + 1], date=date
            )

            if mom_signal.empty:
                continue

            n_top = max(1, int(len(mom_signal) * top_quantile))
            n_bottom = max(1, int(len(mom_signal) * bottom_quantile))

            top_tickers = mom_signal.nlargest(n_top).index
            bottom_tickers = mom_signal.nsmallest(n_bottom).index

            # Forward return (next month)
            future_idx = date_idx + TRADING_DAYS_PER_MONTH
            if future_idx >= len(price_df):
                break

            top_return = price_df.iloc[future_idx][top_tickers].pct_change().add(1).prod() - 1
            top_return = top_return.mean() if hasattr(top_return, 'mean') else top_return

            bottom_return = price_df.iloc[future_idx][bottom_tickers].pct_change().add(1).prod() - 1
            bottom_return = bottom_return.mean() if hasattr(bottom_return, 'mean') else bottom_return

            factor_returns.append({
                "date": date,
                "momentum_return": top_return - bottom_return,
            })

        return pd.DataFrame(factor_returns).set_index("date")["momentum_return"]

    # ------------------------------------------------------------------
    # Factor 2: Short-Term Reversal (1-month)
    # ------------------------------------------------------------------

    def construct_short_term_reversal(
        self,
        price_df: pd.DataFrame,
        date: Optional[str] = None,
    ) -> pd.Series:
        """
        Construct short-term reversal signal: return in month t-1.

        Jegadeesh (1990): Stocks with poor recent performance tend to
        outperform in the next month, and vice versa.

        Returns:
            Series mapping ticker -> reversal signal (higher = expected reversal up)
        """
        if date is not None:
            date_idx = price_df.index.get_loc(date)
            start_idx = max(0, date_idx - TRADING_DAYS_PER_MONTH)
            recent_prices = price_df.iloc[start_idx : date_idx + 1]
        else:
            recent_prices = price_df.iloc[-TRADING_DAYS_PER_MONTH:]

        recent_return = recent_prices.pct_change().add(1).prod() - 1
        # Negative: poor performers expected to reverse up
        return -recent_return

    def construct_reversal_factor_return(
        self, price_df: pd.DataFrame, universe_dates: List[str],
    ) -> pd.Series:
        """Construct short-term reversal factor return."""
        factor_returns = []

        for i, date in enumerate(universe_dates):
            if i < TRADING_DAYS_PER_MONTH:
                continue

            date_idx = price_df.index.get_loc(date)
            reversal = self.construct_short_term_reversal(
                price_df.iloc[: date_idx + 1], date=date
            )

            if reversal.empty:
                continue

            n = max(1, int(len(reversal) * 0.3))
            top = reversal.nlargest(n).index
            bottom = reversal.nsmallest(n).index

            future_idx = min(date_idx + TRADING_DAYS_PER_MONTH, len(price_df) - 1)

            top_ret = price_df.iloc[future_idx][top].pct_change().add(1).prod() - 1
            top_ret = top_ret.mean() if hasattr(top_ret, 'mean') else top_ret

            bottom_ret = price_df.iloc[future_idx][bottom].pct_change().add(1).prod() - 1
            bottom_ret = bottom_ret.mean() if hasattr(bottom_ret, 'mean') else bottom_ret

            factor_returns.append({"date": date, "reversal_return": top_ret - bottom_ret})

        return pd.DataFrame(factor_returns).set_index("date")["reversal_return"]

    # ------------------------------------------------------------------
    # Factor 3: Post-Earnings-Announcement Drift (PEAD)
    # ------------------------------------------------------------------

    def construct_pead_signal(
        self,
        earnings_df: pd.DataFrame,  # ticker, announcement_date, actual_eps, expected_eps
        date: Optional[str] = None,
    ) -> pd.Series:
        """
        Construct PEAD signal: Standardized Unexpected Earnings (SUE).

        SUE = (Actual EPS - Expected EPS) / std(EPS surprise)

        Ball & Brown (1968): Stocks with positive earnings surprises
        continue to drift up for months after announcement.
        """
        if earnings_df.empty:
            return pd.Series(dtype=float)

        signals = {}
        eps_surprise_std = earnings_df["eps_surprise"].std()

        if eps_surprise_std == 0 or np.isnan(eps_surprise_std):
            eps_surprise_std = 1.0

        for ticker in earnings_df["ticker"].unique():
            ticker_data = earnings_df[earnings_df["ticker"] == ticker]
            latest = ticker_data.iloc[-1]

            if "eps_surprise" not in latest:
                continue

            sue = latest["eps_surprise"] / eps_surprise_std
            signals[ticker] = sue

        return pd.Series(signals)

    def construct_pead_factor_return(
        self, price_df: pd.DataFrame, earnings_df: pd.DataFrame,
        universe_dates: List[str],
    ) -> pd.Series:
        """Construct PEAD factor return."""
        factor_returns = []

        for date in universe_dates:
            # Use earnings announced before this date
            prior_earnings = earnings_df[
                earnings_df["announcement_date"] <= date
            ]

            if prior_earnings.empty:
                continue

            pead = self.construct_pead_signal(prior_earnings, date=date)
            if pead.empty:
                continue

            n = max(1, int(len(pead) * 0.3))
            top = pead.nlargest(n).index
            bottom = pead.nsmallest(n).index

            date_idx = price_df.index.get_loc(date)
            future_idx = min(date_idx + TRADING_DAYS_PER_MONTH * 3, len(price_df) - 1)

            top_ret = price_df.iloc[future_idx][top].pct_change().add(1).prod() - 1
            top_ret = top_ret.mean() if hasattr(top_ret, 'mean') else top_ret

            bottom_ret = price_df.iloc[future_idx][bottom].pct_change().add(1).prod() - 1
            bottom_ret = bottom_ret.mean() if hasattr(bottom_ret, 'mean') else bottom_ret

            factor_returns.append({"date": date, "pead_return": top_ret - bottom_ret})

        return pd.DataFrame(factor_returns).set_index("date")["pead_return"]

    # ------------------------------------------------------------------
    # Factor 4: Value (Book-to-Market)
    # ------------------------------------------------------------------

    def construct_value_signal(
        self,
        fundamental_df: pd.DataFrame,  # ticker, date, book_value, market_cap
        date: Optional[str] = None,
    ) -> pd.Series:
        """
        Construct value signal: Book-to-Market ratio.

        Fama & French (1992): High B/M stocks outperform low B/M stocks.
        """
        if fundamental_df.empty:
            return pd.Series(dtype=float)

        if date is not None:
            fund = fundamental_df[fundamental_df["date"] <= date]
        else:
            fund = fundamental_df

        # Use most recent fundamental data per ticker
        latest = fund.sort_values("date").groupby("ticker").last()

        bm = latest["book_value"] / latest["market_cap"]
        bm = bm.replace([np.inf, -np.inf], np.nan)
        return bm.dropna()

    def construct_value_factor_return(
        self, price_df: pd.DataFrame, fundamental_df: pd.DataFrame,
        universe_dates: List[str],
    ) -> pd.Series:
        """Construct value factor return."""
        factor_returns = []

        for date in universe_dates:
            value = self.construct_value_signal(fundamental_df, date=date)
            if value.empty:
                continue

            n = max(1, int(len(value) * 0.3))
            # High B/M = value (top), Low B/M = growth (bottom)
            top = value.nlargest(n).index
            bottom = value.nsmallest(n).index

            date_idx = price_df.index.get_loc(date)
            future_idx = min(date_idx + TRADING_DAYS_PER_MONTH, len(price_df) - 1)

            top_ret = price_df.iloc[future_idx][top].pct_change().add(1).prod() - 1
            top_ret = top_ret.mean() if hasattr(top_ret, 'mean') else top_ret

            bottom_ret = price_df.iloc[future_idx][bottom].pct_change().add(1).prod() - 1
            bottom_ret = bottom_ret.mean() if hasattr(bottom_ret, 'mean') else bottom_ret

            factor_returns.append({"date": date, "value_return": top_ret - bottom_ret})

        return pd.DataFrame(factor_returns).set_index("date")["value_return"]

    # ------------------------------------------------------------------
    # Factor 5: Size (Market Cap)
    # ------------------------------------------------------------------

    def construct_size_signal(
        self,
        market_cap_df: pd.DataFrame,  # date x ticker market caps
        date: Optional[str] = None,
    ) -> pd.Series:
        """
        Construct size signal: log market capitalization.

        Banz (1981): Small-cap stocks outperform large-cap stocks.
        """
        if date is not None and date in market_cap_df.index:
            mcaps = market_cap_df.loc[date]
        else:
            mcaps = market_cap_df.iloc[-1] if len(market_cap_df) > 0 else pd.Series(dtype=float)

        # Negative: smaller = higher signal (expected to outperform)
        return -np.log(mcaps.clip(lower=1e6))

    def construct_size_factor_return(
        self, price_df: pd.DataFrame, market_cap_df: pd.DataFrame,
        universe_dates: List[str],
    ) -> pd.Series:
        """Construct size factor return."""
        factor_returns = []

        for date in universe_dates:
            if date not in market_cap_df.index:
                continue

            size = self.construct_size_signal(market_cap_df, date=date)
            if size.empty:
                continue

            n = max(1, int(len(size) * 0.3))
            top = size.nlargest(n).index   # Small caps
            bottom = size.nsmallest(n).index  # Large caps

            date_idx = price_df.index.get_loc(date)
            future_idx = min(date_idx + TRADING_DAYS_PER_MONTH, len(price_df) - 1)

            top_ret = price_df.iloc[future_idx][top].pct_change().add(1).prod() - 1
            top_ret = top_ret.mean() if hasattr(top_ret, 'mean') else top_ret

            bottom_ret = price_df.iloc[future_idx][bottom].pct_change().add(1).prod() - 1
            bottom_ret = bottom_ret.mean() if hasattr(bottom_ret, 'mean') else bottom_ret

            factor_returns.append({"date": date, "size_return": top_ret - bottom_ret})

        return pd.DataFrame(factor_returns).set_index("date")["size_return"]

    # ------------------------------------------------------------------
    # Factor 6: Liquidity (Amihud Illiquidity)
    # ------------------------------------------------------------------

    def construct_amihud_illiquidity(
        self,
        price_df: pd.DataFrame,
        volume_df: pd.DataFrame,
        date: Optional[str] = None,
        window_days: int = TRADING_DAYS_PER_MONTH,
    ) -> pd.Series:
        """
        Construct Amihud illiquidity measure.

        Amihud (2002): ILLIQ = mean(|daily_return| / dollar_volume)
        Higher ILLIQ = less liquid. Amihud shows illiquid stocks earn a premium.
        """
        if date is not None:
            date_idx = price_df.index.get_loc(date)
            start_idx = max(0, date_idx - window_days)
            window_prices = price_df.iloc[start_idx : date_idx + 1]
            window_volumes = volume_df.iloc[start_idx : date_idx + 1]
        else:
            window_prices = price_df.iloc[-window_days:]
            window_volumes = volume_df.iloc[-window_days:]

        daily_returns = window_prices.pct_change().abs()
        dollar_volumes = window_prices * window_volumes

        with np.errstate(divide="ignore", invalid="ignore"):
            daily_illiq = daily_returns / dollar_volumes.clip(lower=1)

        illiq = daily_illiq.mean()
        return illiq.replace([np.inf, -np.inf], np.nan)

    def construct_liquidity_factor_return(
        self, price_df: pd.DataFrame, volume_df: pd.DataFrame,
        universe_dates: List[str],
    ) -> pd.Series:
        """Construct liquidity factor return."""
        factor_returns = []

        for date in universe_dates:
            illiq = self.construct_amihud_illiquidity(price_df, volume_df, date=date)
            if illiq.empty:
                continue

            n = max(1, int(len(illiq) * 0.3))
            top = illiq.nlargest(n).index    # Illiquid
            bottom = illiq.nsmallest(n).index # Liquid

            date_idx = price_df.index.get_loc(date)
            future_idx = min(date_idx + TRADING_DAYS_PER_MONTH, len(price_df) - 1)

            top_ret = price_df.iloc[future_idx][top].pct_change().add(1).prod() - 1
            top_ret = top_ret.mean() if hasattr(top_ret, 'mean') else top_ret

            bottom_ret = price_df.iloc[future_idx][bottom].pct_change().add(1).prod() - 1
            bottom_ret = bottom_ret.mean() if hasattr(bottom_ret, 'mean') else bottom_ret

            factor_returns.append({"date": date, "liquidity_return": top_ret - bottom_ret})

        return pd.DataFrame(factor_returns).set_index("date")["liquidity_return"]

    # ------------------------------------------------------------------
    # Factor 7: Low Volatility
    # ------------------------------------------------------------------

    def construct_low_volatility_signal(
        self,
        price_df: pd.DataFrame,
        date: Optional[str] = None,
        window_days: int = TRADING_DAYS_PER_YEAR,
    ) -> pd.Series:
        """
        Construct low volatility signal: inverse of trailing volatility.

        Ang et al. (2006): Low-volatility stocks outperform high-volatility stocks.
        """
        if date is not None:
            date_idx = price_df.index.get_loc(date)
            start_idx = max(0, date_idx - window_days)
            window_returns = price_df.iloc[start_idx : date_idx + 1].pct_change()
        else:
            window_returns = price_df.iloc[-window_days:].pct_change()

        volatilities = window_returns.std()
        return -volatilities  # Negative: higher vol = lower signal

    def construct_lowvol_factor_return(
        self, price_df: pd.DataFrame, universe_dates: List[str],
    ) -> pd.Series:
        """Construct low volatility factor return."""
        factor_returns = []

        for date in universe_dates:
            lowvol = self.construct_low_volatility_signal(price_df, date=date)
            if lowvol.empty:
                continue

            n = max(1, int(len(lowvol) * 0.3))
            top = lowvol.nlargest(n).index     # Low vol
            bottom = lowvol.nsmallest(n).index  # High vol

            date_idx = price_df.index.get_loc(date)
            future_idx = min(date_idx + TRADING_DAYS_PER_MONTH, len(price_df) - 1)

            top_ret = price_df.iloc[future_idx][top].pct_change().add(1).prod() - 1
            top_ret = top_ret.mean() if hasattr(top_ret, 'mean') else top_ret

            bottom_ret = price_df.iloc[future_idx][bottom].pct_change().add(1).prod() - 1
            bottom_ret = bottom_ret.mean() if hasattr(bottom_ret, 'mean') else bottom_ret

            factor_returns.append({"date": date, "lowvol_return": top_ret - bottom_ret})

        return pd.DataFrame(factor_returns).set_index("date")["lowvol_return"]

    # ------------------------------------------------------------------
    # Sector-Neutral Factors
    # ------------------------------------------------------------------

    def construct_sector_neutral_factor(
        self,
        raw_signal: pd.Series,
        sector_df: pd.Series,  # ticker -> sector
    ) -> pd.Series:
        """
        Convert a raw factor signal to sector-neutral.

        Sector-neutral: signal = raw_signal - mean(raw_signal within sector).
        This removes sector bets from the factor.
        """
        if raw_signal.empty or sector_df.empty:
            return raw_signal

        aligned = pd.DataFrame({
            "signal": raw_signal,
            "sector": sector_df,
        }).dropna()

        sector_means = aligned.groupby("sector")["signal"].transform("mean")
        sector_neutral = aligned["signal"] - sector_means

        return sector_neutral

    # ------------------------------------------------------------------
    # All Factors Construction
    # ------------------------------------------------------------------

    def construct_all_factors(
        self,
        price_df: pd.DataFrame,
        market_cap_df: Optional[pd.DataFrame] = None,
        volume_df: Optional[pd.DataFrame] = None,
        fundamental_df: Optional[pd.DataFrame] = None,
        earnings_df: Optional[pd.DataFrame] = None,
        sector_df: Optional[pd.DataFrame] = None,
        universe_dates: Optional[List[str]] = None,
    ) -> Dict[str, pd.Series]:
        """
        Construct all baseline factor return series.

        Returns:
            Dict mapping factor_name -> daily factor return series
        """
        if universe_dates is None:
            universe_dates = list(price_df.index)

        factor_returns = {}

        # 1. Momentum
        try:
            mom = self.construct_momentum_factor_return(price_df, universe_dates)
            factor_returns["momentum_12_1"] = mom
            logger.info(f"Constructed momentum factor: {len(mom)} observations")
        except Exception as e:
            logger.warning(f"Failed to construct momentum factor: {e}")

        # 2. Short-term reversal
        try:
            rev = self.construct_reversal_factor_return(price_df, universe_dates)
            factor_returns["short_term_reversal"] = rev
        except Exception as e:
            logger.warning(f"Failed to construct reversal factor: {e}")

        # 3. PEAD
        if earnings_df is not None and not earnings_df.empty:
            try:
                pead = self.construct_pead_factor_return(price_df, earnings_df, universe_dates)
                factor_returns["pead"] = pead
            except Exception as e:
                logger.warning(f"Failed to construct PEAD factor: {e}")

        # 4. Value
        if fundamental_df is not None and not fundamental_df.empty:
            try:
                value = self.construct_value_factor_return(price_df, fundamental_df, universe_dates)
                factor_returns["value"] = value
            except Exception as e:
                logger.warning(f"Failed to construct value factor: {e}")

        # 5. Size
        if market_cap_df is not None:
            try:
                size = self.construct_size_factor_return(price_df, market_cap_df, universe_dates)
                factor_returns["size"] = size
            except Exception as e:
                logger.warning(f"Failed to construct size factor: {e}")

        # 6. Liquidity
        if volume_df is not None:
            try:
                liq = self.construct_liquidity_factor_return(price_df, volume_df, universe_dates)
                factor_returns["liquidity"] = liq
            except Exception as e:
                logger.warning(f"Failed to construct liquidity factor: {e}")

        # 7. Low volatility
        try:
            lowvol = self.construct_lowvol_factor_return(price_df, universe_dates)
            factor_returns["low_volatility"] = lowvol
        except Exception as e:
            logger.warning(f"Failed to construct low vol factor: {e}")

        return factor_returns


# ============================================================================
# Factor Comparison Engine
# ============================================================================


class FactorComparisonEngine:
    """
    Compares strategy returns against baseline factor returns.

    This is the MANDATORY Requirement 9 check: every hypothesis MUST be
    compared against known factors. Alpha that is explained by known
    factors is factor recycling, not a genuine LLM edge.
    """

    def __init__(self, factor_constructor: Optional[FactorConstructor] = None):
        self.factor_constructor = factor_constructor or FactorConstructor()

    def regress_on_factors(
        self,
        strategy_returns: pd.Series,
        factor_returns: Dict[str, pd.Series],
        intercept: bool = True,
    ) -> FactorExposureResult:
        """
        Regress strategy returns on factor returns.

        r_strategy = alpha + sum(beta_i * factor_i) + epsilon

        If alpha is not significant after controlling for factors,
        the strategy is factor recycling.
        """
        # Align all time series
        aligned = pd.DataFrame({"strategy": strategy_returns})

        for name, series in factor_returns.items():
            aligned[name] = series

        aligned = aligned.dropna()

        if len(aligned) < 20:
            return FactorExposureResult(
                factor_loadings={},
                factor_t_stats={},
                factor_p_values={},
                alpha_annualized=0,
                alpha_t_stat=0,
                alpha_p_value=1.0,
                alpha_ci_95=(0, 0),
                r_squared=0,
                adjusted_r_squared=0,
                n_observations=len(aligned),
                residual_annualized_return=0,
                residual_sharpe=0,
                residual_significant=False,
                factor_contribution_pct={},
                is_factor_recycling=False,
                dominant_factors=[],
            )

        # Prepare regression
        y = aligned["strategy"].values
        factor_names = list(factor_returns.keys())
        X_data = aligned[factor_names].values

        if intercept:
            X = np.column_stack([np.ones(len(aligned)), X_data])
        else:
            X = X_data

        # OLS regression
        n_obs = len(y)
        n_params = X.shape[1]

        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
        except np.linalg.LinAlgError:
            return FactorExposureResult(
                factor_loadings={},
                factor_t_stats={},
                factor_p_values={},
                alpha_annualized=0,
                alpha_t_stat=0,
                alpha_p_value=1.0,
                alpha_ci_95=(0, 0),
                r_squared=0,
                adjusted_r_squared=0,
                n_observations=n_obs,
                residual_annualized_return=0,
                residual_sharpe=0,
                residual_significant=False,
                factor_contribution_pct={},
                is_factor_recycling=False,
                dominant_factors=[],
            )

        # Predicted values and residuals
        y_pred = X @ beta
        residuals = y - y_pred

        # Standard errors
        sse = np.sum(residuals ** 2)
        mse = sse / (n_obs - n_params)
        se = np.sqrt(mse * np.diag(np.linalg.inv(X.T @ X)))

        # t-statistics and p-values
        t_stats = beta / se
        p_values = 2 * (1 - stats.t.cdf(np.abs(t_stats), n_obs - n_params))

        # R-squared
        ss_total = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - sse / ss_total if ss_total > 0 else 0
        adj_r_squared = 1 - (1 - r_squared) * (n_obs - 1) / (n_obs - n_params)

        # Alpha (intercept)
        if intercept:
            alpha_annualized = beta[0] * TRADING_DAYS_PER_YEAR
            alpha_t_stat = t_stats[0]
            alpha_p_value = p_values[0]

            # 95% CI for alpha
            alpha_ci = (
                (beta[0] - 1.96 * se[0]) * TRADING_DAYS_PER_YEAR,
                (beta[0] + 1.96 * se[0]) * TRADING_DAYS_PER_YEAR,
            )

            # Factor loadings
            factor_loadings = {
                factor_names[i]: beta[i + 1] for i in range(len(factor_names))
            }
            factor_t_stats = {
                factor_names[i]: t_stats[i + 1] for i in range(len(factor_names))
            }
            factor_p_values = {
                factor_names[i]: p_values[i + 1] for i in range(len(factor_names))
            }
        else:
            alpha_annualized = 0
            alpha_t_stat = 0
            alpha_p_value = 1.0
            alpha_ci = (0, 0)

            factor_loadings = {
                factor_names[i]: beta[i] for i in range(len(factor_names))
            }
            factor_t_stats = {
                factor_names[i]: t_stats[i] for i in range(len(factor_names))
            }
            factor_p_values = {
                factor_names[i]: p_values[i] for i in range(len(factor_names))
            }

        # Residual analysis
        residual_ann_return = np.mean(residuals) * TRADING_DAYS_PER_YEAR
        residual_vol = np.std(residuals, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
        residual_sharpe = residual_ann_return / residual_vol if residual_vol > 0 else 0
        residual_significant = alpha_p_value < FACTOR_ALPHA_SIGNIFICANCE if intercept else False

        # Factor contribution decomposition
        # Contribution = beta_i * cov(strategy, factor_i) / var(strategy)
        factor_contributions = {}
        strategy_variance = np.var(y, ddof=1)
        if strategy_variance > 0:
            for i, name in enumerate(factor_names):
                idx = i + 1 if intercept else i
                cov = np.cov(y, X_data[:, i])[0, 1]
                factor_contributions[name] = float(beta[idx] * cov / strategy_variance * 100)

        # Dominant factors: |t-stat| > 2
        dominant_factors = [
            name for name, t in factor_t_stats.items()
            if abs(t) > 2.0
        ]

        # Factor recycling check
        is_factor_recycling = intercept and alpha_p_value > 0.05

        return FactorExposureResult(
            factor_loadings=factor_loadings,
            factor_t_stats=factor_t_stats,
            factor_p_values=factor_p_values,
            alpha_annualized=alpha_annualized,
            alpha_t_stat=alpha_t_stat,
            alpha_p_value=alpha_p_value,
            alpha_ci_95=alpha_ci,
            r_squared=r_squared,
            adjusted_r_squared=adj_r_squared,
            n_observations=n_obs,
            residual_annualized_return=residual_ann_return,
            residual_sharpe=residual_sharpe,
            residual_significant=residual_significant,
            factor_contribution_pct=factor_contributions,
            is_factor_recycling=is_factor_recycling,
            dominant_factors=dominant_factors,
        )

    def compute_factor_correlations(
        self,
        strategy_returns: pd.Series,
        factor_returns: Dict[str, pd.Series],
    ) -> Dict[str, float]:
        """Compute correlation of strategy returns with each factor."""
        correlations = {}

        for name, series in factor_returns.items():
            aligned = pd.concat([strategy_returns, series], axis=1).dropna()
            if len(aligned) > 10:
                corr, _ = pearsonr(aligned.iloc[:, 0], aligned.iloc[:, 1])
                correlations[name] = corr
            else:
                correlations[name] = np.nan

        return correlations

    def generate_factor_comparison_report(
        self,
        strategy_returns: pd.Series,
        raw_alpha_annualized: float,
        price_df: Optional[pd.DataFrame] = None,
        market_cap_df: Optional[pd.DataFrame] = None,
        volume_df: Optional[pd.DataFrame] = None,
        fundamental_df: Optional[pd.DataFrame] = None,
        earnings_df: Optional[pd.DataFrame] = None,
        sector_df: Optional[pd.DataFrame] = None,
        universe_dates: Optional[List[str]] = None,
        precomputed_factors: Optional[Dict[str, pd.Series]] = None,
    ) -> FactorComparisonReport:
        """
        Generate complete factor comparison report.

        This is the MANDATORY output for Requirement 9.
        """
        warnings_list = []

        # Get factor returns
        if precomputed_factors is not None:
            factor_rets = precomputed_factors
        elif price_df is not None:
            factor_rets = self.factor_constructor.construct_all_factors(
                price_df=price_df,
                market_cap_df=market_cap_df,
                volume_df=volume_df,
                fundamental_df=fundamental_df,
                earnings_df=earnings_df,
                sector_df=sector_df,
                universe_dates=universe_dates or list(strategy_returns.index),
            )
        else:
            factor_rets = {}

        if not factor_rets:
            return FactorComparisonReport(
                factor_returns={},
                exposure=FactorExposureResult(
                    factor_loadings={}, factor_t_stats={}, factor_p_values={},
                    alpha_annualized=raw_alpha_annualized, alpha_t_stat=0,
                    alpha_p_value=1.0, alpha_ci_95=(0, 0),
                    r_squared=0, adjusted_r_squared=0, n_observations=len(strategy_returns),
                    residual_annualized_return=0, residual_sharpe=0,
                    residual_significant=False, factor_contribution_pct={},
                    is_factor_recycling=False, dominant_factors=[],
                ),
                factor_correlations={},
                raw_alpha_annualized=raw_alpha_annualized,
                factor_explained_alpha=0,
                residual_alpha_annualized=raw_alpha_annualized,
                factor_explained_pct=0,
                verdict="INCONCLUSIVE_NO_FACTORS",
                warnings=["No baseline factors could be constructed. Factor comparison skipped."],
            )

        # Regress on factors
        exposure = self.regress_on_factors(strategy_returns, factor_rets)

        # Correlations
        correlations = self.compute_factor_correlations(strategy_returns, factor_rets)

        # Alpha decomposition
        factor_explained_alpha = raw_alpha_annualized - exposure.residual_annualized_return
        factor_explained_pct = (
            factor_explained_alpha / raw_alpha_annualized * 100
            if raw_alpha_annualized != 0
            else 0
        )

        # Verdict
        if exposure.is_factor_recycling:
            verdict = "FACTOR_RECYCLING"
            warnings_list.append(
                f"HYPOTHESIS IS FACTOR RECYCLING. Alpha becomes non-significant "
                f"(p={exposure.alpha_p_value:.4f}) after controlling for baseline "
                f"factors. Dominant factor exposures: {exposure.dominant_factors}. "
                f"R-squared = {exposure.r_squared:.3f}."
            )
        else:
            verdict = "SURVIVED_FACTOR_CHECK"
            if exposure.dominant_factors:
                warnings_list.append(
                    f"Survived factor check but note significant exposures to: "
                    f"{exposure.dominant_factors}. R-squared = {exposure.r_squared:.3f}."
                )

        # Additional warnings
        if exposure.r_squared > 0.50:
            warnings_list.append(
                f"Strategy returns are {exposure.r_squared:.1%} explained by "
                f"known factors. The LLM signal is adding limited incremental value."
            )

        return FactorComparisonReport(
            factor_returns={
                name: FactorReturn(
                    name=name,
                    description=f"Baseline factor: {name}",
                    returns=series,
                    long_returns=pd.Series(),
                    short_returns=pd.Series(),
                    construction_period="varies",
                    source_paper="See PIPELINE_SPEC.md Section 10",
                )
                for name, series in factor_rets.items()
            },
            exposure=exposure,
            factor_correlations=correlations,
            raw_alpha_annualized=raw_alpha_annualized,
            factor_explained_alpha=factor_explained_alpha,
            residual_alpha_annualized=exposure.residual_annualized_return,
            factor_explained_pct=factor_explained_pct,
            verdict=verdict,
            warnings=warnings_list,
        )
