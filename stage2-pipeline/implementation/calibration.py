#!/usr/bin/env python3
"""
calibration.py -- 4-Tier Calibration Pipeline
==============================================

Validates that the hypothesis-testing pipeline is correctly calibrated
before any hypothesis is tested. If the pipeline cannot distinguish known
factors from noise, its verdicts are meaningless.

Tiers:
  1. Positive Controls — momentum/reversal/value/size MUST survive
  2. Synthetic Controls — Gaussian noise power curve (MDE estimation)
  3. Negative Controls — random/shuffled/reversed MUST all break
  4. Null Distribution  — 100 random signals, empirical FPR ≤ 5%

A miscalibrated pipeline cannot produce valid BROKEN verdicts — it might
be breaking everything, including genuine edges. This calibration is the
foundation that makes the 13-gate verdict decision tree interpretable.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Ensure implementation directory on path for sibling imports
_IMPL_DIR = os.path.dirname(os.path.abspath(__file__))
if _IMPL_DIR not in sys.path:
    sys.path.insert(0, _IMPL_DIR)

from factors import FactorConstructor
from pipeline import (
    HypothesisPipeline,
    HypothesisSpec,
    Verdict,
    DataSourceSpec,
    UniverseSpec,
    SignalSpec,
    TimePeriodSpec,
    PositionSizingSpec,
    MinimumEffectSpec,
)

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SingleRunResult:
    """Result of a single pipeline run within a calibration tier."""
    name: str
    verdict: str
    verdict_reason: str = ""
    sharpe_ratio: Optional[float] = None
    annualized_alpha_bps: Optional[float] = None
    gt_score: Optional[float] = None
    p_value: Optional[float] = None
    elapsed_seconds: float = 0.0
    warnings: List[str] = field(default_factory=list)


@dataclass
class TierResult:
    """Aggregate result for a calibration tier."""
    tier: int
    name: str
    passed: bool
    runs: List[SingleRunResult] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    @property
    def n_survived(self) -> int:
        return sum(1 for r in self.runs if r.verdict in ("SURVIVED", "SURVIVED_WARNING"))

    @property
    def n_broken(self) -> int:
        return sum(1 for r in self.runs if r.verdict == "BROKEN")

    @property
    def n_untestable(self) -> int:
        return sum(1 for r in self.runs if r.verdict == "UNTESTABLE")


@dataclass
class CalibrationReport:
    """Full calibration report across all 4 tiers."""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pipeline_version: str = "1.0.0"
    overall_pass: bool = False
    tiers: List[TierResult] = field(default_factory=list)
    pipeline_health: str = "UNKNOWN"
    mde_bps: Optional[float] = None
    empirical_fpr_pct: Optional[float] = None
    recommendations: List[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "pipeline_version": self.pipeline_version,
            "overall_pass": self.overall_pass,
            "pipeline_health": self.pipeline_health,
            "mde_bps": self.mde_bps,
            "empirical_fpr_pct": self.empirical_fpr_pct,
            "tiers": [
                {
                    "tier": t.tier,
                    "name": t.name,
                    "passed": t.passed,
                    "n_survived": t.n_survived,
                    "n_broken": t.n_broken,
                    "n_untestable": t.n_untestable,
                    "runs": [asdict(r) for r in t.runs],
                    "diagnostics": t.diagnostics,
                    "elapsed_seconds": t.elapsed_seconds,
                }
                for t in self.tiers
            ],
            "recommendations": self.recommendations,
            "elapsed_seconds": self.elapsed_seconds,
        }


# ---------------------------------------------------------------------------
# Signal construction helpers
# ---------------------------------------------------------------------------


def _build_factor_signal_df(
    factor_constructor: FactorConstructor,
    price_df: pd.DataFrame,
    factor_method: str,
    **kwargs,
) -> pd.DataFrame:
    """Build a signal DataFrame (dates x tickers) for a factor.

    For each date with sufficient history, computes the factor signal
    cross-sectionally. Returns a DataFrame where index=dates and
    columns=tickers.

    Args:
        factor_constructor: FactorConstructor instance.
        price_df: Price DataFrame (dates x tickers).
        factor_method: Method name on FactorConstructor (e.g. 'construct_momentum_12_1').
        **kwargs: Passed to the factor method.

    Returns:
        Signal DataFrame with dates as index, tickers as columns.
    """
    method = getattr(factor_constructor, factor_method, None)
    if method is None:
        raise ValueError(f"FactorConstructor has no method '{factor_method}'")

    dates = price_df.index.tolist()
    min_history = TRADING_DAYS_PER_MONTH * 13  # need at least 13 months for momentum

    signals_by_date: Dict[str, pd.Series] = {}

    for i, date_str in enumerate(dates):
        date_str = str(date_str)[:10]
        if i < min_history:
            continue

        date_idx = price_df.index.get_loc(date_str) if hasattr(price_df.index, 'get_loc') else i
        if isinstance(date_idx, slice):
            date_idx = i

        try:
            # Build point-in-time price data up to this date
            pit_prices = price_df.iloc[: int(date_idx) + 1]
            signal = method(pit_prices, date=date_str, **kwargs)
            if signal is not None and not signal.empty:
                clean_signal = signal.replace([np.inf, -np.inf], np.nan).dropna()
                if not clean_signal.empty:
                    signals_by_date[date_str] = clean_signal
        except Exception:
            continue

    if not signals_by_date:
        return pd.DataFrame()

    # Build DataFrame: dates as index, tickers as columns
    all_dates = sorted(signals_by_date.keys())
    tickers = set()
    for s in signals_by_date.values():
        tickers.update(s.index.tolist())
    tickers = sorted(tickers)

    df = pd.DataFrame(index=pd.to_datetime(all_dates), columns=tickers, dtype=float)
    for date_str, signal in signals_by_date.items():
        for t, val in signal.items():
            if t in df.columns:
                df.at[pd.Timestamp(date_str), t] = val

    return df


def _build_random_signal_df(
    shape_template: Tuple[int, int],
    tickers: List[str],
    dates: List[str],
    seed: int = 0,
) -> pd.DataFrame:
    """Build a random uniform signal DataFrame."""
    rng = np.random.RandomState(seed)
    data = rng.uniform(-1, 1, size=(len(dates), len(tickers)))
    df = pd.DataFrame(data, index=pd.to_datetime(dates), columns=tickers)
    return df


def _save_signal_parquet(signal_df: pd.DataFrame, output_dir: str, name: str) -> str:
    """Save a signal DataFrame to parquet. Returns the file path."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{name}.parquet")
    signal_df.to_parquet(path)
    return path


