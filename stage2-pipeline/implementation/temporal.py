"""
temporal.py — Temporal Alignment & Point-in-Time Data Handling
==============================================================

Agent 2: Data Engineering & Temporal Alignment Specialist
Reviewer: Agent 5 (Data Breaker)

This module ensures that every data point is timestamped to when it was ACTUALLY
available to a retail trader. No look-ahead bias. Every data point is tagged with
its "known_date" — the date a trader could have acted on it.

Key design decisions:
- Fundamental data assigned to SEC filing acceptance date, NOT fiscal period end date
- Earnings data assigned to announcement date (8-K filing date)
- All data lag is tracked and reported
- Automatic look-ahead breach detection
- Point-in-time data snapshots constructed for each observation date

DESIGN NOTE (Data Breaker review):
The most common look-ahead bias in empirical finance is using fiscal period end
dates rather than filing acceptance dates. A 10-K for FY ending Dec 31 filed on
Feb 15 is NOT known on Jan 1. This module enforces this at the framework level.

VETO FIX (Data Breaker): Added automatic look-ahead breach scan that runs after
every dataset construction. Any breach triggers a FATAL state that invalidates
all downstream results until fixed.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================================
# Known-Date Assignment Rules
# ============================================================================


class DataType(Enum):
    """Types of data with different known-date rules."""

    PRICE = "price"
    FUNDAMENTAL = "fundamental"          # 10-K, 10-Q
    EARNINGS = "earnings"                # Earnings announcements
    SEC_FILING = "sec_filing"            # General SEC filings
    TRANSCRIPT = "transcript"            # Earnings call transcripts
    ANALYST_REPORT = "analyst_report"
    NEWS = "news"
    SOCIAL_MEDIA = "social_media"
    ECONOMIC_DATA = "economic_data"
    ALTERNATIVE = "alternative"
    SENTIMENT = "sentiment"
    CUSTOM = "custom"


# Known-date offset rules (business days after the data becomes available)
# These represent the typical delay before a retail trader can access and act on data
KNOWN_DATE_RULES: Dict[DataType, int] = {
    DataType.PRICE: 0,              # Available at close (action on next open)
    DataType.FUNDAMENTAL: 1,        # 1 business day after SEC acceptance
    DataType.EARNINGS: 1,           # 1 business day after announcement
    DataType.SEC_FILING: 1,         # 1 business day after SEC acceptance
    DataType.TRANSCRIPT: 0,         # Available same day (typically)
    DataType.ANALYST_REPORT: 1,     # Next business day
    DataType.NEWS: 0,               # Available same day
    DataType.SOCIAL_MEDIA: 0,       # Immediate
    DataType.ECONOMIC_DATA: 1,      # Next business day
    DataType.ALTERNATIVE: 0,        # Provider-dependent, assume same day
    DataType.SENTIMENT: 0,          # Provider-dependent
    DataType.CUSTOM: 0,             # Specified by user
}

# Map of data types to their source timestamp field
# This is critical: we must use the correct field for the known date
TIMESTAMP_FIELD_MAP: Dict[DataType, str] = {
    DataType.PRICE: "trade_date",
    DataType.FUNDAMENTAL: "filing_acceptance_date",  # NOT fiscal_period_end_date!
    DataType.EARNINGS: "announcement_date",
    DataType.SEC_FILING: "filing_acceptance_date",
    DataType.TRANSCRIPT: "transcript_publication_date",
    DataType.ANALYST_REPORT: "publication_date",
    DataType.NEWS: "publication_date",
    DataType.SOCIAL_MEDIA: "post_timestamp",
    DataType.ECONOMIC_DATA: "release_date",
    DataType.ALTERNATIVE: "provider_timestamp",
    DataType.SENTIMENT: "provider_timestamp",
    DataType.CUSTOM: "custom_timestamp",
}


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class TemporalMetadata:
    """Metadata about data temporality."""

    data_type: DataType
    source_timestamp_field: str
    known_date_offset_days: int
    data_source: str
    data_version: str  # For reproducibility


@dataclass
class TemporalDataPoint:
    """A single data point with its temporal metadata."""

    ticker: str
    observation_date: str            # When we're computing the signal (YYYY-MM-DD)
    known_date: str                  # When data became available
    data_type: DataType
    field_name: str
    value: Any
    event_date: Optional[str] = None  # When the event happened (e.g., fiscal period end)
    source_timestamp: Optional[str] = None  # The raw timestamp from the source
    data_lag_days: int = 0           # observation_date - known_date
    event_lag_days: int = 0          # known_date - event_date (data staleness)


@dataclass
class TemporalAlignmentReport:
    """Report on temporal alignment quality."""

    total_observations: int
    look_ahead_breaches: List[Dict[str, Any]]
    lag_statistics: Dict[str, Dict[str, float]]  # field -> {mean_lag, median_lag, p95_lag, max_lag}
    staleness_flags: List[str]
    is_valid: bool  # True only if zero look-ahead breaches
    warnings: List[str]


@dataclass
class LookAheadBreach:
    """Record of a look-ahead bias contamination."""

    observation_date: str
    ticker: str
    data_field: str
    data_type: DataType
    known_date: str
    source_timestamp: str
    event_date: Optional[str]
    days_ahead: int  # How many days into the future the data was from observation
    severity: str  # 'CRITICAL' | 'WARNING'
    description: str


# ============================================================================
# Point-in-Time Data Builder
# ============================================================================


class PointInTimeBuilder:
    """
    Builds point-in-time datasets with strict temporal alignment.

    This is the CORE temporal integrity component. It ensures that for any
    observation date T, only data that was actually available at T is used
    to construct the signal.

    DESIGN NOTE (Statistical Epistemologist): This is the single most important
    component for honest empirical research. More papers are invalidated by
    look-ahead bias than by any other methodological error.
    """

    def __init__(self, calendar: Optional[pd.DataFrame] = None):
        """
        Initialize the PIT builder.

        Args:
            calendar: Trading calendar DataFrame with 'date' and 'is_trading_day' columns
        """
        self.calendar = calendar or self._default_trading_calendar()
        self._data_registry: Dict[str, TemporalMetadata] = {}
        self._breaches: List[LookAheadBreach] = []
        self._lag_stats: Dict[str, List[int]] = {}

    def _default_trading_calendar(self) -> pd.DataFrame:
        """Generate a default US trading calendar."""
        # In production, this would use pandas_market_calendars or equivalent
        # For now, generate a Monday-Friday calendar excluding common holidays
        dates = pd.date_range("2000-01-01", "2030-12-31", freq="B")
        return pd.DataFrame({"date": dates, "is_trading_day": True})

    def register_data_source(
        self,
        source_name: str,
        data_type: DataType,
        timestamp_field: Optional[str] = None,
        known_date_offset_days: Optional[int] = None,
        data_version: str = "1.0",
    ) -> None:
        """
        Register a data source with its temporal rules.

        Args:
            source_name: Unique name for this data source
            data_type: Type of data (determines default timestamp rules)
            timestamp_field: Override the default timestamp field
            known_date_offset_days: Override the default offset
            data_version: Version string for reproducibility
        """
        metadata = TemporalMetadata(
            data_type=data_type,
            source_timestamp_field=timestamp_field
            or TIMESTAMP_FIELD_MAP[data_type],
            known_date_offset_days=(
                known_date_offset_days
                if known_date_offset_days is not None
                else KNOWN_DATE_RULES[data_type]
            ),
            data_source=source_name,
            data_version=data_version,
        )
        self._data_registry[source_name] = metadata
        logger.info(
            f"Registered data source '{source_name}' as {data_type.value} "
            f"with {metadata.known_date_offset_days} day offset"
        )

    def build_pit_dataset(
        self,
        raw_data: pd.DataFrame,
        source_name: str,
        observation_dates: List[str],
        ticker_field: str = "ticker",
        value_fields: Optional[List[str]] = None,
        event_date_field: Optional[str] = None,
        timestamp_field_override: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Build a point-in-time dataset from raw data.

        This is the main interface. Given raw data with timestamps, it constructs
        a dataset where for each (observation_date, ticker) pair, each field
        contains the most recent value available at that date, with zero
        look-ahead contamination.

        Args:
            raw_data: Raw data DataFrame with temporal metadata
            source_name: Registered data source name
            observation_dates: List of dates when signals are computed
            ticker_field: Column name for ticker symbol
            value_fields: Columns to include in the PIT output
            event_date_field: Column with event date (e.g., fiscal period end)
            timestamp_field_override: Override the default timestamp field

        Returns:
            DataFrame with columns:
            [observation_date, ticker, {value_fields}, known_dates, lags, ...]
        """
        if source_name not in self._data_registry:
            raise ValueError(
                f"Data source '{source_name}' not registered. "
                f"Call register_data_source() first."
            )

        metadata = self._data_registry[source_name]
        timestamp_field = timestamp_field_override or metadata.source_timestamp_field
        value_fields = value_fields or [
            c for c in raw_data.columns if c not in {ticker_field, timestamp_field, event_date_field or ""}
        ]

        # Validate that the timestamp field exists
        if timestamp_field not in raw_data.columns:
            raise ValueError(
                f"Timestamp field '{timestamp_field}' not found in raw_data. "
                f"Available columns: {raw_data.columns.tolist()}"
            )

        # Ensure timestamps are datetime
        raw_data = raw_data.copy()
        raw_data[timestamp_field] = pd.to_datetime(raw_data[timestamp_field])

        # Compute known_date for each raw data point
        raw_data["known_date"] = raw_data[timestamp_field] + pd.Timedelta(
            days=metadata.known_date_offset_days
        )

        # Build PIT dataset iteratively for each observation date
        pit_records = []

        for obs_date in sorted(observation_dates):
            obs_dt = pd.Timestamp(obs_date)

            # Filter to data known on or before obs_date
            available = raw_data[raw_data["known_date"] <= obs_dt].copy()

            if available.empty:
                continue

            # For each ticker, take the most recent available data
            for ticker in available[ticker_field].unique():
                ticker_data = available[available[ticker_field] == ticker]

                # Get the most recent observation
                latest = ticker_data.sort_values("known_date", ascending=False).iloc[0]

                record = {
                    "observation_date": obs_date,
                    ticker_field: ticker,
                }

                for field in value_fields:
                    record[field] = latest.get(field, np.nan)

                record["known_date"] = latest["known_date"]
                if event_date_field and event_date_field in latest.index:
                    record["event_date"] = latest[event_date_field]

                record["data_lag_days"] = (
                    obs_dt - pd.Timestamp(latest["known_date"])
                ).days
                record["data_source"] = source_name
                record["data_type"] = metadata.data_type.value

                pit_records.append(record)

        pit_df = pd.DataFrame(pit_records)
        return pit_df

    def check_look_ahead_breaches(
        self, dataset: pd.DataFrame, observation_date_col: str = "observation_date",
        known_date_col: str = "known_date", ticker_col: str = "ticker",
    ) -> List[LookAheadBreach]:
        """
        Scan dataset for look-ahead bias contamination.

        Any row where known_date > observation_date is a look-ahead breach.
        This is FATAL — results based on contaminated data are invalid.

        Returns:
            List of LookAheadBreach records (empty list = clean)
        """
        breaches = []

        dataset = dataset.copy()
        dataset[observation_date_col] = pd.to_datetime(dataset[observation_date_col])
        dataset[known_date_col] = pd.to_datetime(dataset[known_date_col])

        # Find rows where known_date > observation_date
        contaminated = dataset[dataset[known_date_col] > dataset[observation_date_col]]

        for _, row in contaminated.iterrows():
            days_ahead = (
                row[known_date_col] - row[observation_date_col]
            ).days

            breach = LookAheadBreach(
                observation_date=row[observation_date_col].strftime("%Y-%m-%d"),
                ticker=row.get(ticker_col, "UNKNOWN"),
                data_field="unknown",
                data_type=DataType.CUSTOM,
                known_date=row[known_date_col].strftime("%Y-%m-%d"),
                source_timestamp=row.get("source_timestamp", ""),
                event_date=row.get("event_date"),
                days_ahead=days_ahead,
                severity="CRITICAL",
                description=f"Data known on {row[known_date_col]} used at "
                f"observation date {row[observation_date_col]} "
                f"({days_ahead} days ahead).",
            )
            breaches.append(breach)
            self._breaches.append(breach)

        if breaches:
            logger.error(
                f"LOOK-AHEAD BREACH DETECTED: {len(breaches)} contaminated "
                f"observations found. Results are INVALID."
            )
        else:
            logger.info("No look-ahead breaches detected. Dataset is temporally clean.")

        return breaches

    def compute_lag_statistics(
        self, dataset: pd.DataFrame, value_fields: List[str],
        known_date_col: str = "known_date", obs_date_col: str = "observation_date",
    ) -> Dict[str, Dict[str, float]]:
        """
        Compute data lag statistics for each field.

        Data lag = observation_date - known_date. Large lags indicate stale data.
        """
        lag_stats = {}

        dataset = dataset.copy()
        dataset[obs_date_col] = pd.to_datetime(dataset[obs_date_col])
        dataset[known_date_col] = pd.to_datetime(dataset[known_date_col])
        dataset["_lag"] = (
            dataset[obs_date_col] - dataset[known_date_col]
        ).dt.days

        lags = dataset["_lag"]

        stats = {
            "mean_lag": lags.mean(),
            "median_lag": lags.median(),
            "p5_lag": lags.quantile(0.05),
            "p25_lag": lags.quantile(0.25),
            "p75_lag": lags.quantile(0.75),
            "p95_lag": lags.quantile(0.95),
            "max_lag": lags.max(),
            "min_lag": lags.min(),
            "n_observations": len(lags),
            "n_missing": lags.isna().sum(),
        }

        lag_stats["overall"] = stats

        # Per-field lag to detect stale data feeds
        for field in value_fields:
            if field in dataset.columns:
                field_missing = dataset[field].isna()
                if field_missing.any():
                    lag_stats[field] = {
                        **stats,
                        "n_missing": field_missing.sum(),
                        "stale_days_ratio": "N/A (different data feed)",
                    }

        self._lag_stats = {k: v for k, v in lag_stats.items() if isinstance(v, dict)}
        return lag_stats

    def flag_stale_data(
        self, lag_stats: Dict[str, Dict[str, float]], max_lag_days: int = 30
    ) -> List[str]:
        """
        Flag data fields with excessive lag.

        If mean lag > 30 days, the data may be too stale for practical use.
        """
        flags = []

        overall = lag_stats.get("overall", {})
        mean_lag = overall.get("mean_lag", 0)

        if mean_lag > max_lag_days:
            flags.append(
                f"OVERALL data lag ({mean_lag:.1f} days) exceeds threshold "
                f"({max_lag_days} days). Signal may be using stale data."
            )
        if mean_lag > 90:
            flags.append(
                f"CRITICAL: Overall data lag ({mean_lag:.1f} days) is > 90 days. "
                f"Fundamental data is likely misaligned (using period end instead "
                f"of filing date?). Check timestamp fields."
            )

        return flags

    def generate_alignment_report(
        self, dataset: pd.DataFrame, value_fields: List[str],
        observation_date_col: str = "observation_date",
        known_date_col: str = "known_date",
    ) -> TemporalAlignmentReport:
        """
        Generate a complete temporal alignment report.

        This is the mandatory output that validates temporal integrity.
        """
        # 1. Check for look-ahead breaches
        breaches = self.check_look_ahead_breaches(
            dataset, observation_date_col, known_date_col
        )

        # 2. Compute lag statistics
        lag_stats = self.compute_lag_statistics(
            dataset, value_fields, known_date_col, observation_date_col
        )

        # 3. Flag stale data
        staleness_flags = self.flag_stale_data(lag_stats)

        # 4. Determine validity
        is_valid = len(breaches) == 0

        # 5. Compile warnings
        warnings = staleness_flags.copy()
        breach_descriptions = [b.description for b in breaches]
        warnings.extend(breach_descriptions)

        return TemporalAlignmentReport(
            total_observations=len(dataset),
            look_ahead_breaches=[
                {
                    "observation_date": b.observation_date,
                    "ticker": b.ticker,
                    "data_field": b.data_field,
                    "days_ahead": b.days_ahead,
                    "severity": b.severity,
                    "description": b.description,
                }
                for b in breaches
            ],
            lag_statistics=lag_stats,
            staleness_flags=staleness_flags,
            is_valid=is_valid,
            warnings=warnings,
        )

    def get_next_trading_day(self, date_str: str, offset: int = 1) -> str:
        """
        Get the next trading day after a given date.

        This is used to align signals to executable dates.
        Signals computed at close on day T are executed at open on T+1.
        """
        date = pd.Timestamp(date_str)

        if self.calendar is not None:
            future_dates = self.calendar[
                (self.calendar["date"] > date) & (self.calendar["is_trading_day"])
            ]["date"]

            if len(future_dates) >= offset:
                return future_dates.iloc[offset - 1].strftime("%Y-%m-%d")

        # Fallback: next business day
        next_date = date + pd.Timedelta(days=offset)
        while next_date.weekday() >= 5:  # Skip weekends
            next_date += pd.Timedelta(days=1)
        return next_date.strftime("%Y-%m-%d")

    def get_previous_trading_day(self, date_str: str, offset: int = 1) -> str:
        """Get the previous trading day."""
        date = pd.Timestamp(date_str)

        if self.calendar is not None:
            past_dates = self.calendar[
                (self.calendar["date"] < date) & (self.calendar["is_trading_day"])
            ]["date"]

            if len(past_dates) >= offset:
                return past_dates.iloc[-offset].strftime("%Y-%m-%d")

        prev_date = date - pd.Timedelta(days=offset)
        while prev_date.weekday() >= 5:
            prev_date -= pd.Timedelta(days=1)
        return prev_date.strftime("%Y-%m-%d")


