"""
gt_score.py — Golden Ticket Score (GT-Score) Composite Objective Function
==========================================================================

A composite objective function that penalises inconsistent returns and
small sample sizes, helping guide optimisation toward robust strategies
rather than overfitted backtests.

Formula:
    GTScore = mu * ln(z) * (d / sigma_d) * r_squared

Where:
    mu        = mean daily return
    z         = t-statistic (z-score), ln(z) anchors at z=1 -> score=0
    d         = number of trading days with positive return
    sigma_d   = downside deviation (annualised)
    r_squared = R^2 from a linear time-trend fit (equity curve smoothness)

The ln(z) term acts as a significance gate: strategies that cannot reject
the null (z <= 1) receive a non-positive composite score regardless of
other dimensions. The d/sigma_d ratio rewards consistency per unit of
downside risk. The r_squared term penalises lumpy, unpredictable equity curves.

Reference:
    Adapted from the TradeFinder research plan. Comparable in spirit to
    the Probabilistic Sharpe Ratio (Bailey & Lopez de Prado, 2012) but
    designed as a single composite metric for strategy ranking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


@dataclass
class GTScoreResult:
    """Complete GT-Score decomposition for a return series."""

    gt_score: float
    mu_daily: float                    # mean daily return
    t_statistic: float                  # one-sample t-statistic vs zero
    z_score: float                      # absolute t-statistic
    ln_z: float                         # ln(z_score), the significance gate
    n_positive_days: int                # count of positive-return days
    n_total_days: int                   # total observations
    d_ratio: float                      # n_positive / n_total
    sigma_d_annual: float               # annualised downside deviation
    r_squared_trend: float              # R^2 of linear time-trend fit
    components: dict                    # individual component values for audit

    def is_positive(self) -> bool:
        """GT-Score > 0 means the strategy outperforms the benchmark beyond
        sampling noise (z > 1)."""
        return self.gt_score > 0

    def to_dict(self) -> dict:
        return {
            "gt_score": float(self.gt_score),
            "mu_daily_bps": float(self.mu_daily * 10000),
            "t_statistic": float(self.t_statistic),
            "z_score": float(self.z_score),
            "ln_z": float(self.ln_z),
            "n_positive_days": self.n_positive_days,
            "n_total_days": self.n_total_days,
            "d_ratio": float(self.d_ratio),
            "sigma_d_annual_bps": float(self.sigma_d_annual * 10000),
            "r_squared_trend": float(self.r_squared_trend),
            "components": {k: float(v) for k, v in self.components.items()},
        }


def compute_downside_deviation(
    returns: np.ndarray,
    mar: float = 0.0,
    annualise: bool = True,
) -> float:
    """Compute downside deviation (annualised by default).

    Downside deviation only considers returns below the minimum acceptable
    return (MAR), typically zero.
    """
    downside = returns[returns < mar]
    if len(downside) < 2:
        return 0.0

    # Population-like std for downside; ddof=0 to match Sortino convention
    sigma_d = np.sqrt(np.mean(downside ** 2))

    if annualise:
        sigma_d *= np.sqrt(TRADING_DAYS_PER_YEAR)

    return float(sigma_d)


def compute_equity_curve_r_squared(
    returns: np.ndarray,
) -> Tuple[float, float]:
    """Fit a linear time trend to the cumulative equity curve.

    Returns (r_squared, trend_coefficient).  A high R^2 indicates smooth,
    consistent growth.  A low R^2 indicates lumpy, unpredictable returns.
    """
    n = len(returns)
    if n < 4:
        return 0.0, 0.0

    cum_returns = np.cumprod(1 + returns)
    x = np.arange(n).reshape(-1, 1)
    y = cum_returns.reshape(-1, 1)

    # Add constant term for intercept
    X = np.column_stack([np.ones(n), x])

    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        y_pred = X @ beta
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        r_sq = max(0.0, min(1.0, float(r_sq)))
        trend_coef = float(beta[1, 0])
        return r_sq, trend_coef
    except np.linalg.LinAlgError:
        return 0.0, 0.0


def compute_gt_score(
    returns: np.ndarray,
    annualisation_factor: float = np.sqrt(TRADING_DAYS_PER_YEAR),
) -> GTScoreResult:
    """Compute the Golden Ticket Score for a strategy return series.

    Args:
        returns: Array of period returns (daily, weekly, etc.).
        annualisation_factor: sqrt(periods_per_year) for t-stat scaling.
                              Default sqrt(252) for daily returns.

    Returns:
        GTScoreResult with the composite score and full decomposition.
    """
    returns = np.asarray(returns, dtype=float)
    returns = returns[np.isfinite(returns)]

    n = len(returns)

    if n < 10:
        return GTScoreResult(
            gt_score=float("-inf"),
            mu_daily=0.0,
            t_statistic=0.0,
            z_score=0.0,
            ln_z=float("-inf"),
            n_positive_days=0,
            n_total_days=n,
            d_ratio=0.0,
            sigma_d_annual=0.0,
            r_squared_trend=0.0,
            components={"mu": 0.0, "ln_z": float("-inf"), "d_ratio": 0.0, "r_sq": 0.0},
        )

    # --- Component 1: mu (mean daily return) ---
    mu = float(np.mean(returns))

    # --- Component 2: ln(z) — significance gate ---
    # z = t-statistic for H0: mu = 0
    if n >= 2:
        se = np.std(returns, ddof=1) / np.sqrt(n)
        t_stat = mu / se if se > 0 else 0.0
    else:
        t_stat = 0.0

    z = abs(t_stat)
    ln_z = np.log(z) if z > 0 else float("-inf")

    # --- Component 3: d / sigma_d (consistency per downside risk) ---
    n_positive = int(np.sum(returns > 0))
    d_ratio = n_positive / n if n > 0 else 0.0

    sigma_d_annual = compute_downside_deviation(returns, mar=0.0, annualise=True)

    # Avoid division by zero — if the strategy never has a down day,
    # the downside deviation is extremely small, which is a good thing.
    # Cap the ratio to prevent infinite scores.
    d_over_sigma = d_ratio / max(sigma_d_annual, 1e-10)
    d_over_sigma = min(d_over_sigma, 1e4)  # cap at 10,000

    # --- Component 4: r_squared (equity curve smoothness) ---
    r_sq, trend_coef = compute_equity_curve_r_squared(returns)

    # --- Composite ---
    # GTScore = mu * ln(z) * (d / sigma_d) * r_squared
    #
    # ln(z) < 0 when z < 1  ->  GTScore < 0 regardless of other terms.
    # This is the significance gate: if you can't beat noise, you score
    # negative no matter how smooth or consistent the curve looks.
    if ln_z == float("-inf") or np.isinf(ln_z):
        gt_score = float("-inf")
    else:
        # Scale mu to bps/day for reasonable magnitude
        mu_bps = mu * 10000.0  # basis points per day
        gt_score = mu_bps * ln_z * d_over_sigma * r_sq

    return GTScoreResult(
        gt_score=float(gt_score),
        mu_daily=mu,
        t_statistic=float(t_stat),
        z_score=float(z),
        ln_z=float(ln_z),
        n_positive_days=n_positive,
        n_total_days=n,
        d_ratio=float(d_ratio),
        sigma_d_annual=sigma_d_annual,
        r_squared_trend=r_sq,
        components={
            "mu_bps_daily": mu_bps if ln_z != float("-inf") else 0.0,
            "ln_z": float(ln_z),
            "d_over_sigma": float(d_over_sigma),
            "r_squared": float(r_sq),
        },
    )


def compute_gt_score_from_series(
    returns: pd.Series,
    annualisation_factor: float = np.sqrt(TRADING_DAYS_PER_YEAR),
) -> GTScoreResult:
    """Convenience wrapper that accepts a pandas Series."""
    return compute_gt_score(returns.dropna().values, annualisation_factor)