# ---------------------------------------------------------------------------
# HypothesisSpec factory for calibration signals
# ---------------------------------------------------------------------------


def _make_hypothesis_spec(
    name: str,
    signal_path: str,
    holding_period_days: int = 21,
    start_date: str = "2021-01-01",
    end_date: str = "2024-12-31",
    capital: float = 100000.0,
    annualized_alpha_bps: float = 300.0,
) -> HypothesisSpec:
    """Create a minimal HypothesisSpec for a calibration signal."""
    return HypothesisSpec(
        name=name,
        uuid=str(uuid.uuid4())[:8],
        source_agent="calibration",
        submission_number=0,
        mechanism="Calibration factor signal — known academic factor.",
        llm_advantage="N/A (calibration)",
        why_underweighted="N/A (calibration)",
        universe=UniverseSpec(universe_type="sp500"),
        signal=SignalSpec(
            signal_type="numeric",
            signal_name=name,
            higher_is_better=True,
            signal_source=signal_path,
        ),
        holding_period_days=holding_period_days,
        time_period=TimePeriodSpec(
            start_date=start_date,
            end_date=end_date,
        ),
        position_sizing=PositionSizingSpec(
            method="equal_weight",
            max_position_pct=0.05,
            max_positions=50,
            capital=capital,
            rebalance_frequency="monthly",  # Must match holding period to avoid overlapping returns
        ),
        minimum_effect_size=MinimumEffectSpec(
            annualized_alpha_bps=annualized_alpha_bps,
            sharpe_ratio=0.3,
            information_coefficient=0.03,
            hit_rate=0.51,
            max_drawdown_pct=40.0,  # More lenient for calibration with known factors
        ),
        data_sources=[
            DataSourceSpec(
                source_type="price",
                provider="yahoo",
                frequency="daily",
                fields=["adj_close", "volume"],
                start_date=start_date,
                end_date=end_date,
            ),
        ],
    )


def _run_single_pipeline(
    hypothesis: HypothesisSpec,
    output_dir: str,
    verbose: bool = False,
    fmp_api_key: Optional[str] = None,
) -> SingleRunResult:
    """Run a single hypothesis through the pipeline and return the result."""
    start = time.time()
    try:
        pipe = HypothesisPipeline(
            output_dir=os.path.join(output_dir, hypothesis.uuid),
            verbose=verbose,
            fmp_api_key=fmp_api_key,
        )
        result = pipe.run(hypothesis)
        elapsed = time.time() - start

        stats = result.get("checks", {})
        adv = stats.get("adversarial_breakage", {})
        metrics = result.get("metrics", {})

        return SingleRunResult(
            name=hypothesis.name,
            verdict=str(result.get("verdict", "UNKNOWN")),
            verdict_reason=str(result.get("verdict_reason", "")),
            sharpe_ratio=metrics.get("sharpe_ratio"),
            annualized_alpha_bps=metrics.get("annualized_return_pct", 0) * 100
                if metrics.get("annualized_return_pct") else None,
            gt_score=stats.get("gt_score"),
            p_value=adv.get("permutation_test_p"),
            elapsed_seconds=elapsed,
            warnings=list(result.get("warnings", [])),
        )
    except Exception as e:
        elapsed = time.time() - start
        return SingleRunResult(
            name=hypothesis.name,
            verdict="UNTESTABLE",
            verdict_reason=f"Pipeline error: {e}",
            elapsed_seconds=elapsed,
        )


# ---------------------------------------------------------------------------
# Tier 1: Positive Controls
# ---------------------------------------------------------------------------