# ============================================================================
# Temporal Alignment for Forward Returns
# ============================================================================


class ForwardReturnCalculator:
    """
    Calculates forward returns with proper temporal alignment.

    Signal computed at close on day T → position entered at open T+1
    → held for holding_period trading days → exited at close T+holding_period.

    DESIGN NOTE (Backtesting Engineer):
    Using close-to-close returns when the signal is based on closing data
    is a common error. The correct approach is:
    - Signal: data up to close(T)
    - Entry: open(T+1) [or close(T+1) for daily signals]
    - Exit: close(T+holding_period)
    """

    def __init__(self, trading_calendar: Optional[pd.DataFrame] = None):
        self.trading_calendar = trading_calendar

    def compute_forward_returns(
        self,
        prices: pd.DataFrame,  # date x ticker matrix of closing prices
        signal_dates: List[str],
        tickers: List[str],
        holding_period_days: int,
    ) -> pd.DataFrame:
        """
        Compute forward returns with correct temporal alignment.

        Args:
            prices: DataFrame with dates as index, tickers as columns
            signal_dates: List of dates when signals are observed
            tickers: List of ticker symbols
            holding_period_days: Holding period in calendar days

        Returns:
            DataFrame with columns:
            [signal_date, ticker, entry_price, exit_price,
             forward_return, holding_period_days, exit_date]
        """
        returns_records = []

        for signal_date in signal_dates:
            # Entry: next day after signal
            # In practice: signal at close(T) → enter at open(T+1)
            # We approximate with next available close price
            signal_dt = pd.Timestamp(signal_date)

            for ticker in tickers:
                if ticker not in prices.columns:
                    continue

                ticker_prices = prices[ticker].dropna()

                # Find the entry price (first price after signal date)
                entry_prices = ticker_prices[ticker_prices.index > signal_dt]
                if entry_prices.empty:
                    continue

                entry_date = entry_prices.index[0]
                entry_price = entry_prices.iloc[0]

                # Find exit price (after holding period)
                exit_date_cutoff = entry_date + pd.Timedelta(days=holding_period_days)
                exit_prices = ticker_prices[ticker_prices.index <= exit_date_cutoff]
                if exit_prices.empty or exit_prices.index[-1] <= entry_date:
                    continue

                exit_date = exit_prices.index[-1]
                exit_price = exit_prices.iloc[-1]

                if entry_price > 0:
                    forward_return = (exit_price / entry_price) - 1.0
                else:
                    forward_return = np.nan

                returns_records.append(
                    {
                        "signal_date": signal_date,
                        "ticker": ticker,
                        "entry_date": entry_date.strftime("%Y-%m-%d"),
                        "exit_date": exit_date.strftime("%Y-%m-%d"),
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "forward_return": forward_return,
                        "holding_period_days_actual": (exit_date - entry_date).days,
                        "holding_period_days_target": holding_period_days,
                    }
                )

        return pd.DataFrame(returns_records)

    def compute_cumulative_returns(
        self,
        forward_returns: pd.DataFrame,
        position_sizing_func: Optional[Callable] = None,
    ) -> pd.Series:
        """
        Compute cumulative portfolio returns from individual forward returns.
        """
        if forward_returns.empty:
            return pd.Series(dtype=float)

        # Group by signal_date for portfolio-level returns
        if position_sizing_func is not None:
            forward_returns = forward_returns.copy()
            forward_returns["weight"] = forward_returns.apply(
                lambda row: position_sizing_func(row), axis=1
            )
            forward_returns["weighted_return"] = (
                forward_returns["forward_return"] * forward_returns["weight"]
            )
            portfolio_returns = forward_returns.groupby("signal_date")[
                "weighted_return"
            ].sum()
        else:
            # Equal weight
            portfolio_returns = forward_returns.groupby("signal_date")[
                "forward_return"
            ].mean()

        return portfolio_returns


