"""
fda.py — FDA Data Adapter
==========================

Acquires FDA review documents (Medical Reviews, Summary Reviews) and drug
decision data from FDA.gov sources for the BRLAS (Benefit-Risk Linguistic
Asymmetry Score) hypothesis.

Data sources (all free, archival):
  - openFDA Drugs@FDA API (api.fda.gov): application metadata, outcomes
  - accessdata.fda.gov: Drug Approval Package PDFs (Medical Reviews, Summary Reviews)
  - accessdata.fda.gov: Drugs@FDA web portal

Limitations (honestly reported):
  - www.fda.gov advisory committee briefing documents are WAF-blocked (Akamai)
  - CRL (Complete Response Letter) applications do not have public approval
    packages — Medical Reviews are only available for approved drugs
  - Sponsor-to-ticker mapping is best-effort (manual mapping + fuzzy match)
  - The full CRL-vs-Approval backtest is limited by CRL document availability;
    within-approved-drug analysis is fully supported

If FDA.gov sources are unreachable, raises DataAcquisitionError — the
hypothesis is UNTESTABLE with currently available data sources.
No synthetic data is ever generated.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import sys as _sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_SIGNAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT_DIR = os.path.dirname(_SIGNAL_DIR)
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
FDA_ADVISORY_BASE = "https://www.fda.gov/advisory-committees"
FDA_DRUGS_DB = "https://www.accessdata.fda.gov/scripts/cder/daf/"
FDA_APPROVAL_DOCS = "https://www.accessdata.fda.gov/drugsatfda_docs/nda"

# ---------------------------------------------------------------------------
# Sponsor-to-Ticker Mapping
# ---------------------------------------------------------------------------
# Maps FDA sponsor names (from openFDA) to stock tickers for price data.
# Covers major pharma/biotech sponsors whose drugs appear in FDA reviews.
# Fallback: fuzzy substring match against company_tickers_cache.json.

SPONSOR_TICKER_MAP: Dict[str, str] = {
    # Large Pharma
    "PFIZER": "PFE", "PFIZER INC": "PFE", "PFIZER LABS": "PFE",
    "MERCK": "MRK", "MERCK SHARP DOHME": "MRK", "MERCK AND CO INC": "MRK",
    "JOHNSON AND JOHNSON": "JNJ", "JOHNSON & JOHNSON": "JNJ",
    "ABBVIE": "ABBV", "ABBVIE INC": "ABBV",
    "BRISTOL MYERS SQUIBB": "BMY", "BRISTOL-MYERS SQUIBB": "BMY",
    "ELI LILLY": "LLY", "LILLY": "LLY", "ELI LILLY AND CO": "LLY",
    "NOVARTIS": "NVS", "NOVARTIS PHARMS": "NVS", "NOVARTIS PHARMACEUTICALS": "NVS",
    "ROCHE": "RHHBY", "HOFFMANN LA ROCHE": "RHHBY", "GENENTECH": "RHHBY",
    "ASTRAZENECA": "AZN", "ASTRAZENECA PHARMS": "AZN",
    "GLAXOSMITHKLINE": "GSK", "GSK": "GSK",
    "SANOFI": "SNY", "SANOFI AVENTIS": "SNY",
    "AMGEN": "AMGN", "AMGEN INC": "AMGN",
    "GILEAD": "GILD", "GILEAD SCIENCES": "GILD",
    "BIOGEN": "BIIB", "BIOGEN INC": "BIIB",
    "REGENERON": "REGN", "REGENERON PHARMS": "REGN",
    "VERTEX": "VRTX",
    "MODERNA": "MRNA", "MODERNA INC": "MRNA",
    "CELLTRION": "068270.KS",  # Korean listing
    # Biotech (mid-cap)
    "SEAGEN": "SGEN", "SEATTLE GENETICS": "SGEN",
    "INCYTE": "INCY",
    "ALNYLAM": "ALNY",
    "IONIS": "IONS",
    "SAREPTA": "SRPT",
    "ULTRAGENYX": "RARE",
    "ALEXION": "ALXN",
    "JAZZ": "JAZZ",
    "HORIZON": "HZNP",
    "KARYOPHARM": "KPTI",
    "BLUEBIRD BIO": "BLUE",
    "SANGAMO": "SGMO",
    # Generic / Specialty
    "TEVA": "TEVA", "TEVA PHARMS": "TEVA",
    "MYLAN": "VTRS", "VIATRIS": "VTRS",
    "SANDOZ": "SDZNY",
    "HIKMA": "HIK.L", "HIKMA PHARM": "HIK.L",
    "ENDO": "ENDP",
    "MALLINCKRODT": "MNK",
    "BAUSCH": "BHC",
    # Mid-cap biotech (from our sample)
    "AXSOME": "AXSM", "AXSOME MALTA": "AXSM",
    "APELLIS": "APLS", "APELLIS PHARMS": "APLS",
    "TARSUS": "TARS",
    "PHARMACOSMOS": "PHCS",
    "COSETTE": "CSTX",
    "ZYLA": "ZYLA",
    "MERZ": "MRZ.F",
    "LUPIN": "LUPIN.NS",
    "CMP DEV": "CMPD",
    "FRESENIUS KABI": "FRE.DE", "FRESENIUS KABI USA": "FRE.DE",
    "EISAI": "ESALY", "EISAI INC": "ESALY",
    "TAKEDA": "TAK", "TAKEDA PHARMS": "TAK", "TAKEDA PHARMS USA": "TAK",
    "BOEHRINGER INGELHEIM": "BAYRY",  # Private but has ADR
    "JANSSEN": "JNJ", "JANSSEN PHARMS": "JNJ", "JANSSEN BIOTECH": "JNJ",
    "WYETH": "PFE", "WYETH PHARMS": "PFE",  # Acquired by Pfizer
    "MSD SUB MERCK": "MRK",
    "ONYX PHARMS AMGEN": "AMGN",
    "BIOGEN IDEC": "BIIB",
    "AVYXA HOLDINGS": "",
    "AVID RADIOPHARMS": "LLY",  # Acquired by Lilly
    "SUN PHARMA CANADA": "SUNPHARMA.NS",
    "ECI PHARMS": "ECIP",
    # Medical Device / Other (some drugs approved for device companies)
    "ABBOTT": "ABT", "ABBOTT LABORATORIES": "ABT",
    "BAXTER": "BAX", "BAXTER HLTHCARE": "BAX", "BAXTER HLTHCARE CORP": "BAX",
    "B BRAUN": "BBS.F", "B BRAUN MEDICAL": "BBS.F",
    "BECTON DICKINSON": "BDX",
    "BOSTON SCIENTIFIC": "BSX",
    "MEDTRONIC": "MDT",
    "STRYKER": "SYK",
}

# Sponsor name normalisation patterns
_SPONSOR_CLEANUP = [
    (re.compile(r'\b(INC|LTD|LLC|CORP|CO|L\.P\.|PLC|AG|SA|S\.A\.|S\.P\.A\.|GMBH|PTY|LTD\.)\b\.?', re.I), ''),
    (re.compile(r'\b(PHARMACEUTICALS|PHARMA|PHARMS|LABS|LABORATORIES|INTERNATIONAL|HOLDINGS|THERAPEUTICS|BIOSCIENCES|BIOTECH)\b', re.I), ''),
    (re.compile(r'\b(THE|A/S|GROUP|COMPANY)\b', re.I), ''),
    (re.compile(r'[,.]'), ''),
    (re.compile(r'\s+'), ' '),
]


# ---------------------------------------------------------------------------
# FDA Medical Review Section Headers (for benefit/risk segmentation)
# ---------------------------------------------------------------------------

BENEFIT_SECTION_KEYWORDS = [
    "risk benefit assessment",
    "recommendation",
    "efficacy",
    "review of efficacy",
    "clinical efficacy",
    "efficacy evaluation",
    "efficacy results",
    "benefit",
    "benefit assessment",
    "benefit-risk",
    "benefit risk",
    "clinical benefit",
]

RISK_SECTION_KEYWORDS = [
    "review of safety",
    "safety review",
    "safety evaluation",
    "safety results",
    "safety assessment",
    "adverse events",
    "serious adverse",
    "safety summary",
    "risk assessment",
    "risk evaluation",
    "toxicity",
    "safety data",
    "deaths",
    "major safety",
]


def _normalise_sponsor(name: str) -> str:
    """Normalise a sponsor name for matching."""
    n = name.upper().strip()
    for pattern, replacement in _SPONSOR_CLEANUP:
        n = pattern.sub(replacement, n)
    return n.strip()


def _lookup_ticker(sponsor_name: str, ticker_cache: Optional[Dict] = None) -> Optional[str]:
    """Map a sponsor name to a stock ticker.

    Checks: (1) hard-coded SPONSOR_TICKER_MAP, (2) normalised match,
    (3) fuzzy substring match in ticker cache.
    """
    if not sponsor_name:
        return None

    # Exact match
    upper = sponsor_name.upper().strip()
    if upper in SPONSOR_TICKER_MAP:
        return SPONSOR_TICKER_MAP[upper]

    # Normalised match
    norm = _normalise_sponsor(upper)
    for key, ticker in SPONSOR_TICKER_MAP.items():
        if _normalise_sponsor(key) == norm:
            return ticker

    # Substring match (e.g. "ONYX PHARMS AMGEN" contains "AMGEN")
    for key, ticker in SPONSOR_TICKER_MAP.items():
        key_norm = _normalise_sponsor(key)
        if key_norm and (key_norm in norm or norm in key_norm):
            return ticker

    # Fuzzy match in ticker cache
    if ticker_cache:
        for ticker, data in ticker_cache.items():
            if isinstance(data, dict):
                title = data.get('title', '').upper()
            else:
                title = str(data).upper()
            if norm and (norm[:10] in title or title[:10] in norm):
                return ticker

    return None


class FDAAdapter(DataAdapter):
    """Acquire FDA review documents and drug decision data.

    Supports:
    - Medical Review PDF download from accessdata.fda.gov
    - Summary Review PDF download
    - Text extraction with benefit/risk section segmentation
    - Sponsor-to-ticker mapping for price data integration
    - Outcome labeling (APPROVED, CRL, etc.) from openFDA

    All data is free and archival. Raises DataAcquisitionError if
    FDA sources are unreachable — no synthetic fallback.
    """

    @property
    def source_name(self) -> str:
        return "fda"

    @property
    def version(self) -> str:
        return "3.0.0"

    def __init__(self, cache_dir: Optional[str] = None):
        self._cache_dir = cache_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "_cache", "fda"
        )
        self._connectivity_checked = False
        self._is_accessible = False
        self._ticker_cache: Optional[Dict] = None
        os.makedirs(self._cache_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Health Check
    # ------------------------------------------------------------------

    def health_check(self) -> Tuple[bool, str]:
        """Check if FDA data sources are accessible."""
        reasons = []
        accessible = True

        ua = _get_ua()

        # Check openFDA API
        try:
            import requests
            resp = requests.get(
                "https://api.fda.gov/drug/event.json?limit=1",
                headers={"User-Agent": ua},
                timeout=10,
            )
            if resp.status_code not in (200, 404):
                accessible = False
                reasons.append(f"openFDA API returned {resp.status_code}")
        except Exception as e:
            accessible = False
            reasons.append(f"openFDA API unreachable: {e}")

        # Check accessdata.fda.gov (for PDF downloads)
        try:
            import requests
            resp = requests.get(
                "https://www.accessdata.fda.gov/scripts/cder/daf/",
                headers={"User-Agent": ua},
                timeout=20,
            )
            if resp.status_code != 200:
                accessible = False
                reasons.append(f"accessdata.fda.gov returned {resp.status_code}")
        except Exception as e:
            accessible = False
            reasons.append(f"accessdata.fda.gov unreachable: {e}")

        # Note www.fda.gov status
        reasons.append("www.fda.gov advisory committee pages are WAF-blocked "
                       "(Akamai abuse-detection); review documents acquired "
                       "from accessdata.fda.gov instead")

        if accessible:
            self._is_accessible = True
            return True, "FDA data sources accessible: " + "; ".join(reasons)
        return False, "; ".join(reasons)

    # ------------------------------------------------------------------
    # Main Acquisition
    # ------------------------------------------------------------------

    def acquire(self, spec: DataSourceSpec) -> RawData:
        """Acquire FDA review documents and drug decision data.

        Downloads Medical Review PDFs for NDA/BLA applications within
        the specified date range, extracts text, segments into benefit/risk
        sections, and maps sponsors to stock tickers.

        Raises DataAcquisitionError if FDA sources are unreachable.
        No synthetic data is ever generated.
        """
        if not self._connectivity_checked:
            accessible, msg = self.health_check()
            self._connectivity_checked = True
            if not accessible:
                raise DataAcquisitionError(
                    source="FDA",
                    reason=f"FDA data sources not accessible: {msg}. "
                           "Hypothesis is UNTESTABLE until FDA document "
                           "acquisition is implemented.",
                    missing_data="FDA review documents, drug decision data",
                )

        # Load ticker cache for sponsor mapping
        self._load_ticker_cache()

        return self._acquire_live(spec)

    def _load_ticker_cache(self) -> None:
        """Load company ticker cache for sponsor-to-ticker mapping."""
        if self._ticker_cache is not None:
            return
        cache_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "_cache", "company_tickers_cache.json",
        )
        try:
            with open(cache_path) as f:
                self._ticker_cache = json.load(f)
            logger.info(f"Loaded ticker cache: {len(self._ticker_cache)} entries")
        except Exception:
            logger.debug("No ticker cache available; sponsor mapping will be "
                         "hard-coded only")
            self._ticker_cache = {}

    # ------------------------------------------------------------------
    # Live Acquisition
    # ------------------------------------------------------------------

    def _acquire_live(self, spec: DataSourceSpec) -> RawData:
        """Acquire FDA data using the live pipeline.

        1. Query openFDA for NDA/BLA applications in date range
        2. For each with review documents, download Medical Review PDF
        3. Extract text and segment into benefit/risk sections
        4. Map sponsor to ticker
        5. Return RawData with text columns populated
        """
        start_date = spec.start_date
        end_date = spec.end_date

        # Step 1: Discover applications via openFDA
        applications = self._discover_applications(start_date, end_date)

        if not applications:
            raise DataAcquisitionError(
                source="FDA",
                reason=f"No FDA applications with review documents found "
                       f"for {start_date} to {end_date}. The openFDA API "
                       f"may be returning only ANDA (generic) results, or "
                       f"no review documents exist for this date range. "
                       f"Try a wider date range.",
                missing_data="FDA NDA/BLA applications with review documents",
            )

        # Step 2: Download and process each application's documents
        documents = []
        errors = []
        n_crls = 0
        n_no_ticker = 0

        for app in applications:
            try:
                doc = self._process_application(app, start_date, end_date)
                if doc:
                    documents.append(doc)
                    if doc.get("decision") == "CRL":
                        n_crls += 1
                    if not doc.get("ticker"):
                        n_no_ticker += 1
            except Exception as e:
                errors.append(f"{app.get('application_number', '?')}: {e}")
                logger.debug(f"Failed to process {app.get('application_number')}: {e}")

        if not documents:
            raise DataAcquisitionError(
                source="FDA",
                reason=f"Failed to download or process any FDA review documents. "
                       f"Errors: {'; '.join(errors[:5])}",
                missing_data="FDA Medical Review PDFs (accessdata.fda.gov)",
            )

        df = pd.DataFrame(documents)

        # Deduplicate by application_number (keep first occurrence)
        if "application_number" in df.columns and not df.empty:
            n_before = len(df)
            df = df.drop_duplicates(subset=["application_number"], keep="first")
            n_removed = n_before - len(df)
            if n_removed > 0:
                logger.info(f"  Removed {n_removed} duplicate application entries")

        # Count tickers that are non-empty (empty string means no mapping)
        n_with_ticker = int((df["ticker"].fillna("").str.strip() != "").sum()) if "ticker" in df.columns else 0
        n_no_ticker = len(df) - n_with_ticker

        # Log honest assessment
        logger.info(
            f"FDA adapter acquired {len(df)} document records "
            f"({df['drug_name'].nunique()} unique drugs) for {start_date} to {end_date}"
        )
        logger.info(
            f"  APPROVED: {len(df[df['decision'] == 'APPROVED'])}, "
            f"CRL: {len(df[df['decision'] == 'CRL'])}, "
            f"TENTATIVE: {len(df[df['decision'] == 'TENTATIVE_APPROVAL'])}, "
            f"OTHER: {len(df[~df['decision'].isin(['APPROVED', 'CRL', 'TENTATIVE_APPROVAL'])])}"
        )
        logger.info(
            f"  With benefit text: {int(df['benefit_section_text'].fillna('').str.strip().astype(bool).sum())}, "
            f"With risk text: {int(df['risk_section_text'].fillna('').str.strip().astype(bool).sum())}"
        )
        logger.info(
            f"  With ticker: {n_with_ticker}/{len(df)}, "
            f"Without ticker (no price data): {n_no_ticker}"
        )
        if n_crls == 0:
            logger.warning(
                "  NO CRL APPLICATIONS WITH REVIEW DOCUMENTS: The backtest "
                "will be limited to within-approved-drug analysis. CRL "
                "documents are not publicly available on accessdata.fda.gov. "
                "See limitation in adapter docstring."
            )

        return RawData(
            records=df,
            source_type=spec.source_type,
            provider="fda",
            metadata={
                "n_documents": len(df),
                "n_unique_drugs": len(df["drug_name"].unique()) if "drug_name" in df.columns else 0,
                "n_approved": int((df["decision"] == "APPROVED").sum()) if "decision" in df.columns else 0,
                "n_crl": int((df["decision"] == "CRL").sum()) if "decision" in df.columns else 0,
                "n_with_ticker": int(df["ticker"].notna().sum()) if "ticker" in df.columns else 0,
                "date_range": f"{start_date} to {end_date}",
                "errors": errors[:10],
                "limitation": (
                    "CRL applications have no public Medical Reviews on "
                    "accessdata.fda.gov. Advisory committee briefing documents "
                    "on www.fda.gov are WAF-blocked. This sample is biased "
                    "toward approved drugs and within-approved analysis."
                ),
            },
        )

    # ------------------------------------------------------------------
    # Application Discovery (openFDA)
    # ------------------------------------------------------------------

    def _discover_applications(
        self, start_date: str, end_date: str
    ) -> List[Dict[str, Any]]:
        """Query openFDA for NDA/BLA applications with review documents.

        Returns list of application dicts with keys:
        application_number, sponsor_name, drug_name, submission_status,
        submission_status_date, review_priority, has_review_docs, review_doc_urls
        """
        import requests

        applications = []

        # Search for original submissions in date range
        # openFDA returns max 100 results per page; paginate if needed
        for skip in [0, 100, 200]:
            url = (
                f"{FDA_DRUGS_API}"
                f"?search=submissions.submission_type:ORIG"
                f"+AND+submissions.submission_status_date:[{start_date}+TO+{end_date}]"
                f"&limit=100&skip={skip}"
            )

            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": _get_ua()},
                    timeout=30,
                )
            except Exception as e:
                logger.warning(f"openFDA query failed (skip={skip}): {e}")
                break

            if resp.status_code != 200:
                logger.warning(f"openFDA returned {resp.status_code} (skip={skip})")
                break

            try:
                data = resp.json()
            except Exception:
                break

            results = data.get("results", [])
            if not results:
                break

            for result in results:
                app_num = result.get("application_number", "")
                # Filter to NDA/BLA only (skip ANDAs — generics don't have
                # advisory committees and rarely have detailed Medical Reviews)
                if not (app_num.startswith("NDA") or app_num.startswith("BLA")):
                    continue

                sponsor = result.get("sponsor_name", "")

                # Extract drug name
                products = result.get("products", [])
                drug_name = ""
                if products:
                    drug_name = products[0].get("brand_name", "")
                    if not drug_name:
                        ingr = products[0].get("active_ingredients", [{}])
                        drug_name = ingr[0].get("name", "") if ingr else ""

                for sub in result.get("submissions", []):
                    if sub.get("submission_type") != "ORIG":
                        continue

                    status = sub.get("submission_status", "")
                    status_date = sub.get("submission_status_date", "")

                    # Check for review documents
                    docs = sub.get("application_docs", [])
                    review_docs = [
                        d for d in docs
                        if d.get("type", "") in ("Review", "Summary Review")
                    ]

                    if not review_docs:
                        continue

                    # Extract year from the review URL or status date
                    year = status_date[:4] if status_date else "2024"
                    for doc in review_docs:
                        url = doc.get("url", "")
                        yr_match = re.search(r'/nda/(\d{4})/', url)
                        if yr_match:
                            year = yr_match.group(1)
                            break

                    app_entry = {
                        "application_number": app_num,
                        "sponsor_name": sponsor,
                        "drug_name": drug_name,
                        "submission_status": status,
                        "submission_status_date": status_date,
                        "review_priority": sub.get("review_priority", ""),
                        "review_docs": review_docs,
                        "approval_year": year,
                    }
                    applications.append(app_entry)

        logger.info(
            f"Discovered {len(applications)} NDA/BLA applications "
            f"with review documents ({start_date} to {end_date})"
        )
        return applications

    # ------------------------------------------------------------------
    # Application Processing
    # ------------------------------------------------------------------

    def _process_application(
        self, app: Dict[str, Any], start_date: str, end_date: str
    ) -> Optional[Dict[str, Any]]:
        """Process a single FDA application: download PDF, extract text,
        segment sections, map ticker.

        Returns a document dict or None if processing fails.
        """
        app_num = app["application_number"]
        sponsor = app["sponsor_name"]
        drug_name = app["drug_name"]

        # Strip NDA/BLA prefix for URL construction
        app_num_clean = re.sub(r'^(NDA|BLA|ANDA)', '', app_num)

        # Get the review doc URLs from the API response
        review_docs = app.get("review_docs", [])
        toc_url = None
        for doc in review_docs:
            url = doc.get("url", "")
            if "TOC" in url or doc.get("type") == "Review":
                toc_url = url
                break

        # Use the TOC URL to determine the base path and year
        if toc_url:
            # URL format: .../nda/YYYY/XXXXXXOrig1s000TOC.html
            url_match = re.search(r'/nda/(\d{4})/(\w+Orig1s\d+)', toc_url)
            if url_match:
                year = url_match.group(1)
                base_name = url_match.group(2).replace('TOC.html', '').replace('TOC', '')
            else:
                year_match = re.search(r'/nda/(\d{4})/', toc_url)
                year = year_match.group(1) if year_match else "2024"
                base_name = f"{app_num_clean}Orig1s000"
        else:
            year = "2024"
            base_name = f"{app_num_clean}Orig1s000"

        base_url = f"https://www.accessdata.fda.gov/drugsatfda_docs/nda/{year}/{base_name}"

        # Step 1: Try to download Medical Review PDF directly
        pdf_content = self._download_pdf(f"{base_url}MedR.pdf", app_num, "medr")

        # Step 2: If not found, try Summary Review PDF
        if pdf_content is None:
            pdf_content = self._download_pdf(f"{base_url}SumR.pdf", app_num, "sumr")

        # Step 3: If TOC page exists, parse it for PDF links
        if pdf_content is None and toc_url:
            pdf_links = self._parse_toc_page_for_pdfs(toc_url, app_num)
            for pdf_url in pdf_links:
                if any(kw in pdf_url.lower() for kw in ['medr', 'medical', 'sumr', 'summary']):
                    pdf_content = self._download_pdf(pdf_url, app_num, "medr")
                    if pdf_content:
                        break
            # If no specific review found, try the first available PDF
            if pdf_content is None and pdf_links:
                pdf_content = self._download_pdf(pdf_links[0], app_num, "review")

        if pdf_content is None:
            logger.debug(f"No review PDF available for {app_num}")
            return None

        # Extract text from PDF
        full_text = self._extract_text(pdf_content, app_num)
        if not full_text or len(full_text) < 500:
            logger.debug(f"Insufficient text extracted from {app_num} PDF "
                         f"({len(full_text or '')} chars)")
            return None

        # Segment into benefit and risk sections
        benefit_text, risk_text = self._segment_sections(full_text)

        # Map sponsor to ticker
        ticker = _lookup_ticker(sponsor, self._ticker_cache)

        # Map submission status to decision
        decision = self._map_status_to_decision(app.get("submission_status", ""))

        # Determine the relevant date (decision date)
        decision_date = self._parse_date(app.get("submission_status_date", ""))

        doc = {
            "application_number": app_num,
            "drug_name": drug_name,
            "sponsor": sponsor,
            "ticker": ticker or "",
            "submission_type": "ORIG",
            "submission_date": decision_date or "",
            "submission_status": app.get("submission_status", ""),
            "review_priority": app.get("review_priority", ""),
            "decision": decision,
            "pdufa_date": decision_date or "",
            "is_advisory": False,  # Not reliably available from openFDA
            "advisory_committee_date": "",
            "advisory_committee": "",
            "benefit_section_text": benefit_text or "",
            "risk_section_text": risk_text or "",
            "full_document_text": full_text,
            "documents_available": [
                {
                    "type": "medical_review",
                    "date": decision_date or "",
                    "source": "accessdata.fda.gov",
                }
            ],
            "pdf_length_chars": len(full_text),
            "benefit_length_chars": len(benefit_text or ""),
            "risk_length_chars": len(risk_text or ""),
        }

        logger.debug(
            f"  {drug_name} ({app_num}): {len(full_text)} chars, "
            f"benefit={len(benefit_text or '')}c, risk={len(risk_text or '')}c, "
            f"ticker={ticker or 'NONE'}, decision={decision}"
        )

        return doc

    # ------------------------------------------------------------------
    # PDF Download with Caching
    # ------------------------------------------------------------------

    def _download_pdf(
        self, url: str, app_num: str, doc_type: str
    ) -> Optional[bytes]:
        """Download a PDF, caching to _cache/fda/. Returns PDF bytes."""
        import requests

        cache_filename = f"{app_num}_{doc_type}.pdf"
        cache_path = os.path.join(self._cache_dir, cache_filename)

        # Cache hit
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    content = f.read()
                if content[:5] == b"%PDF-":
                    logger.debug(f"Cache hit: {cache_filename}")
                    return content
                else:
                    logger.debug(f"Cache corrupt, re-downloading: {cache_filename}")
            except Exception:
                pass

        # Download
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": _get_ua()},
                timeout=60,
            )
        except Exception as e:
            logger.debug(f"Download failed for {url}: {e}")
            return None

        if resp.status_code != 200:
            logger.debug(f"HTTP {resp.status_code} for {url}")
            return None

        content = resp.content
        if not content or content[:5] != b"%PDF-":
            logger.debug(f"Not a valid PDF: {url}")
            return None

        # Cache it
        try:
            with open(cache_path, "wb") as f:
                f.write(content)
        except Exception:
            pass

        return content

    # ------------------------------------------------------------------
    # TOC Page Parsing
    # ------------------------------------------------------------------

    def _parse_toc_page_for_pdfs(
        self, toc_url: str, app_num: str
    ) -> List[str]:
        """Parse a Drug Approval Package TOC page to extract PDF URLs.

        FDA TOC pages contain JavaScript variables (pdfFilenames) mapping
        document types to PDF filenames. We extract these and construct
        full PDF URLs.
        """
        import requests

        cache_filename = f"{app_num}_toc.html"
        cache_path = os.path.join(self._cache_dir, cache_filename)

        html = None
        # Check cache
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r") as f:
                    html = f.read()
            except Exception:
                pass

        if html is None:
            try:
                url_https = toc_url.replace("http://", "https://")
                resp = requests.get(
                    url_https,
                    headers={"User-Agent": _get_ua()},
                    timeout=30,
                )
                if resp.status_code != 200:
                    logger.debug(f"TOC page returned {resp.status_code}: {toc_url}")
                    return []
                html = resp.text
                # Cache it
                try:
                    with open(cache_path, "w") as f:
                        f.write(html)
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"TOC page fetch failed: {e}")
                return []

        # Extract PDF filenames from JavaScript
        # Pattern: pdfFilenames = { ... medr: "XXXXOrig1s000MedR.pdf", ... };
        filenames = {}

        # Try JavaScript object extraction
        js_match = re.search(
            r'pdfFilenames\s*=\s*\{([^}]+)\}',
            html, re.DOTALL,
        )
        if js_match:
            pairs = js_match.group(1)
            for match in re.finditer(
                r'(\w+)\s*:\s*"([^"]+\.pdf)"',
                pairs, re.I,
            ):
                filenames[match.group(1).lower()] = match.group(2)

        # Also try pdfFiles flags
        flags_match = re.search(
            r'pdfFiles\s*=\s*\{([^}]+)\}',
            html, re.DOTALL,
        )
        available_types = set()
        if flags_match:
            for match in re.finditer(r'(\w+)\s*:\s*1', flags_match.group(1)):
                available_types.add(match.group(1).lower())

        # Construct PDF URLs from the base TOC URL
        base_pdf_url = toc_url.replace("http://", "https://").rsplit("/", 1)[0] + "/"

        pdf_urls = []
        for doc_type in ["medr", "sumr", "riskr", "statr", "clinpharmr"]:
            if doc_type in filenames:
                pdf_urls.append(base_pdf_url + filenames[doc_type])
            elif doc_type in available_types:
                # Try standard naming
                base_name = toc_url.rsplit("/", 1)[-1].replace("TOC.html", "").replace("TOC", "")
                if base_name:
                    pdf_urls.append(base_pdf_url + f"{base_name}{doc_type.replace('r', 'R')}.pdf")

        # If no JavaScript found, try regex for direct PDF links
        if not pdf_urls:
            pdf_matches = re.findall(
                r"""href=["']([^"']*\.pdf)["']""",
                html, re.I,
            )
            for match in pdf_matches:
                if match.startswith("http"):
                    pdf_urls.append(match)
                else:
                    pdf_urls.append(base_pdf_url + match)

        logger.debug(f"TOC parsed: {len(pdf_urls)} PDFs from {toc_url}")
        return pdf_urls

    # ------------------------------------------------------------------
    # PDF Text Extraction
    # ------------------------------------------------------------------

    def _extract_text(self, pdf_content: bytes, app_num: str) -> Optional[str]:
        """Extract text from PDF bytes using pdfplumber. Cache extracted text."""
        cache_filename = f"{app_num}_medr.txt"
        cache_path = os.path.join(self._cache_dir, cache_filename)

        # Cache hit
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r") as f:
                    return f.read()
            except Exception:
                pass

        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber not installed; cannot extract PDF text. "
                           "Install with: pip install pdfplumber")
            return None

        try:
            with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                pages_text = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages_text.append(text)

                full_text = "\n".join(pages_text)

                # Cache extracted text
                try:
                    with open(cache_path, "w") as f:
                        f.write(full_text)
                except Exception:
                    pass

                return full_text
        except Exception as e:
            logger.warning(f"PDF text extraction failed for {app_num}: {e}")
            return None

    # ------------------------------------------------------------------
    # Section Segmentation (Benefit / Risk)
    # ------------------------------------------------------------------

    def _segment_sections(self, full_text: str) -> Tuple[str, str]:
        """Segment Medical Review text into benefit and risk sections.

        FDA Medical Reviews follow a standard structure:
          Section 1: Recommendations/Risk Benefit Assessment
          Section 6: Review of Efficacy (benefit)
          Section 7: Review of Safety (risk)

        Strategy:
        1. Find Table of Contents to identify section page boundaries
        2. Extract Section 1 (benefit-risk assessment) + Section 6 (efficacy)
           as the "benefit" section
        3. Extract Section 1 + Section 7 (safety) as the "risk" section
        4. Fallback: keyword-based extraction
        """
        lines = full_text.split('\n')

        # Find section boundaries from Table of Contents
        toc_entries = self._parse_toc(lines)

        benefit_start, benefit_end = None, None
        risk_start, risk_end = None, None

        # Strategy: Find Section 1 (contains risk/benefit), Section 6 (efficacy),
        # Section 7 (safety)
        sec1_start, sec1_end = None, None
        sec6_start, sec6_end = None, None
        sec7_start, sec7_end = None, None

        for entry in toc_entries:
            sec_num = entry["section"]
            if sec_num in (1, "1", "1.") or "recommendation" in entry["title"].lower():
                sec1_start = entry["line_idx"]
            elif sec_num in (2, "2", "2.") and sec1_start and not sec1_end:
                sec1_end = entry["line_idx"]
            elif sec_num in (6, "6", "6.") or "efficacy" in entry["title"].lower():
                sec6_start = entry["line_idx"]
            elif sec_num in (7, "7", "7.") and sec6_start and not sec6_end:
                sec6_end = entry["line_idx"]
            elif sec_num in (8, "8", "8.") or "reference" in entry["title"].lower():
                if sec7_start and not sec7_end:
                    sec7_end = entry["line_idx"]

        # If TOC parsing found section boundaries, use them
        if sec1_start and sec6_start:
            benefit_text = "\n".join(lines[sec1_start:sec1_end or sec1_start + 50])
            benefit_text += "\n" + "\n".join(lines[sec6_start:sec6_end or sec6_start + 200])
            benefit_start, benefit_end = sec1_start, (sec6_end or sec6_start + 200)
        if sec1_start and sec7_start:
            risk_text = "\n".join(lines[sec7_start:sec7_end or sec7_start + 200])
            risk_start, risk_end = sec7_start, (sec7_end or sec7_start + 200)

        # Fallback: keyword-based extraction
        if not benefit_start:
            benefit_start, benefit_end = self._find_section_boundaries(
                lines, BENEFIT_SECTION_KEYWORDS
            )
        if not risk_start:
            risk_start, risk_end = self._find_section_boundaries(
                lines, RISK_SECTION_KEYWORDS
            )

        # Extract text
        if benefit_start:
            benefit_text = "\n".join(lines[benefit_start:benefit_end or benefit_start + 300])
        else:
            benefit_text = full_text[:len(full_text)//2]  # Fallback: first half

        if risk_start:
            risk_text = "\n".join(lines[risk_start:risk_end or risk_start + 300])
        else:
            risk_text = full_text[len(full_text)//2:]  # Fallback: second half

        # Ensure minimum length
        if len(benefit_text.strip()) < 200:
            benefit_text = full_text[:len(full_text)//2]
        if len(risk_text.strip()) < 200:
            risk_text = full_text[len(full_text)//2:]

        return benefit_text[:200000], risk_text[:200000]

    def _parse_toc(self, lines: List[str]) -> List[Dict[str, Any]]:
        """Parse the Table of Contents from Medical Review text.

        Looks for lines matching patterns like:
          "1  RECOMMENDATIONS/RISK BENEFIT ASSESSMENT"
          "6  REVIEW OF EFFICACY"
          "7  REVIEW OF SAFETY"
        """
        entries = []
        pattern = re.compile(
            r'^\s*(\d+\.?\d*)\s+([A-Z][A-Z\s/]+(?:ASSESSMENT|REVIEW|BACKGROUND|'
            r'INTRODUCTION|EFFICACY|SAFETY|EVALUATION|RESULTS|SUMMARY|'
            r'STUDIES|TRIALS|PHARMACOLOGY|CHEMISTRY|STATISTICS|'
            r'RECOMMENDATIONS|CONCLUSIONS|DISCUSSION|APPENDIX|REFERENCES))',
            re.I,
        )

        for i, line in enumerate(lines):
            match = pattern.match(line.strip())
            if match:
                sec_num = match.group(1)
                title = match.group(2).strip()
                entries.append({
                    "line_idx": i,
                    "section": sec_num,
                    "title": title,
                })

        return entries

    def _find_section_boundaries(
        self, lines: List[str], keywords: List[str]
    ) -> Tuple[Optional[int], Optional[int]]:
        """Find section boundaries using keyword matching.

        Returns (start_line_idx, end_line_idx) or (None, None).
        """
        best_start = None
        best_keyword = ""

        for i, line in enumerate(lines):
            line_lower = line.strip().lower()
            for kw in keywords:
                if kw in line_lower and len(line_lower) < 120:
                    # Prefer shorter lines (headings) and earlier matches
                    if best_start is None or (
                        len(line_lower) < 80 and "review" in line_lower
                    ):
                        best_start = i
                        best_keyword = kw
                        break

        if best_start is None:
            return None, None

        # Find the next major section heading as the end boundary
        # Look for patterns like "X  SECTION_NAME" where X is a number
        next_section_pattern = re.compile(r'^\s*\d+\.?\d*\s+[A-Z][A-Z\s/]{5,}')
        end = None
        for i in range(best_start + 10, min(best_start + 500, len(lines))):
            if next_section_pattern.match(lines[i].strip()):
                end = i
                break

        if end is None:
            end = best_start + 300  # Default: 300 lines from start

        return best_start, end

    # ------------------------------------------------------------------
    # Status/Decision Mapping
    # ------------------------------------------------------------------

    def _map_status_to_decision(self, status: str) -> str:
        """Map FDA submission status to decision type.

        openFDA status codes (from Drugs@FDA):
          AP = Approved
          TA = Tentative Approval
          CR = Complete Response (CRL)
          WD = Withdrawn
          PD = Pending
          PS = Partial Approval
          RX = Refuse to Approve
        """
        status_upper = (status or "").upper().strip()
        if status_upper in ("AP", "APPROVED", "APPROVAL"):
            return "APPROVED"
        elif status_upper in ("TA", "TENTATIVE APPROVAL", "TENTATIVE_APPROVAL"):
            return "TENTATIVE_APPROVAL"
        elif status_upper in ("CR", "COMPLETE RESPONSE", "CRL"):
            return "CRL"
        elif status_upper in ("WD", "WITHDRAWN", "WITHDRAW"):
            return "WITHDRAWN"
        elif status_upper in ("PD", "PENDING"):
            return "PENDING"
        elif status_upper in ("RX", "REFUSE TO APPROVE"):
            return "CRL"
        elif status_upper in ("PS", "PARTIAL APPROVAL"):
            return "APPROVED"
        else:
            logger.debug(f"Unknown FDA status code: '{status_upper}'")
            return "UNKNOWN"

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse an openFDA date string (YYYYMMDD) to ISO format."""
        if not date_str or len(date_str) < 8:
            return None
        try:
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, raw_data: RawData) -> Tuple[bool, List[str]]:
        """Validate that FDA data has the expected schema and quality."""
        issues = []
        valid, basic_issues = raw_data.validate()
        issues.extend(basic_issues)
        if not valid:
            return False, issues

        df = raw_data.records
        required_cols = ["application_number", "drug_name", "decision"]
        for col in required_cols:
            if col not in df.columns:
                issues.append(f"Missing required column: {col}")

        if "decision" in df.columns:
            valid_decisions = {"APPROVED", "CRL", "PENDING", "WITHDRAWN",
                               "UNKNOWN", "TENTATIVE_APPROVAL"}
            unexpected = set(df["decision"].unique()) - valid_decisions
            if unexpected:
                issues.append(f"Unexpected decision values: {unexpected}")

        # Check text columns
        has_benefit = (
            "benefit_section_text" in df.columns
            and df["benefit_section_text"].notna().sum() > 0
        )
        has_risk = (
            "risk_section_text" in df.columns
            and df["risk_section_text"].notna().sum() > 0
        )

        if not has_benefit and not has_risk:
            issues.append(
                "No document text columns found (benefit_section_text, "
                "risk_section_text). Linguistic extraction cannot proceed. "
                "Medical Review PDFs may not be available for these applications."
            )
        elif not has_benefit:
            issues.append(
                "Benefit section text missing — BRLAS will use fallback "
                "segmentation (first half of document)"
            )
        elif not has_risk:
            issues.append(
                "Risk section text missing — BRLAS will use fallback "
                "segmentation (second half of document)"
            )

        if "ticker" in df.columns:
            n_ticker = df["ticker"].notna().sum()
            if n_ticker == 0:
                issues.append(
                    "No sponsor-to-ticker mappings resolved. Price data "
                    "integration will not be possible. Consider expanding "
                    "SPONSOR_TICKER_MAP."
                )
            elif n_ticker < len(df) * 0.3:
                issues.append(
                    f"Only {n_ticker}/{len(df)} drugs mapped to tickers. "
                    f"Statistical power reduced."
                )

        if len(df) < 5:
            issues.append(
                f"Only {len(df)} documents found; need at least 5 for "
                f"meaningful statistical analysis"
            )

        has_text = has_benefit or has_risk or (
            "full_document_text" in df.columns
            and df["full_document_text"].notna().sum() > 0
        )
        if not has_text:
            issues.append("No document text available at all (needed for "
                          "linguistic extraction)")

        return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_ua() -> str:
    """Return a browser-mimetic User-Agent for FDA HTTP requests."""
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36 "
        "TradeFinderResearch/1.0"
    )
