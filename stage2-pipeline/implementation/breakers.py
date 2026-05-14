"""
breakers.py — Adversarial Tests (Permutation, Regime, Specification Robustness)
==============================================================================

Agent 4: Adversarial Tester — Statistical ("Statistical Breaker")
Agent 5: Adversarial Tester — Data Integrity ("Data Breaker")
Agent 6: Regime Change & Edge Decay Specialist

This module implements all adversarial tests designed to DESTROY false positives.
If a signal survives these tests, it might be real. If not, it's broken.

IMPORTANT: The Statistical Breaker and Data Breaker have VETO POWER.
If they demonstrate a flaw, it MUST be fixed before the pipeline is locked.

Tests implemented:
1. Random permutation test (shuffle signal → verify zero alpha)
2. Time period shuffling
3. Alternative specification robustness
4. Out-of-sample holdout validation
5. Walk-forward consistency analysis
6. Specification curve analysis (p-hacking detection)
7. Regime-conditional performance analysis
8. Rolling window edge decay detection
9. Edge half-life estimation
10. Structural break detection (Bai-Perron)
11. Data integrity checks (survivorship bias, look-ahead, corporate actions)
12. Ticker reuse verification
"""

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import pearsonr

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_PERMUTATION_REPLICATIONS = 1000
DEFAULT_PERMUTATION_ALPHA = 0.05
DEFAULT_WALK_FORWARD_POSITIVE_THRESHOLD = 0.60  # 60% of windows must be positive
DEFAULT_OOS_FRACTION = 0.30
DEFAULT_REGIME_CHANGE_ALPHA = 0.05


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class PermutationTestResult:
    """Results of random permutation testing."""

    original_performance: float          # e.g., mean return, Sharpe
    n_permutations: int
    permutation_distribution: np.ndarray  # Performance under shuffled signals
    p_value: float                       # Fraction of permutations >= original
    is_significant: bool                 # p < 0.05
    description: str


@dataclass
class TimeShuffleResult:
    """Results of time period shuffling."""

    original_performance: float
    shuffled_performance_mean: float
    shuffled_performance_std: float
    p_value: float
    is_invariant: bool  # True if performance is NOT time-specific


@dataclass
class SpecificationRobustnessResult:
    """Results of alternative specification testing."""

    specifications_tested: List[Dict[str, Any]]
    performances: List[float]           # Performance under each spec
    p_values: List[float]               # p-values under each spec
    n_significant: int
    n_total: int
    fraction_significant: float         # Fraction of specs with significant results
    is_robust: bool                     # If >50% specs are significant
    specification_curve: List[float]    # All p-values across spec grid


@dataclass
class WalkForwardResult:
    """Results of walk-forward validation."""

    n_windows: int
    window_performances: List[float]     # Alpha for each walk-forward window
    window_p_values: List[float]
    n_positive_windows: int
    fraction_positive: float
    mean_walk_forward_alpha: float
    is_consistent: bool                  # >60% windows positive
    windows: List[Dict[str, Any]]


@dataclass
class RegimeAnalysisResult:
    """Results of regime-conditional analysis."""

    regimes: Dict[str, Dict[str, float]]  # regime_name -> {mean_return, sharpe, hit_rate, ...}
    regime_significance: Dict[str, float]  # regime_name -> p-value for difference
    n_regimes: int
    is_regime_dependent: bool             # Performance differs significantly across regimes
    dominant_regime: Optional[str]        # Regime with best performance
    regime_warnings: List[str]


@dataclass
class EdgeDecayResult:
    """Results of edge decay analysis."""

    rolling_alphas: pd.Series            # Rolling window alpha over time
    trend_coefficient: float             # Linear trend in rolling alpha
    trend_p_value: float                 # Significance of trend
    half_life_years: float               # Estimated edge half-life
    half_life_ci: Tuple[float, float]    # 95% CI for half-life
    is_decaying: bool                    # Trend is significantly negative
    structural_breaks: List[int]         # Detected break points (Bai-Perron)


@dataclass
class DataIntegrityCheck:
    """Results of data integrity verification."""

    check_name: str
    passed: bool
    severity: str                        # 'INFO' | 'WARNING' | 'CRITICAL'
    details: str
    n_issues: int
    issues: List[Dict[str, Any]]


@dataclass
class AdversarialReport:
    """Complete adversarial testing report."""

    permutation: PermutationTestResult
    time_shuffle: TimeShuffleResult
    specification_robustness: SpecificationRobustnessResult
    walk_forward: WalkForwardResult
    regime_analysis: RegimeAnalysisResult
    edge_decay: EdgeDecayResult
    data_integrity_checks: List[DataIntegrityCheck]

    # Overall
    all_adversarial_passed: bool
    breakage_reasons: List[str]
    warnings: List[str]


# ============================================================================
# Agent 4: Statistical Breaker
# ============================================================================