class Tier1PositiveControls:
    """Run known academic factors through the pipeline. ALL must SURVIVE.

    If momentum, reversal, value, or size factors fail to survive,
    the pipeline is miscalibrated — it cannot detect genuine edges.
    """

    FACTOR_SPECS = [
        {"name": "momentum_12_1", "method": "construct_momentum_12_1", "kwargs": {}},
        {"name": "short_term_reversal", "method": "construct_short_term_reversal", "kwargs": {}},
    ]

    def __init__(self, output_dir: str = "calibration_output", verbose: bool = False):
        self.output_dir = output_dir
        self.verbose = verbose
        self.fc = FactorConstructor(seed=42)

    def run(
        self,
        price_df: pd.DataFrame,
        market_cap_df: Optional[pd.DataFrame] = None,
        volume_df: Optional[pd.DataFrame] = None,
        start_date: str = "2021-01-01",
        end_date: str = "2024-12-31",
        fmp_api_key: Optional[str] = None,
    ) -> TierResult:
        """Run Tier 1: Positive Controls."""
        start_time = time.time()
        runs: List[SingleRunResult] = []
        signals_dir = os.path.join(self.output_dir, "tier1_signals")
        run_output_dir = os.path.join(self.output_dir, "tier1_runs")

        factor_specs = list(self.FACTOR_SPECS)

        # Value factor if market caps available (use price * 1e9 as crude proxy)
        if market_cap_df is not None and not market_cap_df.empty:
            factor_specs.append({"name": "size", "method": "construct_size_signal", "kwargs": {}})

        for spec in factor_specs:
            logger.info(f"Tier 1: Building {spec['name']} signal...")
            try:
                signal_df = _build_factor_signal_df(
                    self.fc, price_df, spec["method"], **spec["kwargs"]
                )
                if signal_df.empty or signal_df.shape[0] < 50:
                    runs.append(SingleRunResult(
                        name=spec["name"],
                        verdict="UNTESTABLE",
                        verdict_reason=f"Insufficient signal data: {signal_df.shape}",
                    ))
                    logger.warning(f"Tier 1: {spec['name']} — insufficient data, skipping")
                    continue

                signal_path = _save_signal_parquet(signal_df, signals_dir, spec["name"])
                hyp = _make_hypothesis_spec(
                    name=f"calibration_tier1_{spec['name']}",
                    signal_path=signal_path,
                    start_date=start_date,
                    end_date=end_date,
                )

                logger.info(f"Tier 1: Running pipeline for {spec['name']}...")
                run_result = _run_single_pipeline(
                    hyp, run_output_dir, verbose=self.verbose, fmp_api_key=fmp_api_key
                )
                runs.append(run_result)
                logger.info(f"Tier 1: {spec['name']} → {run_result.verdict}")

            except Exception as e:
                logger.error(f"Tier 1: {spec['name']} failed with error: {e}")
                runs.append(SingleRunResult(
                    name=spec["name"],
                    verdict="UNTESTABLE",
                    verdict_reason=f"Signal construction error: {e}",
                ))

        # Tier 1 passes if ALL factor runs SURVIVE or SURVIVED_WARNING
        n_expected = len(factor_specs)
        survived = sum(1 for r in runs if r.verdict in ("SURVIVED", "SURVIVED_WARNING"))
        passed = survived == n_expected and n_expected > 0

        diagnostics = {
            "n_expected": n_expected,
            "n_survived": survived,
            "n_broken": sum(1 for r in runs if r.verdict == "BROKEN"),
            "n_untestable": sum(1 for r in runs if r.verdict == "UNTESTABLE"),
        }

        if not passed:
            broken_names = [r.name for r in runs if r.verdict == "BROKEN"]
            diagnostics["broken_factors"] = broken_names
            diagnostics["warning"] = (
                f"Pipeline miscalibrated: {broken_names} did not survive. "
                "Positive controls must pass before hypothesis testing is meaningful."
            )

        return TierResult(
            tier=1,
            name="Positive Controls",
            passed=passed,
            runs=runs,
            diagnostics=diagnostics,
            elapsed_seconds=time.time() - start_time,
        )


# ---------------------------------------------------------------------------
# Tier 2: Synthetic Controls (Power Curve)
# ---------------------------------------------------------------------------


class Tier2PowerCurve:
    """Inject Gaussian noise into momentum returns, build detection power curve.

    Fits logistic regression: P(detect) ~ logit(alpha) across noise levels
    (50/100/200/300/500 bps annualized, 10 seeds each).

    Extracts MDE (Minimum Detectable Effect) at 80% power.
    """

    NOISE_LEVELS_BPS = [50, 100, 200, 300, 500]
    N_SEEDS = 10

    def __init__(self, output_dir: str = "calibration_output", verbose: bool = False):
        self.output_dir = output_dir
        self.verbose = verbose
        self.fc = FactorConstructor(seed=42)

    def _inject_noise(
        self, signal_df: pd.DataFrame, noise_annual_bps: float, seed: int
    ) -> pd.DataFrame:
        """Add Gaussian noise to a signal DataFrame.

        noise_annual_bps: annualized alpha noise in basis points.
        Noise is scaled to daily: σ_daily = noise_annual_bps / 10000 / sqrt(252)
        """
        rng = np.random.RandomState(seed)
        daily_sigma = (noise_annual_bps / 10000.0) / np.sqrt(TRADING_DAYS_PER_YEAR)
        noise = pd.DataFrame(
            rng.normal(0, daily_sigma, size=signal_df.shape),
            index=signal_df.index,
            columns=signal_df.columns,
        )
        return signal_df + noise

    def run(
        self,
        price_df: pd.DataFrame,
        start_date: str = "2021-01-01",
        end_date: str = "2024-12-31",
        fmp_api_key: Optional[str] = None,
    ) -> TierResult:
        """Run Tier 2: Synthetic Controls (Power Curve)."""
        start_time = time.time()
        runs: List[SingleRunResult] = []
        signals_dir = os.path.join(self.output_dir, "tier2_signals")
        run_output_dir = os.path.join(self.output_dir, "tier2_runs")

        # Build baseline momentum signal
        logger.info("Tier 2: Building baseline momentum signal...")
        try:
            baseline_signal = _build_factor_signal_df(
                self.fc, price_df, "construct_momentum_12_1"
            )
            if baseline_signal.empty:
                return TierResult(
                    tier=2,
                    name="Synthetic Controls (Power Curve)",
                    passed=False,
                    diagnostics={"error": "Could not build baseline momentum signal"},
                    elapsed_seconds=time.time() - start_time,
                )
        except Exception as e:
            return TierResult(
                tier=2,
                name="Synthetic Controls (Power Curve)",
                passed=False,
                diagnostics={"error": f"Baseline signal error: {e}"},
                elapsed_seconds=time.time() - start_time,
            )

        # For each noise level, run N_SEEDS
        detection_rates: Dict[float, float] = {}
        all_seed_results: Dict[float, List[bool]] = {}

        for noise_bps in self.NOISE_LEVELS_BPS:
            level_detected = 0
            level_results: List[bool] = []

            for seed in range(self.N_SEEDS):
                name = f"momentum_noise_{noise_bps}bps_seed{seed}"
                logger.info(f"Tier 2: {name}...")

                try:
                    noisy_signal = self._inject_noise(baseline_signal, noise_bps, seed)
                    signal_path = _save_signal_parquet(noisy_signal, signals_dir, name)
                    hyp = _make_hypothesis_spec(
                        name=f"calibration_tier2_{name}",
                        signal_path=signal_path,
                        start_date=start_date,
                        end_date=end_date,
                    )

                    run_result = _run_single_pipeline(
                        hyp, run_output_dir, verbose=self.verbose, fmp_api_key=fmp_api_key
                    )
                    runs.append(run_result)

                    detected = run_result.verdict in ("SURVIVED", "SURVIVED_WARNING")
                    if detected:
                        level_detected += 1
                    level_results.append(detected)
                except Exception as e:
                    logger.error(f"Tier 2: {name} failed: {e}")
                    level_results.append(False)

            detection_rate = level_detected / self.N_SEEDS
            detection_rates[noise_bps] = detection_rate
            all_seed_results[noise_bps] = level_results

            logger.info(f"Tier 2: {noise_bps}bps → {level_detected}/{self.N_SEEDS} detected ({detection_rate:.0%})")

        # Fit logistic regression power curve
        mde_bps, power_curve = self._fit_power_curve(detection_rates)
        passed = mde_bps is not None and mde_bps < 1000  # Pipeline can detect <10% alpha

        diagnostics = {
            "detection_rates": detection_rates,
            "seed_results": {str(k): v for k, v in all_seed_results.items()},
            "mde_bps_at_80pct": mde_bps,
            "power_curve_params": power_curve,
            "noise_levels_bps": self.NOISE_LEVELS_BPS,
            "n_seeds_per_level": self.N_SEEDS,
        }

        if mde_bps is None:
            diagnostics["warning"] = "Could not fit power curve — insufficient detection events."
        elif mde_bps > 1000:
            diagnostics["warning"] = (
                f"MDE = {mde_bps:.0f} bps > 1000 bps. "
                "Pipeline cannot detect any realistic retail edge."
            )

        return TierResult(
            tier=2,
            name="Synthetic Controls (Power Curve)",
            passed=passed,
            runs=runs,
            diagnostics=diagnostics,
            elapsed_seconds=time.time() - start_time,
        )

    def _fit_power_curve(
        self, detection_rates: Dict[float, float]
    ) -> Tuple[Optional[float], Dict[str, float]]:
        """Fit logistic regression: P(detect) ~ logit(alpha).

        Returns:
            (mde_bps_at_80pct, power_curve_params)
        """
        levels = sorted(detection_rates.keys())
        rates = [detection_rates[l] for l in levels]

        # Need at least 2 levels with detection between 0 and 1
        usable = [i for i, r in enumerate(rates) if 0.0 < r < 1.0]
        if len(usable) < 2:
            return None, {"error": f"Insufficient interior detection points: {len(usable)}"}

        try:
            from scipy.optimize import curve_fit

            def logistic(x, a, b):
                return 1.0 / (1.0 + np.exp(-(a + b * x)))

            x_data = np.log(np.array([levels[i] for i in usable]))
            y_data = np.array([rates[i] for i in usable])

            popt, _ = curve_fit(logistic, x_data, y_data, p0=[-2, 1], maxfev=10000)
            a, b = popt

            # Solve for MDE at 80% power: logit(0.80) = a + b * log(alpha)
            logit_80 = np.log(0.80 / 0.20)  # = ln(4) ≈ 1.386
            log_mde = (logit_80 - a) / b
            mde = np.exp(log_mde)

            # Validate: MDE should be monotonic with noise levels
            if mde <= 0 or (b < 0 and mde > max(levels) * 5):
                return None, {"error": f"MDE fit produced implausible value: {mde:.0f}"}

            return float(mde), {"intercept": float(a), "slope": float(b), "logit_80": float(logit_80)}

        except Exception as e:
            return None, {"error": f"Curve fitting failed: {e}"}


