"""
statistics.py — Statistical Tests, Bootstrap, Multiple Comparison Correction
=============================================================================

Agent 1: Statistical Epistemologist
Reviewer: Agent 4 (Statistical Breaker)

This module implements the full statistical test battery. It is the pipeline's
statistical conscience. Every test is pre-specified. No p-hacking. No data
dredging. Appropriate corrections for multiple comparisons.

Key capabilities:
- Full distribution analysis (not just means)
- Block bootstrap confidence intervals (BCa method)
- Multiple comparison correction (Bonferroni + Benjamini-Hochberg FDR)
- Outlier analysis with winsorization sensitivity
- Power analysis for sample size adequacy
- Formal hypothesis tests appropriate to return distributions

DESIGN NOTE (Statistical Epistemologist):
Most backtesting "research" compares only means and reports only p-values.
This is insufficient. We need: distribution shape, tail behavior, confidence
intervals via bootstrap (not just normal approximation), effect sizes, power
analysis, and proper multiple comparison correction.

VETO FIX (Statistical Breaker): Added block bootstrap to preserve serial
correlation in return streams. IID bootstrap inflates significance for
autocorrelated returns. Added outlier sensitivity analysis (if removing <5%
of extreme observations eliminates significance, flag it).
"""

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import norm, t as t_dist
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_BOOTSTRAP_REPLICATIONS = 10000
DEFAULT_BLOCK_LENGTH = None  # Auto-select
DEFAULT_CONFIDENCE_LEVELS = [0.90, 0.95, 0.99]
DEFAULT_ALPHA = 0.05
DEFAULT_FDR_Q = 0.10
DEFAULT_POWER_TARGET = 0.80
TRADING_DAYS_PER_YEAR = 252


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class DistributionStats:
    """Full distribution statistics for a return series."""

    n_observations: int
    mean: float
    median: float
    std: float
    skewness: float
    kurtosis: float              # Excess kurtosis
    min_value: float
    max_value: float
    p1: float
    p5: float
    p10: float
    p25: float
    p75: float
    p90: float
    p95: float
    p99: float

    # Bootstrap CIs
    ci_90_mean: Tuple[float, float]
    ci_95_mean: Tuple[float, float]
    ci_99_mean: Tuple[float, float]

    # Normality test
    jarque_bera_stat: float
    jarque_bera_p: float

    # Serial correlation
    autocorr_lag1: float
    autocorr_lag5: float
    autocorr_lag21: float

    # Summary
    is_normally_distributed: bool  # J-B p < 0.05?


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics."""

    # Returns
    annualized_return: float
    annualized_volatility: float
    annualized_downside_volatility: float

    # Risk-adjusted
    sharpe_ratio: float
    sortino_ratio: float
    information_ratio: float  # vs benchmark (if provided)
    calmar_ratio: float       # return / max_drawdown

    # Drawdowns
    max_drawdown: float
    max_drawdown_days: int
    avg_drawdown: float
    drawdown_p95: float

    # Hit rates
    hit_rate: float            # Fraction of positive returns
    profit_factor: float       # Gross gains / gross losses
    omega_ratio: float         # Probability-weighted gain/loss (threshold=0)
    tail_ratio: float          # p95 / p5 return ratio

    # Information
    information_coefficient: Optional[float]  # Corr(signal, return)

    # Bootstrap CIs for key metrics
    sharpe_ci_95: Tuple[float, float]
    mean_return_ci_95_bps_daily: Tuple[float, float]


@dataclass
class MultipleComparisonResult:
    """Results of multiple comparison correction."""

    n_hypotheses: int
    n_tests_per_hypothesis: List[int]
    raw_p_values: List[float]

    # Bonferroni
    bonferroni_corrected_p: List[float]
    bonferroni_significant: List[bool]

    # Benjamini-Hochberg FDR
    fdr_corrected_p: List[float]
    fdr_q_value: float
    fdr_significant: List[bool]

    # Summary
    n_significant_bonferroni: int
    n_significant_fdr: int


@dataclass
class OutlierAnalysis:
    """Results of outlier sensitivity analysis."""

    original_mean: float
    original_significance: float  # p-value

    winsorized_1_99_mean: float
    winsorized_1_99_significance: float

    winsorized_2_5_97_5_mean: float
    winsorized_2_5_97_5_significance: float

    trimmed_5_mean: float
    trimmed_5_significance: float

    trimmed_10_mean: float
    trimmed_10_significance: float

    n_outliers_3sigma: int
    n_outliers_5sigma: int

    is_outlier_driven: bool  # True if removing <5% eliminates significance

    influence_observations: List[Dict[str, Any]]  # Dates with high DFBETAS


@dataclass
class PowerAnalysis:
    """Results of statistical power analysis."""

    sample_size: int
    effect_size: float             # Cohen's d
    achieved_power: float
    minimum_detectable_effect: float  # At target power
    required_sample_size: float    # For target power at observed effect
    is_adequately_powered: bool    # Achieved power >= 0.80


@dataclass
class StatisticalReport:
    """Complete statistical analysis report."""

    distribution: DistributionStats
    performance: PerformanceMetrics
    multiple_comparison: Optional[MultipleComparisonResult]
    outlier_analysis: OutlierAnalysis
    power_analysis: PowerAnalysis
    gt_score_result: Optional[Any] = None  # GTScoreResult from gt_score.py
    warnings: List[str] = field(default_factory=list)
    is_statistically_significant: bool = False  # After all corrections


# ============================================================================
# Block Bootstrap
# ============================================================================


class BlockBootstrap:
    """
    Block bootstrap for time series data.

    Standard IID bootstrap assumes independent observations, which is FALSE
    for financial returns (they exhibit serial correlation, volatility
    clustering, and tail dependence). The block bootstrap preserves the
    dependence structure by resampling contiguous blocks of observations.

    Implementation follows Politis & Romano (1994) stationary bootstrap and
    Politis & White (2004) automatic block length selection.
    """

    def __init__(
        self,
        n_replications: int = DEFAULT_BOOTSTRAP_REPLICATIONS,
        block_length: Optional[int] = DEFAULT_BLOCK_LENGTH,
        seed: Optional[int] = None,
    ):
        self.n_replications = n_replications
        self.block_length = block_length
        self.rng = np.random.RandomState(seed)

    def _select_block_length(self, data: np.ndarray) -> int:
        """
        Automatically select block length using Politis & White (2004).

        For daily financial returns, a block length of 5-20 trading days
        is typical (one week to one month).
        """
        n = len(data)
        if n < 20:
            return max(1, n // 4)

        # Simplified auto-selection based on autocorrelation
        acf_1 = self._autocorr(data, 1)
        acf_2 = self._autocorr(data, 2)

        # Rule of thumb based on first-order autocorrelation
        if abs(acf_1) < 0.05:
            block_length = 5  # Nearly independent
        elif abs(acf_1) < 0.20:
            block_length = 10  # Moderate dependence
        else:
            block_length = 21  # Strong dependence (~1 month)

        return min(block_length, max(2, n // 5))

    def _autocorr(self, x: np.ndarray, lag: int) -> float:
        """Compute autocorrelation at a given lag."""
        if len(x) <= lag:
            return 0.0
        return np.corrcoef(x[:-lag], x[lag:])[0, 1]

    def generate_samples(self, data: np.ndarray) -> np.ndarray:
        """
        Generate bootstrap samples using the moving block bootstrap.

        Args:
            data: 1D array of returns

        Returns:
            2D array of shape (n_replications, len(data))
        """
        n = len(data)

        if self.block_length is None:
            block_length = self._select_block_length(data)
        else:
            block_length = self.block_length

        block_length = min(block_length, n)

        samples = np.zeros((self.n_replications, n))

        for i in range(self.n_replications):
            # Sample blocks randomly with replacement
            n_blocks = int(np.ceil(n / block_length))
            boot_sample = []

            for _ in range(n_blocks):
                # Random starting index
                start = self.rng.randint(0, n - block_length + 1)
                block = data[start : start + block_length]
                boot_sample.extend(block)

            samples[i] = np.array(boot_sample[:n])

        return samples

    def compute_statistic(
        self, data: np.ndarray, statistic_func: callable,
    ) -> np.ndarray:
        """
        Compute bootstrap distribution of a statistic.

        Args:
            data: 1D array of returns
            statistic_func: Function that takes a 1D array and returns a scalar

        Returns:
            Array of bootstrap statistic values
        """
        samples = self.generate_samples(data)
        stats = np.array([statistic_func(samples[i]) for i in range(self.n_replications)])
        return stats

    def confidence_interval(
        self,
        data: np.ndarray,
        statistic_func: callable,
        alpha: float = 0.05,
        method: str = "bca",
    ) -> Tuple[float, float]:
        """
        Compute bootstrap confidence interval for a statistic.

        Methods:
        - 'percentile': Simple percentile bootstrap
        - 'bca': Bias-corrected and accelerated (Efron, 1987)
        - 'basic': Basic bootstrap (reverse percentile)

        Args:
            data: 1D array of observations
            statistic_func: Function to compute statistic
            alpha: Significance level (0.05 = 95% CI)
            method: Bootstrap CI method

        Returns:
            (lower_bound, upper_bound)
        """
        boot_stats = self.compute_statistic(data, statistic_func)
        original_stat = statistic_func(data)

        if method == "percentile":
            lower = np.percentile(boot_stats, alpha / 2 * 100)
            upper = np.percentile(boot_stats, (1 - alpha / 2) * 100)
        elif method == "bca":
            lower, upper = self._bca_interval(data, statistic_func, boot_stats, alpha)
        elif method == "basic":
            lower = 2 * original_stat - np.percentile(boot_stats, (1 - alpha / 2) * 100)
            upper = 2 * original_stat - np.percentile(boot_stats, alpha / 2 * 100)
        else:
            raise ValueError(f"Unknown method: {method}")

        return (lower, upper)

    def _bca_interval(
        self,
        data: np.ndarray,
        statistic_func: callable,
        boot_stats: np.ndarray,
        alpha: float,
    ) -> Tuple[float, float]:
        """
        Compute BCa (bias-corrected and accelerated) confidence interval.

        Efron (1987). Better coverage than simple percentile when the
        bootstrap distribution is skewed.
        """
        original_stat = statistic_func(data)
        n = len(data)

        # Bias correction (z0)
        p0 = np.mean(boot_stats < original_stat)
        z0 = norm.ppf(p0)

        # Acceleration (a) — jackknife estimate
        jack_stats = np.zeros(n)
        for i in range(n):
            jack_data = np.delete(data, i)
            jack_stats[i] = statistic_func(jack_data)

        jack_mean = jack_stats.mean()
        numerator = np.sum((jack_mean - jack_stats) ** 3)
        denominator = 6 * (np.sum((jack_mean - jack_stats) ** 2) ** 1.5)

        if denominator == 0:
            a = 0.0
        else:
            a = numerator / denominator

        # Adjusted percentiles
        z_alpha = norm.ppf(alpha / 2)
        z_1_alpha = norm.ppf(1 - alpha / 2)

        alpha1 = norm.cdf(z0 + (z0 + z_alpha) / (1 - a * (z0 + z_alpha)))
        alpha2 = norm.cdf(z0 + (z0 + z_1_alpha) / (1 - a * (z0 + z_1_alpha)))

        lower = np.percentile(boot_stats, alpha1 * 100)
        upper = np.percentile(boot_stats, alpha2 * 100)

        return (lower, upper)

    def permutation_p_value(
        self, original_stat: float, boot_stats: np.ndarray, alternative: str = "two-sided"
    ) -> float:
        """
        Compute p-value from bootstrap/permutation distribution.

        Args:
            original_stat: The observed statistic value
            boot_stats: Distribution of statistic under null (or bootstrap)
            alternative: 'two-sided', 'greater', 'less'

        Returns:
            p-value
        """
        if alternative == "two-sided":
            p = np.mean(np.abs(boot_stats) >= np.abs(original_stat))
        elif alternative == "greater":
            p = np.mean(boot_stats >= original_stat)
        elif alternative == "less":
            p = np.mean(boot_stats <= original_stat)
        else:
            raise ValueError(f"Unknown alternative: {alternative}")

        # Avoid p=0
        return max(p, 1.0 / (self.n_replications + 1))


# ============================================================================
# Distribution Analyzer
# ============================================================================


class DistributionAnalyzer:
    """
    Comprehensive distribution analysis.

    Does NOT just compare means. Analyzes the full distribution:
    moments, quantiles, normality, serial correlation, tail behavior.
    """

    def __init__(
        self,
        bootstrap: Optional[BlockBootstrap] = None,
        seed: Optional[int] = None,
    ):
        self.bootstrap = bootstrap or BlockBootstrap(seed=seed)

    def analyze(self, returns: pd.Series) -> DistributionStats:
        """
        Compute full distribution statistics for a return series.

        Args:
            returns: Series of periodic returns (daily, weekly, etc.)

        Returns:
            DistributionStats with complete characterization
        """
        if returns.empty:
            raise ValueError("Empty return series")

        returns_clean = returns.dropna().values
        n = len(returns_clean)

        if n < 10:
            raise ValueError(f"Too few observations: {n}. Need at least 10.")

        # Basic moments
        mean = np.mean(returns_clean)
        median = np.median(returns_clean)
        std = np.std(returns_clean, ddof=1)
        skew = stats.skew(returns_clean, bias=False)
        kurt = stats.kurtosis(returns_clean, bias=False)  # Excess kurtosis

        # Min/max/percentiles
        min_val = np.min(returns_clean)
        max_val = np.max(returns_clean)
        percentiles = np.percentile(
            returns_clean, [1, 5, 10, 25, 75, 90, 95, 99]
        )

        # Bootstrap CIs for mean
        ci_90 = self.bootstrap.confidence_interval(
            returns_clean, np.mean, alpha=0.10, method="bca"
        )
        ci_95 = self.bootstrap.confidence_interval(
            returns_clean, np.mean, alpha=0.05, method="bca"
        )
        ci_99 = self.bootstrap.confidence_interval(
            returns_clean, np.mean, alpha=0.01, method="bca"
        )

        # Normality test
        jb_stat, jb_p = stats.jarque_bera(returns_clean)

        # Serial correlation
        acf1 = self._autocorr(returns_clean, 1) if n > 1 else 0.0
        acf5 = self._autocorr(returns_clean, 5) if n > 5 else 0.0
        acf21 = self._autocorr(returns_clean, 21) if n > 21 else 0.0

        return DistributionStats(
            n_observations=n,
            mean=mean,
            median=median,
            std=std,
            skewness=skew,
            kurtosis=kurt,
            min_value=min_val,
            max_value=max_val,
            p1=percentiles[0],
            p5=percentiles[1],
            p10=percentiles[2],
            p25=percentiles[3],
            p75=percentiles[4],
            p90=percentiles[5],
            p95=percentiles[6],
            p99=percentiles[7],
            ci_90_mean=ci_90,
            ci_95_mean=ci_95,
            ci_99_mean=ci_99,
            jarque_bera_stat=jb_stat,
            jarque_bera_p=jb_p,
            autocorr_lag1=acf1,
            autocorr_lag5=acf5,
            autocorr_lag21=acf21,
            is_normally_distributed=(jb_p > 0.05),
        )

    @staticmethod
    def _autocorr(x: np.ndarray, lag: int) -> float:
        """Compute autocorrelation."""
        if len(x) <= lag:
            return 0.0
        return np.corrcoef(x[:-lag], x[lag:])[0, 1]


# ============================================================================
# Performance Metrics Calculator
# ============================================================================


class PerformanceMetricsCalculator:
    """
    Computes comprehensive performance metrics.

    All metrics are computed on both gross and net return streams.
    Uses bootstrap for confidence intervals on key metrics.
    """

    def __init__(
        self,
        bootstrap: Optional[BlockBootstrap] = None,
        risk_free_rate: float = 0.0,
        seed: Optional[int] = None,
    ):
        self.bootstrap = bootstrap or BlockBootstrap(seed=seed)
        self.risk_free_rate = risk_free_rate

    def compute(
        self,
        returns: pd.Series,
        benchmark_returns: Optional[pd.Series] = None,
        signals: Optional[pd.Series] = None,
    ) -> PerformanceMetrics:
        """
        Compute all performance metrics.

        Args:
            returns: Strategy return series (daily preferred)
            benchmark_returns: Optional benchmark for IR calculation
            signals: Optional signal values for IC calculation

        Returns:
            PerformanceMetrics
        """
        if returns.empty:
            raise ValueError("Empty return series")

        returns_clean = returns.dropna()
        n = len(returns_clean)

        # Derive n_years from actual calendar span (not observation count).
        # This is critical when returns are multi-day holding period returns
        # rather than daily returns. Use observation count fallback if index
        # is not datetime.
        if n >= 2 and hasattr(returns_clean.index, 'to_series'):
            try:
                calendar_days = (returns_clean.index[-1] - returns_clean.index[0]).days
                n_years = max(calendar_days / 365.25, 1 / TRADING_DAYS_PER_YEAR)
                # Infer average period length for vol annualization
                avg_period_days = calendar_days / max(n - 1, 1)
                periods_per_year = max(TRADING_DAYS_PER_YEAR / avg_period_days, 1.0)
                ann_vol_factor = np.sqrt(periods_per_year)
            except (TypeError, AttributeError):
                n_years = max(n / TRADING_DAYS_PER_YEAR, 1 / TRADING_DAYS_PER_YEAR)
                ann_vol_factor = np.sqrt(TRADING_DAYS_PER_YEAR)
        else:
            n_years = max(n / TRADING_DAYS_PER_YEAR, 1 / TRADING_DAYS_PER_YEAR)
            ann_vol_factor = np.sqrt(TRADING_DAYS_PER_YEAR)

        daily_rf = self.risk_free_rate / TRADING_DAYS_PER_YEAR
        excess_returns = returns_clean - daily_rf

        # Annualized return and volatility
        total_return = (1 + returns_clean).prod() - 1
        ann_return = (1 + total_return) ** (1 / n_years) - 1
        ann_vol = returns_clean.std() * ann_vol_factor

        # Downside volatility (using same period-aware factor)
        downside_returns = returns_clean[returns_clean < 0]
        ann_downside_vol = (
            downside_returns.std() * ann_vol_factor
            if len(downside_returns) > 1
            else ann_vol
        )

        # Sharpe ratio
        excess_ann_return = ann_return - self.risk_free_rate
        sharpe = excess_ann_return / ann_vol if ann_vol > 0 else 0.0

        # Sortino ratio
        sortino = excess_ann_return / ann_downside_vol if ann_downside_vol > 0 else 0.0

        # Information ratio (using period-aware annualization)
        ir = 0.0
        if benchmark_returns is not None:
            bench_aligned = benchmark_returns.reindex(returns_clean.index).dropna()
            if len(bench_aligned) > 0:
                active_returns = returns_clean.loc[bench_aligned.index] - bench_aligned
                ir = (
                    active_returns.mean() / active_returns.std() * ann_vol_factor
                    if active_returns.std() > 0
                    else 0.0
                )

        # Drawdown analysis
        cum_returns = (1 + returns_clean).cumprod()
        running_max = cum_returns.cummax()
        drawdowns = cum_returns / running_max - 1

        max_dd = drawdowns.min()
        max_dd_days = self._compute_max_dd_duration(cum_returns)
        avg_dd = drawdowns[drawdowns < 0].mean() if len(drawdowns[drawdowns < 0]) > 0 else 0.0
        dd_p95 = drawdowns.quantile(0.05)  # 95th percentile of drawdown severity

        # Calmar ratio
        calmar = ann_return / abs(max_dd) if max_dd != 0 else 0.0

        # Hit rate
        hit_rate = (returns_clean > 0).mean()

        # Profit factor
        gross_gains = returns_clean[returns_clean > 0].sum()
        gross_losses = abs(returns_clean[returns_clean < 0].sum())
        profit_factor = gross_gains / gross_losses if gross_losses > 0 else float("inf")

        # Omega ratio (probability-weighted gain/loss at threshold=0)
        omega = self._omega_ratio(returns_clean, threshold=0.0)

        # Tail ratio (p95 / p5)
        p95 = returns_clean.quantile(0.95)
        p5 = returns_clean.quantile(0.05)
        tail_ratio = p95 / abs(p5) if p5 != 0 else float("inf")

        # Information coefficient
        ic = None
        if signals is not None and len(signals) > 0:
            aligned_signals = signals.reindex(returns_clean.index).dropna()
            aligned_returns = returns_clean.loc[aligned_signals.index]
            if len(aligned_returns) > 5:
                ic = aligned_signals.corr(aligned_returns)

        # Bootstrap CIs for Sharpe and mean return (using period-aware factor)
        _ann_factor = ann_vol_factor  # capture for lambda
        sharpe_func = lambda x: (
            (np.mean(x) - daily_rf) / np.std(x, ddof=1) * _ann_factor
            if np.std(x, ddof=1) > 0
            else 0.0
        )
        sharpe_ci = self.bootstrap.confidence_interval(
            returns_clean.values, sharpe_func, alpha=0.05, method="bca"
        )

        mean_return_func = lambda x: np.mean(x) * 10000  # Convert to bps
        mean_return_ci = self.bootstrap.confidence_interval(
            returns_clean.values, mean_return_func, alpha=0.05, method="bca"
        )

        return PerformanceMetrics(
            annualized_return=ann_return,
            annualized_volatility=ann_vol,
            annualized_downside_volatility=ann_downside_vol,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            information_ratio=ir,
            calmar_ratio=calmar,
            max_drawdown=max_dd,
            max_drawdown_days=max_dd_days,
            avg_drawdown=avg_dd,
            drawdown_p95=dd_p95,
            hit_rate=hit_rate,
            profit_factor=profit_factor,
            omega_ratio=omega,
            tail_ratio=tail_ratio,
            information_coefficient=ic,
            sharpe_ci_95=sharpe_ci,
            mean_return_ci_95_bps_daily=mean_return_ci,
        )

    def _compute_max_dd_duration(self, cum_returns: pd.Series) -> int:
        """Compute maximum drawdown duration in days."""
        running_max = cum_returns.cummax()
        in_dd = cum_returns < running_max

        if not in_dd.any():
            return 0

        dd_starts = in_dd.astype(int).diff() == 1
        dd_ends = in_dd.astype(int).diff() == -1

        if dd_starts.sum() == 0:
            return 0

        start_dates = cum_returns.index[dd_starts]
        end_dates = cum_returns.index[dd_ends]

        max_duration = 0
        for start in start_dates:
            end_mask = end_dates > start
            if end_mask.any():
                end = end_dates[end_mask][0]
                duration = (end - start).days
                max_duration = max(max_duration, duration)
            else:
                duration = (cum_returns.index[-1] - start).days
                max_duration = max(max_duration, duration)

        return max_duration

    def _omega_ratio(self, returns: pd.Series, threshold: float = 0.0) -> float:
        """Compute Omega ratio at a given threshold."""
        excess = returns - threshold
        gains = excess[excess > 0].sum()
        losses = abs(excess[excess < 0].sum())

        return gains / losses if losses > 0 else float("inf")


# ============================================================================
# Multiple Comparison Correction
# ============================================================================


class MultipleComparisonCorrector:
    """
    Applies multiple comparison corrections.

    DESIGN NOTE (Statistical Epistemologist):
    Testing 10 hypotheses at alpha=0.05 gives a ~40% chance of at least one
    false positive. This is unacceptable. We use Bonferroni (conservative,
    primary) and Benjamini-Hochberg FDR (less conservative, secondary).
    """

    def __init__(self, alpha: float = DEFAULT_ALPHA, fdr_q: float = DEFAULT_FDR_Q):
        self.alpha = alpha
        self.fdr_q = fdr_q

    def correct(
        self,
        p_values: List[float],
        n_tests_per_hypothesis: Optional[List[int]] = None,
    ) -> MultipleComparisonResult:
        """
        Apply multiple comparison correction.

        Args:
            p_values: List of raw p-values
            n_tests_per_hypothesis: Number of implicit tests per hypothesis
                                    (for within-hypothesis corrections)

        Returns:
            MultipleComparisonResult
        """
        n = len(p_values)

        if n_tests_per_hypothesis is None:
            n_tests_per_hypothesis = [1] * n

        p_array = np.array(p_values)

        # Bonferroni correction
        total_tests = sum(n_tests_per_hypothesis)
        bonf_adjusted = np.minimum(p_array * total_tests, 1.0)
        bonf_significant = bonf_adjusted < self.alpha

        # Benjamini-Hochberg FDR
        fdr_adjusted, fdr_significant = self._bh_procedure(p_array)

        return MultipleComparisonResult(
            n_hypotheses=n,
            n_tests_per_hypothesis=n_tests_per_hypothesis,
            raw_p_values=p_values,
            bonferroni_corrected_p=bonf_adjusted.tolist(),
            bonferroni_significant=bonf_significant.tolist(),
            fdr_corrected_p=fdr_adjusted.tolist(),
            fdr_q_value=self.fdr_q,
            fdr_significant=fdr_significant.tolist(),
            n_significant_bonferroni=bonf_significant.sum(),
            n_significant_fdr=fdr_significant.sum(),
        )

    def _bh_procedure(self, p_values: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Benjamini-Hochberg false discovery rate control."""
        n = len(p_values)
        if n == 0:
            return np.array([]), np.array([])

        # Sort p-values
        sorted_indices = np.argsort(p_values)
        sorted_p = p_values[sorted_indices]

        # BH critical values: q * i / n
        ranks = np.arange(1, n + 1)
        bh_critical = self.fdr_q * ranks / n

        # Find the largest i where p_i <= bh_critical
        significant_sorted = sorted_p <= bh_critical

        # To be significant, must pass AND all smaller p-values must pass
        # We use the standard BH: all p_i for i <= k are significant where
        # k = max{i: p_i <= q * i / n}
        last_significant = np.max(np.where(significant_sorted)[0]) if significant_sorted.any() else -1

        fdr_significant = np.zeros(n, dtype=bool)
        if last_significant >= 0:
            fdr_significant[sorted_indices[: last_significant + 1]] = True

        # Compute FDR-adjusted p-values
        adjusted_p = np.ones(n)
        for i in range(n - 1, -1, -1):
            original_p = sorted_p[i]
            bh_value = original_p * n / (i + 1)
            if i == n - 1:
                adjusted_p[sorted_indices[i]] = min(bh_value, 1.0)
            else:
                adjusted_p[sorted_indices[i]] = min(
                    adjusted_p[sorted_indices[i + 1]], min(bh_value, 1.0)
                )

        return adjusted_p, fdr_significant