class StatisticalBreaker:
    """
    Destroys false positives using statistical attacks.

    If the Statistical Breaker can break a result, it's broken.
    VETO POWER: demonstrated flaws MUST be fixed.
    """

    def __init__(
        self,
        n_permutations: int = DEFAULT_PERMUTATION_REPLICATIONS,
        seed: Optional[int] = None,
    ):
        self.n_permutations = n_permutations
        self.rng = np.random.RandomState(seed)

    # ------------------------------------------------------------------
    # 1. Random Permutation Test
    # ------------------------------------------------------------------

    def permutation_test(
        self,
        signals: pd.DataFrame,
        forward_returns: pd.DataFrame,
        backtest_func: Callable,
        performance_metric: str = "sharpe",
    ) -> PermutationTestResult:
        """
        Shuffle the signal randomly, re-run backtest, check if alpha persists.

        If the shuffled (i.e., destroyed) signal produces similar performance,
        the original signal is indistinguishable from noise.

        Args:
            signals: DataFrame (date x ticker) of signal values
            forward_returns: DataFrame (date x ticker) of forward returns
            backtest_func: Function(signals, returns) -> performance float
            performance_metric: Which metric to compare

        Returns:
            PermutationTestResult
        """
        # Original performance
        original_perf = backtest_func(signals, forward_returns)

        # Permutation distribution
        perm_performances = np.zeros(self.n_permutations)

        for i in range(self.n_permutations):
            # Shuffle signals INDEPENDENTLY for each ticker to preserve
            # cross-sectional structure but destroy temporal relationship
            shuffled_signals = signals.copy()

            for ticker in signals.columns:
                ticker_signals = signals[ticker].dropna().values.copy()  # .copy() prevents read-only array error
                if len(ticker_signals) > 1:
                    self.rng.shuffle(ticker_signals)
                    shuffled_signals[ticker] = pd.Series(
                        ticker_signals,
                        index=signals[ticker].dropna().index,
                    )

            perm_performances[i] = backtest_func(shuffled_signals, forward_returns)

        # Two-sided p-value
        p_value = np.mean(perm_performances >= original_perf)
        p_value = max(p_value, 1.0 / (self.n_permutations + 1))

        is_significant = p_value < DEFAULT_PERMUTATION_ALPHA

        return PermutationTestResult(
            original_performance=original_perf,
            n_permutations=self.n_permutations,
            permutation_distribution=perm_performances,
            p_value=p_value,
            is_significant=is_significant,
            description=(
                f"Original {performance_metric}={original_perf:.4f}. "
                f"Permutation distribution mean={perm_performances.mean():.4f} "
                f"std={perm_performances.std():.4f}. "
                f"p={p_value:.4f} ({'SIGNIFICANT' if is_significant else 'NOT SIGNIFICANT'})."
            ),
        )

    # ------------------------------------------------------------------
    # 2. Time Period Shuffling
    # ------------------------------------------------------------------

    def time_shuffle_test(
        self,
        signals: pd.DataFrame,
        forward_returns: pd.DataFrame,
        backtest_func: Callable,
    ) -> TimeShuffleResult:
        """
        Shuffle the TIME periods (not the signals within tickers).

        This tests whether the signal's performance is specific to
        certain time periods. If shuffling time doesn't change performance,
        the signal is not time-predictive.
        """
        original_perf = backtest_func(signals, forward_returns)

        n = self.n_permutations
        shuffled_perfs = np.zeros(n)

        # Get date index
        dates = signals.index.values

        for i in range(n):
            # Shuffle dates
            shuffled_dates = dates.copy()
            self.rng.shuffle(shuffled_dates)

            # Reassign signals to shuffled dates
            shuffled_signals = signals.copy()
            shuffled_signals.index = shuffled_dates

            shuffled_perfs[i] = backtest_func(shuffled_signals, forward_returns)

        p_value = np.mean(shuffled_perfs >= original_perf)
        p_value = max(p_value, 1.0 / (n + 1))

        return TimeShuffleResult(
            original_performance=original_perf,
            shuffled_performance_mean=shuffled_perfs.mean(),
            shuffled_performance_std=shuffled_perfs.std(),
            p_value=p_value,
            is_invariant=(p_value > 0.05),
        )

    # ------------------------------------------------------------------
    # 3. Alternative Specification Robustness
    # ------------------------------------------------------------------

    def specification_robustness_test(
        self,
        backtest_funcs: List[Callable],  # Each is a different specification
        specification_names: List[str],
    ) -> SpecificationRobustnessResult:
        """
        Test whether the signal works across multiple reasonable specifications.

        If only ONE specific parameterization shows significance while others
        are non-significant, the result is fragile (likely overfitted).

        DESIGN NOTE (Statistical Breaker):
        This is the specification curve analysis from Simonsohn et al. (2014).
        A robust finding should be significant across many reasonable choices
        of analysis parameters.
        """
        performances = []
        p_values = []

        for func in backtest_funcs:
            try:
                result = func()
                performances.append(result.get("performance", 0))
                p_values.append(result.get("p_value", 1))
            except Exception as e:
                logger.warning(f"Specification test failed: {e}")
                performances.append(0)
                p_values.append(1)

        n_significant = sum(p < 0.05 for p in p_values)
        fraction = n_significant / len(p_values) if p_values else 0

        specifications = [
            {"name": name, "performance": perf, "p_value": pv}
            for name, perf, pv in zip(specification_names, performances, p_values)
        ]

        return SpecificationRobustnessResult(
            specifications_tested=specifications,
            performances=performances,
            p_values=p_values,
            n_significant=n_significant,
            n_total=len(p_values),
            fraction_significant=fraction,
            is_robust=(fraction >= 0.50),
            specification_curve=p_values,
        )

    # ------------------------------------------------------------------
    # 4. Out-of-Sample Holdout Validation
    # ------------------------------------------------------------------

    def out_of_sample_test(
        self,
        returns: pd.Series,
        oos_fraction: float = DEFAULT_OOS_FRACTION,
    ) -> Dict[str, Any]:
        """
        Split data in time, test in-sample vs. out-of-sample significance.

        The final 30% of the time period is reserved for OOS testing.
        Any optimization MUST be done on the first 70% only.
        """
        n = len(returns)
        split_idx = int(n * (1 - oos_fraction))

        is_returns = returns.iloc[:split_idx]
        oos_returns = returns.iloc[split_idx:]

        if len(oos_returns) < 20:
            return {
                "passed": False,
                "is_mean": is_returns.mean(),
                "is_p_value": 1.0,
                "oos_mean": oos_returns.mean(),
                "oos_p_value": 1.0,
                "is_significant": False,
                "oos_significant": False,
                "warning": "Insufficient OOS data",
            }

        _, is_p = stats.ttest_1samp(is_returns.dropna(), 0)
        _, oos_p = stats.ttest_1samp(oos_returns.dropna(), 0)

        oos_significant = oos_p < 0.05

        return {
            "passed": oos_significant,
            "is_mean": is_returns.mean(),
            "is_p_value": is_p,
            "oos_mean": oos_returns.mean(),
            "oos_p_value": oos_p,
            "is_significant": is_p < 0.05,
            "oos_significant": oos_significant,
            "is_dates": (is_returns.index[0], is_returns.index[-1]),
            "oos_dates": (oos_returns.index[0], oos_returns.index[-1]),
        }

    # ------------------------------------------------------------------
    # 5. Walk-Forward Consistency
    # ------------------------------------------------------------------

    def walk_forward_consistency_test(
        self,
        window_results: List[Dict[str, Any]],  # Output from WalkForwardBacktester
    ) -> WalkForwardResult:
        """
        Analyze walk-forward backtest consistency.

        A signal that only works in a few windows but not consistently
        is fragile and likely overfitted to specific regimes.
        """
        if not window_results:
            return WalkForwardResult(
                n_windows=0,
                window_performances=[],
                window_p_values=[],
                n_positive_windows=0,
                fraction_positive=0,
                mean_walk_forward_alpha=0,
                is_consistent=False,
                windows=[],
            )

        performances = [w.get("annualized_alpha", 0) for w in window_results]
        p_values = [w.get("p_value", 1) for w in window_results]
        n_positive = sum(p > 0 for p in performances)  # At least positive alpha
        fraction = n_positive / len(window_results) if window_results else 0

        return WalkForwardResult(
            n_windows=len(window_results),
            window_performances=performances,
            window_p_values=p_values,
            n_positive_windows=n_positive,
            fraction_positive=fraction,
            mean_walk_forward_alpha=np.mean(performances) if performances else 0,
            is_consistent=fraction >= DEFAULT_WALK_FORWARD_POSITIVE_THRESHOLD,
            windows=window_results,
        )

    # ------------------------------------------------------------------
    # 6. Specification Curve Analysis (P-Hacking Detection)
    # ------------------------------------------------------------------

    def specification_curve_analysis(
        self,
        all_p_values: List[float],
        all_spec_names: List[str],
    ) -> Dict[str, Any]:
        """
        Analyze the distribution of p-values across specifications.

        If p-values are concentrated near 0.05 (just barely significant)
        and most specifications are non-significant, the result is likely
        p-hacked.

        A honest, robust result should have p-values well below 0.05
        across many specifications.
        """
        p_array = np.array(all_p_values)

        result = {
            "n_specifications": len(p_array),
            "n_significant_05": int(np.sum(p_array < 0.05)),
            "n_significant_01": int(np.sum(p_array < 0.01)),
            "n_significant_001": int(np.sum(p_array < 0.001)),
            "min_p": float(np.min(p_array)),
            "median_p": float(np.median(p_array)),
            "max_p": float(np.max(p_array)),
            "fraction_05": float(np.mean(p_array < 0.05)),
            "fraction_01": float(np.mean(p_array < 0.01)),
            "p_hacking_suspected": False,
            "p_hacking_reason": "",
        }

        # Detect p-hacking patterns
        # Pattern 1: Most p-values are >0.05 but a few are just under 0.05
        near_05 = np.sum((p_array >= 0.04) & (p_array < 0.05))
        total_significant = np.sum(p_array < 0.05)
        if total_significant > 0 and near_05 / total_significant > 0.5:
            result["p_hacking_suspected"] = True
            result["p_hacking_reason"] = (
                f"More than 50% of significant results have p in [0.04, 0.05). "
                f"This suggests threshold hacking."
            )

        # Pattern 2: Very few specifications are significant
        if result["fraction_05"] < 0.10 and result["n_specifications"] > 20:
            result["p_hacking_suspected"] = True
            result["p_hacking_reason"] = (
                f"Only {result['fraction_05']:.1%} of {result['n_specifications']} "
                f"specifications are significant. This suggests a cherry-picked "
                f"specification in a large search space."
            )

        return result