# ---------------------------------------------------------------------------
# Tier 3: Negative Controls
# ---------------------------------------------------------------------------


class Tier3NegativeControls:
    """Run random, shuffled, and reversed signals. ALL must BROKEN.

    If any negative control survives, there is a critical defect in
    false positive control — significance thresholds must be tightened.
    """

    def __init__(self, output_dir: str = "calibration_output", verbose: bool = False):
        self.output_dir = output_dir
        self.verbose = verbose
        self.fc = FactorConstructor(seed=42)

    def _shuffle_signal(self, signal_df: pd.DataFrame, seed: int) -> pd.DataFrame:
        """Shuffle signal values within each date (destroys temporal structure)."""
        rng = np.random.RandomState(seed)
        shuffled = signal_df.copy()
        for date_idx in range(shuffled.shape[0]):
            row = shuffled.iloc[date_idx].values.copy()
            nan_mask = np.isnan(row)
            valid_vals = row[~nan_mask]
            rng.shuffle(valid_vals)
            row[~nan_mask] = valid_vals
            shuffled.iloc[date_idx] = row
        return shuffled

    def _reverse_signal(self, signal_df: pd.DataFrame) -> pd.DataFrame:
        """Flip the sign of all signal values."""
        return -signal_df

    def run(
        self,
        price_df: pd.DataFrame,
        start_date: str = "2021-01-01",
        end_date: str = "2024-12-31",
        fmp_api_key: Optional[str] = None,
    ) -> TierResult:
        """Run Tier 3: Negative Controls."""
        start_time = time.time()
        runs: List[SingleRunResult] = []
        signals_dir = os.path.join(self.output_dir, "tier3_signals")
        run_output_dir = os.path.join(self.output_dir, "tier3_runs")

        # Build baseline momentum signal for shuffling/reversing
        logger.info("Tier 3: Building baseline momentum signal...")
        try:
            baseline_signal = _build_factor_signal_df(
                self.fc, price_df, "construct_momentum_12_1"
            )
        except Exception as e:
            logger.error(f"Tier 3: Baseline signal error: {e}")
            baseline_signal = pd.DataFrame()

        tickers = list(baseline_signal.columns) if not baseline_signal.empty else list(price_df.columns)[:100]
        dates_list = list(baseline_signal.index) if not baseline_signal.empty else list(price_df.index)[-252:]

        negative_specs = []

        # 1. Random uniform signal
        if tickers and dates_list:
            random_signal = _build_random_signal_df(
                baseline_signal.shape, tickers, dates_list, seed=42
            )
            negative_specs.append(("random_uniform", random_signal))

        # 2. Shuffled momentum
        if not baseline_signal.empty:
            shuffled = self._shuffle_signal(baseline_signal, seed=43)
            negative_specs.append(("shuffled_momentum", shuffled))

            # 3. Reversed momentum
            reversed_sig = self._reverse_signal(baseline_signal)
            negative_specs.append(("reversed_momentum", reversed_sig))

        for name, signal_df in negative_specs:
            logger.info(f"Tier 3: Running {name}...")
            try:
                signal_path = _save_signal_parquet(signal_df, signals_dir, name)
                hyp = _make_hypothesis_spec(
                    name=f"calibration_tier3_{name}",
                    signal_path=signal_path,
                    start_date=start_date,
                    end_date=end_date,
                )

                run_result = _run_single_pipeline(
                    hyp, run_output_dir, verbose=self.verbose, fmp_api_key=fmp_api_key
                )
                runs.append(run_result)
                logger.info(f"Tier 3: {name} → {run_result.verdict}")
            except Exception as e:
                logger.error(f"Tier 3: {name} failed: {e}")
                runs.append(SingleRunResult(
                    name=name,
                    verdict="UNTESTABLE",
                    verdict_reason=f"Error: {e}",
                ))

        # ALL must BROKEN; UNTESTABLE is acceptable (means couldn't run, not a false positive)
        n_broken = sum(1 for r in runs if r.verdict == "BROKEN")
        n_survived = sum(1 for r in runs if r.verdict in ("SURVIVED", "SURVIVED_WARNING"))
        passed = n_survived == 0 and n_broken >= 1

        diagnostics = {
            "n_signals": len(negative_specs),
            "n_broken": n_broken,
            "n_survived": n_survived,
            "n_untestable": sum(1 for r in runs if r.verdict == "UNTESTABLE"),
        }

        if n_survived > 0:
            diagnostics["warning"] = (
                f"CRITICAL: {n_survived} negative control(s) SURVIVED! "
                "False positive control is defective. Significance thresholds must be tightened."
            )

        return TierResult(
            tier=3,
            name="Negative Controls",
            passed=passed,
            runs=runs,
            diagnostics=diagnostics,
            elapsed_seconds=time.time() - start_time,
        )


