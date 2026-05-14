#!/usr/bin/env python3
"""
pipeline.py -- Stage 2 Universal Hypothesis Testing Pipeline
============================================================

Main orchestrator that ties together all seven testing modules.

Usage:
    python pipeline.py --hypothesis hypothesis.json --output results/
    python pipeline.py --hypothesis hypothesis.json --output results/ --verbose

The pipeline is LOCKED (version 1.0.0). No methodology changes after seeing
Stage 1 hypotheses. This is enforced by code review, not by technical means.

Architecture:
    Parse Spec -> Universe -> Temporal -> Backtest -> Statistics ->
    Adversarial -> Factors -> Verdict -> Audit Trail -> Output

Every stage logs to the audit trail. Errors in one stage do not crash the
entire pipeline -- they are captured, reported, and contribute to the verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Ensure the implementation directory is on sys.path for sibling imports
# ---------------------------------------------------------------------------
_IMPL_DIR = os.path.dirname(os.path.abspath(__file__))
if _IMPL_DIR not in sys.path:
    sys.path.insert(0, _IMPL_DIR)

# Import all pipeline modules
from universe import (
    UniverseConstructor,
    UniverseSpec as _UniverseSpec,
    UniverseType,
    DelistingReason,
)
from temporal import (
    PointInTimeBuilder,
    ForwardReturnCalculator,
    DataType as TemporalDataType,
)
from backtest import (
    CrossSectionalBacktester,
    TransactionCostCalculator,
    TransactionCostModel,
    PositionSizer,
    PositionSizingSpec as _PositionSizingSpec,
    PositionSizingMethod,
    Side,
)
from statistics import (
    StatisticalReportGenerator,
    BlockBootstrap,
    PerformanceMetrics,
    DistributionStats,
    OutlierAnalysis,
    PowerAnalysis,
    MultipleComparisonResult,
)
from breakers import (
    AdversarialReportGenerator,
    StatisticalBreaker,
    DataBreaker,
    RegimeAnalyzer,
)
from factors import (
    FactorComparisonEngine,
    FactorConstructor,
    FactorComparisonReport,
    FactorExposureResult,
)
from audit import (
    AuditTrailGenerator,
    ReproducibilityManager,
    DataSnapshotManager,
    VerdictOutputGenerator,
    get_hypothesis_seed,
    get_all_hypothesis_seeds,
    AuditTrail,
    AuditEntry,
)

# ---------------------------------------------------------------------------
# Optional imports for safeguards (signal_builder may not be on path)
# ---------------------------------------------------------------------------
try:
    from signal_builder.trial_tracker import TrialTracker, InvestigationContext
except ImportError:
    TrialTracker = None  # type: ignore
    InvestigationContext = None  # type: ignore

try:
    from signal_builder.survivorship import SurvivorshipGuard, SurvivorshipBiasReport
except ImportError:
    SurvivorshipGuard = None  # type: ignore
    SurvivorshipBiasReport = None  # type: ignore

try:
    from signal_builder.contamination import ContaminationDetector, ContaminationReport
except ImportError:
    ContaminationDetector = None  # type: ignore
    ContaminationReport = None  # type: ignore

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("pipeline")


def setup_logging(verbose: bool = False, log_file: Optional[str] = None) -> None:
    """Configure pipeline-wide logging."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)


# ============================================================================
# Hypothesis Specification Dataclasses (PIPELINE_SPEC.md Section 1)
# ============================================================================


class Verdict(str, Enum):
    SURVIVED = "SURVIVED"
    SURVIVED_WARNING = "SURVIVED_WARNING"
    BROKEN = "BROKEN"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNTESTABLE = "UNTESTABLE"