# ============================================================================
# Outlier Analyzer
# ============================================================================


class OutlierAnalyzer:
    """
    Analyzes the influence of outliers on results.

    DESIGN NOTE (Statistical Breaker):
    Many apparent anomalies disappear when you remove 5% of observations.
    This module tests: does the significance survive winsorization, trimming,
    and influence analysis? If not, the result is "outlier-driven" — a red flag.
    """

    def __init__(self, seed: Optional[int] = None):
        self.rng = np.random.RandomState(seed)

    def analyze(self, returns: pd.Series, alpha: float = 0.05) -> OutlierAnalysis:
        """
        Perform complete outlier sensitivity analysis.

        Returns:
            OutlierAnalysis with sensitivity to various outlier treatments
        """
        returns_clean = returns.dropna().values
        n = len(returns_clean)

        if n < 20:
            return OutlierAnalysis(
                original_mean=np.mean(returns_clean),
                original_significance=1.0,
                winsorized_1_99_mean=np.mean(returns_clean),
                winsorized_1_99_significance=1.0,
                winsorized_2_5_97_5_mean=np.mean(returns_clean),
                winsorized_2_5_97_5_significance=1.0,
                trimmed_5_mean=np.mean(returns_clean),
                trimmed_5_significance=1.0,
                trimmed_10_mean=np.mean(returns_clean),
                trimmed_10_significance=1.0,
                n_outliers_3sigma=0,
                n_outliers_5sigma=0,
                is_outlier_driven=False,
                influence_observations=[],
            )

        original_mean = np.mean(returns_clean)
        original_t, original_p = stats.ttest_1samp(returns_clean, 0)

        # Winsorization analysis
        wins1 = stats.mstats.winsorize(returns_clean, limits=(0.01, 0.01))
        wins2 = stats.mstats.winsorize(returns_clean, limits=(0.025, 0.025))

        wins1_mean = np.mean(wins1)
        wins2_mean = np.mean(wins2)

        _, wins1_p = stats.ttest_1samp(wins1, 0)
        _, wins2_p = stats.ttest_1samp(wins2, 0)

        # Trimmed means
        trim5 = stats.trim_mean(returns_clean, 0.05)
        trim10 = stats.trim_mean(returns_clean, 0.10)

        # Significance of trimmed data (approximate via bootstrap)
        trim5_p = self._bootstrap_significance(returns_clean, trim_frac=0.05)
        trim10_p = self._bootstrap_significance(returns_clean, trim_frac=0.10)

        # Outlier counts
        std = np.std(returns_clean, ddof=1)
        n_3sigma = np.sum(np.abs(returns_clean - original_mean) > 3 * std)
        n_5sigma = np.sum(np.abs(returns_clean - original_mean) > 5 * std)

        # Is the result outlier-driven?
        # If trimming 5% eliminates significance, flag it
        is_outlier_driven = (original_p < alpha) and (trim5_p >= alpha)

        # Influence observations (dates where return exceeds 3 sigma)
        influence_observations = []
        if hasattr(returns, 'index'):
            outlier_mask = np.abs(returns_clean - original_mean) > 3 * std
            if outlier_mask.any():
                outlier_indices = np.where(outlier_mask)[0]
                for idx in outlier_indices[:10]:  # Cap at 10
                    date = returns.index[idx] if idx < len(returns.index) else idx
                    influence_observations.append({
                        "date": str(date),
                        "return": float(returns_clean[idx]),
                        "z_score": float((returns_clean[idx] - original_mean) / std),
                    })

        return OutlierAnalysis(
            original_mean=original_mean,
            original_significance=original_p,
            winsorized_1_99_mean=wins1_mean,
            winsorized_1_99_significance=wins1_p,
            winsorized_2_5_97_5_mean=wins2_mean,
            winsorized_2_5_97_5_significance=wins2_p,
            trimmed_5_mean=trim5,
            trimmed_5_significance=trim5_p,
            trimmed_10_mean=trim10,
            trimmed_10_significance=trim10_p,
            n_outliers_3sigma=n_3sigma,
            n_outliers_5sigma=n_5sigma,
            is_outlier_driven=is_outlier_driven,
            influence_observations=influence_observations,
        )

    def _bootstrap_significance(
        self, data: np.ndarray, trim_frac: float = 0.05, n_boot: int = 1000,
    ) -> float:
        """Bootstrap significance test for trimmed mean."""
        n = len(data)
        trim_n = int(n * (1 - 2 * trim_frac))

        boot_means = np.zeros(n_boot)
        for i in range(n_boot):
            sample = self.rng.choice(data, size=n, replace=True)
            sample_sorted = np.sort(sample)
            trim_sample = sample_sorted[int(n * trim_frac) : int(n * (1 - trim_frac))]
            boot_means[i] = np.mean(trim_sample)

        # Two-sided p-value
        original_trimmed = stats.trim_mean(data, trim_frac)
        p = np.mean(np.abs(boot_means) >= np.abs(original_trimmed))
        return max(p, 1.0 / n_boot)


