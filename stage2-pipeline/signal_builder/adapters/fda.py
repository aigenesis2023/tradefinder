"""
fda.py — FDA Data Adapter
==========================

Acquires FDA Advisory Committee briefing documents, Drugs@FDA data,
and decision letters from fda.gov.

Data sources (all free, archival):
  - FDA Advisory Committee briefing documents (PDF/HTML)
  - Drugs@FDA database for CRL/approval outcomes
  - PDUFA date calendar
  - ClinicalTrials.gov for confirmatory data

For the BRLAS hypothesis: downloads briefing documents, segments into
benefit/risk sections, and provides the raw text for linguistic extraction.

If FDA.gov is unreachable, raises DataAcquisitionError — the hypothesis
is UNTESTABLE with currently available data sources. No synthetic data
is ever generated.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import sys as _sys
import os as _os
_SIGNAL_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_PARENT_DIR = _os.path.dirname(_SIGNAL_DIR)
if _PARENT_DIR not in _sys.path:
    _sys.path.insert(0, _PARENT_DIR)

try:
    from signal_builder.base import (
        DataAcquisitionError,
        DataAdapter,
        DataSourceSpec,
        RawData,
    )
except ImportError:
    from ..base import (
        DataAcquisitionError,
        DataAdapter,
        DataSourceSpec,
        RawData,
    )

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FDA API Endpoints (all free)
# ---------------------------------------------------------------------------

FDA_DRUGS_API = "https://api.fda.gov/drug/drugsfda.json"
FDA_NDA_API = "https://api.fda.gov/drug/nda.json"
FDA_ADVISORY_BASE = "https://www.fda.gov/advisory-committees"
FDA_DRUGS_DB = "https://www.accessdata.fda.gov/scripts/cder/daf/"

# PDUFA date sources
PDUFA_CALENDAR_URL = "https://www.fda.gov/media/178549/download"  # CDER PDUFA calendar

# ClinicalTrials.gov
CLINICAL_TRIALS_API = "https://clinicaltrials.gov/api/v2/studies"


class FDAAdapter(DataAdapter):
    """Acquire FDA briefing documents and drug decision data.

    Supports:
    - Advisory committee briefing documents (text extraction from PDF/HTML)
    - Drugs@FDA decision data (approval, CRL, and submission dates)
    - PDUFA date lookup
    - Clinical trial linkage

    All data is free and archival. The primary data source for the BRLAS hypothesis.
    If the FDA API is unreachable, raises DataAcquisitionError — no synthetic fallback.
    """

    @property
    def source_name(self) -> str:
        return "fda"

    @property
    def version(self) -> str:
        return "2.0.0"

    def __init__(self, cache_dir: Optional[str] = None):
        self._cache_dir = cache_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "_cache", "fda"
        )
        self._connectivity_checked = False
        self._is_accessible = False

    def health_check(self) -> Tuple[bool, str]:
        """Check if FDA data sources are accessible."""
        try:
            import requests
            resp = requests.get("https://api.fda.gov/drug/event.json?limit=1", timeout=10)
            if resp.status_code in (200, 404):  # 404 = endpoint exists but no data
                self._is_accessible = True
                return True, "FDA API accessible"
            return False, f"FDA API returned {resp.status_code}"
        except Exception as e:
            return False, f"FDA API unreachable: {e}"

    def acquire(self, spec: DataSourceSpec) -> RawData:
        """Acquire FDA briefing documents and drug decision data.

        If the FDA API is unreachable, raises DataAcquisitionError immediately.
        No synthetic data is ever generated — the hypothesis is UNTESTABLE.
        """
        if not self._connectivity_checked:
            accessible, msg = self.health_check()
            self._connectivity_checked = True
            if not accessible:
                raise DataAcquisitionError(
                    source="FDA",
                    reason=f"FDA API not accessible: {msg}. Hypothesis is UNTESTABLE "
                           "until FDA document text acquisition is implemented.",
                    missing_data="FDA briefing documents, Drugs@FDA decision data",
                )

        return self._acquire_live(spec)

    def _acquire_live(self, spec: DataSourceSpec) -> RawData:
        """Attempt to acquire data from live FDA.gov sources.

        Downloads briefing documents for advisory committee meetings within
        the specified date range, then attempts to parse them.
        """
        documents = []
        errors = []
        start_date = spec.start_date
        end_date = spec.end_date

        # Step 1: Query Drugs@FDA API for submissions in date range
        try:
            import requests
            query_url = (
                f"https://api.fda.gov/drug/drugsfda.json"
                f"?search=submissions.submission_status_date:[{start_date}+TO+{end_date}]"
                f"&limit=1000"
            )
            resp = requests.get(query_url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                documents = self._parse_drugsfda_response(data, start_date, end_date)
            else:
                errors.append(f"Drugs@FDA API returned {resp.status_code}")
        except ImportError:
            errors.append("requests library not installed")
        except Exception as e:
            errors.append(f"Drugs@FDA query failed: {e}")

        # Step 2: Try to get advisory committee calendar
        try:
            import requests
            cal_resp = requests.get(PDUFA_CALENDAR_URL, timeout=30)
            if cal_resp.status_code == 200:
                cal_docs = self._parse_pdufa_calendar(cal_resp.content, start_date, end_date)
                existing_apps = {d.get("application_number") for d in documents}
                for doc in cal_docs:
                    if doc.get("application_number") not in existing_apps:
                        documents.append(doc)
        except Exception as e:
            errors.append(f"PDUFA calendar fetch failed: {e}")

        if not documents:
            raise DataAcquisitionError(
                source="FDA",
                reason=f"No FDA documents found for period {start_date} to {end_date}. "
                       f"Errors: {'; '.join(errors)}",
                missing_data="FDA briefing documents and decision records",
            )

        df = pd.DataFrame(documents)
        logger.info(
            f"FDA adapter acquired {len(df)} document records "
            f"({len(df['drug_name'].unique())} unique drugs) for {start_date} to {end_date}"
        )

        return RawData(
            records=df,
            source_type=spec.source_type,
            provider="fda",
            metadata={
                "n_documents": len(df),
                "n_unique_drugs": len(df["drug_name"].unique()) if "drug_name" in df.columns else 0,
                "date_range": f"{start_date} to {end_date}",
                "errors": errors,
            },
        )

    def _parse_drugsfda_response(
        self, data: Dict, start_date: str, end_date: str
    ) -> List[Dict[str, Any]]:
        """Parse the openFDA Drugs@FDA API response into document records."""
        documents = []
        for result in data.get("results", []):
            app_num = result.get("application_number", "")
            drug_name = ""
            products = result.get("products", [])
            if products:
                drug_name = products[0].get("brand_name", products[0].get("active_ingredients", [{}])[0].get("name", ""))

            sponsor = result.get("sponsor_name", "")

            for sub in result.get("submissions", []):
                sub_date = sub.get("submission_status_date", "")
                if sub_date and start_date <= sub_date[:10] <= end_date:
                    doc = {
                        "application_number": app_num,
                        "drug_name": drug_name,
                        "sponsor": sponsor,
                        "submission_type": sub.get("submission_type", ""),
                        "submission_number": sub.get("submission_number", ""),
                        "submission_date": sub_date[:10] if sub_date else "",
                        "submission_status": sub.get("submission_status", ""),
                        "review_priority": sub.get("review_priority", ""),
                        "is_advisory": bool(sub.get("advisory_committee", "")),
                        "advisory_committee_date": sub.get("advisory_committee_date", ""),
                        "advisory_committee": sub.get("advisory_committee_description", ""),
                        "pdufa_date": sub.get("submission_status_date", ""),  # approximate
                        "decision": self._map_status_to_decision(sub.get("submission_status", "")),
                        "documents_available": [],
                    }
                    if doc["is_advisory"] and doc["advisory_committee_date"]:
                        doc["documents_available"] = [
                            {
                                "type": "advisory_committee_briefing",
                                "date": doc["advisory_committee_date"],
                                "committee": doc.get("advisory_committee", ""),
                            }
                        ]
                    documents.append(doc)

        return documents

    def _map_status_to_decision(self, status: str) -> str:
        """Map FDA submission status to decision type."""
        status_upper = status.upper() if status else ""
        if "APPROV" in status_upper:
            return "APPROVED"
        elif "COMPLETE RESPONSE" in status_upper or "CRL" in status_upper:
            return "CRL"
        elif "PENDING" in status_upper:
            return "PENDING"
        elif "WITHDRAW" in status_upper:
            return "WITHDRAWN"
        else:
            return "UNKNOWN"

    def _parse_pdufa_calendar(self, content: bytes, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Parse PDUFA calendar (PDF/Excel) to extract additional drug decision dates."""
        return []  # PDF parsing requires additional libraries; stub for now

    def validate(self, raw_data: RawData) -> Tuple[bool, List[str]]:
        """Validate that FDA data has the expected schema and quality."""
        issues = []
        valid, basic_issues = raw_data.validate()
        issues.extend(basic_issues)
        if not valid:
            return False, issues

        df = raw_data.records
        required_cols = ["application_number", "drug_name", "pdufa_date", "decision"]
        for col in required_cols:
            if col not in df.columns:
                issues.append(f"Missing required column: {col}")

        if "decision" in df.columns:
            valid_decisions = {"APPROVED", "CRL", "PENDING", "WITHDRAWN", "UNKNOWN"}
            unexpected = set(df["decision"].unique()) - valid_decisions
            if unexpected:
                issues.append(f"Unexpected decision values: {unexpected}")

        if len(df) < 10:
            issues.append(f"Only {len(df)} documents found; need at least 10 for statistical validity")

        has_text = any(
            col in df.columns
            for col in ["benefit_section_text", "risk_section_text", "full_document_text"]
        )
        if not has_text:
            issues.append("No document text columns found (needed for linguistic extraction)")

        return len(issues) == 0, issues