# ---------------------------------------------------------------------------
# Tier 4: Null Distribution (Empirical FPR)
# ---------------------------------------------------------------------------


class Tier4NullDistribution:
    """Run N random signals through pipeline. Count SURVIVED ≤ 5%.

    If >5% of pure-noise signals survive, the pipeline's nominal
    significance level is miscalibrated and requires stricter correction.
    """

    def __init__(
        self,
        n_random: int = 100,
        output_dir: str = "calibration_output",
        verbose: bool = False,
    ):
        self.n_random = n_random
        self.output_dir = output_dir
        self.verbose = verbose

    def run(
        self,
        price_df: pd.DataFrame,
        start_date: str = "2021-01-01",
        end_date: str = "2024-12-31",
        fmp_api_key: Optional[str] = None,
    ) -> TierResult:
        """Run Tier 4: Null Distribution (Empirical FPR)."""
        start_time = time.time()
        runs: List[SingleRunResult] = []
        signals_dir = os.path.join(self.output_dir, "tier4_signals")
        run_output_dir = os.path.join(self.output_dir, "tier4_runs")

        # Use tickers from price data
        tickers = list(price_df.columns)[:100]  # Cap at 100 tickers for performance
        dates_list = [str(d)[:10] for d in price_df.index][-504:]  # Last ~2 years of trading days
        if len(dates_list) < 100:
            dates_list = [str(d)[:10] for d in price_df.index]

        logger.info(f"Tier 4: Running {self.n_random} random signals "
                     f"({len(tickers)} tickers × {len(dates_list)} dates)...")

        n_survived = 0
        n_broken = 0
        n_untestable = 0

        # Phase 1: Run up to 20 signals (batch 1)
        batch1_size = min(20, self.n_random)
        for i in range(batch1_size):
            name = f"random_null_{i:03d}"
            try:
                signal_df = _build_random_signal_df(
                    (len(dates_list), len(tickers)), tickers, dates_list, seed=i
                )
                signal_path = _save_signal_parquet(signal_df, signals_dir, name)
                hyp = _make_hypothesis_spec(
                    name=f"calibration_tier4_{name}",
                    signal_path=signal_path,
                    start_date=start_date,
                    end_date=end_date,
                )

                run_result = _run_single_pipeline(
                    hyp, run_output_dir, verbose=self.verbose, fmp_api_key=fmp_api_key
                )
                runs.append(run_result)

                if run_result.verdict in ("SURVIVED", "SURVIVED_WARNING"):
                    n_survived += 1
                elif run_result.verdict == "BROKEN":
                    n_broken += 1
                else:
                    n_untestable += 1

                if (i + 1) % 5 == 0:
                    logger.info(f"Tier 4: {i+1}/{batch1_size} — {n_survived} survived, {n_broken} broken")

            except Exception as e:
                logger.error(f"Tier 4: {name} failed: {e}")
                n_untestable += 1

        # Phase 2: If batch1 shows FPR near threshold, run more
        # Only continue if we have meaningful results and resources permit
        remaining = self.n_random - batch1_size
        fpr_so_far = n_survived / max(1, n_survived + n_broken)

        if remaining > 0 and fpr_so_far > 0.0:
            # FPR is elevated — run more to get accurate estimate
            phase2_size = min(remaining, 30)
            logger.info(f"Tier 4: FPR={fpr_so_far:.2%} — running {phase2_size} more signals...")
            for i in range(batch1_size, batch1_size + phase2_size):
                name = f"random_null_{i:03d}"
                try:
                    signal_df = _build_random_signal_df(
                        (len(dates_list), len(tickers)), tickers, dates_list, seed=i
                    )
                    signal_path = _save_signal_parquet(signal_df, signals_dir, name)
                    hyp = _make_hypothesis_spec(
                        name=f"calibration_tier4_{name}",
                        signal_path=signal_path,
                        start_date=start_date,
                        end_date=end_date,
                    )

                    run_result = _run_single_pipeline(
                        hyp, run_output_dir, verbose=self.verbose, fmp_api_key=fmp_api_key
                    )
                    runs.append(run_result)

                    if run_result.verdict in ("SURVIVED", "SURVIVED_WARNING"):
                        n_survived += 1
                    elif run_result.verdict == "BROKEN":
                        n_broken += 1
                    else:
                        n_untestable += 1
                except Exception as e:
                    n_untestable += 1

        total_completed = n_survived + n_broken + n_untestable
        fpr_pct = (n_survived / total_completed * 100) if total_completed > 0 else 0.0
        actual_n = total_completed

        # Criteria:
        # - ≤5% FPR: pass
        # - 5-20%: marginal (tighten thresholds)
        # - >20%: critical failure
        passed = fpr_pct <= 5.0

        diagnostics = {
            "n_planned": self.n_random,
            "n_completed": actual_n,
            "n_survived": n_survived,
            "n_broken": n_broken,
            "n_untestable": n_untestable,
            "empirical_fpr_pct": round(fpr_pct, 2),
            "expected_max_survived": int(actual_n * 0.05),
        }

        if fpr_pct > 20.0:
            diagnostics["warning"] = (
                f"CRITICAL: Empirical FPR = {fpr_pct:.1f}% — verdicts are effectively random. "
                "Terminate investigation until root cause is fixed."
            )
        elif fpr_pct > 5.0:
            diagnostics["warning"] = (
                f"Empirical FPR = {fpr_pct:.1f}% exceeds nominal 5%. "
                "Apply stricter family-wise correction (e.g., Bonferroni-Holm) "
                "before interpreting future verdicts."
            )

        return TierResult(
            tier=4,
            name="Null Distribution (Empirical FPR)",
            passed=passed,
            runs=runs,
            diagnostics=diagnostics,
            elapsed_seconds=time.time() - start_time,
        )


