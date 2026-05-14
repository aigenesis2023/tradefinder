"""
fred.py — FRED (Federal Reserve Economic Data) Adapter
=========================================================

Acquires macroeconomic data from the St. Louis Fed's FRED database.

Data sources (free, no API key required for basic access):
  - 823,000+ US and international economic time series
  - Interest rates, GDP, employment, inflation, etc.
  - Federal Reserve data releases

Status: FUNCTIONAL SKELETON — uses fredapi when available.
  Falls back to synthetic macro data when API is unavailable.
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


# Common FRED series codes
COMMON_SERIES = {
    "GDP": "GDP",                       # Gross Domestic Product
    "UNRATE": "UNRATE",                # Unemployment Rate
    "CPIAUCSL": "CPIAUCSL",           # Consumer Price Index
    "FEDFUNDS": "FEDFUNDS",           # Federal Funds Rate
    "DGS10": "DGS10",                 # 10-Year Treasury Rate
    "DGS2": "DGS2",                   # 2-Year Treasury Rate
    "VIXCLS": "VIXCLS",              # VIX (CBOE Volatility Index)
    "T10YIE": "T10YIE",             # 10-Year Breakeven Inflation
    "INDPRO": "INDPRO",            # Industrial Production Index
    "PAYEMS": "PAYEMS",           # Total Nonfarm Payrolls
    "SP500": "SP500",             # S&P 500 Index
    "BAMLH0A0HYM2": "BAMLH0A0HYM2",  # ICE BofA US High Yield Spread
}


class FREDAdapter(DataAdapter):
    """Acquire macroeconomic data from FRED.

    Requires fredapi for live data (pip install fredapi).
    FRED API key is free from https://fred.stlouisfed.org/docs/api/api_key.html
    """

    @property
    def source_name(self) -> str:
        return "fred"

    @property
    def version(self) -> str:
        return "1.0.0"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("FRED_API_KEY", "")

    def health_check(self) -> Tuple[bool, str]:
        """Check if FRED is accessible."""
        try:
            import fredapi
            return True, "fredapi available"
        except ImportError:
            return False, "fredapi not installed (pip install fredapi). Free API key at fred.stlouisfed.org"

    def acquire(self, spec: DataSourceSpec) -> RawData:
        """Acquire macro data for specified series codes.

        Args:
            spec: DataSourceSpec with fields listing FRED series codes.

        Returns:
            RawData with macro time series.
        """
        series_codes = spec.fields if spec.fields else list(COMMON_SERIES.keys())

        try:
            import fredapi
            if not self._api_key:
                raise ValueError("FRED_API_KEY not set")
            fred = fredapi.Fred(api_key=self._api_key)
            macro_data = {}
            for code in series_codes:
                actual_code = COMMON_SERIES.get(code, code)
                try:
                    series = fred.get_series(actual_code, observation_start=spec.start_date, observation_end=spec.end_date)
                    macro_data[code] = series
                except Exception as e:
                    logger.warning(f"Failed to get FRED series {code}: {e}")

            if macro_data:
                df = pd.DataFrame(macro_data)
                df.index.name = "date"
                df = df.reset_index()

                return RawData(
                    records=df,
                    source_type=spec.source_type,
                    provider="fred",
                    metadata={
                        "n_series": len(macro_data),
                        "date_range": f"{spec.start_date} to {spec.end_date}",
                    },
                )
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"FRED live data failed: {e}")

        # Fallback: generate synthetic macro data
        return self._synthetic_macro(spec, series_codes)

    def _synthetic_macro(self, spec: DataSourceSpec, series_codes: List[str]) -> RawData:
        """Generate synthetic macro data for testing."""
        np.random.seed(137)
        dates = pd.date_range(spec.start_date, spec.end_date, freq="ME")
        data = {}
        for code in series_codes:
            if code in ("FEDFUNDS",):
                data[code] = np.cumsum(np.random.randn(len(dates)) * 0.1) + 2.5
            elif code in ("DGS10", "T10YIE"):
                data[code] = np.cumsum(np.random.randn(len(dates)) * 0.05) + 3.0
            elif code in ("VIXCLS",):
                data[code] = 15 + 5 * np.random.randn(len(dates)) + 5 * np.sin(np.linspace(0, 10, len(dates)))
            else:
                data[code] = np.cumsum(np.random.randn(len(dates)) * 0.5) + 100

        df = pd.DataFrame(data, index=dates)
        df.index.name = "date"
        df = df.reset_index()

        return RawData(
            records=df,
            source_type=spec.source_type,
            provider="fred",
            metadata={"synthetic": True, "n_series": len(series_codes)},
        )

    def validate(self, raw_data: RawData) -> Tuple[bool, List[str]]:
        """Validate FRED data."""
        return raw_data.validate()
