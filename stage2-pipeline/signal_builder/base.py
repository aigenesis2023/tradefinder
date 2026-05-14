"""
base.py — Abstract Base Classes for Signal Construction
========================================================

Defines the core abstractions for the Signal Construction Framework.

Architecture:
    HypothesisSpec -> DataAdapter -> SignalExtractor -> SignalBuilder -> Signal File

Design principles:
1.  Deterministic signal extraction (keyword-based primary, LLM optional with temp=0)
2.  Retail-accessible data sources only (free or low-cost)
3.  Full reproducibility (metadata, version tracking, content hashing)
4.  Graceful error handling (UNTESTABLE verdict when data cannot be acquired)
5.  Standardized schema for all signal files
"""

from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

# ============================================================================
# Re-export pipeline dataclasses so signal_builder can operate standalone
# (or import from pipeline.py when available).
# ============================================================================


class Verdict(str, Enum):
    SURVIVED = "SURVIVED"
    SURVIVED_WARNING = "SURVIVED_WARNING"
    BROKEN = "BROKEN"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNTESTABLE = "UNTESTABLE"


UNTESTABLE = Verdict.UNTESTABLE


@dataclass
class DataSourceSpec:
    """Specification of a required data source (PIPELINE_SPEC.md Section 1.7)."""
    source_type: str          # 'price' | 'fundamental' | 'sec_filing' | 'fda_document' | ...
    provider: str             # 'yahoo' | 'fmp' | 'sec_edgar' | 'fda' | 'fred' | ...
    frequency: str            # 'daily' | 'quarterly' | 'annual' | 'as_filed'
    fields: List[str]         # Required fields
    start_date: str           # YYYY-MM-DD
    end_date: str             # YYYY-MM-DD
    known_biases: List[str] = field(default_factory=list)
    api_tier: str = "free"
    monthly_cost_usd: float = 0.0


@dataclass
class UniverseSpec:
    universe_type: str = "sp500"
    custom_tickers: Optional[List[str]] = None
    custom_filter: Optional[str] = None
    min_price: float = 1.0
    min_daily_volume: int = 0
    exchanges: List[str] = field(default_factory=lambda: ["NYSE", "NASDAQ", "NYSEARCA", "NYSEAMERICAN"])
    include_delisted: bool = True


@dataclass
class SignalSpec:
    signal_type: str = "numeric"
    signal_name: str = "signal"
    higher_is_better: bool = True
    llm_model_used: Optional[str] = None
    llm_temperature: Optional[float] = None
    llm_seed: Optional[int] = None
    llm_is_deterministic: bool = False
    signal_source: Optional[str] = None


@dataclass
class TimePeriodSpec:
    start_date: str
    end_date: str
    oos_start_date: Optional[str] = None
    min_training_days: int = 252
    frequency: str = "daily"


@dataclass
class PositionSizingSpec:
    method: str = "equal_weight"
    max_position_pct: float = 0.05
    max_positions: int = 50
    max_sector_pct: float = 0.30
    capital: float = 100000.0
    rebalance_frequency: str = "daily"


@dataclass
class MinimumEffectSpec:
    annualized_alpha_bps: float = 300
    sharpe_ratio: float = 0.3
    information_coefficient: float = 0.03
    hit_rate: float = 0.51
    max_drawdown_pct: float = 25.0