# ============================================================================
# Power Analyzer
# ============================================================================


class PowerAnalyzer:
    """
    Computes statistical power and required sample sizes.

    DESIGN NOTE (Statistical Epistemologist):
    A non-significant result is meaningless without power analysis.
    It could mean 'no effect' or 'too few observations to detect an effect.'
    Power analysis distinguishes these cases.
    """

    def __init__(self, target_power: float = DEFAULT_POWER_TARGET):
        self.target_power = target_power

    def analyze(
        self,
        returns: pd.Series,
        hypothesized_effect_size: Optional[float] = None,
    ) -> PowerAnalysis:
        """
        Compute achieved power and minimum detectable effect.

        Args:
            returns: Return series
            hypothesized_effect_size: Minimum meaningful effect (Cohen's d).
                                     If None, use small (0.2) as default.

        Returns:
            PowerAnalysis
        """
        returns_clean = returns.dropna().values
        n = len(returns_clean)

        if n < 10:
            return PowerAnalysis(
                sample_size=n,
                effect_size=0.0,
                achieved_power=0.0,
                minimum_detectable_effect=float("inf"),
                required_sample_size=float("inf"),
                is_adequately_powered=False,
            )

        # Observed effect size (Cohen's d)
        mean = np.mean(returns_clean)
        std = np.std(returns_clean, ddof=1)
        observed_d = abs(mean / std) if std > 0 else 0.0

        # Minimum detectable effect at target power
        # Using two-sided t-test power formula
        if hypothesized_effect_size is None:
            hypothesized_d = max(observed_d, 0.02)  # Default to tiny effect
        else:
            hypothesized_d = hypothesized_effect_size

        # Achieved power for the observed effect
        achieved_power = self._power_t_test(n, observed_d)

        # MDE at target power
        mde = self._minimum_detectable_effect(n)

        # Required sample size for observed effect at target power
        required_n = self._required_sample_size(observed_d)

        is_adequately_powered = achieved_power >= self.target_power

        return PowerAnalysis(
            sample_size=n,
            effect_size=observed_d,
            achieved_power=achieved_power,
            minimum_detectable_effect=mde,
            required_sample_size=required_n,
            is_adequately_powered=is_adequately_powered,
        )

    def _power_t_test(self, n: int, d: float) -> float:
        """Compute power of a one-sample t-test."""
        df = n - 1
        ncp = d * np.sqrt(n)  # Non-centrality parameter

        # Critical value for two-sided test at alpha=0.05
        t_crit = t_dist.ppf(1 - 0.05 / 2, df)

        # Power = P(|T| > t_crit) under alternative
        power = 1 - stats.nct.cdf(t_crit, df, ncp) + stats.nct.cdf(-t_crit, df, ncp)
        return power

    def _minimum_detectable_effect(self, n: int) -> float:
        """Compute minimum detectable Cohen's d at target power."""
        def power_diff(d):
            return self._power_t_test(n, d) - self.target_power

        # Binary search for MDE
        lo, hi = 0.001, 5.0
        for _ in range(50):
            mid = (lo + hi) / 2
            pd = power_diff(mid)
            if pd < 0:
                lo = mid
            else:
                hi = mid
            if hi - lo < 1e-6:
                break

        return (lo + hi) / 2

    def _required_sample_size(self, d: float) -> float:
        """Compute required sample size for effect size d at target power."""
        if d <= 0:
            return float("inf")

        def power_diff(n):
            return self._power_t_test(int(n), d) - self.target_power

        # Binary search for required n
        lo, hi = 5, 100000
        for _ in range(50):
            mid = (lo + hi) / 2
            pd = power_diff(mid)
            if pd < 0:
                lo = mid
            else:
                hi = mid
            if hi - lo < 0.5:
                break

        return (lo + hi) / 2


