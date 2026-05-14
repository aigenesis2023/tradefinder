"""
yahoo_finance.py — Yahoo Finance Price Data Adapter
====================================================

Acquires historical price data (OHLCV) for US equities from Yahoo Finance
via the yfinance library.

Data: Free, retail-accessible. No API key required.
Known limitation: survivorship bias for stocks delisted before ~2017.

Caching: Per-ticker price data is cached as parquet files. Subsequent runs
for the same ticker+date range use cached data, not re-downloaded.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
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
    """Acquire historical price data from Yahoo Finance via yfinance.

    Known limitation: yfinance may not return data for stocks delisted
    before ~2017, introducing survivorship bias. The SurvivorshipGuard
    in the pipeline flags this limitation.

    Caching is enabled by default to avoid re-downloading on re-runs.
    """

    @property
    def source_name(self) -> str:
        return "yahoo"

    @property
    def version(self) -> str:
        return "2.0.0"

    def __init__(self, cache_dir: Optional[str] = None):
        self._cache_dir = cache_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "_cache", "yahoo"
        )
        os.makedirs(self._cache_dir, exist_ok=True)

    def health_check(self) -> Tuple[bool, str]:
        """Check if yfinance is available."""
        try:
            import yfinance as yf
            return True, "yfinance available"
        except ImportError:
            return False, "yfinance not installed (pip install yfinance)"

    def acquire(self, spec: DataSourceSpec) -> RawData:
        """Acquire price data for specified tickers and date range.

        Caches per-ticker data as parquet files to avoid re-downloading.
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

        logger.info(f"Downloading Yahoo Finance data for {len(tickers)} tickers...")

        # Use parallel download pool for 10+ tickers
        if len(tickers) >= 10:
            all_data = self._download_parallel(tickers, spec, yf)
        else:
            all_data = self._download_sequential(tickers, spec, yf)

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

    def _download_sequential(
        self, tickers: List[str], spec: DataSourceSpec, yf
    ) -> List[pd.DataFrame]:
        """Download tickers one at a time (for small batches)."""
        all_data = []
        for ticker in tickers:
            hist = self._get_ticker_history(ticker, spec, yf)
            if hist is not None:
                all_data.append(hist)
        return all_data

    def _download_parallel(
        self, tickers: List[str], spec: DataSourceSpec, yf
    ) -> List[pd.DataFrame]:
        """Download tickers in parallel using a thread pool."""
        try:
            from ..download_pool import DownloadPool
        except ImportError:
            # Fall back to sequential if download_pool unavailable
            return self._download_sequential(tickers, spec, yf)

        def fetch_one(ticker: str) -> Optional[pd.DataFrame]:
            return self._get_ticker_history(ticker, spec, yf)

        all_data = []
        with DownloadPool(max_workers=8, rate_limit=20.0, retries=1) as pool:
            results = pool.map(fetch_one, tickers, desc="Yahoo price downloads")
            for r in results:
                if r.success and r.result is not None:
                    all_data.append(r.result)

        return all_data

    def _get_ticker_history(
        self, ticker: str, spec: DataSourceSpec, yf
    ) -> Optional[pd.DataFrame]:
        """Get price history for a single ticker, with caching."""
        cache_key = f"{ticker}_{spec.start_date}_{spec.end_date}"
        cache_path = os.path.join(self._cache_dir, f"{cache_key}.parquet")

        # Check cache
        if os.path.exists(cache_path):
            try:
                cached = pd.read_parquet(cache_path)
                if not cached.empty:
                    return cached
            except Exception:
                pass  # Cache corrupt, re-download

        # Download from Yahoo Finance
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
                result = hist.reset_index()

                # Cache for future runs
                try:
                    result.to_parquet(cache_path, index=False)
                except Exception:
                    pass  # Non-critical: cache write failure

                return result
        except Exception as e:
            logger.warning(f"Failed to download {ticker}: {e}")

        return None

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