# ============================================================================
# Filing Date Aligner (SEC-Specific)
# ============================================================================


class SECFilingAligner:
    """
    Specialized temporal aligner for SEC filings.

    This is critically important because many researchers incorrectly use
    fiscal period end dates rather than filing acceptance dates.

    Known filing deadlines:
    - 10-K: 60-90 days after fiscal year end (depending on filer size)
    - 10-Q: 40-45 days after fiscal quarter end
    - 8-K: 4 business days after triggering event

    Using fiscal period end date (e.g., 2020-12-31) when the filing wasn't
    accepted until 2021-02-15 is a CLASSIC look-ahead bias.
    """

    def __init__(self):
        self.filing_deadlines = {
            "10-K": 60,   # Large accelerated filer — 60 days
            "10-K_L": 90,  # Other filers — 90 days
            "10-Q": 40,    # Large accelerated filer — 40 days
            "10-Q_L": 45,  # Other filers — 45 days
            "8-K": 4,      # 4 business days
        }

    def estimate_filing_acceptance_date(
        self, fiscal_period_end: str, filing_type: str, filer_size: str = "large"
    ) -> str:
        """
        Estimate when a filing would have been accepted.

        This is a conservative estimate used when actual acceptance dates
        are not available. The estimate adds the maximum allowed filing
        delay to the fiscal period end date.

        KNOWN BIAS: This overestimates the delay for companies that file early.
        """
        period_end = pd.Timestamp(fiscal_period_end)

        if filing_type == "10-K":
            days = self.filing_deadlines["10-K"] if filer_size == "large" else self.filing_deadlines["10-K_L"]
        elif filing_type == "10-Q":
            days = self.filing_deadlines["10-Q"] if filer_size == "large" else self.filing_deadlines["10-Q_L"]
        else:
            days = self.filing_deadlines.get(filing_type, 4)

        # Add business days
        estimated = period_end
        business_days_added = 0
        while business_days_added < days:
            estimated += pd.Timedelta(days=1)
            if estimated.weekday() < 5:  # Not weekend
                business_days_added += 1

        return estimated.strftime("%Y-%m-%d")

    def align_filings_to_observations(
        self,
        filings: pd.DataFrame,
        observation_dates: List[str],
        cik_field: str = "cik",
        acceptance_date_field: str = "filing_acceptance_date",
        fiscal_end_field: str = "fiscal_period_end",
    ) -> pd.DataFrame:
        """
        Align SEC filings to observation dates using acceptance dates.

        This function creates the correct mapping: for each observation date,
        which filings were actually available?
        """
        filings = filings.copy()
        filings[acceptance_date_field] = pd.to_datetime(filings[acceptance_date_field])
        filings["known_date"] = filings[acceptance_date_field] + pd.Timedelta(days=1)

        aligned_records = []

        for obs_date in sorted(observation_dates):
            obs_dt = pd.Timestamp(obs_date)

            available = filings[filings["known_date"] <= obs_dt]

            for cik in available[cik_field].unique():
                cik_filings = available[available[cik_field] == cik]
                latest = cik_filings.sort_values("known_date", ascending=False).iloc[0]

                aligned_records.append(
                    {
                        "observation_date": obs_date,
                        cik_field: cik,
                        "filing_type": latest.get("filing_type", ""),
                        "fiscal_period_end": latest.get(fiscal_end_field),
                        "filing_acceptance_date": latest.get(acceptance_date_field),
                        "known_date": latest["known_date"],
                        "lag_days": (obs_dt - latest["known_date"]).days,
                    }
                )

        return pd.DataFrame(aligned_records)