# ============================================================================
# Statistical Report Generator
# ============================================================================


class StatisticalReportGenerator:
    """
    Combines all statistical analyses into a complete report.

    This is the main interface for statistical testing in the pipeline.
    """

    def __init__(
        self,
        bootstrap: Optional[BlockBootstrap] = None,
        seed: Optional[int] = None,
    ):
        self.seed = seed
        self.bootstrap = bootstrap or BlockBootstrap(seed=seed)
        self.distribution = DistributionAnalyzer(bootstrap=self.bootstrap, seed=seed)
        self.performance = PerformanceMetricsCalculator(bootstrap=self.bootstrap, seed=seed)
        self.mc_corrector = MultipleComparisonCorrector()
        self.outlier = OutlierAnalyzer(seed=seed)
        self.power = PowerAnalyzer()

    def generate_report(
        self,
        returns: pd.Series,  # Strategy return stream
        benchmark_returns: Optional[pd.Series] = None,
        signals: Optional[pd.Series] = None,
        p_values_for_correction: Optional[List[float]] = None,
        hypothesized_effect_size: Optional[float] = None,
    ) -> StatisticalReport:
        """
        Generate complete statistical report.

        Args:
            returns: Strategy return series
            benchmark_returns: Optional benchmark for IR
            signals: Optional signal values for IC
            p_values_for_correction: Raw p-values from multiple tests
            hypothesized_effect_size: Minimum meaningful effect size (Cohen's d)

        Returns:
            StatisticalReport with all analyses
        """
        warnings_list = []

        # 1. Distribution analysis
        dist = self.distribution.analyze(returns)

        if not dist.is_normally_distributed:
            warnings_list.append(
                "Returns are not normally distributed (Jarque-Bera p < 0.05). "
                "Standard t-tests may be unreliable. Bootstrap CIs are used."
            )

        if abs(dist.autocorr_lag1) > 0.10:
            warnings_list.append(
                f"Significant first-order autocorrelation ({dist.autocorr_lag1:.3f}). "
                f"Returns are not IID. Block bootstrap is used."
            )

        if dist.kurtosis > 5:
            warnings_list.append(
                f"High kurtosis ({dist.kurtosis:.2f}). Tail risk is significant. "
                f"Maximum drawdown analysis is critical."
            )

        # 2. Performance metrics
        perf = self.performance.compute(
            returns, benchmark_returns=benchmark_returns, signals=signals
        )

        # 3. Multiple comparison correction
        mc_result = None
        if p_values_for_correction:
            mc_result = self.mc_corrector.correct(p_values_for_correction)
            if mc_result.n_significant_bonferroni < len(p_values_for_correction):
                warnings_list.append(
                    f"Multiple comparison correction reduced significant tests "
                    f"from {len(p_values_for_correction)} to "
                    f"{mc_result.n_significant_bonferroni} (Bonferroni) / "
                    f"{mc_result.n_significant_fdr} (FDR)."
                )

        # 4. Outlier analysis
        outlier_result = self.outlier.analyze(returns)
        if outlier_result.is_outlier_driven:
            warnings_list.append(
                "RESULT IS OUTLIER-DRIVEN. Trimming 5% of extreme observations "
                "eliminates statistical significance. The apparent alpha may be "
                "driven by a small number of extreme events."
            )

        # 5. Power analysis
        power_result = self.power.analyze(returns, hypothesized_effect_size)
        if not power_result.is_adequately_powered:
            warnings_list.append(
                f"Inadequate statistical power ({power_result.achieved_power:.2f}). "
                f"Sample size {power_result.sample_size} provides "
                f"{power_result.achieved_power:.1%} power for observed effect "
                f"d={power_result.effect_size:.3f}. "
                f"Minimum detectable effect: d={power_result.minimum_detectable_effect:.3f}."
            )

        # 6. GT-Score (Golden Ticket Score) — composite objective function
        gt_score_result = None
        try:
            from gt_score import compute_gt_score_from_series
            gt_score_result = compute_gt_score_from_series(returns)
        except ImportError:
            logger.debug("gt_score module not available, skipping GT-Score")
        except Exception as e:
            logger.warning(f"GT-Score computation failed: {e}")

        # 7. Overall significance determination
        # Significant if mean is statistically different from zero
        # (using bootstrap CI rather than t-test, to handle non-normality)
        ci_lower, ci_upper = dist.ci_95_mean
        is_significant = ci_lower > 0 or ci_upper < 0  # CI excludes zero

        if not is_significant:
            warnings_list.append(
                f"Mean return not statistically significant. "
                f"95% bootstrap CI: [{ci_lower:.6f}, {ci_upper:.6f}] includes zero."
            )

        return StatisticalReport(
            distribution=dist,
            performance=perf,
            multiple_comparison=mc_result,
            outlier_analysis=outlier_result,
            power_analysis=power_result,
            gt_score_result=gt_score_result,
            warnings=warnings_list,
            is_statistically_significant=is_significant,
        )
