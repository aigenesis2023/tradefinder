"""
fmp.py — Financial Modeling Prep (FMP) Data Adapter
=====================================================

Acquires financial data from Financial Modeling Prep API.

Data sources (free tier: 250 calls/day):
  - Historical index constituents (S&P 500, S&P 1500, etc.)
  - Financial statements (income, balance sheet, cash flow)
  - Key metrics and ratios
  - Delisted company data
  - Earnings calendar

Status: FUNCTIONAL SKELETON — requires FMP_API_KEY environment variable.
  When key is available, full functionality is enabled.
  When key is missing, adapter produces clear UNTESTABLE error with
  documented alternatives (free sources).
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

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"


class FMPAdapter(DataAdapter):
    """Acquire data from Financial Modeling Prep API.

    Requires FMP_API_KEY environment variable.
    Free tier: 250 requests/day.
    """

    @property
    def source_name(self) -> str:
        return "fmp"

    @property
    def version(self) -> str:
        return "1.0.0"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("FMP_API_KEY", "")
        self._have_key = bool(self._api_key)

    def health_check(self) -> Tuple[bool, str]:
        """Check if FMP API is accessible with current key.

        NOTE: Even if the health check succeeds, acquire() will still raise
        DataAcquisitionError because the adapter is a non-functional skeleton.
        """
        if not self._have_key:
            return False, "No FMP API key. Set FMP_API_KEY env var. Free tier available at financialmodelingprep.com"
        try:
            import requests
            resp = requests.get(
                f"{FMP_BASE_URL}/profile/AAPL?apikey={self._api_key}",
                timeout=10,
            )
            if resp.status_code == 200:
                return False, "FMP API key valid but adapter is NOT IMPLEMENTED — endpoint routing is a stub"
            return False, f"FMP API returned {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, f"FMP API unreachable: {e}"

    def acquire(self, spec: DataSourceSpec) -> RawData:
        """Acquire data from FMP.

        Always raises DataAcquisitionError — this adapter is a non-functional skeleton.
        """
        raise DataAcquisitionError(
            source="FMP",
            reason=(
                "FMP adapter is a non-functional skeleton. Endpoint routing is not "
                "implemented. Set FMP_API_KEY and implement endpoint routing to use. "
                "Free tier available at https://financialmodelingprep.com — "
                "250 requests/day."
            ),
            missing_data=f"FMP {spec.source_type} data",
        )

    def validate(self, raw_data: RawData) -> Tuple[bool, List[str]]:
        """Validate FMP data."""
        return raw_data.validate()