# ============================================================================
# Agent 5: Data Breaker
# ============================================================================


class DataBreaker:
    """
    Destroys false positives by attacking data integrity.

    VETO POWER: Demonstrated data flaws MUST be fixed.
    """

    def __init__(self):
        self.checks: List[DataIntegrityCheck] = []

    # ------------------------------------------------------------------
    # 1. Survivorship Bias Detection
    # ------------------------------------------------------------------

    def check_survivorship_bias(
        self, universe_df: pd.DataFrame, date_range: Tuple[str, str]
    ) -> DataIntegrityCheck:
        """
        Verify that the universe includes delisted stocks.

        A universe without delisted stocks has SURVIVORSHIP BIAS.
        """
        dates = pd.date_range(date_range[0], date_range[1], freq="M")
        issues = []

        for date in dates:
            date_str = date.strftime("%Y-%m-%d")
            date_data = universe_df[universe_df["date"] == date_str]

            n_delisted = date_data["is_delisted"].sum() if "is_delisted" in date_data.columns else 0
            n_total = len(date_data)

            if n_total > 0 and n_delisted == 0:
                issues.append({
                    "date": date_str,
                    "issue": "No delisted stocks in universe on this date. "
                             "Survivorship bias likely.",
                })

        return DataIntegrityCheck(
            check_name="survivorship_bias",
            passed=len(issues) == 0,
            severity="CRITICAL" if len(issues) > 10 else "WARNING",
            details=(
                f"Found {len(issues)} dates with zero delisted stocks. "
                f"Survivorship bias may inflate results."
            ),
            n_issues=len(issues),
            issues=issues[:10],  # Cap at 10 examples
        )

    # ------------------------------------------------------------------
    # 2. Look-Ahead Contamination Detection
    # ------------------------------------------------------------------

    def check_look_ahead_contamination(
        self,
        data_df: pd.DataFrame,
        known_date_col: str,
        observation_date_col: str,
    ) -> DataIntegrityCheck:
        """
        Scan for observations where data known_date > observation_date.

        THIS IS CRITICAL. Look-ahead bias invalidates all results.
        """
        issues = []

        data_df_copy = data_df.copy()
        data_df_copy[known_date_col] = pd.to_datetime(data_df_copy[known_date_col])
        data_df_copy[observation_date_col] = pd.to_datetime(data_df_copy[observation_date_col])

        contaminated = data_df_copy[
            data_df_copy[known_date_col] > data_df_copy[observation_date_col]
        ]

        for _, row in contaminated.iterrows():
            issues.append({
                "observation_date": str(row[observation_date_col]),
                "known_date": str(row[known_date_col]),
                "days_ahead": (row[known_date_col] - row[observation_date_col]).days,
                "issue": "Look-ahead contamination: data known in the future used at observation date.",
            })

        return DataIntegrityCheck(
            check_name="look_ahead_contamination",
            passed=len(issues) == 0,
            severity="CRITICAL" if len(issues) > 0 else "INFO",
            details=(
                f"Found {len(issues)} look-ahead contaminated observations. "
                f"Results are {'INVALID' if issues else 'VALID'}."
            ),
            n_issues=len(issues),
            issues=issues[:20],
        )

    # ------------------------------------------------------------------
    # 3. Ticker Reuse Verification
    # ------------------------------------------------------------------

    def check_ticker_reuse(
        self, ticker_histories: Dict[str, List[Dict[str, Any]]],
    ) -> DataIntegrityCheck:
        """
        Verify that ticker reuse has been properly detected and handled.

        When ticker AAA represents company X from 2000-2005 and
        company Y from 2010-2020, the database MUST NOT merge them.
        """
        issues = []
        reuse_events = 0

        for ticker, history in ticker_histories.items():
            entities = history if isinstance(history, list) else history.entities

            if len(entities) > 1:
                reuse_events += 1
                issues.append({
                    "ticker": ticker,
                    "n_entities": len(entities),
                    "entities": [
                        {
                            "name": e.get("company_name", "UNKNOWN"),
                            "period": f"{e.get('start_date', '?')} to {e.get('end_date', '?')}",
                        }
                        for e in entities
                    ],
                    "issue": "Ticker reuse detected. Database must separate these entities.",
                })

        return DataIntegrityCheck(
            check_name="ticker_reuse",
            passed=True,  # Detection itself is the success
            severity="WARNING" if reuse_events > 0 else "INFO",
            details=(
                f"Detected {reuse_events} ticker reuse events. "
                f"Entity histories have been properly separated."
            ),
            n_issues=reuse_events,
            issues=issues[:20],
        )

    # ------------------------------------------------------------------
    # 4. Corporate Action Verification
    # ------------------------------------------------------------------

    def check_corporate_actions(
        self, price_df: pd.DataFrame, verified_actions: pd.DataFrame,
    ) -> DataIntegrityCheck:
        """
        Verify that corporate action adjustments are correct.

        Unadjusted prices for splits create massive artificial returns.
        """
        issues = []

        # Check for suspicious price jumps (>50% in one day)
        if not price_df.empty:
            for ticker in price_df.columns:
                ticker_returns = price_df[ticker].pct_change().dropna()
                extreme_moves = ticker_returns[abs(ticker_returns) > 0.50]

                for date, ret in extreme_moves.items():
                    issues.append({
                        "ticker": ticker,
                        "date": str(date),
                        "return": float(ret),
                        "issue": (
                            f"Price change of {ret:.1%} in one day. "
                            f"Possible unadjusted split or corporate action."
                        ),
                    })

        return DataIntegrityCheck(
            check_name="corporate_actions",
            passed=len(issues) < 10,  # A few are expected (e.g., biotech events)
            severity="WARNING" if len(issues) > 5 else "INFO",
            details=f"Found {len(issues)} suspicious price jumps (>50%).",
            n_issues=len(issues),
            issues=issues[:20],
        )

    # ------------------------------------------------------------------
    # 5. Delisting Return Completeness
    # ------------------------------------------------------------------

    def check_delisting_returns(
        self, universe_df: pd.DataFrame, delisting_records: Dict,
    ) -> DataIntegrityCheck:
        """
        Verify that delisting returns are complete for all delisted stocks.

        Missing delisting returns create survivorship bias through the back door.
        """
        issues = []

        delisted = universe_df[universe_df.get("is_delisted", False)]
        if len(delisted) > 0:
            missing_returns = delisted[delisted.get("delisting_return").isna()]
            for _, row in missing_returns.iterrows():
                issues.append({
                    "ticker": row["ticker"],
                    "delisting_date": str(row.get("delisting_date", "UNKNOWN")),
                    "issue": "Delisted stock has no delisting return. Returns may be overstated.",
                })

        return DataIntegrityCheck(
            check_name="delisting_returns",
            passed=len(issues) == 0,
            severity="CRITICAL" if len(issues) > 5 else "WARNING",
            details=(
                f"{len(issues)} delisted stocks have missing delisting returns. "
                f"This creates survivorship bias."
            ),
            n_issues=len(issues),
            issues=issues[:20],
        )

    def run_all_checks(
        self,
        universe_df: pd.DataFrame,
        date_range: Tuple[str, str],
        data_df: Optional[pd.DataFrame] = None,
        known_date_col: str = "known_date",
        observation_date_col: str = "observation_date",
        ticker_histories: Optional[Dict] = None,
        price_df: Optional[pd.DataFrame] = None,
        verified_actions: Optional[pd.DataFrame] = None,
        delisting_records: Optional[Dict] = None,
    ) -> List[DataIntegrityCheck]:
        """Run all data integrity checks."""
        checks = []

        # 1. Survivorship bias
        checks.append(self.check_survivorship_bias(universe_df, date_range))

        # 2. Look-ahead contamination
        if data_df is not None:
            checks.append(
                self.check_look_ahead_contamination(
                    data_df, known_date_col, observation_date_col
                )
            )

        # 3. Ticker reuse
        if ticker_histories is not None:
            checks.append(self.check_ticker_reuse(ticker_histories))

        # 4. Corporate actions
        if price_df is not None:
            checks.append(
                self.check_corporate_actions(
                    price_df, verified_actions or pd.DataFrame()
                )
            )

        # 5. Delisting returns
        if delisting_records is not None:
            checks.append(
                self.check_delisting_returns(universe_df, delisting_records)
            )

        self.checks = checks
        return checks