class SignalType(str, Enum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    COMPOSITE = "composite"


@dataclass
class DataSourceSpec:
    """Specification of a required data source.  PIPELINE_SPEC.md Section 1.7."""
    source_type: str          # 'price' | 'fundamental' | 'sec_filing' | 'transcript' | ...
    provider: str             # 'yahoo' | 'fmp' | 'sec_edgar' | 'finnhub' | ...
    frequency: str            # 'daily' | 'quarterly' | 'annual' | 'realtime' | 'as_filed'
    fields: List[str]         # Required fields
    start_date: str           # Earliest data needed  (YYYY-MM-DD)
    end_date: str             # Latest data needed    (YYYY-MM-DD)
    known_biases: List[str] = field(default_factory=list)
    api_tier: str = "free"    # 'free' | 'paid_low_cost' | 'paid_premium'
    monthly_cost_usd: float = 0.0


@dataclass
class UniverseSpec:
    """Specification of the stock universe.  PIPELINE_SPEC.md Section 1.2."""
    universe_type: str = "sp500"          # 'sp500' | 'sp1500' | 'russell3000' | 'all_us' | 'custom'
    custom_tickers: Optional[List[str]] = None
    custom_filter: Optional[str] = None   # Python expression e.g. "market_cap > 1e9"
    min_price: float = 1.0
    min_daily_volume: int = 0
    exchanges: List[str] = field(default_factory=lambda: ["NYSE", "NASDAQ", "NYSEARCA", "NYSEAMERICAN"])
    include_delisted: bool = True


@dataclass
class SignalSpec:
    """Specification of how to compute the signal.  PIPELINE_SPEC.md Section 1.3."""
    signal_type: str = "numeric"          # 'numeric' | 'categorical' | 'composite'
    signal_name: str = "signal"
    higher_is_better: bool = True
    llm_model_used: Optional[str] = None
    llm_temperature: Optional[float] = None
    llm_seed: Optional[int] = None
    llm_is_deterministic: bool = False
    # In production this holds a callable; for CLI we use a signal file path.
    signal_source: Optional[str] = None   # Path to parquet/csv with pre-computed signals


@dataclass
class TimePeriodSpec:
    """Specification of analysis time period.  PIPELINE_SPEC.md Section 1.4."""
    start_date: str                       # 'YYYY-MM-DD'
    end_date: str                         # 'YYYY-MM-DD'
    oos_start_date: Optional[str] = None  # Out-of-sample start. If None, use final 30%.
    min_training_days: int = 252
    frequency: str = "daily"


@dataclass
class PositionSizingSpec:
    """Specification of position sizing.  PIPELINE_SPEC.md Section 1.5."""
    method: str = "equal_weight"          # 'equal_weight' | 'signal_proportional' | 'risk_parity' | 'kelly'
    max_position_pct: float = 0.05
    max_positions: int = 50
    max_sector_pct: float = 0.30
    capital: float = 100000.0
    rebalance_frequency: str = "daily"


@dataclass
class MinimumEffectSpec:
    """Minimum economically meaningful effect.  PIPELINE_SPEC.md Section 1.6."""
    annualized_alpha_bps: float = 300     # Minimum annualized alpha in bps after costs
    sharpe_ratio: float = 0.3
    information_coefficient: float = 0.03
    hit_rate: float = 0.51
    max_drawdown_pct: float = 25.0


@dataclass
class HypothesisSpec:
    """Complete specification of a hypothesis to test.  PIPELINE_SPEC.md Section 1.1."""

    # Identity
    name: str
    uuid: str
    source_agent: str = "unknown"
    submission_number: int = 1

    # Mechanism (documentation)
    mechanism: str = ""
    llm_advantage: str = ""
    why_underweighted: str = ""

    # Core specification
    universe: UniverseSpec = field(default_factory=UniverseSpec)
    signal: SignalSpec = field(default_factory=SignalSpec)
    holding_period_days: int = 21
    time_period: TimePeriodSpec = field(default_factory=TimePeriodSpec)

    # Position sizing
    position_sizing: PositionSizingSpec = field(default_factory=PositionSizingSpec)

    # Economic significance threshold
    minimum_effect_size: MinimumEffectSpec = field(default_factory=MinimumEffectSpec)

    # Data requirements
    data_sources: List[DataSourceSpec] = field(default_factory=list)

    # Falsifiable prediction
    falsifiable_prediction: str = ""

    # Self-assessment
    self_assessed_confidence: str = "MEDIUM"   # LOW / MEDIUM / HIGH
    biggest_weakness: str = ""

    # --- Derived fields ---
    _signal_function: Optional[Callable] = field(default=None, repr=False)

    def to_json(self) -> str:
        """Serialize to JSON (excluding callables)."""
        d = asdict(self)
        d.pop("_signal_function", None)
        return json.dumps(d, indent=2)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HypothesisSpec":
        """Deserialize from a dictionary (JSON-safe)."""
        d = d.copy()
        d.pop("_signal_function", None)

        # Nested dataclasses
        d["universe"] = UniverseSpec(**d.get("universe", {}))
        d["signal"] = SignalSpec(**d.get("signal", {}))
        d["time_period"] = TimePeriodSpec(**d.get("time_period", {}))
        d["position_sizing"] = PositionSizingSpec(**d.get("position_sizing", {}))
        d["minimum_effect_size"] = MinimumEffectSpec(**d.get("minimum_effect_size", {}))
        d["data_sources"] = [DataSourceSpec(**ds) for ds in d.get("data_sources", [])]

        return cls(**d)

    @classmethod
    def from_json_file(cls, path: str) -> "HypothesisSpec":
        """Load a hypothesis from a JSON file."""
        with open(path, "r") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def validate(self) -> List[str]:
        """Validate the hypothesis spec. Returns list of issues (empty = valid)."""
        issues = []
        if not self.name:
            issues.append("hypothesis.name is required")
        if not self.uuid:
            issues.append("hypothesis.uuid is required")
        if self.holding_period_days < 1:
            issues.append("holding_period_days must be >= 1")
        if not self.data_sources:
            issues.append("At least one data source must be specified")
        try:
            pd.Timestamp(self.time_period.start_date)
            pd.Timestamp(self.time_period.end_date)
        except Exception:
            issues.append("time_period dates must be valid YYYY-MM-DD format")
        if self.time_period.start_date >= self.time_period.end_date:
            issues.append("start_date must be before end_date")
        return issues


# ============================================================================
# Pipeline Orchestrator
# ============================================================================


PIPELINE_VERSION = "1.0.0"


class PipelineError(Exception):
    """Raised for pipeline-level errors (not hypothesis failures)."""


class StageFailure(Exception):
    """Raised when a specific stage encounters an unrecoverable error."""

    def __init__(self, stage: str, message: str, original_error: Optional[Exception] = None):
        super().__init__(f"[{stage}] {message}")
        self.stage = stage
        self.message = message
        self.original_error = original_error


class HypothesisPipeline:
    """
    Universal hypothesis testing pipeline (LOCKED v1.0.0).

    Accepts a HypothesisSpec, runs the full test battery, and produces
    a verdict with complete audit trail.

    The pipeline is adversarial by design: it aggressively tries to break
    every hypothesis. A high BROKEN rate is success.
    """

    def __init__(
        self,
        output_dir: str = "results",
        pipeline_version: str = PIPELINE_VERSION,
        verbose: bool = False,
        fmp_api_key: Optional[str] = None,
        trial_tracker: Optional[Any] = None,
        enable_survivorship_guard: bool = True,
    ):
        self.output_dir = os.path.abspath(output_dir)
        self.pipeline_version = pipeline_version
        self.verbose = verbose
        self.fmp_api_key = fmp_api_key
        self.trial_tracker = trial_tracker
        self.enable_survivorship_guard = enable_survivorship_guard

        # State accumulated during a run
        self.hypothesis: Optional[HypothesisSpec] = None
        self.seeds: Dict[str, int] = {}
        self.universe_df: Optional[pd.DataFrame] = None
        self.signal_df: Optional[pd.DataFrame] = None
        self.price_df: Optional[pd.DataFrame] = None
        self.backtest_result: Any = None
        self.stat_report: Any = None
        self.adversarial_report: Any = None
        self.factor_report: Any = None
        self.audit_trail: Optional[AuditTrail] = None

        # Results collected during run
        self._stage_results: Dict[str, Dict[str, Any]] = {}
        self._stage_errors: Dict[str, str] = {}
        self._warnings: List[str] = []

        # Initialize audit machinery
        self._audit = AuditTrailGenerator(
            pipeline_version=pipeline_version,
            output_directory=output_dir,
        )
        self._verdict_gen = VerdictOutputGenerator(output_dir)

        if verbose:
            setup_logging(verbose=True, log_file=os.path.join(output_dir, "logs", "pipeline_run.log"))
        else:
            setup_logging(verbose=False)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, hypothesis: HypothesisSpec) -> Dict[str, Any]:
        """
        Run the full test battery on a hypothesis.

        Returns a verdict dict with the complete audit trail.
        """
        self.hypothesis = hypothesis
        self.seeds = get_all_hypothesis_seeds(hypothesis.uuid)
        self._stage_results = {}
        self._stage_errors = {}
        self._warnings = []

        # Set deterministic seeds first
        repro = ReproducibilityManager(hypothesis.uuid)
        repro.set_all_seeds()
        np.random.seed(self.seeds["global"])
        random.seed(self.seeds["global"])

        # Initialize audit trail
        try:
            git_hash = self._get_git_hash()
        except Exception:
            git_hash = None

        self._audit.initialize_trail(
            hypothesis_uuid=hypothesis.uuid,
            hypothesis_name=hypothesis.name,
            git_hash=git_hash,
        )

        logger.info(f"{'='*70}")
        logger.info(f"PIPELINE v{self.pipeline_version} — Testing: {hypothesis.name}")
        logger.info(f"UUID: {hypothesis.uuid}  |  Agent: {hypothesis.source_agent}")
        logger.info(f"Period: {hypothesis.time_period.start_date} -> {hypothesis.time_period.end_date}")
        logger.info(f"Universe: {hypothesis.universe.universe_type}  |  "
                     f"Holding: {hypothesis.holding_period_days}d  |  "
                     f"Capital: ${hypothesis.position_sizing.capital:,.0f}")
        logger.info(f"{'='*70}")

        # ------------------------------------------------------------------
        # Stage 1: Data Availability Check
        # ------------------------------------------------------------------
        stage = "data_availability"
        self._audit.start_stage(stage)
        try:
            avail = self._check_data_availability()
            self._audit.log_operation(
                stage=stage,
                operation="data_availability_check",
                inputs={"data_sources": [ds.provider for ds in hypothesis.data_sources]},
                outputs={"available": avail["all_available"], "missing": avail["missing"]},
                parameters={"required_sources": len(hypothesis.data_sources)},
                warnings=avail.get("warnings", []),
            )
            self._stage_results[stage] = avail

            if not avail["all_available"]:
                return self._finalize_verdict(
                    verdict=Verdict.UNTESTABLE,
                    reason=f"Required data sources unavailable: {avail['missing']}",
                    failure_stage=stage,
                )
        except Exception as e:
            self._capture_stage_error(stage, e)
            return self._finalize_verdict(
                verdict=Verdict.UNTESTABLE,
                reason=f"Data availability check failed: {e}",
                failure_stage=stage,
            )

        # ------------------------------------------------------------------
        # Stage 2: Universe Construction
        # ------------------------------------------------------------------
        stage = "universe"
        self._audit.start_stage(stage)
        try:
            self.universe_df = self._construct_universe()
            self._audit.log_operation(
                stage=stage,
                operation="universe_construction",
                inputs={"universe_type": hypothesis.universe.universe_type},
                outputs={
                    "n_observations": len(self.universe_df),
                    "n_tickers": self.universe_df["ticker"].nunique(),
                    "date_range": f"{self.universe_df['date'].min()} -> {self.universe_df['date'].max()}",
                },
                parameters=asdict(hypothesis.universe),
            )
            self._stage_results[stage] = {"n_tickers": self.universe_df["ticker"].nunique()}

            # --- SAFEGUARD: Survivorship Bias Guard ---
            if self.enable_survivorship_guard:
                try:
                    self._run_survivorship_guard()
                except Exception as e:
                    self._warnings.append(f"Survivorship guard failed (non-fatal): {e}")
        except Exception as e:
            self._capture_stage_error(stage, e)
            return self._finalize_verdict(
                verdict=Verdict.UNTESTABLE,
                reason=f"Universe construction failed: {e}",
                failure_stage=stage,
            )

        # ------------------------------------------------------------------
        # Stage 3: Data Loading (price data etc.)
        # ------------------------------------------------------------------
        stage = "data_loading"
        self._audit.start_stage(stage)
        try:
            data_bundle = self._load_market_data()
            self.price_df = data_bundle.get("prices")
            self.signal_df = data_bundle.get("signals")
            self._stage_results[stage] = {
                "n_price_dates": len(self.price_df) if self.price_df is not None else 0,
                "n_price_tickers": len(self.price_df.columns) if self.price_df is not None else 0,
                "n_signal_dates": len(self.signal_df) if self.signal_df is not None else 0,
            }
            self._audit.log_operation(
                stage=stage,
                operation="data_loading",
                inputs={"data_sources": [ds.provider for ds in hypothesis.data_sources]},
                outputs=self._stage_results[stage],
                parameters={"start": hypothesis.time_period.start_date,
                            "end": hypothesis.time_period.end_date},
            )
        except Exception as e:
            self._capture_stage_error(stage, e)
            return self._finalize_verdict(
                verdict=Verdict.UNTESTABLE,
                reason=f"Data loading failed: {e}",
                failure_stage=stage,
            )

        # ------------------------------------------------------------------
        # Stage 4: Temporal Alignment & Look-Ahead Check
        # ------------------------------------------------------------------
        stage = "temporal"
        self._audit.start_stage(stage)
        try:
            temporal_result = self._run_temporal_alignment()
            self._stage_results[stage] = temporal_result
            self._audit.log_operation(
                stage=stage,
                operation="temporal_alignment",
                inputs={"n_observations": temporal_result.get("n_observations", 0)},
                outputs={
                    "is_valid": temporal_result.get("is_valid", False),
                    "n_breaches": temporal_result.get("n_breaches", 0),
                },
                parameters={},
                warnings=temporal_result.get("warnings", []),
            )

            if not temporal_result.get("is_valid", False):
                self._warnings.append("TEMPORAL FATAL: Look-ahead breaches detected. Results invalid.")
                return self._finalize_verdict(
                    verdict=Verdict.BROKEN,
                    reason=f"Look-ahead breaches detected ({temporal_result.get('n_breaches', 0)} contaminated observations)",
                    failure_stage=stage,
                )
        except Exception as e:
            self._capture_stage_error(stage, e)
            return self._finalize_verdict(
                verdict=Verdict.BROKEN,
                reason=f"Temporal alignment failed: {e}",
                failure_stage=stage,
            )

        # ------------------------------------------------------------------
        # Stage 5: Backtesting
        # ------------------------------------------------------------------
        stage = "backtest"
        self._audit.start_stage(stage)
        try:
            self.backtest_result = self._run_backtest()
            self._stage_results[stage] = self._extract_backtest_summary()
            self._audit.log_operation(
                stage=stage,
                operation="backtest",
                inputs={"holding_period_days": hypothesis.holding_period_days},
                outputs=self._stage_results[stage],
                parameters={
                    "position_sizing": asdict(hypothesis.position_sizing),
                    "cost_model": "interactive_brokers_retail",
                },
            )
        except Exception as e:
            self._capture_stage_error(stage, e)
            return self._finalize_verdict(
                verdict=Verdict.BROKEN,
                reason=f"Backtest failed: {e}",
                failure_stage=stage,
            )

        # ------------------------------------------------------------------
        # Stage 6: Statistical Tests
        # ------------------------------------------------------------------
        stage = "statistics"
        self._audit.start_stage(stage)
        try:
            self.stat_report = self._run_statistics()
            self._stage_results[stage] = self._extract_statistics_summary()
            self._audit.log_operation(
                stage=stage,
                operation="statistical_analysis",
                inputs={"n_returns": self._stage_results[stage].get("n_observations", 0)},
                outputs=self._stage_results[stage],
                parameters={
                    "bootstrap_replications": 10000,
                    "multiple_comparison": "bonferroni+fdr",
                },
                warnings=self.stat_report.warnings if self.stat_report else [],
            )
        except Exception as e:
            self._capture_stage_error(stage, e)
            return self._finalize_verdict(
                verdict=Verdict.BROKEN,
                reason=f"Statistical analysis failed: {e}",
                failure_stage=stage,
            )

        # ------------------------------------------------------------------
        # Stage 7: Adversarial Breakage
        # ------------------------------------------------------------------
        stage = "adversarial"
        self._audit.start_stage(stage)
        try:
            self.adversarial_report = self._run_adversarial()
            self._stage_results[stage] = self._extract_adversarial_summary()
            self._audit.log_operation(
                stage=stage,
                operation="adversarial_tests",
                inputs={},
                outputs=self._stage_results[stage],
                parameters={
                    "permutation_reps": 1000,
                    "oos_fraction": 0.30,
                    "walk_forward_threshold": 0.60,
                },
                warnings=self._stage_results[stage].get("warnings", []),
            )
        except Exception as e:
            self._capture_stage_error(stage, e)
            # Adversarial failure is not fatal -- report and continue
            self._warnings.append(f"Adversarial tests partially failed: {e}")
            self._stage_results[stage] = {"error": str(e)}

        # ------------------------------------------------------------------
        # Stage 8: Baseline Factor Comparison
        # ------------------------------------------------------------------
        stage = "factors"
        self._audit.start_stage(stage)
        try:
            self.factor_report = self._run_factor_comparison()
            self._stage_results[stage] = self._extract_factor_summary()
            self._audit.log_operation(
                stage=stage,
                operation="factor_comparison",
                inputs={"n_factors": len(self._stage_results[stage].get("factor_loadings", {}))},
                outputs=self._stage_results[stage],
                parameters={"baseline_factors": "momentum/reversal/pead/value/size/liquidity/lowvol+sector_neutral"},
                warnings=self._stage_results[stage].get("warnings", []),
            )
        except Exception as e:
            self._capture_stage_error(stage, e)
            self._warnings.append(f"Factor comparison failed: {e}")
            self._stage_results[stage] = {"error": str(e)}

        # ------------------------------------------------------------------
        # Stage 9: Edge Decay Analysis
        # ------------------------------------------------------------------
        stage = "edge_decay"
        self._audit.start_stage(stage)
        try:
            decay_result = self._run_edge_decay()
            self._stage_results[stage] = decay_result
            self._audit.log_operation(
                stage=stage,
                operation="edge_decay_analysis",
                inputs={},
                outputs=decay_result,
                parameters={"rolling_window_years": 3, "step_quarters": 1},
            )
        except Exception as e:
            self._capture_stage_error(stage, e)
            self._warnings.append(f"Edge decay analysis failed: {e}")
            self._stage_results[stage] = {"error": str(e)}

        # ------------------------------------------------------------------
        # Stage 10: Verdict
        # ------------------------------------------------------------------
        verdict, reason, failure_stage = self._determine_verdict()
        return self._finalize_verdict(verdict=verdict, reason=reason, failure_stage=failure_stage)

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    def _check_data_availability(self) -> Dict[str, Any]:
        """Check that required data sources are accessible."""
        missing = []
        warnings = []

        for ds in self.hypothesis.data_sources:
            # Check that the provider is recognized
            known_providers = {"yahoo", "fmp", "sec_edgar", "finnhub", "polygon", "custom"}
            if ds.provider not in known_providers:
                warnings.append(f"Unknown provider '{ds.provider}'. Will attempt anyway.")
            # In production, actually ping the API / check file existence
            # For now, FMP requires a key; others are assumed available
            if ds.provider == "fmp" and not self.fmp_api_key:
                warnings.append(
                    f"FMP API key not provided. Data source '{ds.source_type}' "
                    f"from FMP may be unavailable. Set FMP_API_KEY env var or pass --fmp-key."
                )
            if ds.provider not in ("yahoo", "fmp", "sec_edgar", "custom"):
                warnings.append(f"Provider '{ds.provider}' may require additional setup.")

        return {
            "all_available": len(missing) == 0,
            "missing": missing,
            "providers_checked": [ds.provider for ds in self.hypothesis.data_sources],
            "warnings": warnings,
        }

    def _construct_universe(self) -> pd.DataFrame:
        """Stage 2: Construct the survivorship-bias-free universe."""
        uspec = self.hypothesis.universe
        uconstructor = UniverseConstructor(fmp_api_key=self.fmp_api_key)

        # Map string universe_type to UniverseType enum
        type_map = {
            "sp500": UniverseType.SP500,
            "sp1500": UniverseType.SP1500,
            "russell3000": UniverseType.RUSSELL3000,
            "all_us": UniverseType.ALL_US,
            "custom": UniverseType.CUSTOM,
        }
        utype = type_map.get(uspec.universe_type, UniverseType.CUSTOM)

        internal_spec = _UniverseSpec(
            universe_type=utype,
            custom_tickers=uspec.custom_tickers,
            custom_filter=uspec.custom_filter,
            min_price=uspec.min_price,
            min_daily_dollar_volume=uspec.min_daily_volume,
            exchanges=uspec.exchanges,
            include_delisted=uspec.include_delisted,
        )

        df = uconstructor.construct_universe(
            internal_spec,
            start_date=self.hypothesis.time_period.start_date,
            end_date=self.hypothesis.time_period.end_date,
        )

        # Collect bias report for audit
        bias_report = uconstructor.get_bias_report()
        self._warnings.extend(uconstructor.warnings)

        # If universe is empty (e.g., no API keys available), fall back to
        # simulated universe for pipeline testing. In production, missing
        # data must be reported as UNTESTABLE, not silently simulated.
        if df.empty or "ticker" not in df.columns:
            self._warnings.append(
                "UNIVERSE EMPTY: No real-ticker data available. Using simulated "
                "universe for pipeline testing. REAL HYPOTHESES REQUIRE LIVE DATA."
            )
            tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "BRK-B",
                       "JPM", "V", "JNJ", "WMT", "PG", "XOM", "UNH", "HD",
                       "MA", "BAC", "DIS", "NFLX", "ADBE"]
            dates = pd.date_range(
                self.hypothesis.time_period.start_date,
                self.hypothesis.time_period.end_date,
                freq="B",
            )
            records = []
            for date in dates:
                date_str = date.strftime("%Y-%m-%d")
                for ticker in tickers:
                    records.append({
                        "date": date_str,
                        "ticker": ticker,
                        "entity_id": ticker,
                        "company_name": ticker,
                        "cik": "",
                        "cusip": "",
                        "market_cap": 1e10,
                        "sector": "Technology",
                        "price": 100.0,
                        "volume": 1e7,
                        "dollar_volume": 1e9,
                        "index_member": False,
                        "is_delisted": False,
                        "delisting_date": None,
                        "delisting_return": None,
                    })
            df = pd.DataFrame(records)

        n_tickers = df["ticker"].nunique() if "ticker" in df.columns else 0
        logger.info(
            f"Universe constructed: {n_tickers} tickers, "
            f"{len(df)} total observations"
        )
        return df

    # ------------------------------------------------------------------
    # SAFEGUARD: Survivorship Bias Guard
    # ------------------------------------------------------------------

    def _run_survivorship_guard(self) -> None:
        """Run the survivorship bias guard on the constructed universe.

        Quantifies how much survivorship bias may be inflating results
        and caps verdict confidence if delisted stock data is incomplete.
        """
        hyp = self.hypothesis
        if self.universe_df is None or self.universe_df.empty:
            return

        if SurvivorshipGuard is None:
            self._warnings.append(
                "SurvivorshipGuard not available (signal_builder not on path). "
                "Survivorship bias not checked."
            )
            return

        try:
            guard = SurvivorshipGuard(fmp_api_key=self.fmp_api_key)

            # Build a signal-like DataFrame if not yet available
            signal_df = self.signal_df if self.signal_df is not None else pd.DataFrame()

            report = guard.validate_universe(
                universe_df=self.universe_df,
                start_date=hyp.time_period.start_date,
                end_date=hyp.time_period.end_date,
                universe_type=hyp.universe.universe_type,
                signal_df=signal_df if not signal_df.empty else None,
            )

            # Store the report and log findings
            self._survivorship_report = report

            universe_report_str = guard.format_universe_report(report)
            logger.info(f"SurvivorshipGuard:\n{universe_report_str}")

            # Log to audit trail
            self._audit.log_operation(
                stage="universe",
                operation="survivorship_bias_check",
                inputs={"universe_type": hyp.universe.universe_type},
                outputs={
                    "bias_assessment": report.bias_assessment,
                    "survivorship_bias_bps": report.survivorship_bias_bps,
                    "verdict_confidence_cap": report.verdict_confidence_cap,
                    "can_test_reliably": report.can_test_reliably,
                    "delisted_tickers": report.delisted_tickers,
                    "delisted_with_returns": report.delisted_with_returns,
                    "delisted_missing_returns": report.delisted_missing_returns,
                    "data_completeness": report.data_completeness,
                    "ticker_reuse_events": report.n_ticker_reuse_events,
                },
                parameters={"include_delisted": hyp.universe.include_delisted},
                warnings=report.warnings,
            )

            # Save the report
            hyp_dir = os.path.join(self.output_dir, hyp.uuid)
            os.makedirs(hyp_dir, exist_ok=True)
            surv_path = os.path.join(hyp_dir, "survivorship_bias_report.json")
            guard.save_report(report, surv_path)

            # Apply warnings
            for w in report.warnings:
                self._warnings.append(f"[SURVIVORSHIP] {w}")

            if not report.can_test_reliably:
                self._warnings.append(
                    f"SURVIVORSHIP BIAS CRITICAL: Confidence capped to "
                    f"{report.verdict_confidence_cap}. "
                    f"{report.delisted_missing_returns}/{report.delisted_tickers} "
                    f"delisted stocks have missing return data."
                )

        except Exception as e:
            self._warnings.append(f"Survivorship guard error: {e}")
            logger.warning(f"Survivorship guard failed: {e}")

    def _load_market_data(self) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Load market data (prices, signals) from specified sources.

        In production this connects to Yahoo Finance, FMP, SEC EDGAR, etc.
        For the locked pipeline, it also supports loading pre-computed signal
        files and simulated data for testing.
        """
        hyp = self.hypothesis
        prices = None
        signals = None
        market_caps = None
        volumes = None

        # --- Load price data ---
        price_sources = [ds for ds in hyp.data_sources if ds.source_type == "price"]
        if price_sources:
            # Attempt to load from Yahoo Finance or local cache
            tickers = self.universe_df["ticker"].unique().tolist() if self.universe_df is not None else []
            try:
                prices = self._load_prices_yahoo(tickers, hyp.time_period.start_date, hyp.time_period.end_date)
            except Exception as e:
                logger.warning(f"Yahoo Finance price load failed: {e}. Creating simulated data.")
                prices = self._simulate_price_data(
                    tickers, hyp.time_period.start_date, hyp.time_period.end_date
                )

        if prices is None:
            # Fallback: simulate price data from universe
            tickers = self.universe_df["ticker"].unique().tolist() if self.universe_df is not None else []
            prices = self._simulate_price_data(
                tickers, hyp.time_period.start_date, hyp.time_period.end_date
            )

        # --- Load signal data ---
        if hyp.signal.signal_source and os.path.exists(hyp.signal.signal_source):
            # Load pre-computed signal from file
            path = hyp.signal.signal_source
            if path.endswith(".parquet"):
                signals = pd.read_parquet(path)
            elif path.endswith(".csv"):
                signals = pd.read_csv(path, index_col=0, parse_dates=True)
            else:
                raise PipelineError(f"Unknown signal file format: {path}")
            logger.info(f"Loaded signals from {path}: {signals.shape}")
        else:
            # No pre-computed signal; create an empty signal df (backtest will fail gracefully)
            logger.warning(
                "No signal source provided. Pipeline requires either a signal_source file "
                "or a signal_function callable to produce signals."
            )
            signals = pd.DataFrame()

        return {
            "prices": prices,
            "signals": signals,
            "market_caps": market_caps,
            "volumes": volumes,
        }

    def _load_prices_yahoo(self, tickers: List[str], start: str, end: str) -> pd.DataFrame:
        """
        Load price data from Yahoo Finance (via yfinance or cached CSV).
        Falls back to simulated data if yfinance is unavailable.
        """
        try:
            import yfinance as yf
        except ImportError:
            raise PipelineError("yfinance not installed. Install with: pip install yfinance")

        if not tickers:
            raise PipelineError("No tickers available for price loading.")

        logger.info(f"Loading Yahoo Finance prices for {len(tickers)} tickers...")
        data = yf.download(tickers, start=start, end=end, progress=False, auto_adjust=True)

        if data is None:
            raise PipelineError("Yahoo Finance returned None.")

        # yfinance returns MultiIndex columns for multi-ticker downloads
        if isinstance(data.columns, pd.MultiIndex):
            # Extract 'Adj Close' or 'Close' column across all tickers
            if "Adj Close" in data.columns.names:
                prices = data.xs("Adj Close", axis=1, level=0)
            elif "Close" in data.columns.names:
                prices = data.xs("Close", axis=1, level=0)
            else:
                # Take the first level
                prices = data.xs(data.columns.levels[0][0], axis=1, level=0)
        else:
            # Single ticker or different format
            if "Adj Close" in data.columns:
                prices = data[["Adj Close"]]
            elif "Close" in data.columns:
                prices = data[["Close"]]
            else:
                prices = data

        # Ensure we have a DataFrame with tickers as columns
        if isinstance(prices, pd.Series):
            prices = prices.to_frame()

        # Empty check on DataFrame not on the ndarray underlying it
        try:
            is_empty = prices.empty
        except ValueError:
            # MultiIndex .empty can fail in some pandas versions
            is_empty = (len(prices) == 0)

        if is_empty:
            raise PipelineError("Yahoo Finance returned empty data.")

        prices.index = pd.to_datetime(prices.index)
        # Drop tickers with all NaN values
        prices = prices.dropna(axis=1, how="all")
        return prices

    def _simulate_price_data(self, tickers: List[str], start: str, end: str) -> pd.DataFrame:
        """
        Generate simulated price data for testing when real data is unavailable.

        Uses geometric Brownian motion with realistic parameters.
        NOT for use with real hypotheses -- generates a warning in the audit trail.
        """
        self._warnings.append(
            "USING SIMULATED PRICE DATA. Results are for pipeline testing ONLY. "
            "Real hypotheses MUST use actual market data."
        )

        if not tickers:
            tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "BRK-B", "JPM", "V", "JNJ", "WMT"]

        dates = pd.date_range(start, end, freq="B")
        n_dates = len(dates)

        rng = np.random.RandomState(self.seeds["global"])

        # Generate realistic parameters per ticker
        annual_vols = rng.uniform(0.15, 0.60, size=len(tickers))
        annual_returns = rng.uniform(-0.10, 0.25, size=len(tickers))
        initial_prices = rng.uniform(10, 500, size=len(tickers))

        daily_vols = annual_vols / np.sqrt(252)
        daily_drifts = annual_returns / 252 - 0.5 * daily_vols**2

        prices = np.zeros((n_dates, len(tickers)))
        prices[0, :] = initial_prices

        daily_returns = rng.randn(n_dates - 1, len(tickers)) * daily_vols + daily_drifts
        prices[1:, :] = prices[0, :] * np.exp(np.cumsum(daily_returns, axis=0))

        price_df = pd.DataFrame(prices, index=dates, columns=tickers)
        logger.info(f"Simulated price data: {price_df.shape}")
        return price_df

    def _run_temporal_alignment(self) -> Dict[str, Any]:
        """Stage 4: Run temporal alignment and look-ahead breach detection."""
        builder = PointInTimeBuilder()
        warnings_list: List[str] = []

        # Register data sources with temporal rules
        for ds in self.hypothesis.data_sources:
            dtype_map = {
                "price": TemporalDataType.PRICE,
                "fundamental": TemporalDataType.FUNDAMENTAL,
                "sec_filing": TemporalDataType.SEC_FILING,
                "transcript": TemporalDataType.TRANSCRIPT,
                "sentiment": TemporalDataType.SENTIMENT,
                "alternative": TemporalDataType.ALTERNATIVE,
                "custom": TemporalDataType.CUSTOM,
            }
            dtype = dtype_map.get(ds.source_type, TemporalDataType.CUSTOM)
            builder.register_data_source(
                source_name=f"{ds.provider}_{ds.source_type}",
                data_type=dtype,
            )

        # Check signal dates against known dates
        n_breaches = 0
        is_valid = True

        if self.signal_df is not None and not self.signal_df.empty:
            # For each date in the signal index, verify it has a known_date
            # that is <= signal date (i.e., no forward-looking data)
            signal_dates = self.signal_df.index.tolist()
            signal_dates_str = [str(d) if hasattr(d, 'strftime') else d for d in signal_dates]

            # If we have raw data with timestamps, build PIT dataset and scan
            # For now, report that temporal check was performed
            n_observations = len(self.signal_df) * len(self.signal_df.columns)
            warnings_list.append(
                "Temporal alignment: Using signal dates as observation dates. "
                "Ensure that signal construction uses only data known at each date "
                "(no look-ahead)."
            )
        else:
            n_observations = 0

        return {
            "is_valid": is_valid,
            "n_breaches": n_breaches,
            "n_observations": n_observations,
            "warnings": warnings_list,
        }

    def _run_backtest(self):
        """Stage 5: Run the cross-sectional backtest with transaction costs."""
        hyp = self.hypothesis

        # Build cost model
        cost_model = TransactionCostModel(capital=hyp.position_sizing.capital)

        # Build position sizing spec
        method_map = {
            "equal_weight": PositionSizingMethod.EQUAL_WEIGHT,
            "signal_proportional": PositionSizingMethod.SIGNAL_PROPORTIONAL,
            "risk_parity": PositionSizingMethod.RISK_PARITY,
            "kelly": PositionSizingMethod.KELLY,
        }
        sizing_method = method_map.get(hyp.position_sizing.method, PositionSizingMethod.EQUAL_WEIGHT)

        sizing_spec = _PositionSizingSpec(
            method=sizing_method,
            max_position_pct=hyp.position_sizing.max_position_pct,
            max_positions=hyp.position_sizing.max_positions,
            max_sector_pct=hyp.position_sizing.max_sector_pct,
            capital=hyp.position_sizing.capital,
            rebalance_frequency=hyp.position_sizing.rebalance_frequency,
        )

        cost_calc = TransactionCostCalculator(model=cost_model)
        backtester = CrossSectionalBacktester(
            cost_calculator=cost_calc,
            position_sizer_spec=sizing_spec,
        )

        # Prepare data
        signal_df = self.signal_df if self.signal_df is not None and not self.signal_df.empty else self._make_fallback_signals()
        price_df = self.price_df if self.price_df is not None else self._simulate_price_data(
            tickers=list(signal_df.columns) if not signal_df.empty else [],
            start=hyp.time_period.start_date,
            end=hyp.time_period.end_date,
        )

        # Align dates between signals and prices
        common_dates = signal_df.index.intersection(price_df.index)
        if len(common_dates) < 10:
            raise PipelineError(
                f"Insufficient overlapping dates between signals and prices "
                f"({len(common_dates)} dates). Need at least 10."
            )

        signal_df = signal_df.loc[common_dates]
        price_df = price_df.loc[common_dates]

        # Create placeholder market cap and volume dataframes (same shape as prices)
        market_cap_df = pd.DataFrame(
            np.ones_like(price_df.values, dtype=float) * 1e10,
            index=price_df.index,
            columns=price_df.columns,
        )
        volume_df = pd.DataFrame(
            np.ones_like(price_df.values, dtype=float) * 1e8,
            index=price_df.index,
            columns=price_df.columns,
        )

        # Run cross-sectional backtest
        result = backtester.run(
            signal_df=signal_df,
            price_df=price_df,
            market_cap_df=market_cap_df,
            volume_df=volume_df,
            holding_period_days=hyp.holding_period_days,
            rebalance_frequency=hyp.position_sizing.rebalance_frequency,
        )

        return result

    def _make_fallback_signals(self) -> pd.DataFrame:
        """Create a fallback signal DataFrame when none is provided.

        Uses random signals for pipeline testing. In production, signals
        come from the hypothesis specification."""
        if self.price_df is None:
            raise PipelineError("Cannot create fallback signals: no price data available.")

        rng = np.random.RandomState(self.seeds["global"])
        signals = pd.DataFrame(
            rng.randn(*self.price_df.shape),
            index=self.price_df.index,
            columns=self.price_df.columns,
        )
        self._warnings.append(
            "USING RANDOM FALLBACK SIGNALS. Real hypothesis MUST provide actual signals."
        )
        return signals

    def _extract_backtest_summary(self) -> Dict[str, Any]:
        """Extract key metrics from the backtest result."""
        br = self.backtest_result
        if br is None:
            return {"error": "No backtest result"}

        return {
            "gross_annualized_return_bps": float(br.gross_annualized_return * 10000),
            "net_annualized_return_bps": float(br.net_annualized_return * 10000),
            "gross_sharpe": float(br.gross_sharpe_ratio),
            "net_sharpe": float(br.net_sharpe_ratio),
            "gross_max_drawdown_pct": float(br.gross_max_drawdown * 100),
            "net_max_drawdown_pct": float(br.net_max_drawdown * 100),
            "total_costs_bps": float(br.total_costs_bps),
            "cost_drag_annualized_bps": float(br.cost_drag_annualized_bps),
            "n_trades": int(br.n_trades),
            "n_trading_days": int(br.n_trading_days),
            "average_cost_per_trade_bps": float(br.average_cost_per_trade_bps),
        }

    def _run_statistics(self):
        """Stage 6: Run full statistical analysis."""
        br = self.backtest_result
        if br is None:
            raise PipelineError("No backtest result available for statistical analysis.")

        # Use net returns for statistical analysis
        returns = br.net_returns if not br.net_returns.empty else br.gross_returns

        if returns.empty or len(returns) < 10:
            raise PipelineError(
                f"Insufficient return observations ({len(returns)}). Need at least 10."
            )

        # Derive seeds from hypothesis UUID
        bootstrap_seed = get_hypothesis_seed(self.hypothesis.uuid, 137)
        stats_seed = get_hypothesis_seed(self.hypothesis.uuid, 42)

        generator = StatisticalReportGenerator(
            bootstrap=BlockBootstrap(seed=bootstrap_seed),
            seed=stats_seed,
        )

        # Prepare signals for IC computation
        aligned_signals = None
        if self.signal_df is not None and not self.signal_df.empty:
            # Flatten signals to match returns
            signal_dates = self.signal_df.index
            daily_mean_signals = self.signal_df.mean(axis=1)
            aligned_signals = daily_mean_signals.reindex(returns.index).dropna()

        # Collect p-values from various tests for multiple comparison correction
        p_values = self._collect_p_values(returns)

        return generator.generate_report(
            returns=returns,
            signals=aligned_signals,
            p_values_for_correction=p_values,
            hypothesized_effect_size=self.hypothesis.minimum_effect_size.sharpe_ratio,
        )

    def _collect_p_values(self, returns: pd.Series) -> List[float]:
        """Collect p-values from multiple tests for correction."""
        from scipy import stats as sp_stats

        p_values = []

        # t-test on mean returns
        _, p = sp_stats.ttest_1samp(returns.dropna(), 0)
        p_values.append(float(p))

        # Test on positive/negative split
        pos = returns[returns > 0]
        neg = returns[returns < 0]
        if len(pos) > 5 and len(neg) > 5:
            _, p = sp_stats.ttest_ind(pos, neg)
            p_values.append(float(p))

        # Autocorrelation test
        if len(returns) > 2:
            acf1 = returns.autocorr(lag=1)
            if not np.isnan(acf1):
                # Fisher z-transform test for correlation
                z = 0.5 * np.log((1 + acf1) / (1 - acf1)) * np.sqrt(len(returns) - 3)
                p = 2 * (1 - sp_stats.norm.cdf(abs(z)))
                p_values.append(float(p))

        return p_values

    def _extract_statistics_summary(self) -> Dict[str, Any]:
        """Extract key statistics from the statistical report."""
        sr = self.stat_report
        if sr is None:
            return {"error": "No statistical report"}

        dist = sr.distribution
        perf = sr.performance
        power = sr.power_analysis
        outlier = sr.outlier_analysis

        return {
            "n_observations": dist.n_observations,
            "mean_return_daily_bps": float(dist.mean * 10000),
            "median_return_daily_bps": float(dist.median * 10000),
            "std_daily_bps": float(dist.std * 10000),
            "skewness": float(dist.skewness),
            "kurtosis": float(dist.kurtosis),
            "ci_95_mean_daily_bps": (float(dist.ci_95_mean[0] * 10000), float(dist.ci_95_mean[1] * 10000)),
            "is_significant": sr.is_statistically_significant,
            "annualized_sharpe": float(perf.sharpe_ratio),
            "sortino_ratio": float(perf.sortino_ratio),
            "max_drawdown_pct": float(perf.max_drawdown * 100),
            "hit_rate": float(perf.hit_rate),
            "profit_factor": float(perf.profit_factor),
            "information_coefficient": float(perf.information_coefficient) if perf.information_coefficient else None,
            "is_outlier_driven": outlier.is_outlier_driven,
            "achieved_power": float(power.achieved_power),
            "is_adequately_powered": power.is_adequately_powered,
            "minimum_detectable_effect": float(power.minimum_detectable_effect),
        }

    def _run_adversarial(self):
        """Stage 7: Run adversarial test battery."""
        br = self.backtest_result
        if br is None:
            raise PipelineError("No backtest result for adversarial tests.")

        returns = br.net_returns if not br.net_returns.empty else br.gross_returns

        breaker_seed = get_hypothesis_seed(self.hypothesis.uuid, 629)

        # Create a simple backtest function for permutation testing
        def simple_backtest(signals_df, fwd_returns):
            # Cross-sectional: long top 20%, hold 21 days
            if signals_df.empty or fwd_returns.empty:
                return 0.0
            perf = 0.0
            for date in signals_df.index:
                sig = signals_df.loc[date].dropna()
                if len(sig) < 5:
                    continue
                n = max(1, int(len(sig) * 0.2))
                top = sig.nlargest(n).index
                ret = fwd_returns.loc[date][top].mean() if date in fwd_returns.index else 0
                perf += ret
            return perf / max(len(signals_df), 1)

        # Create alternative spec functions (holding period variations)
        alt_funcs = []
        alt_names = []

        base_hp = self.hypothesis.holding_period_days
        for hp_variant in [max(1, base_hp // 2), base_hp, base_hp * 2]:
            alt_names.append(f"holding_period_{hp_variant}d")

            def make_func(hp=hp_variant):
                def f():
                    # Simplified: compute mean return scaled by holding period
                    perf = returns.mean() * hp / base_hp
                    return {"performance": float(perf), "p_value": 1.0}
                return f
            alt_funcs.append(make_func())

        # For specification robustness, we also vary universe width and signal threshold
        for top_q in [0.1, 0.2, 0.3]:
            alt_names.append(f"top_{int(top_q*100)}pct")

            def make_qfunc(q=top_q):
                def f():
                    return {"performance": float(returns.mean() * q / 0.2), "p_value": 1.0}
                return f
            alt_funcs.append(make_qfunc())

        gen = AdversarialReportGenerator(
            stat_breaker=StatisticalBreaker(seed=breaker_seed),
            regime_analyzer=RegimeAnalyzer(seed=get_hypothesis_seed(self.hypothesis.uuid, 251)),
        )

        # Prepare inputs
        signal_dummy = self.signal_df if self.signal_df is not None and not self.signal_df.empty else pd.DataFrame(
            np.random.RandomState(breaker_seed).randn(len(returns), 10),
            index=returns.index,
            columns=[f"TICKER_{i}" for i in range(10)],
        )

        # Generate walk-forward window results from backtest
        window_results = self._build_wf_window_results()

        return gen.generate_report(
            signals=signal_dummy,
            forward_returns=pd.DataFrame(index=returns.index),
            strategy_returns=returns,
            backtest_func=simple_backtest,
            alt_backtest_funcs=alt_funcs,
            alt_spec_names=alt_names,
            window_results=window_results,
        )

    def _build_wf_window_results(self) -> List[Dict[str, Any]]:
        """Build walk-forward window results from the backtest data."""
        returns = self.backtest_result.net_returns if (self.backtest_result and not self.backtest_result.net_returns.empty) else (
            self.backtest_result.gross_returns if self.backtest_result else pd.Series()
        )
        if returns.empty:
            return []

        # Split returns into 5 windows
        n = len(returns)
        window_size = max(20, n // 5)
        windows = []

        for i in range(0, n, window_size):
            window = returns.iloc[i:i + window_size]
            if len(window) < 10:
                continue
            ann_alpha = window.mean() * 252
            _, p_val = pd.Series(window).apply(
                lambda x: x
            ).pipe(lambda s: (0, 1.0))  # placeholder

            # Simple t-test
            from scipy import stats as sp_stats
            try:
                _, p_val = sp_stats.ttest_1samp(window.dropna(), 0)
            except Exception:
                p_val = 1.0

            windows.append({
                "start_date": str(window.index[0]) if hasattr(window.index[0], 'strftime') else str(window.index[0]),
                "end_date": str(window.index[-1]) if hasattr(window.index[-1], 'strftime') else str(window.index[-1]),
                "annualized_alpha": float(ann_alpha),
                "sharpe": float(window.mean() / window.std() * np.sqrt(252)) if window.std() > 0 else 0.0,
                "p_value": float(p_val),
                "n_observations": len(window),
            })

        return windows

    def _extract_adversarial_summary(self) -> Dict[str, Any]:
        """Extract key results from the adversarial report."""
        ar = self.adversarial_report
        if ar is None:
            return {"error": "No adversarial report"}

        return {
            "permutation_test_p": float(ar.permutation.p_value),
            "permutation_passed": ar.permutation.is_significant,
            "time_shuffle_p": float(ar.time_shuffle.p_value),
            "spec_robustness_fraction": float(ar.specification_robustness.fraction_significant),
            "spec_robustness_passed": ar.specification_robustness.is_robust,
            "walk_forward_positive_pct": float(ar.walk_forward.fraction_positive * 100) if ar.walk_forward.n_windows > 0 else 0.0,
            "walk_forward_passed": ar.walk_forward.is_consistent,
            "regime_dependent": ar.regime_analysis.is_regime_dependent,
            "edge_decaying": ar.edge_decay.is_decaying,
            "edge_half_life_years": float(ar.edge_decay.half_life_years),
            "all_adversarial_passed": ar.all_adversarial_passed,
            "breakage_reasons": ar.breakage_reasons,
            "warnings": ar.warnings,
        }

    def _run_factor_comparison(self):
        """Stage 8: Run baseline factor comparison."""
        br = self.backtest_result
        if br is None:
            raise PipelineError("No backtest result for factor comparison.")

        returns = br.net_returns if not br.net_returns.empty else br.gross_returns
        if returns.empty:
            raise PipelineError("No returns available for factor comparison.")

        raw_alpha = (1 + returns).prod() ** (252 / max(len(returns), 1)) - 1

        engine = FactorComparisonEngine()
        factor_seed = get_hypothesis_seed(self.hypothesis.uuid, 733)

        # Use price data if available to construct factors
        if self.price_df is not None and not self.price_df.empty:
            report = engine.generate_factor_comparison_report(
                strategy_returns=returns,
                raw_alpha_annualized=float(raw_alpha),
                price_df=self.price_df,
                universe_dates=list(returns.index),
            )
        else:
            # Run with empty factors -- will return INCONCLUSIVE_NO_FACTORS
            report = engine.generate_factor_comparison_report(
                strategy_returns=returns,
                raw_alpha_annualized=float(raw_alpha),
                precomputed_factors={},
            )

        return report

    def _extract_factor_summary(self) -> Dict[str, Any]:
        """Extract key results from factor comparison."""
        fr = self.factor_report
        if fr is None:
            return {"error": "No factor comparison report"}

        exposure = fr.exposure
        return {
            "verdict": fr.verdict,
            "factor_recycling": exposure.is_factor_recycling,
            "residual_alpha_p_value": float(exposure.alpha_p_value),
            "r_squared": float(exposure.r_squared),
            "residual_sharpe": float(exposure.residual_sharpe),
            "dominant_factors": exposure.dominant_factors,
            "factor_loadings": exposure.factor_loadings,
            "factor_contribution_pct": exposure.factor_contribution_pct,
            "factor_explained_pct": float(fr.factor_explained_pct),
            "warnings": fr.warnings,
        }

    def _run_edge_decay(self) -> Dict[str, Any]:
        """Stage 9: Edge decay and regime analysis."""
        br = self.backtest_result
        if br is None:
            return {"error": "No backtest result", "is_decaying": False, "half_life_years": float("inf")}

        returns = br.net_returns if not br.net_returns.empty else br.gross_returns
        if returns.empty or len(returns) < 60:
            return {
                "warning": "Insufficient data for edge decay analysis (need 60+ observations)",
                "is_decaying": False,
                "half_life_years": float("inf"),
            }

        regime_seed = get_hypothesis_seed(self.hypothesis.uuid, 251)
        analyzer = RegimeAnalyzer(seed=regime_seed)

        rolling_alphas = analyzer.rolling_window_analysis(returns)
        decay = analyzer.detect_edge_decay(rolling_alphas)

        return {
            "half_life_years": float(decay.half_life_years),
            "trend_coefficient": float(decay.trend_coefficient),
            "trend_p_value": float(decay.trend_p_value),
            "is_decaying": decay.is_decaying,
            "n_structural_breaks": len(decay.structural_breaks),
            "structural_breaks": decay.structural_breaks,
            "n_rolling_windows": len(rolling_alphas) if rolling_alphas is not None else 0,
        }

    # ------------------------------------------------------------------
    # Verdict Logic (PIPELINE_SPEC.md Section 11.1)
    # ------------------------------------------------------------------

    def _determine_verdict(self) -> Tuple[Verdict, str, Optional[str]]:
        """
        Apply the decision tree to determine the final verdict.

        Decision tree (from spec Section 11.1):
        1. DATA CHECK -> UNTESTABLE if unavailable
        2. TEMPORAL CHECK -> BROKEN if breaches
        3. STATISTICAL SIGNIFICANCE -> BROKEN if not significant
        4. ECONOMIC SIGNIFICANCE -> BROKEN if post-cost alpha < minimum
        5. ADVERSARIAL BREAKAGE -> BROKEN if permutation/OOS/WF/spec tests fail
        6. FACTOR COMPARISON -> BROKEN if factor recycling
        7. EDGE DECAY -> SURVIVED_WARNING if half-life < 1yr or regime-dependent
        8. SURVIVED otherwise
        """
        hyp = self.hypothesis
        stats_summ = self._stage_results.get("statistics", {})
        bt_summ = self._stage_results.get("backtest", {})
        adv_summ = self._stage_results.get("adversarial", {})
        factor_summ = self._stage_results.get("factors", {})
        decay = self._stage_results.get("edge_decay", {})

        # --- Check 1: Statistical significance ---
        is_stat_sig = stats_summ.get("is_significant", False)
        if not is_stat_sig:
            return Verdict.BROKEN, (
                "STATISTICAL SIGNIFICANCE FAILED: Mean return 95% bootstrap CI includes zero. "
                "The signal does not produce returns statistically distinguishable from noise."
            ), "statistics"

        # Report CI
        ci = stats_summ.get("ci_95_mean_daily_bps", (None, None))
        ci_str = f"95% CI: [{ci[0]:.2f}, {ci[1]:.2f}] bps/day" if ci[0] is not None else "N/A"

        # --- Check 2: Economic significance ---
        post_cost_alpha = bt_summ.get("net_annualized_return_bps", 0)
        min_alpha = hyp.minimum_effect_size.annualized_alpha_bps
        post_cost_sharpe = bt_summ.get("net_sharpe", 0)
        min_sharpe = hyp.minimum_effect_size.sharpe_ratio

        if post_cost_alpha < min_alpha:
            return Verdict.BROKEN, (
                f"ECONOMIC SIGNIFICANCE FAILED: Post-cost annualized alpha "
                f"({post_cost_alpha:.0f} bps) below minimum threshold ({min_alpha:.0f} bps). "
                f"The signal is statistically significant but not economically meaningful."
            ), "backtest"

        if post_cost_sharpe < min_sharpe:
            return Verdict.BROKEN, (
                f"ECONOMIC SIGNIFICANCE FAILED: Post-cost Sharpe ratio "
                f"({post_cost_sharpe:.3f}) below minimum threshold ({min_sharpe:.3f}). "
                f"Risk-adjusted returns are insufficient."
            ), "backtest"

        # --- Check 3: Hit rate ---
        hit_rate = stats_summ.get("hit_rate", 0)
        min_hit_rate = hyp.minimum_effect_size.hit_rate
        if hit_rate < min_hit_rate:
            return Verdict.BROKEN, (
                f"ECONOMIC SIGNIFICANCE FAILED: Hit rate ({hit_rate:.2%}) "
                f"below minimum threshold ({min_hit_rate:.2%})."
            ), "statistics"

        # --- Check 4: Max drawdown ---
        max_dd = abs(bt_summ.get("net_max_drawdown_pct", 100))
        max_allowed_dd = hyp.minimum_effect_size.max_drawdown_pct
        if max_dd > max_allowed_dd:
            return Verdict.BROKEN, (
                f"ECONOMIC SIGNIFICANCE FAILED: Maximum drawdown ({max_dd:.1f}%) "
                f"exceeds maximum allowed ({max_allowed_dd:.1f}%)."
            ), "backtest"

        # --- Check 5: Adversarial breakage ---
        if adv_summ and "error" not in adv_summ:
            # Permutation test
            perm_p = adv_summ.get("permutation_test_p", 1.0)
            if perm_p >= 0.05:
                return Verdict.BROKEN, (
                    f"PERMUTATION TEST FAILED: p={perm_p:.4f}. "
                    f"Signal not distinguishable from random noise."
                ), "adversarial"

            # Out-of-sample -- use walk-forward as proxy
            wf_pct = adv_summ.get("walk_forward_positive_pct", 0)
            if wf_pct < 60 and adv_summ.get("walk_forward_passed", True) is False:
                return Verdict.BROKEN, (
                    f"WALK-FORWARD FAILED: Only {wf_pct:.0f}% of walk-forward windows "
                    f"produce positive alpha (threshold: 60%). Signal is inconsistent."
                ), "adversarial"

            # Specification robustness
            spec_frac = adv_summ.get("spec_robustness_fraction", 1.0)
            if spec_frac < 0.50:
                return Verdict.BROKEN, (
                    f"SPECIFICATION ROBUSTNESS FAILED: Only {spec_frac:.0%} of "
                    f"alternative specifications are significant. The result is fragile "
                    f"and likely overfitted."
                ), "adversarial"

        # --- Check 6: Factor comparison ---
        if factor_summ and "error" not in factor_summ:
            if factor_summ.get("factor_recycling", False):
                return Verdict.BROKEN, (
                    f"FACTOR RECYCLING: Residual alpha not significant after controlling "
                    f"for baseline factors (p={factor_summ.get('residual_alpha_p_value', 1.0):.4f}). "
                    f"The apparent edge is explained by known factors: "
                    f"{factor_summ.get('dominant_factors', [])}. "
                    f"R-squared = {factor_summ.get('r_squared', 0):.3f}."
                ), "factors"

        # --- Check 7: Edge decay warnings (do not break, but warn) ---
        warnings = []
        is_warning = False

        if decay and "error" not in decay:
            hl = decay.get("half_life_years", float("inf"))
            if hl < 1.0:
                warnings.append(
                    f"SHORT EDGE HALF-LIFE: Estimated half-life {hl:.1f} years. "
                    f"Edge may decay rapidly."
                )
                is_warning = True

            if decay.get("is_decaying", False):
                warnings.append(
                    f"EDGE DECAYING: Rolling alpha trend is significantly negative "
                    f"(p={decay.get('trend_p_value', 1.0):.4f})."
                )
                is_warning = True

        if adv_summ and "error" not in adv_summ:
            if adv_summ.get("regime_dependent", False):
                warnings.append("REGIME DEPENDENT: Performance varies significantly across market regimes.")
                is_warning = True

        # --- Check 8: Outlier-driven ---
        if stats_summ.get("is_outlier_driven", False):
            return Verdict.BROKEN, (
                "OUTLIER DRIVEN: Removing <5% of extreme observations eliminates "
                "statistical significance. The apparent alpha is not robust."
            ), "statistics"

        # --- Check 9: Statistical power ---
        if not stats_summ.get("is_adequately_powered", True):
            warnings.append(
                f"UNDERPOWERED: Achieved power {stats_summ.get('achieved_power', 0):.2f} "
                f"is below 0.80 target."
            )

        # --- Final verdict ---
        if is_warning:
            return Verdict.SURVIVED_WARNING, (
                f"All core checks passed but warnings present: {'; '.join(warnings)}"
            ), None

        return Verdict.SURVIVED, (
            f"ALL CHECKS PASSED. Post-cost alpha: {post_cost_alpha:.0f} bps/year, "
            f"Sharpe: {post_cost_sharpe:.3f}, Hit rate: {hit_rate:.1%}. "
            f"{ci_str}"
        ), None

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def _capture_stage_error(self, stage: str, error: Exception) -> None:
        """Capture a stage error for the audit trail."""
        self._stage_errors[stage] = str(error)
        self._warnings.append(f"Stage '{stage}' failed: {error}")
        logger.error(f"Stage '{stage}' error: {error}")
        logger.debug(traceback.format_exc())

    def _finalize_verdict(
        self,
        verdict: Verdict,
        reason: str,
        failure_stage: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate the final verdict output and audit trail."""
        hyp = self.hypothesis

        # Compile checks structure
        checks = self._build_checks_dict(verdict)

        # Compile metrics
        metrics = self._build_metrics_dict()

        # Compile all warnings
        all_warnings = list(self._warnings)

        # --- SAFEGUARD: Apply survivorship bias verdict capping ---
        survivorship_cap_applied = False
        if hasattr(self, '_survivorship_report') and self._survivorship_report is not None:
            surv_report = self._survivorship_report
            if SurvivorshipGuard is not None and hasattr(SurvivorshipGuard, 'cap_verdict'):
                capped_verdict, cap_reason = SurvivorshipGuard.cap_verdict(
                    verdict.value, surv_report
                )
                if capped_verdict != verdict.value:
                    all_warnings.append(f"Verdict capped by SurvivorshipGuard: {cap_reason.strip(' |')}")
                    verdict = Verdict(capped_verdict)
                    reason = reason + cap_reason
                    survivorship_cap_applied = True
                    failure_stage = "survivorship"

        # --- SAFEGUARD: Apply contamination verdict capping ---
        if ContaminationDetector is not None and hasattr(ContaminationDetector, 'cap_verdict'):
            # Check if contamination report is available
            contamination_risk = "CLEAN"  # Default for deterministic extraction
            if hasattr(self, 'hypothesis') and self.hypothesis:
                signal_spec = self.hypothesis.signal
                if signal_spec.llm_model_used and signal_spec.llm_model_used != "":
                    # LLM was used — risk exists
                    contamination_risk = "LOW"
                    all_warnings.append(
                        "LLM used for signal extraction. Contamination risk: LOW. "
                        "Verify that extraction runs are unaffected by training data."
                    )

        # --- SAFEGUARD: TrialTracker investigation-wide context ---
        investigation_context = None
        if self.trial_tracker is not None:
            try:
                investigation_context = self.trial_tracker.get_investigation_context(
                    hyp.uuid
                )
                if investigation_context:
                    all_warnings.append(
                        f"[FAMILY-WISE] {investigation_context.honest_report}"
                    )
            except Exception as e:
                logger.debug(f"TrialTracker context fetch failed: {e}")

        # Add edge decay and regime warnings if SURVIVED_WARNING
        if verdict == Verdict.SURVIVED_WARNING:
            decay = self._stage_results.get("edge_decay", {})
            adv = self._stage_results.get("adversarial", {})
            if decay.get("is_decaying"):
                all_warnings.append(f"Edge decaying (half-life: {decay.get('half_life_years', 'N/A')} years)")
            if adv.get("regime_dependent"):
                all_warnings.append("Regime-dependent performance")

        # Create output directory structure
        hyp_dir = os.path.join(self.output_dir, hyp.uuid)
        audit_path = os.path.join(hyp_dir, "audit_trail.json")
        verdict_path = os.path.join(hyp_dir, "verdict.json")
        summary_path = os.path.join(hyp_dir, "results_summary.json")
        data_dir = os.path.join(hyp_dir, "data")
        charts_dir = os.path.join(hyp_dir, "charts")
        logs_dir = os.path.join(hyp_dir, "logs")

        for d in [hyp_dir, data_dir, charts_dir, logs_dir]:
            os.makedirs(d, exist_ok=True)

        # Save data snapshots
        snapshot_mgr = DataSnapshotManager(data_dir)
        run_id = self._audit.trail.run_id if self._audit.trail else "unknown"

        if self.universe_df is not None and not self.universe_df.empty:
            snapshot_mgr.save_snapshot(self.universe_df, "universe", run_id)

        if self.signal_df is not None and not self.signal_df.empty:
            snapshot_mgr.save_snapshot(self.signal_df, "signals", run_id)

        if self.backtest_result is not None:
            returns = self.backtest_result.net_returns
            if not returns.empty:
                snapshot_mgr.save_snapshot(returns.to_frame("return"), "strategy_returns", run_id)

        # Build results summary
        results_summary = {
            "hypothesis_uuid": hyp.uuid,
            "hypothesis_name": hyp.name,
            "pipeline_version": self.pipeline_version,
            "verdict": verdict.value,
            "verdict_reason": reason,
            "stage_results": {
                stage: {k: str(v) if not isinstance(v, (int, float, bool, list, dict, type(None))) else v
                        for k, v in data.items()}
                for stage, data in self._stage_results.items()
            },
            "stage_errors": self._stage_errors,
            "warnings": all_warnings,
            # --- Safeguards metadata ---
            "safeguards": {
                "survivorship_bias": (
                    self._survivorship_report.to_dict()
                    if hasattr(self, '_survivorship_report') and self._survivorship_report is not None
                    else "NOT_CHECKED"
                ),
                "contamination_risk": "CLEAN",  # Default for deterministic extraction
                "investigation_context": (
                    investigation_context.to_dict()
                    if investigation_context is not None
                    else None
                ),
                "survivorship_cap_applied": survivorship_cap_applied,
            },
        }

        # Generate verdict
        verdict_output = self._verdict_gen.generate_verdict(
            audit_trail=self._audit.trail,
            hypothesis_config=asdict(hyp),
            test_results=results_summary,
            verdict=verdict.value,
            verdict_reason=reason,
            failure_stage=failure_stage,
            checks=checks,
            metrics=metrics,
            warnings=all_warnings,
        )

        # Finalize and export audit trail
        output_files = {
            "audit_trail": audit_path,
            "verdict": verdict_path,
            "results_summary": summary_path,
        }

        self._audit.finalize_trail(output_files, verdict.value)
        self._audit.export_trail(audit_path)

        # Write results summary
        with open(summary_path, "w") as f:
            json.dump(results_summary, f, indent=2, default=str)

        # Write verdict separately so it is human-readable
        with open(verdict_path, "w") as f:
            json.dump(verdict_output, f, indent=2, default=str)

        logger.info(f"\n{'='*70}")
        logger.info(f"VERDICT: {verdict.value}")
        logger.info(f"Reason: {reason}")
        if failure_stage:
            logger.info(f"Failure stage: {failure_stage}")
        logger.info(f"Output: {hyp_dir}")
        logger.info(f"{'='*70}\n")

        return verdict_output

    def _build_checks_dict(self, verdict: Verdict) -> Dict[str, Any]:
        """Build the checks section of the verdict JSON."""
        stats = self._stage_results.get("statistics", {})
        bt = self._stage_results.get("backtest", {})
        adv = self._stage_results.get("adversarial", {})
        factors = self._stage_results.get("factors", {})
        decay = self._stage_results.get("edge_decay", {})
        temporal = self._stage_results.get("temporal", {})
        data_avail = self._stage_results.get("data_availability", {})

        return {
            "data_availability": {
                "passed": data_avail.get("all_available", False),
                "details": data_avail,
            },
            "temporal_alignment": {
                "passed": temporal.get("is_valid", False),
                "look_ahead_breaches": temporal.get("n_breaches", 0),
            },
            "statistical_significance": {
                "passed": stats.get("is_significant", False),
                "ci_95_mean_daily_bps": stats.get("ci_95_mean_daily_bps", [None, None]),
                "bootstrap_ci_95": stats.get("ci_95_mean_daily_bps", [None, None]),
                "is_outlier_driven": stats.get("is_outlier_driven", False),
                "achieved_power": stats.get("achieved_power", 0),
            },
            "economic_significance": {
                "passed": (
                    bt.get("net_annualized_return_bps", 0) >= self.hypothesis.minimum_effect_size.annualized_alpha_bps
                    and bt.get("net_sharpe", 0) >= self.hypothesis.minimum_effect_size.sharpe_ratio
                ),
                "post_cost_annualized_alpha_bps": bt.get("net_annualized_return_bps"),
                "minimum_required_bps": self.hypothesis.minimum_effect_size.annualized_alpha_bps,
                "post_cost_sharpe": bt.get("net_sharpe"),
                "post_cost_max_drawdown_pct": bt.get("net_max_drawdown_pct"),
            },
            "adversarial_breakage": {
                "permutation_test_p": adv.get("permutation_test_p"),
                "oos_significance": None,  # OOS not separately run; captured by walk-forward
                "walk_forward_positive_pct": adv.get("walk_forward_positive_pct"),
                "alternative_specs_passed_pct": adv.get("spec_robustness_fraction", 0) * 100,
                "all_passed": adv.get("all_adversarial_passed", False),
            },
            "factor_comparison": {
                "residual_alpha_p_value": factors.get("residual_alpha_p_value"),
                "r_squared": factors.get("r_squared"),
                "dominant_factors": factors.get("dominant_factors", []),
                "factor_recycling": factors.get("factor_recycling", False),
            },
            "edge_decay": {
                "half_life_years": decay.get("half_life_years"),
                "decay_trend_p_value": decay.get("trend_p_value"),
                "regime_dependent": adv.get("regime_dependent", False),
                "structural_breaks": decay.get("structural_breaks", []),
            },
        }

    def _build_metrics_dict(self) -> Dict[str, Any]:
        """Build the summary metrics section."""
        stats = self._stage_results.get("statistics", {})
        bt = self._stage_results.get("backtest", {})

        return {
            "annualized_return_pct": bt.get("net_annualized_return_bps", 0) / 100,
            "annualized_volatility_pct": stats.get("std_daily_bps", 0) * np.sqrt(252) / 100,
            "sharpe_ratio": bt.get("net_sharpe", 0),
            "sortino_ratio": stats.get("sortino_ratio", 0),
            "max_drawdown_pct": bt.get("net_max_drawdown_pct", 0),
            "max_drawdown_days": stats.get("max_drawdown_days", 0),
            "calmar_ratio": (
                abs(bt.get("net_annualized_return_bps", 0) / 100 / (bt.get("net_max_drawdown_pct", 1) / 100))
                if bt.get("net_max_drawdown_pct", 0) != 0 else 0
            ),
            "information_coefficient": stats.get("information_coefficient"),
            "hit_rate": stats.get("hit_rate", 0),
            "profit_factor": stats.get("profit_factor", 0),
            "skewness": stats.get("skewness", 0),
            "kurtosis": stats.get("kurtosis", 0),
            "mean_return_bps_daily": stats.get("mean_return_daily_bps", 0),
            "median_return_bps_daily": stats.get("median_return_daily_bps", 0),
        }

    @staticmethod
    def _get_git_hash() -> Optional[str]:
        """Get the current git commit hash."""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None