@dataclass
class HypothesisSpec:
    """Complete specification of a hypothesis to test (PIPELINE_SPEC.md Section 1.1)."""
    name: str
    uuid: str
    source_agent: str = "unknown"
    submission_number: int = 1
    mechanism: str = ""
    llm_advantage: str = ""
    why_underweighted: str = ""

    universe: UniverseSpec = field(default_factory=UniverseSpec)
    signal: SignalSpec = field(default_factory=SignalSpec)
    holding_period_days: int = 21
    time_period: TimePeriodSpec = field(default_factory=lambda: TimePeriodSpec("2020-01-01", "2025-12-31"))
    position_sizing: PositionSizingSpec = field(default_factory=PositionSizingSpec)
    minimum_effect_size: MinimumEffectSpec = field(default_factory=MinimumEffectSpec)
    data_sources: List[DataSourceSpec] = field(default_factory=list)
    falsifiable_prediction: str = ""
    self_assessed_confidence: str = "MEDIUM"
    biggest_weakness: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HypothesisSpec":
        d = d.copy()
        d["universe"] = UniverseSpec(**d.get("universe", {}))
        d["signal"] = SignalSpec(**d.get("signal", {}))
        d["time_period"] = TimePeriodSpec(**d.get("time_period", {}))
        d["position_sizing"] = PositionSizingSpec(**d.get("position_sizing", {}))
        d["minimum_effect_size"] = MinimumEffectSpec(**d.get("minimum_effect_size", {}))
        d["data_sources"] = [DataSourceSpec(**ds) for ds in d.get("data_sources", [])]
        return cls(**d)

    @classmethod
    def from_json_file(cls, path: str) -> "HypothesisSpec":
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def validate(self) -> List[str]:
        issues = []
        if not self.name:
            issues.append("hypothesis.name is required")
        if not self.uuid:
            issues.append("hypothesis.uuid is required")
        if self.holding_period_days < 1:
            issues.append("holding_period_days must be >= 1")
        return issues


# ============================================================================
# Data Abstractions
# ============================================================================


@dataclass
class RawData:
    """Container for raw data acquired from a data source.

    Attributes:
        records: The raw data as a DataFrame.
        source_type: Type of data (e.g., 'fda_document', 'sec_filing', 'price').
        provider: Which adapter provided the data.
        acquired_at: ISO 8601 timestamp of acquisition.
        source_urls: URLs or identifiers for each record (optional).
        content_hash: SHA-256 hash of the serialized data for reproducibility.
        metadata: Arbitrary additional metadata.
    """
    records: pd.DataFrame
    source_type: str
    provider: str
    acquired_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_urls: Dict[str, str] = field(default_factory=dict)
    content_hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.content_hash and self.records is not None and not self.records.empty:
            self.content_hash = hashlib.sha256(
                self.records.to_csv(index=False).encode()
            ).hexdigest()[:16]

    def validate(self) -> Tuple[bool, List[str]]:
        """Basic validation: non-empty, has expected columns."""
        issues = []
        if self.records is None:
            issues.append("Records DataFrame is None")
            return False, issues
        if self.records.empty:
            issues.append("Records DataFrame is empty")
            return False, issues
        return len(issues) == 0, issues


@dataclass
class SignalMetadata:
    """Metadata embedded in every signal file for reproducibility."""
    builder_version: str = "1.0.0"
    adapter_name: str = ""
    adapter_version: str = "1.0.0"
    extractor_name: str = ""
    extractor_version: str = "1.0.0"
    extractor_method: str = "deterministic"  # 'deterministic' | 'llm_temperature_zero' | 'llm_sampled'
    hypothesis_uuid: str = ""
    hypothesis_name: str = ""
    built_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    parameters: Dict[str, Any] = field(default_factory=dict)
    data_source_timestamps: Dict[str, str] = field(default_factory=dict)
    content_hash: str = ""
    warnings: List[str] = field(default_factory=list)