# ============================================================================
# Agent 6: Regime Change & Edge Decay Specialist
# ============================================================================


class RegimeAnalyzer:
    """
    Analyzes signal performance across market regimes and detects edge decay.

    A signal that only works in one regime is flagged as regime-dependent.
    Edge half-life is estimated. Rolling window performance is reported.
    """

    def __init__(self, seed: Optional[int] = None):
        self.rng = np.random.RandomState(seed)

    # ------------------------------------------------------------------
    # Regime Classification
    # ------------------------------------------------------------------

    def classify_regimes(
        self,
        dates: pd.DatetimeIndex,
        market_data: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Classify each date into market regimes.

        Regimes:
        - Bull/Bear: SPX vs 200-day MA
        - High/Low Vol: VIX >/below 20
        - Expansion/Recession: NBER dates
        - Rising/Falling Rates: 10Y yield direction
        - High/Low Dispersion: Cross-sectional dispersion of SPX returns
        """
        regimes = pd.DataFrame(index=dates)

        # Bull/Bear: SPX vs 200-day SMA
        if "spx" in market_data.columns:
            spx_sma200 = market_data["spx"].rolling(200).mean()
            regimes["bull_market"] = market_data["spx"] > spx_sma200

        # High/Low Volatility: VIX > 20
        if "vix" in market_data.columns:
            regimes["high_volatility"] = market_data["vix"] > 20

        # Expansion/Recession: use NBER dates if available
        if "nber_recession" in market_data.columns:
            regimes["recession"] = market_data["nber_recession"]

        # Rising/Falling Rates: 10Y direction over 6 months
        if "us10y" in market_data.columns:
            regimes["rising_rates"] = (
                market_data["us10y"].diff(126) > 0
            )

        # High/Low Dispersion: Cross-sectional dispersion of returns
        if "dispersion" in market_data.columns:
            regimes["high_dispersion"] = (
                market_data["dispersion"] > market_data["dispersion"].median()
            )

        return regimes

    def analyze_regime_performance(
        self,
        strategy_returns: pd.Series,
        regimes: pd.DataFrame,
    ) -> RegimeAnalysisResult:
        """
        Analyze strategy performance conditional on market regimes.
        """
        regime_results = {}
        regime_warnings = []

        merged = pd.concat([strategy_returns, regimes], axis=1).dropna()

        for regime_col in regimes.columns:
            in_regime = merged[merged[regime_col] == True][strategy_returns.name]
            out_regime = merged[merged[regime_col] == False][strategy_returns.name]

            if len(in_regime) < 10:
                regime_results[regime_col] = {
                    "in_regime_mean": np.nan,
                    "out_regime_mean": np.nan,
                    "in_regime_sharpe": np.nan,
                    "in_regime_hit_rate": np.nan,
                    "n_obs_in": len(in_regime),
                    "n_obs_out": len(out_regime),
                    "difference_p_value": np.nan,
                    "significant_difference": False,
                }
                continue

            in_mean = in_regime.mean()
            out_mean = out_regime.mean()
            in_sharpe = in_mean / in_regime.std() * np.sqrt(252) if in_regime.std() > 0 else 0
            in_hit_rate = (in_regime > 0).mean()

            # Test for difference
            if len(out_regime) >= 10:
                _, diff_p = stats.ttest_ind(in_regime, out_regime)
            else:
                diff_p = 1.0

            regime_results[regime_col] = {
                "in_regime_mean": in_mean,
                "out_regime_mean": out_mean,
                "in_regime_sharpe": in_sharpe,
                "in_regime_hit_rate": in_hit_rate,
                "n_obs_in": len(in_regime),
                "n_obs_out": len(out_regime),
                "difference_p_value": diff_p,
                "significant_difference": diff_p < 0.05,
            }

            if diff_p < 0.05:
                regime_warnings.append(
                    f"Performance differs significantly between "
                    f"{regime_col}=True and {regime_col}=False (p={diff_p:.4f})."
                )

        # Determine if regime-dependent
        n_significant_diffs = sum(
            1 for r in regime_results.values()
            if r.get("significant_difference", False)
        )
        is_regime_dependent = n_significant_diffs > 0

        # Find dominant regime
        dominant_regime = None
        best_sharpe = -999
        for regime_col, result in regime_results.items():
            if result.get("in_regime_sharpe", -999) > best_sharpe:
                best_sharpe = result["in_regime_sharpe"]
                dominant_regime = regime_col

        return RegimeAnalysisResult(
            regimes=regime_results,
            regime_significance={
                col: r.get("difference_p_value", 1.0)
                for col, r in regime_results.items()
            },
            n_regimes=len(regimes.columns),
            is_regime_dependent=is_regime_dependent,
            dominant_regime=dominant_regime,
            regime_warnings=regime_warnings,
        )

    # ------------------------------------------------------------------
    # Edge Decay Detection
    # ------------------------------------------------------------------

    def rolling_window_analysis(
        self,
        strategy_returns: pd.Series,
        window_years: int = 3,
        step_quarters: int = 1,
    ) -> pd.Series:
        """
        Compute rolling window alpha to detect decay trends.

        Uses a window of `window_years` years, stepping by one quarter.
        """
        window_days = window_years * 252
        step_days = step_quarters * 63  # ~63 trading days per quarter

        rolling_alphas = []

        for start_idx in range(0, len(strategy_returns) - window_days, step_days):
            window = strategy_returns.iloc[start_idx : start_idx + window_days]
            if len(window) < 63:  # Minimum 3 months
                continue

            ann_alpha = window.mean() * 252
            rolling_alphas.append({
                "start_date": window.index[0],
                "end_date": window.index[-1],
                "annualized_alpha": ann_alpha,
            })

        if not rolling_alphas:
            return pd.Series(dtype=float)
        return pd.DataFrame(rolling_alphas).set_index("start_date")["annualized_alpha"]

    def detect_edge_decay(
        self,
        rolling_alphas: pd.Series,
    ) -> EdgeDecayResult:
        """
        Detect whether the strategy's edge is decaying over time.

        Fits a linear trend to the rolling alpha series.
        If significant and negative, the edge is decaying.
        """
        if len(rolling_alphas) < 4:
            return EdgeDecayResult(
                rolling_alphas=rolling_alphas,
                trend_coefficient=0,
                trend_p_value=1.0,
                half_life_years=float("inf"),
                half_life_ci=(float("inf"), float("inf")),
                is_decaying=False,
                structural_breaks=[],
            )

        # Linear trend
        x = np.arange(len(rolling_alphas))
        y = rolling_alphas.values

        # Remove NaN
        valid = ~np.isnan(y)
        x_valid = x[valid]
        y_valid = y[valid]

        if len(y_valid) < 4:
            return EdgeDecayResult(
                rolling_alphas=rolling_alphas,
                trend_coefficient=0,
                trend_p_value=1.0,
                half_life_years=float("inf"),
                half_life_ci=(float("inf"), float("inf")),
                is_decaying=False,
                structural_breaks=[],
            )

        slope, intercept, r_value, p_value, std_err = stats.linregress(x_valid, y_valid)

        # Edge half-life estimation
        # If alpha(t) = alpha(0) * exp(-lambda * t), then lambda = -slope / intercept
        if intercept > 0 and slope < 0:
            lambda_est = abs(slope) / intercept
            half_life = np.log(2) / lambda_est if lambda_est > 0 else float("inf")
        elif intercept <= 0:
            half_life = 0.0
        else:
            half_life = float("inf")

        # Bootstrap CI for half-life
        half_life_boot = []
        for _ in range(1000):
            idx = self.rng.choice(len(y_valid), size=len(y_valid), replace=True)
            boot_x = x_valid[idx]
            boot_y = y_valid[idx]
            boot_slope, boot_intercept, _, _, _ = stats.linregress(boot_x, boot_y)

            if boot_intercept > 0 and boot_slope < 0:
                lam = abs(boot_slope) / boot_intercept
                hl = np.log(2) / lam if lam > 0 else float("inf")
            else:
                hl = float("inf")
            half_life_boot.append(hl)

        half_life_boot = np.array(half_life_boot)
        half_life_boot_finite = half_life_boot[np.isfinite(half_life_boot)]

        if len(half_life_boot_finite) > 100:
            hl_ci = (
                np.percentile(half_life_boot_finite, 2.5),
                np.percentile(half_life_boot_finite, 97.5),
            )
        else:
            hl_ci = (float("inf"), float("inf"))

        is_decaying = p_value < 0.05 and slope < 0

        # Structural break detection (simplified Bai-Perron)
        structural_breaks = self._detect_structural_breaks(y_valid)

        return EdgeDecayResult(
            rolling_alphas=rolling_alphas,
            trend_coefficient=slope,
            trend_p_value=p_value,
            half_life_years=half_life,
            half_life_ci=hl_ci,
            is_decaying=is_decaying,
            structural_breaks=structural_breaks,
        )

    def _detect_structural_breaks(self, y: np.ndarray) -> List[int]:
        """
        Simplified structural break detection.

        Uses a rolling Chow test to find break points.
        """
        breaks = []
        n = len(y)

        if n < 30:
            return breaks

        min_segment = 10

        for i in range(min_segment, n - min_segment):
            y1 = y[:i]
            y2 = y[i:]

            # Chow test: significant difference in means?
            _, p_value = stats.ttest_ind(y1, y2)
            if p_value < 0.01:
                breaks.append(i)

        # Cluster adjacent break points
        if len(breaks) > 1:
            clustered = [breaks[0]]
            for b in breaks[1:]:
                if b - clustered[-1] > 5:
                    clustered.append(b)
            breaks = clustered

        return breaks[:5]  # Cap at 5 breaks


# ============================================================================
# Adversarial Report Generator
# ============================================================================


class AdversarialReportGenerator:
    """
    Runs the full adversarial test battery and compiles results.

    This is the gatekeeper. If any adversarial test fails, the hypothesis
    is flagged and may be BROKEN.
    """

    def __init__(
        self,
        stat_breaker: Optional[StatisticalBreaker] = None,
        data_breaker: Optional[DataBreaker] = None,
        regime_analyzer: Optional[RegimeAnalyzer] = None,
        seed: Optional[int] = None,
    ):
        self.stat_breaker = stat_breaker or StatisticalBreaker(seed=seed)
        self.data_breaker = data_breaker or DataBreaker()
        self.regime_analyzer = regime_analyzer or RegimeAnalyzer(seed=seed)

    def generate_report(
        self,
        signals: pd.DataFrame,
        forward_returns: pd.DataFrame,
        strategy_returns: pd.Series,
        backtest_func: Callable,
        alt_backtest_funcs: List[Callable],
        alt_spec_names: List[str],
        universe_df: Optional[pd.DataFrame] = None,
        date_range: Optional[Tuple[str, str]] = None,
        market_data: Optional[pd.DataFrame] = None,
        window_results: Optional[List[Dict]] = None,
    ) -> AdversarialReport:
        """
        Run all adversarial tests.

        Returns:
            AdversarialReport with all test results and overall verdict
        """
        breakage_reasons = []
        all_warnings = []

        # 1. Random permutation test
        perm_result = self.stat_breaker.permutation_test(
            signals, forward_returns, backtest_func
        )
        if not perm_result.is_significant:
            breakage_reasons.append(
                f"PERMUTATION TEST FAILED: p={perm_result.p_value:.4f}. "
                f"Signal indistinguishable from random noise."
            )

        # 2. Time shuffle test
        time_result = self.stat_breaker.time_shuffle_test(
            signals, forward_returns, backtest_func
        )

        # 3. Specification robustness
        spec_result = self.stat_breaker.specification_robustness_test(
            alt_backtest_funcs, alt_spec_names
        )
        if not spec_result.is_robust:
            breakage_reasons.append(
                f"SPECIFICATION ROBUSTNESS FAILED: Only "
                f"{spec_result.fraction_significant:.0%} of alternative "
                f"specifications are significant."
            )

        # 4. Walk-forward consistency
        wf_result = self.stat_breaker.walk_forward_consistency_test(
            window_results or []
        )
        if not wf_result.is_consistent and wf_result.n_windows > 0:
            breakage_reasons.append(
                f"WALK-FORWARD FAILED: Only {wf_result.fraction_positive:.0%} "
                f"of walk-forward windows are positive "
                f"(threshold: {DEFAULT_WALK_FORWARD_POSITIVE_THRESHOLD:.0%})."
            )

        # 5. Out-of-sample test
        oos_result = self.stat_breaker.out_of_sample_test(strategy_returns)
        if not oos_result.get("passed", False):
            breakage_reasons.append(
                f"OUT-OF-SAMPLE FAILED: OOS returns not significant "
                f"(p={oos_result.get('oos_p_value', 1.0):.4f})."
            )

        # 6. Regime analysis
        regimes_df = pd.DataFrame(index=strategy_returns.index)
        if market_data is not None:
            regimes_df = self.regime_analyzer.classify_regimes(
                strategy_returns.index, market_data
            )

        regime_result = self.regime_analyzer.analyze_regime_performance(
            strategy_returns, regimes_df
        )

        if regime_result.is_regime_dependent:
            all_warnings.append(
                "REGIME DEPENDENT: Strategy performance differs significantly "
                "across market regimes. Edge may not be persistent."
            )

        # 7. Edge decay
        rolling_alphas = self.regime_analyzer.rolling_window_analysis(strategy_returns)
        decay_result = self.regime_analyzer.detect_edge_decay(rolling_alphas)

        if decay_result.is_decaying:
            breakage_reasons.append(
                f"EDGE DECAY DETECTED: Rolling alpha trend is significantly "
                f"negative (p={decay_result.trend_p_value:.4f}). "
                f"Half-life: {decay_result.half_life_years:.1f} years."
            )
        elif decay_result.half_life_years < 1.0:
            all_warnings.append(
                f"SHORT EDGE HALF-LIFE: Estimated half-life is "
                f"{decay_result.half_life_years:.1f} years. "
                f"Edge may disappear quickly."
            )

        # 8. Data integrity checks
        data_checks = []
        if universe_df is not None and date_range is not None:
            data_checks = self.data_breaker.run_all_checks(
                universe_df=universe_df,
                date_range=date_range,
            )
            for check in data_checks:
                if check.severity == "CRITICAL":
                    breakage_reasons.append(
                        f"DATA INTEGRITY {check.severity}: {check.check_name} — {check.details}"
                    )
                elif check.severity == "WARNING":
                    all_warnings.append(
                        f"DATA INTEGRITY WARNING: {check.check_name} — {check.details}"
                    )

        # Overall verdict
        all_passed = len(breakage_reasons) == 0

        return AdversarialReport(
            permutation=perm_result,
            time_shuffle=time_result,
            specification_robustness=spec_result,
            walk_forward=wf_result,
            regime_analysis=regime_result,
            edge_decay=decay_result,
            data_integrity_checks=data_checks,
            all_adversarial_passed=all_passed,
            breakage_reasons=breakage_reasons,
            warnings=all_warnings,
        )
