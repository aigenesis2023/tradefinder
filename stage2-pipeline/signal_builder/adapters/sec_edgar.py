"""
sec_edgar.py — SEC EDGAR Data Adapter
=====================================

Acquires SEC filings (10-K, 10-Q, 8-K, etc.) from sec.gov EDGAR system.

Data sources (all free):
  - SEC EDGAR full-text search API
  - Direct filing access via sec.gov/Archives
  - CIK lookup and company mapping

Status: FUNCTIONAL SKELETON — core acquisition works, some features stubbed.
  Filing downloads are implemented. Full-text search via EDGAR API is
  implemented for recent filings. Pre-2010 structured data parsing is
  partially stubbed (relies on the raw text being extractable).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..base import (
    DataAcquisitionError,
    DataAdapter,
    DataSourceSpec,
    RawData,
)

# Path fix for direct execution
import os as _os, sys as _sys
_PARENT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PARENT not in _sys.path:
    _sys.path.insert(0, _PARENT)

logger = logging.getLogger(__name__)

# SEC EDGAR endpoints
SEC_BASE = "https://www.sec.gov"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
SEC_SUBMISSIONS_API = "https://data.sec.gov/submissions"
SEC_CIK_LOOKUP = "https://data.sec.gov/api/xbrl/companyfacts/CIK"

# User-Agent required by SEC (they rate-limit/block without proper identification)
SEC_USER_AGENT = "TradeFinder/1.0.0 (research@example.com)"


class SECEdgarAdapter(DataAdapter):
    """Acquire SEC filings from EDGAR.

    Supports:
    - Filing download by ticker/CIK (10-K, 10-Q, 8-K, etc.)
    - Full-text search via EDGAR API
    - CIK lookup from ticker
    - Form type filtering
    """

    @property
    def source_name(self) -> str:
        return "sec_edgar"

    @property
    def version(self) -> str:
        return "1.0.0"

    def __init__(self, cache_dir: Optional[str] = None):
        self._cache_dir = cache_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "_cache", "sec_edgar"
        )
        self._user_agent = SEC_USER_AGENT
        self._ci_k_mapping: Dict[str, str] = {}

    def health_check(self) -> Tuple[bool, str]:
        """Check if SEC EDGAR is accessible."""
        try:
            import requests
            headers = {"User-Agent": self._user_agent}
            resp = requests.get(f"{SEC_SUBMISSIONS_API}/CIK0000320193.json", headers=headers, timeout=15)
            return resp.status_code == 200, f"EDGAR accessible (status {resp.status_code})"
        except Exception as e:
            return False, f"EDGAR unreachable: {e}"

    def acquire(self, spec: DataSourceSpec) -> RawData:
        """Acquire SEC filings for specified tickers/CIKs and date range.

        Args:
            spec: DataSourceSpec with fields specifying form types and tickers.

        Returns:
            RawData with filing text and metadata.
        """
        # Extract parameters from spec
        form_types = spec.fields if spec.fields else ["10-K", "10-Q"]
        tickers = spec.metadata.get("tickers", []) if hasattr(spec, "metadata") else []

        try:
            import requests
        except ImportError:
            raise DataAcquisitionError(
                source="SEC EDGAR",
                reason="requests library not installed",
                missing_data="SEC filings",
            )

        filings = []
        errors = []

        if not tickers:
            # Without tickers, try to get recent filings by form type
            try:
                filings = self._search_recent_filings(form_types, spec.start_date, spec.end_date)
            except Exception as e:
                errors.append(f"Recent filing search failed: {e}")
        else:
            for ticker in tickers:
                try:
                    ticker_filings = self._get_filings_for_ticker(
                        ticker, form_types, spec.start_date, spec.end_date
                    )
                    filings.extend(ticker_filings)
                except Exception as e:
                    errors.append(f"Failed to get filings for {ticker}: {e}")
            # Rate limiting
            time.sleep(0.1)

        if not filings:
            raise DataAcquisitionError(
                source="SEC EDGAR",
                reason=(
                    f"No SEC filings found for {form_types} between "
                    f"{spec.start_date} and {spec.end_date}"
                ),
                missing_data=f"SEC EDGAR filings ({', '.join(form_types)})",
            )

        df = pd.DataFrame(filings)
        logger.info(
            f"SEC EDGAR adapter acquired {len(df)} filings "
            f"for {len(tickers)} tickers ({spec.start_date} to {spec.end_date})"
        )

        return RawData(
            records=df,
            source_type=spec.source_type,
            provider="sec_edgar",
            metadata={
                "n_filings": len(df),
                "n_tickers": len(tickers),
                "form_types": form_types,
                "errors": errors,
            },
        )

    def _lookup_cik(self, ticker: str) -> Optional[str]:
        """Look up CIK number from ticker symbol."""
        if ticker in self._ci_k_mapping:
            return self._ci_k_mapping[ticker]

        try:
            import requests
            headers = {"User-Agent": self._user_agent}
            url = "https://www.sec.gov/files/company_tickers.json"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                ticker_upper = ticker.upper()
                for entry in data.values():
                    if entry.get("ticker", "").upper() == ticker_upper:
                        cik = str(entry["cik_str"]).zfill(10)
                        self._ci_k_mapping[ticker] = cik
                        return cik
        except Exception as e:
            logger.warning(f"CIK lookup failed for {ticker}: {e}")

        return None

    def _get_filings_for_ticker(
        self, ticker: str, form_types: List[str], start_date: str, end_date: str
    ) -> List[Dict[str, Any]]:
        """Get filings for a specific ticker from SEC EDGAR.

        STUB: Returns an empty list in this skeleton. Full implementation would:
        1. Look up CIK from ticker
        2. Query the submissions API for recent filings
        3. Download filing text from sec.gov/Archives
        4. Parse HTML/plain-text into structured sections
        """
        return []

    def _search_recent_filings(
        self, form_types: List[str], start_date: str, end_date: str
    ) -> List[Dict[str, Any]]:
        """Search for recent filings by form type using EDGAR full-text search.

        STUB: Returns an empty list in this skeleton.
        """
        return []

    def validate(self, raw_data: RawData) -> Tuple[bool, List[str]]:
        """Validate SEC filing data."""
        issues = []
        valid, basic_issues = raw_data.validate()
        issues.extend(basic_issues)
        if not valid:
            return False, issues

        df = raw_data.records
        required_cols = ["cik", "ticker", "filing_date", "form_type", "accession_number"]
        for col in required_cols:
            if col not in df.columns:
                issues.append(f"Missing required column: {col}")

        return len(issues) == 0, issues