@dataclass
class SignalData:
    """Standardized signal data ready for pipeline ingestion.

    Schema:
        date: Observation date (index).
        ticker: Ticker symbol (columns, or a column in long format).
        signal_value: The computed signal value.
        Plus arbitrary additional columns depending on the signal type.
    """
    df: pd.DataFrame                          # Wide format: date index, ticker columns
    metadata: SignalMetadata = field(default_factory=SignalMetadata)
    long_format: Optional[pd.DataFrame] = None  # Optional long format: date, ticker, signal_value, ...

    def validate(self) -> Tuple[bool, List[str]]:
        """Validate that the signal data conforms to the pipeline's expected format."""
        issues = []
        if self.df is None:
            issues.append("Signal DataFrame is None")
            return False, issues
        if self.df.empty:
            issues.append("Signal DataFrame is empty")
            return False, issues
        if not isinstance(self.df.index, pd.DatetimeIndex):
            issues.append("Signal DataFrame index must be DatetimeIndex (dates)")
        if len(self.df.columns) == 0:
            issues.append("Signal DataFrame has no columns (tickers)")
        return len(issues) == 0, issues

    def save(self, path: str) -> str:
        """Save signal data to parquet (or CSV fallback) with embedded metadata."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        # Try parquet first, fall back to CSV
        try:
            self.df.to_parquet(path, index=True)
        except (ImportError, Exception) as e:
            path = path.replace(".parquet", ".csv")
            self.df.to_csv(path, index=True)
            logger = __import__("logging").getLogger(__name__)
            logger.warning(
                f"Parquet save failed ({e}), saved as CSV instead: {path}"
            )

        # Save metadata alongside
        meta_path = path.replace(".parquet", "_metadata.json").replace(".csv", "_metadata.json")
        with open(meta_path, "w") as f:
            json.dump(asdict(self.metadata), f, indent=2, default=str)

        return path


# ============================================================================
# Abstract Base Classes
# ============================================================================


class DataAdapter(ABC):
    """Abstract base class for raw data acquisition.

    Each concrete adapter knows how to acquire data from one source
    (FDA, SEC EDGAR, Yahoo Finance, FMP, FRED, etc.) and return a
    standardized RawData object.

    Subclasses must implement:
        acquire(spec) -> RawData
        validate(raw_data) -> bool
        source_name -> property
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable source identifier (e.g., 'fda', 'sec_edgar')."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Adapter version for reproducibility tracking."""
        ...

    @abstractmethod
    def acquire(self, spec: DataSourceSpec) -> RawData:
        """Acquire raw data from the source.

        Args:
            spec: Data source specification from the hypothesis.

        Returns:
            A RawData container with the acquired data.

        Raises:
            DataAcquisitionError: If the data cannot be acquired and the
                hypothesis should be judged UNTESTABLE.
        """
        ...

    @abstractmethod
    def validate(self, raw_data: RawData) -> Tuple[bool, List[str]]:
        """Validate that acquired raw data meets quality standards.

        Args:
            raw_data: The data to validate.

        Returns:
            Tuple of (is_valid, list_of_issues).
        """
        ...

    def health_check(self) -> Tuple[bool, str]:
        """Check if the data source is accessible.

        Returns:
            Tuple of (is_accessible, message).
        """
        return False, "Health check not implemented"


class SignalExtractor(ABC):
    """Abstract base class for signal extraction from raw data.

    Each concrete extractor implements one type of signal extraction
    (linguistic features, filing diffs, classification, etc.).

    Subclasses must implement:
        extract(raw_data, params) -> SignalData
        extractor_name -> property
    """

    @property
    @abstractmethod
    def extractor_name(self) -> str:
        """Human-readable extractor identifier (e.g., 'linguistic', 'filing_diff')."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Extractor version for reproducibility tracking."""
        ...

    @abstractmethod
    def extract(self, raw_data: RawData, params: Optional[Dict[str, Any]] = None) -> SignalData:
        """Extract a signal from raw data.

        Args:
            raw_data: Raw data to extract from.
            params: Extraction parameters (thresholds, weights, etc.).

        Returns:
            SignalData with the computed signal.
        """
        ...

    def validate_signal(self, signal: SignalData) -> Tuple[bool, List[str]]:
        """Validate the extracted signal. Override for extractor-specific checks."""
        return signal.validate()


# ============================================================================
# Exceptions
# ============================================================================


class DataAcquisitionError(Exception):
    """Raised when a data adapter cannot acquire the required data.

    Maps to UNTESTABLE verdict in the pipeline."""
    def __init__(self, source: str, reason: str, missing_data: Optional[str] = None):
        super().__init__(f"[{source}] {reason}")
        self.source = source
        self.reason = reason
        self.missing_data = missing_data


class SignalExtractionError(Exception):
    """Raised when signal extraction fails."""
    def __init__(self, extractor: str, reason: str):
        super().__init__(f"[{extractor}] {reason}")
        self.extractor = extractor
        self.reason = reason


class UntestableHypothesisError(Exception):
    """Raised when a hypothesis cannot be tested due to data constraints.

    This is the canonical error type for hypotheses that must be marked UNTESTABLE."""
    def __init__(self, hypothesis_uuid: str, reason: str, data_gap: str = ""):
        super().__init__(f"UNTESTABLE [{hypothesis_uuid}]: {reason}")
        self.hypothesis_uuid = hypothesis_uuid
        self.reason = reason
        self.data_gap = data_gap