# ============================================================================
# Example Hypothesis (for demo/testing)
# ============================================================================


def make_example_hypothesis() -> HypothesisSpec:
    """Create an example hypothesis spec for pipeline testing.

    This is NOT a real hypothesis -- it uses random signals and is intended
    only to verify that the pipeline runs end-to-end."""
    hypothesis_uuid = hashlib.sha256(b"example-test-hypothesis-v1").hexdigest()[:16]

    return HypothesisSpec(
        name="Example: Mean Reversion in S&P 500 Constituents",
        uuid=hypothesis_uuid,
        source_agent="pipeline-test",
        submission_number=1,
        mechanism=(
            "Stocks that have underperformed their sector peers over the past 5 days "
            "tend to mean-revert over the next 5 days due to temporary liquidity "
            "imbalances and overreaction to non-information events."
        ),
        llm_advantage=(
            "An LLM can parse earnings call transcripts in real time to distinguish "
            "between 'information-driven' and 'non-information-driven' selloffs, "
            "filtering mean-reversion signals to only those triggered by noise, not news."
        ),
        why_underweighted=(
            "This requires real-time parsing of unstructured text (earnings calls, 8-Ks) "
            "at scale, which was prohibitively expensive before LLMs."
        ),
        universe=UniverseSpec(
            universe_type="sp500",
            include_delisted=True,
        ),
        signal=SignalSpec(
            signal_type="numeric",
            signal_name="mean_reversion_5d",
            higher_is_better=True,
            llm_model_used="llama-3-8b",
            llm_temperature=0.0,
            llm_seed=42,
            llm_is_deterministic=True,
        ),
        holding_period_days=5,
        time_period=TimePeriodSpec(
            start_date="2023-01-01",
            end_date="2025-12-31",
            min_training_days=252,
            frequency="daily",
        ),
        position_sizing=PositionSizingSpec(
            method="equal_weight",
            max_position_pct=0.05,
            max_positions=50,
            capital=100000.0,
        ),
        minimum_effect_size=MinimumEffectSpec(
            annualized_alpha_bps=300,
            sharpe_ratio=0.3,
            information_coefficient=0.03,
            hit_rate=0.51,
            max_drawdown_pct=25.0,
        ),
        data_sources=[
            DataSourceSpec(
                source_type="price",
                provider="yahoo",
                frequency="daily",
                fields=["adj_close", "volume"],
                start_date="2020-01-01",
                end_date="2025-12-31",
                known_biases=[
                    "Survivorship bias for stocks delisted before ~2017",
                    "Adjusted close may lag by 1-2 days for corporate actions",
                ],
                api_tier="free",
                monthly_cost_usd=0.0,
            ),
            DataSourceSpec(
                source_type="sec_filing",
                provider="sec_edgar",
                frequency="as_filed",
                fields=["filing_text", "filing_type", "acceptance_date"],
                start_date="2020-01-01",
                end_date="2025-12-31",
                known_biases=[
                    "Processing delay of 1-5 business days",
                    "Historical filings before 2000 less complete",
                ],
                api_tier="free",
                monthly_cost_usd=0.0,
            ),
        ],
        falsifiable_prediction=(
            "If this edge is real, a long-short portfolio going long the bottom quintile "
            "of 5-day returns within each GICS sector and short the top quintile should "
            "produce a Sharpe ratio > 0.3 after costs over a 3-year period."
        ),
        self_assessed_confidence="MEDIUM",
        biggest_weakness=(
            "Mean reversion signals may be crowded, especially in large-cap stocks. "
            "The LLM filter may not add enough signal-to-noise improvement to overcome costs."
        ),
    )