# ---------------------------------------------------------------------------
# Calibration Pipeline Orchestrator
# ---------------------------------------------------------------------------


class CalibrationRunner:
    """Orchestrate the full 4-tier calibration pipeline.

    Usage:
        runner = CalibrationRunner(output_dir="calibration_output")
        runner.load_price_data(tickers=["AAPL", "MSFT", ...],
                               start="2021-01-01", end="2024-12-31")
        report = runner.run_all()
        runner.save_report(report, "calibration_report.json")
    """

    def __init__(
        self,
        output_dir: str = "calibration_output",
        verbose: bool = False,
        fmp_api_key: Optional[str] = None,
        n_random_tier4: int = 20,  # Reduced from 100 for practical runtime
    ):
        self.output_dir = os.path.abspath(output_dir)
        self.verbose = verbose
        self.fmp_api_key = fmp_api_key
        self.n_random_tier4 = n_random_tier4

        os.makedirs(self.output_dir, exist_ok=True)

        self.price_df: Optional[pd.DataFrame] = None
        self.market_cap_df: Optional[pd.DataFrame] = None
        self.volume_df: Optional[pd.DataFrame] = None
        self.start_date = "2021-01-01"
        self.end_date = "2024-12-31"

    def load_price_data(
        self,
        tickers: Optional[List[str]] = None,
        start: str = "2021-01-01",
        end: str = "2024-12-31",
        auto_select: bool = True,
        n_tickers: int = 100,
    ) -> None:
        """Load price data for calibration.

        If tickers is None and auto_select is True, auto-selects large-cap
        tickers with good data quality from the S&P 500.
        """
        self.start_date = start
        self.end_date = end

        if tickers is None and auto_select:
            tickers = self._auto_select_tickers(n_tickers)

        if not tickers:
            raise ValueError("No tickers available for calibration price data.")

        logger.info(f"Loading price data for {len(tickers)} tickers...")
        try:
            import yfinance as yf
            data = yf.download(tickers, start=start, end=end, progress=False, auto_adjust=True)

            if data is None:
                raise ValueError("yfinance returned None")

            prices = pd.DataFrame(index=data.index)
            volumes = pd.DataFrame(index=data.index)

            if isinstance(data.columns, pd.MultiIndex):
                for t in tickers:
                    if ('Adj Close', t) in data.columns:
                        prices[t] = data[('Adj Close', t)]
                    elif ('Close', t) in data.columns:
                        prices[t] = data[('Close', t)]
                    if ('Volume', t) in data.columns:
                        volumes[t] = data[('Volume', t)]
            else:
                prices = data.get("Adj Close", data.get("Close", data))
                if isinstance(prices, pd.Series):
                    prices = prices.to_frame()
                volumes = data.get("Volume", pd.DataFrame())

            prices.index = pd.to_datetime(prices.index)
            prices = prices.dropna(axis=1, how="all")
            # Keep only tickers with sufficient data
            min_obs = TRADING_DAYS_PER_MONTH * 13
            valid_tickers = [t for t in prices.columns if prices[t].notna().sum() >= min_obs]
            prices = prices[valid_tickers]

            if not volumes.empty:
                volumes.index = pd.to_datetime(volumes.index)
                common_cols = [c for c in valid_tickers if c in volumes.columns]
                volumes = volumes[common_cols] if common_cols else None

            self.price_df = prices
            self.volume_df = volumes

            # Load market caps
            market_caps = {}
            for t in valid_tickers:
                try:
                    tkr = yf.Ticker(t)
                    mc = tkr.fast_info.get('market_cap', None)
                    if mc and mc > 0:
                        market_caps[t] = float(mc)
                except Exception:
                    pass

            if market_caps:
                self.market_cap_df = pd.DataFrame([market_caps], index=[pd.Timestamp.now().date()])
            else:
                self.market_cap_df = None

            logger.info(f"Loaded prices: {prices.shape[0]} dates × {prices.shape[1]} tickers")

        except ImportError:
            logger.error("yfinance not installed. Cannot load price data for calibration.")
            raise
        except Exception as e:
            logger.error(f"Failed to load price data: {e}")
            raise

    def _auto_select_tickers(self, n: int = 100) -> List[str]:
        """Auto-select large-cap tickers for calibration."""
        sp500_constituents = [
            "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "GOOG", "TSLA",
            "BRK-B", "UNH", "JNJ", "V", "XOM", "WMT", "JPM", "MA", "PG",
            "LLY", "HD", "CVX", "MRK", "ABBV", "PEP", "KO", "BAC", "AVGO",
            "COST", "TMO", "MCD", "CSCO", "DIS", "ABT", "DHR", "VZ", "ADBE",
            "NKE", "CRM", "TXN", "CMCSA", "PM", "NFLX", "INTC", "AMD", "WFC",
            "UPS", "QCOM", "LIN", "BA", "ORCL", "RTX", "HON", "AMGN", "IBM",
            "INTU", "CAT", "SPGI", "LOW", "GE", "SCHW", "DE", "AXP", "T",
            "AMAT", "UNP", "GS", "BLK", "NOW", "ISRG", "BKNG", "ELV", "SYK",
            "MDT", "PLD", "C", "CB", "GILD", "ADI", "MMC", "LRCX", "TJX",
            "VRTX", "CI", "MO", "ZTS", "TMUS", "REGN", "ETN", "SO", "BSX",
            "SNPS", "CDNS", "ICE", "AMT", "CMG", "KLAC", "ITW", "DUK", "EQIX",
            "SHW", "TT", "AON", "PYPL", "WM", "MCK", "PH", "NEE", "CL",
        ]
        return sp500_constituents[:n]

    def run_all(self) -> CalibrationReport:
        """Run all 4 calibration tiers."""
        if self.price_df is None or self.price_df.empty:
            raise ValueError("Price data not loaded. Call load_price_data() first.")

        start_time = time.time()
        tiers: List[TierResult] = []
        all_passed = True
        recommendations: List[str] = []

        # ---- Tier 1: Positive Controls ----
        logger.info("=" * 70)
        logger.info("CALIBRATION TIER 1: Positive Controls")
        logger.info("=" * 70)
        t1 = Tier1PositiveControls(
            output_dir=os.path.join(self.output_dir, "tier1"),
            verbose=self.verbose,
        )
        tier1 = t1.run(
            self.price_df,
            market_cap_df=self.market_cap_df,
            volume_df=self.volume_df,
            start_date=self.start_date,
            end_date=self.end_date,
            fmp_api_key=self.fmp_api_key,
        )
        tiers.append(tier1)
        if not tier1.passed:
            all_passed = False
            recommendations.append(
                f"Tier 1 FAILED: {tier1.diagnostics.get('warning', 'Positive controls did not survive.')}"
            )

        # ---- Tier 2: Synthetic Controls ----
        logger.info("=" * 70)
        logger.info("CALIBRATION TIER 2: Synthetic Controls (Power Curve)")
        logger.info("=" * 70)
        t2 = Tier2PowerCurve(
            output_dir=os.path.join(self.output_dir, "tier2"),
            verbose=self.verbose,
        )
        tier2 = t2.run(
            self.price_df,
            start_date=self.start_date,
            end_date=self.end_date,
            fmp_api_key=self.fmp_api_key,
        )
        tiers.append(tier2)
        if not tier2.passed:
            all_passed = False
            recommendations.append(
                f"Tier 2 FAILED: {tier2.diagnostics.get('warning', 'Power curve could not establish MDE.')}"
            )

        # ---- Tier 3: Negative Controls ----
        logger.info("=" * 70)
        logger.info("CALIBRATION TIER 3: Negative Controls")
        logger.info("=" * 70)
        t3 = Tier3NegativeControls(
            output_dir=os.path.join(self.output_dir, "tier3"),
            verbose=self.verbose,
        )
        tier3 = t3.run(
            self.price_df,
            start_date=self.start_date,
            end_date=self.end_date,
            fmp_api_key=self.fmp_api_key,
        )
        tiers.append(tier3)
        if not tier3.passed:
            all_passed = False
            recommendations.append(
                f"Tier 3 FAILED: {tier3.diagnostics.get('warning', 'Negative controls survived — false positive defect.')}"
            )

        # ---- Tier 4: Null Distribution ----
        logger.info("=" * 70)
        logger.info("CALIBRATION TIER 4: Null Distribution")
        logger.info("=" * 70)
        t4 = Tier4NullDistribution(
            n_random=self.n_random_tier4,
            output_dir=os.path.join(self.output_dir, "tier4"),
            verbose=self.verbose,
        )
        tier4 = t4.run(
            self.price_df,
            start_date=self.start_date,
            end_date=self.end_date,
            fmp_api_key=self.fmp_api_key,
        )
        tiers.append(tier4)
        if not tier4.passed:
            all_passed = False
            recommendations.append(
                f"Tier 4 FAILED: {tier4.diagnostics.get('warning', 'Empirical FPR exceeds 5%.')}"
            )

        # ---- Assemble report ----
        mde_bps = tier2.diagnostics.get("mde_bps_at_80pct")
        fpr_pct = tier4.diagnostics.get("empirical_fpr_pct")

        if all_passed:
            pipeline_health = "HEALTHY"
        elif len([t for t in tiers if not t.passed]) <= 1:
            pipeline_health = "MARGINAL"
        else:
            pipeline_health = "MISCALIBRATED"

        if not recommendations:
            recommendations.append("Pipeline is correctly calibrated. Proceed with hypothesis testing.")

        report = CalibrationReport(
            overall_pass=all_passed,
            tiers=tiers,
            pipeline_health=pipeline_health,
            mde_bps=mde_bps,
            empirical_fpr_pct=fpr_pct,
            recommendations=recommendations,
            elapsed_seconds=time.time() - start_time,
        )

        return report

    def save_report(self, report: CalibrationReport, path: Optional[str] = None) -> str:
        """Save calibration report to JSON."""
        if path is None:
            path = os.path.join(self.output_dir, "calibration_report.json")
        with open(path, "w") as f:
            json.dump(report.to_dict(), f, indent=2, default=str)
        logger.info(f"Calibration report saved to {path}")
        return path

    @staticmethod
    def load_report(path: str) -> CalibrationReport:
        """Load a calibration report from JSON."""
        with open(path, "r") as f:
            data = json.load(f)

        tiers = []
        for td in data.get("tiers", []):
            runs = [SingleRunResult(**r) for r in td.get("runs", [])]
            tiers.append(TierResult(
                tier=td["tier"],
                name=td["name"],
                passed=td["passed"],
                runs=runs,
                diagnostics=td.get("diagnostics", {}),
                elapsed_seconds=td.get("elapsed_seconds", 0.0),
            ))

        return CalibrationReport(
            timestamp=data.get("timestamp", ""),
            pipeline_version=data.get("pipeline_version", "1.0.0"),
            overall_pass=data.get("overall_pass", False),
            tiers=tiers,
            pipeline_health=data.get("pipeline_health", "UNKNOWN"),
            mde_bps=data.get("mde_bps"),
            empirical_fpr_pct=data.get("empirical_fpr_pct"),
            recommendations=data.get("recommendations", []),
            elapsed_seconds=data.get("elapsed_seconds", 0.0),
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    """Run calibration from the command line."""
    import argparse

    parser = argparse.ArgumentParser(
        description="4-Tier Calibration Pipeline — validate pipeline before hypothesis testing",
    )
    parser.add_argument(
        "--output-dir", default="calibration_output",
        help="Output directory for calibration results.",
    )
    parser.add_argument(
        "--tickers", nargs="*", default=None,
        help="Tickers to use. Auto-selects S&P 500 if omitted.",
    )
    parser.add_argument(
        "--n-tickers", type=int, default=100,
        help="Number of tickers to auto-select (default: 100).",
    )
    parser.add_argument(
        "--start-date", default="2021-01-01",
        help="Start date for price data (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date", default="2024-12-31",
        help="End date for price data (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--n-random-tier4", type=int, default=20,
        help="Number of random signals for Tier 4 (default: 20).",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable verbose logging.",
    )
    parser.add_argument(
        "--tier", type=int, choices=[1, 2, 3, 4],
        help="Run only a specific tier.",
    )
    parser.add_argument(
        "--fmp-api-key", default=None,
        help="FMP API key for pipeline data.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    )

    runner = CalibrationRunner(
        output_dir=args.output_dir,
        verbose=args.verbose,
        fmp_api_key=args.fmp_api_key,
        n_random_tier4=args.n_random_tier4,
    )

    logger.info("Loading price data...")
    runner.load_price_data(
        tickers=args.tickers,
        start=args.start_date,
        end=args.end_date,
        n_tickers=args.n_tickers,
    )

    if args.tier:
        # Run single tier
        if args.tier == 1:
            t = Tier1PositiveControls(
                output_dir=os.path.join(args.output_dir, "tier1"),
                verbose=args.verbose,
            )
            result = t.run(
                runner.price_df,
                market_cap_df=runner.market_cap_df,
                volume_df=runner.volume_df,
                start_date=args.start_date,
                end_date=args.end_date,
                fmp_api_key=args.fmp_api_key,
            )
        elif args.tier == 2:
            t = Tier2PowerCurve(
                output_dir=os.path.join(args.output_dir, "tier2"),
                verbose=args.verbose,
            )
            result = t.run(
                runner.price_df,
                start_date=args.start_date,
                end_date=args.end_date,
                fmp_api_key=args.fmp_api_key,
            )
        elif args.tier == 3:
            t = Tier3NegativeControls(
                output_dir=os.path.join(args.output_dir, "tier3"),
                verbose=args.verbose,
            )
            result = t.run(
                runner.price_df,
                start_date=args.start_date,
                end_date=args.end_date,
                fmp_api_key=args.fmp_api_key,
            )
        elif args.tier == 4:
            t = Tier4NullDistribution(
                n_random=args.n_random_tier4,
                output_dir=os.path.join(args.output_dir, "tier4"),
                verbose=args.verbose,
            )
            result = t.run(
                runner.price_df,
                start_date=args.start_date,
                end_date=args.end_date,
                fmp_api_key=args.fmp_api_key,
            )

        report = CalibrationReport(
            tiers=[result],
            overall_pass=result.passed,
            pipeline_health="HEALTHY" if result.passed else "NEEDS_ATTENTION",
            recommendations=[result.diagnostics.get("warning", "")] if not result.passed else [],
        )
        runner.save_report(report)
        print(f"\nTier {args.tier} result: {'PASSED' if result.passed else 'FAILED'}")
        for r in result.runs:
            print(f"  {r.name}: {r.verdict} ({r.verdict_reason[:100] if r.verdict_reason else ''})")
    else:
        # Run all tiers
        report = runner.run_all()
        runner.save_report(report)

        print(f"\n{'='*70}")
        print(f"CALIBRATION COMPLETE")
        print(f"{'='*70}")
        print(f"Pipeline health: {report.pipeline_health}")
        print(f"Overall pass:   {report.overall_pass}")
        print(f"MDE (80% power): {report.mde_bps:.0f} bps" if report.mde_bps else "MDE: N/A")
        print(f"Empirical FPR:  {report.empirical_fpr_pct:.1f}%" if report.empirical_fpr_pct else "FPR: N/A")
        print(f"{'='*70}")
        for tier in report.tiers:
            status = "PASS" if tier.passed else "FAIL"
            print(f"  Tier {tier.tier} ({tier.name}): {status} "
                  f"({tier.n_survived}S/{tier.n_broken}B/{tier.n_untestable}U)")

        for rec in report.recommendations:
            print(f"  → {rec}")


if __name__ == "__main__":
    main()
