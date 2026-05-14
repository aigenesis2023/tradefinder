"""
yahoo_finance.py — Yahoo Finance Data Adapter
=============================================

Acquires price, volume, and fundamental data via yfinance.

Data sources (free but with limitations):
  - Yahoo Finance (via yfinance library)
  - Known biases: survivorship bias pre-2017, no historical index constituents,
    corporate actions may lag 1-2 days

Status: FUNCTIONAL SKELETON — price acquisition works end-to-end.
  For real pipeline runs, yfinance is the primary free price data source.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..base import (
    DataAcquisitionError,
    DataAdapter,
    DataSourceSpec,
    RawData,
)

import os as _os, sys as _sys
_PARENT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PARENT not in _sys.path:
    _sys.path.insert(0, _PARENT)

logger = logging.getLogger(__name__)


class YahooFinanceAdapter(DataAdapter):
    """Acquire price and fundamental data from Yahoo Finance.

    Supports:
    - Historical price data (OHLCV) via yfinance
    - Dividend and split data
    - Basic fundamental data (market cap, P/E, etc.)

    All data is free but has known survivorship bias for stocks delisted
    before approximately 2017.
    """

    @property
    def source_name(self) -> str:
        return "yahoo"

    @property
    def version(self) -> str:
        return "1.0.0"

    def __init__(self, cache_dir: Optional[str] = None):
        self._cache_dir = cache_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "_cache", "yahoo"
        )

    def health_check(self) -> Tuple[bool, str]:
        """Check if yfinance is available."""
        try:
            import yfinance as yf
            return True, "yfinance available"
        except ImportError:
            return False, "yfinance not installed (pip install yfinance)"

    def acquire(self, spec: DataSourceSpec) -> RawData:
        """Acquire price data for specified tickers and date range.

        Args:
            spec: DataSourceSpec with tickers in metadata or custom_tickers field.

        Returns:
            RawData with price records.
        """
        try:
            import yfinance as yf
        except ImportError:
            raise DataAcquisitionError(
                source="Yahoo Finance",
                reason="yfinance not installed. Install with: pip install yfinance",
                missing_data="Price data",
            )

        tickers = spec.metadata.get("tickers", []) if hasattr(spec, "metadata") else []
        if not tickers:
            raise DataAcquisitionError(
                source="Yahoo Finance",
                reason="No tickers specified in data source",
                missing_data="Ticker list for price data",
            )

        if len(tickers) > 50:
            logger.warning(
                f"Downloading data for {len(tickers)} tickers; yfinance may be slow. "
                f"Consider splitting into batches."
            )

        logger.info(f"Downloading Yahoo Finance data for {len(tickers)} tickers...")
        all_data = []

        for i, ticker in enumerate(tickers):
            try:
                tkr = yf.Ticker(ticker)
                hist = tkr.history(
                    start=spec.start_date,
                    end=spec.end_date,
                    auto_adjust=True,
                )
                if not hist.empty:
                    hist["ticker"] = ticker
                    hist.index.name = "date"
                    all_data.append(hist.reset_index())
            except Exception as e:
                logger.warning(f"Failed to download {ticker}: {e}")

        if not all_data:
            raise DataAcquisitionError(
                source="Yahoo Finance",
                reason=f"No price data available for any of {len(tickers)} tickers",
                missing_data=f"Price history for {tickers[:5]}...",
            )

        df = pd.concat(all_data, ignore_index=True)
        logger.info(
            f"Yahoo Finance adapter acquired {len(df)} price records "
            f"for {df['ticker'].nunique()} tickers"
        )

        return RawData(
            records=df,
            source_type=spec.source_type,
            provider="yahoo",
            metadata={
                "n_records": len(df),
                "n_tickers": df["ticker"].nunique(),
                "date_range": f"{spec.start_date} to {spec.end_date}",
            },
        )

    def validate(self, raw_data: RawData) -> Tuple[bool, List[str]]:
        """Validate price data quality."""
        issues = []
        valid, basic_issues = raw_data.validate()
        issues.extend(basic_issues)
        if not valid:
            return False, issues

        df = raw_data.records
        required_cols = ["date", "ticker", "Close"]
        for col in required_cols:
            if col not in df.columns:
                issues.append(f"Missing required column: {col}")

        if "Close" in df.columns and df["Close"].isna().mean() > 0.5:
            issues.append("More than 50% of Close prices are NaN")

        return len(issues) == 0, issues