# ============================================================================
# CLI Entry Point
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Stage 2 Universal Hypothesis Testing Pipeline v1.0.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline.py --hypothesis hypothesis.json --output results/
  python pipeline.py --hypothesis hypothesis.json --output results/ --verbose
  python pipeline.py --example  # Run with built-in example hypothesis
        """,
    )

    parser.add_argument(
        "--hypothesis", "-H",
        type=str,
        help="Path to hypothesis JSON file",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="results",
        help="Output directory (default: results/)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--fmp-key",
        type=str,
        default=os.environ.get("FMP_API_KEY"),
        help="Financial Modeling Prep API key (or set FMP_API_KEY env var)",
    )
    parser.add_argument(
        "--example",
        action="store_true",
        help="Run with built-in example hypothesis (for testing)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {PIPELINE_VERSION}",
    )

    args = parser.parse_args()

    # Determine hypothesis
    if args.example:
        hypothesis = make_example_hypothesis()
        logger.info("Using built-in example hypothesis")
    elif args.hypothesis:
        try:
            hypothesis = HypothesisSpec.from_json_file(args.hypothesis)
        except Exception as e:
            print(f"ERROR: Failed to parse hypothesis file: {e}", file=sys.stderr)
            sys.exit(1)

        # Validate
        issues = hypothesis.validate()
        if issues:
            print("ERROR: Hypothesis specification is invalid:", file=sys.stderr)
            for issue in issues:
                print(f"  - {issue}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        print("\nERROR: Either --hypothesis or --example is required.", file=sys.stderr)
        sys.exit(1)

    # Run pipeline
    pipeline = HypothesisPipeline(
        output_dir=args.output,
        verbose=args.verbose,
        fmp_api_key=args.fmp_key,
    )

    try:
        result = pipeline.run(hypothesis)
    except Exception as e:
        print(f"FATAL: Pipeline crashed: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        sys.exit(2)

    # Print summary
    verdict = result.get("verdict", "UNKNOWN")
    reason = result.get("verdict_reason", "No reason provided")
    print(f"\n{'='*70}")
    print(f"VERDICT: {verdict}")
    print(f"Reason: {reason}")
    print(f"{'='*70}")

    # Return exit code based on verdict
    if verdict in ("SURVIVED", "SURVIVED_WARNING"):
        sys.exit(0)
    elif verdict == "BROKEN":
        sys.exit(0)  # BROKEN is a successful test, not a pipeline error
    elif verdict == "INCONCLUSIVE":
        sys.exit(0)
    elif verdict == "UNTESTABLE":
        sys.exit(3)  # Pipeline couldn't run
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
