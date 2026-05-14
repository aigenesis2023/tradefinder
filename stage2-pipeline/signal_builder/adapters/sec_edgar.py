"""
sec_edgar.py — SEC EDGAR Data Adapter
=====================================

Acquires SEC filings (10-K, 10-Q, 8-K, etc.) from sec.gov EDGAR system.

Data sources (all free):
  - SEC EDGAR submissions API (filing metadata, CIK lookup)
  - Direct filing text download via sec.gov/Archives
  - HTML-to-text extraction with section segmentation

Implements real filing downloads — no synthetic fallback.
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

# User-Agent required by SEC (rate-limit/block without proper identification).
# Override with SEC_USER_AGENT env var for production use.
_SEC_UA = os.environ.get("SEC_USER_AGENT", "")
SEC_USER_AGENT = _SEC_UA if _SEC_UA else "TradeFinder aigenesis2023@github.com"

# Rate limiting: SEC allows 10 requests/second
SEC_RATE_LIMIT_DELAY = 0.12

# Maximum number of filings to download per ticker per query.
# Set to 4 (last year of quarterly filings) to keep single-threaded
# runs practical. For production: use parallel downloads or pre-built
# filing database. SEC filing text is 1-30MB each, download-bound.
MAX_FILINGS_PER_TICKER = 4


class SECEdgarAdapter(DataAdapter):
    """Acquire SEC filings from EDGAR with real text download.

    Supports:
    - Filing download by ticker/CIK (10-K, 10-Q, 8-K, etc.)
    - Full-text HTML download from sec.gov/Archives
    - Section extraction (Risk Factors, MD&A, full text)
    - File-based caching of downloaded filings

    Rate limited to ~8 requests/second (SEC allows 10/s).
    """

    @property
    def source_name(self) -> str:
        return "sec_edgar"

    @property
    def version(self) -> str:
        return "2.0.0"

    def __init__(self, cache_dir: Optional[str] = None):
        self._cache_dir = cache_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "_cache", "sec_edgar"
        )
        os.makedirs(self._cache_dir, exist_ok=True)
        self._user_agent = SEC_USER_AGENT
        self._ci_k_mapping: Dict[str, str] = {}
        self._ticker_name_cache_path = os.path.join(self._cache_dir, "_ticker_cik_map.json")
        self._load_cik_cache()

    def _load_cik_cache(self):
        """Load persisted CIK→ticker mapping."""
        try:
            if os.path.exists(self._ticker_name_cache_path):
                with open(self._ticker_name_cache_path) as f:
                    self._ci_k_mapping = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"CIK cache corrupted, will rebuild: {e}")
            self._ci_k_mapping = {}

    def _save_cik_cache(self):
        """Persist CIK→ticker mapping."""
        try:
            with open(self._ticker_name_cache_path, "w") as f:
                json.dump(self._ci_k_mapping, f)
        except (IOError, OSError) as e:
            logger.warning(f"Failed to save CIK cache: {e}")

    def health_check(self) -> Tuple[bool, str]:
        """Check if SEC EDGAR is accessible."""
        try:
            import requests
            headers = {"User-Agent": self._user_agent}
            resp = requests.get(
                f"{SEC_SUBMISSIONS_API}/CIK0000320193.json",
                headers=headers, timeout=15,
            )
            return resp.status_code == 200, f"EDGAR accessible (status {resp.status_code})"
        except Exception as e:
            return False, f"EDGAR unreachable: {e}"

    # ------------------------------------------------------------------
    # Main acquisition
    # ------------------------------------------------------------------

    def acquire(self, spec: DataSourceSpec) -> RawData:
        """Acquire SEC filings for specified tickers/CIKs and date range.

        Args:
            spec: DataSourceSpec with fields=list of form types and
                  metadata.tickers=list of ticker symbols.

        Returns:
            RawData with filing text and metadata.
        """
        try:
            import requests
        except ImportError:
            raise DataAcquisitionError(
                source="SEC EDGAR",
                reason="requests library not installed",
                missing_data="SEC filings",
            )

        form_types = spec.fields if spec.fields else ["10-K", "10-Q"]
        tickers = spec.metadata.get("tickers", []) if hasattr(spec, "metadata") else []

        filings: List[Dict[str, Any]] = []
        errors: List[str] = []

        if tickers:
            for ticker in tickers:
                try:
                    ticker_filings = self._get_filings_for_ticker(
                        ticker, form_types, spec.start_date, spec.end_date
                    )
                    filings.extend(ticker_filings)
                except Exception as e:
                    msg = f"Failed to get filings for {ticker}: {e}"
                    logger.warning(msg)
                    errors.append(msg)
        else:
            try:
                filings = self._search_recent_filings(
                    form_types, spec.start_date, spec.end_date
                )
            except Exception as e:
                errors.append(f"Recent filing search failed: {e}")

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
        # Drop full_text to control memory — the extractor uses section
        # columns (mda_text, risk_factors_text, business_text), not full_text.
        # Full 10-K/10-Q text is 10-30MB per filing; sections are ~100KB-2MB.
        df.drop(columns=["full_text"], inplace=True, errors="ignore")

        logger.info(
            f"SEC EDGAR adapter acquired {len(df)} filings "
            f"for {df['ticker'].nunique()} tickers ({spec.start_date} to {spec.end_date})"
        )

        return RawData(
            records=df,
            source_type=spec.source_type,
            provider="sec_edgar",
            metadata={
                "n_filings": len(df),
                "n_tickers": df["ticker"].nunique(),
                "form_types": form_types,
                "errors": errors,
            },
        )

    # ------------------------------------------------------------------
    # CIK lookup
    # ------------------------------------------------------------------

    def _lookup_cik(self, ticker: str) -> Optional[str]:
        """Look up CIK number from ticker symbol (with caching)."""
        ticker_upper = ticker.upper()
        if ticker_upper in self._ci_k_mapping:
            return self._ci_k_mapping[ticker_upper]

        try:
            import requests
            headers = {"User-Agent": self._user_agent}
            url = "https://www.sec.gov/files/company_tickers.json"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for entry in data.values():
                    if entry.get("ticker", "").upper() == ticker_upper:
                        cik = str(entry["cik_str"]).zfill(10)
                        self._ci_k_mapping[ticker_upper] = cik
                        self._save_cik_cache()
                        return cik
        except Exception as e:
            logger.warning(f"CIK lookup failed for {ticker}: {e}")

        return None

    # ------------------------------------------------------------------
    # Filing download
    # ------------------------------------------------------------------

    def _get_filings_for_ticker(
        self, ticker: str, form_types: List[str], start_date: str, end_date: str
    ) -> List[Dict[str, Any]]:
        """Download real SEC filings for a ticker.

        1. Look up CIK from ticker
        2. Query submissions API for recent filings
        3. Filter by form type and date
        4. Download full text from SEC Archives
        5. Extract sections (MD&A, Risk Factors)
        """
        import requests

        cik = self._lookup_cik(ticker)
        if not cik:
            logger.warning(f"No CIK found for ticker {ticker}")
            return []

        cik_stripped = cik.lstrip("0")
        headers = {"User-Agent": self._user_agent}

        # Query submissions API
        submissions_url = f"{SEC_SUBMISSIONS_API}/CIK{cik}.json"
        try:
            resp = requests.get(submissions_url, headers=headers, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"Submissions API returned {resp.status_code} for {ticker}")
                return []
            data = resp.json()
        except Exception as e:
            logger.warning(f"Submissions API failed for {ticker}: {e}")
            return []

        recent = data.get("filings", {}).get("recent", {})
        if not recent:
            return []

        accession_numbers = recent.get("accessionNumber", [])
        form_list = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])
        report_dates = recent.get("reportDate", [])

        form_set = set(f.upper() for f in form_types)
        filings = []
        downloaded = 0

        for i, acc in enumerate(accession_numbers):
            if downloaded >= MAX_FILINGS_PER_TICKER:
                break

            form = (form_list[i] if i < len(form_list) else "").upper()
            date = filing_dates[i] if i < len(filing_dates) else ""
            primary = primary_docs[i] if i < len(primary_docs) else ""
            report_date = report_dates[i] if i < len(report_dates) else ""

            if form not in form_set:
                continue
            if date and (date < start_date or date > end_date):
                continue

            # Download the filing text
            filing_text = self._download_filing_text(
                cik_stripped, acc, primary, headers
            )
            if not filing_text:
                continue

            # Get clean text (cached after first parse — skips BeautifulSoup
            # on re-runs, which is the dominant cost at 5-15s per filing).
            cache_key = f"{cik_stripped}_{acc.replace('-', '')}"
            clean_text = self._get_or_make_clean_text(cache_key, filing_text)

            # Extract sections from clean text (no double parse)
            sections = self._extract_filing_sections_from_clean(clean_text, form)

            filings.append({
                "cik": cik_stripped,
                "ticker": ticker.upper(),
                "filing_date": date,
                "report_date": report_date,
                "form_type": form,
                "accession_number": acc,
                "primary_document": primary,
                "full_text": clean_text,
                "risk_factors_text": sections.get("risk_factors", ""),
                "mda_text": sections.get("mda", ""),
                "business_text": sections.get("business", ""),
                "n_chars": len(clean_text),
            })

            downloaded += 1
            time.sleep(SEC_RATE_LIMIT_DELAY)

        logger.info(
            f"Downloaded {len(filings)} {', '.join(form_types)} filings "
            f"for {ticker} ({start_date} to {end_date})"
        )
        return filings

    def _download_filing_text(
        self,
        cik_stripped: str,
        accession: str,
        primary_doc: str,
        headers: Dict[str, str],
    ) -> Optional[str]:
        """Download the full text of a filing from SEC Archives.

        URL pattern:
          /Archives/edgar/data/{CIK}/{acc_no_dashes}/{acc_no}.txt

        Falls back to the primary document if the full submission isn't
        available as .txt. Uses retry with exponential backoff for transient
        network errors.
        """
        import requests

        acc_no_dashes = accession.replace("-", "")

        # Check cache first
        cache_key = f"{cik_stripped}_{acc_no_dashes}"
        cached = self._get_cached_filing(cache_key)
        if cached is not None:
            return cached

        # Primary URL: full submission text file
        url = (
            f"{SEC_ARCHIVES}/{cik_stripped}/{acc_no_dashes}/"
            f"{accession}.txt"
        )

        text = self._fetch_url_with_retry(url, headers)
        if text is not None:
            if len(text) > 1000 and "<SEC-DOCUMENT>" in text[:500]:
                self._cache_filing(cache_key, text)
            return text

        # Fallback: try the primary document directly
        if primary_doc:
            fallback_url = (
                f"{SEC_ARCHIVES}/{cik_stripped}/{acc_no_dashes}/"
                f"{primary_doc}"
            )
            text = self._fetch_url_with_retry(fallback_url, headers)
            if text is not None and len(text) > 1000:
                self._cache_filing(cache_key, text)
                return text

        return None

    @staticmethod
    def _fetch_url_with_retry(
        url: str, headers: Dict[str, str], max_retries: int = 3, timeout: int = 60
    ) -> Optional[str]:
        """Fetch a URL with retry and exponential backoff.

        Retries on network errors and 429/503 status codes.
        """
        import requests

        last_error = None
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code in (429, 503):
                    # Rate limited or server overload — back off
                    wait = 2 ** attempt
                    logger.debug(f"SEC {resp.status_code} for {url[-60:]}, retry in {wait}s")
                    time.sleep(wait)
                    continue
                elif resp.status_code == 404:
                    return None  # Not found, don't retry
                else:
                    logger.debug(f"SEC {resp.status_code} for {url[-60:]}")
                    return None
            except requests.exceptions.Timeout:
                wait = 2 ** attempt
                logger.debug(f"SEC timeout for {url[-60:]}, attempt {attempt + 1}/{max_retries}")
                last_error = f"Timeout after {timeout}s"
                if attempt < max_retries - 1:
                    time.sleep(wait)
            except requests.exceptions.ConnectionError as e:
                wait = 2 ** attempt
                logger.debug(f"SEC connection error for {url[-60:]}, attempt {attempt + 1}/{max_retries}")
                last_error = str(e)
                if attempt < max_retries - 1:
                    time.sleep(wait)
            except Exception as e:
                logger.debug(f"SEC fetch failed for {url[-60:]}: {e}")
                return None

        if last_error:
            logger.warning(f"SEC fetch failed after {max_retries} retries: {last_error}")
        return None

    # ------------------------------------------------------------------
    # HTML stripping (with parsed-text cache)
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_html(text: str) -> str:
        """Strip HTML/SGML tags and return clean text.

        Uses BeautifulSoup with lxml parser (fast C implementation, ~2-5x
        faster than Python's built-in html.parser). Falls back to html.parser
        if lxml is not installed, then to regex.
        The result is NOT cached here — use _get_or_make_clean_text for
        cache-aware access.
        """
        try:
            from bs4 import BeautifulSoup
            # Prefer lxml for speed; fall back to html.parser
            parser = "lxml"
            try:
                import lxml  # noqa: F401
            except ImportError:
                parser = "html.parser"
            soup = BeautifulSoup(text, parser)
            # Remove script and style elements
            for tag in soup(["script", "style", "meta", "link"]):
                tag.decompose()
            clean = soup.get_text(separator="\n")
        except ImportError:
            # Fallback: regex-based tag stripping
            clean = re.sub(r"<[^>]+>", " ", text)
            clean = re.sub(r"&[a-z]+;", " ", clean)

        # Collapse whitespace
        clean = re.sub(r"\n\s*\n", "\n\n", clean)
        clean = re.sub(r"[ \t]+", " ", clean)
        clean = re.sub(r"\n{3,}", "\n\n", clean)
        return clean.strip()

    def _get_or_make_clean_text(self, cache_key: str, raw_text: str) -> str:
        """Return clean (HTML-stripped) text, using cache when available.

        BeautifulSoup parsing of 10-30MB HTML is the dominant cost in
        the adapter (~5-15s per filing). This second-level cache skips
        re-parsing on re-runs.
        """
        clean_path = os.path.join(self._cache_dir, f"{cache_key}.clean.txt")

        # Cache hit — read pre-parsed clean text
        if os.path.exists(clean_path):
            try:
                with open(clean_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"Failed to read cached clean text: {e}")

        # Cache miss — parse and store
        clean = self._strip_html(raw_text)
        try:
            with open(clean_path, "w", encoding="utf-8") as f:
                f.write(clean)
        except Exception as e:
            logger.debug(f"Failed to cache clean text: {e}")

        return clean

    # ------------------------------------------------------------------
    # Section extraction
    # ------------------------------------------------------------------

    # Section header patterns for 10-K and 10-Q filings
    SECTION_PATTERNS = {
        "risk_factors": re.compile(
            r"(?:ITEM|Item)\s*1A[\.\s]\s*Risk\s*Factors",
            re.IGNORECASE,
        ),
        "mda": re.compile(
            r"(?:ITEM|Item)\s*7[\.\s]\s*Management(?:'s|’s)?\s*Discussion",
            re.IGNORECASE,
        ),
        "business": re.compile(
            r"(?:ITEM|Item)\s*1[\.\s]\s*Business",
            re.IGNORECASE,
        ),
        "market_risk": re.compile(
            r"(?:ITEM|Item)\s*7A[\.\s]\s*Quantitative",
            re.IGNORECASE,
        ),
        "legal_proceedings": re.compile(
            r"(?:ITEM|Item)\s*3[\.\s]\s*Legal\s*Proceedings",
            re.IGNORECASE,
        ),
    }

    # Next-section markers (anything that looks like a new Item heading)
    _NEXT_SECTION = re.compile(
        r"\n\s*(?:ITEM|Item)\s*\d+[A-Z]?\s*[\.\s]\s",
    )

    @classmethod
    def _extract_filing_sections(
        cls, raw_text: str, form_type: str
    ) -> Dict[str, str]:
        """Extract key sections from a filing's raw HTML/SGML text.

        Convenience wrapper — strips HTML then delegates to the clean-text
        extractor. Prefer _extract_filing_sections_from_clean when you
        already have clean text.
        """
        clean = cls._strip_html(raw_text)
        return cls._extract_filing_sections_from_clean(clean, form_type)

    @classmethod
    def _extract_filing_sections_from_clean(
        cls, clean_text: str, form_type: str
    ) -> Dict[str, str]:
        """Extract key sections from already-stripped clean text.

        Section headers appear twice in SEC filings: once in the Table of
        Contents (early in the document) and once in the body. We use the
        LAST occurrence of each header — the body section.

        For 10-K: Item 1A (Risk Factors), Item 7 (MD&A),
                  Item 1 (Business), Item 7A (Market Risk).
        For 10-Q: Part II Item 1A (Risk Factors), Item 2 (MD&A).
        """
        form_upper = form_type.upper() if form_type else ""
        if "10-K" not in form_upper and "10-Q" not in form_upper:
            return {}

        sections: Dict[str, str] = {}

        for section_name, pattern in cls.SECTION_PATTERNS.items():
            # Find ALL occurrences — the last one is the body section
            # (the first is usually in the Table of Contents)
            all_matches = list(pattern.finditer(clean_text))
            if not all_matches:
                continue

            # Use the last match (body section, not TOC)
            match = all_matches[-1]
            start = match.start()

            # Find the next section heading after this body section
            remaining = clean_text[match.end():]
            next_match = cls._NEXT_SECTION.search(remaining)
            if next_match:
                end = match.end() + next_match.start()
            else:
                # Take up to 100KB after the heading
                end = min(start + 100000, len(clean_text))

            section_text = clean_text[start:end].strip()
            if len(section_text) > 100:  # Sanity: real sections are > 100 chars
                sections[section_name] = section_text

        return sections

    # ------------------------------------------------------------------
    # Tickerless search
    # ------------------------------------------------------------------

    def _search_recent_filings(
        self, form_types: List[str], start_date: str, end_date: str
    ) -> List[Dict[str, Any]]:
        """Search for recent filings by form type.

        When no tickers are specified, downloads a sample of filings
        from the EDGAR full-text search API.
        """
        import requests

        filings: List[Dict[str, Any]] = []
        headers = {"User-Agent": self._user_agent}

        for form_type in form_types[:2]:  # Limit breadth
            query = (
                f"https://efts.sec.gov/LATEST/search-index?"
                f"q=formType:{form_type}&dateRange=custom&"
                f"startdt={start_date}&enddt={end_date}&"
                f"from=0&size=20"
            )
            try:
                resp = requests.get(query, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    hits = data.get("hits", {}).get("hits", [])
                    for hit in hits[:10]:
                        source = hit.get("_source", {})
                        cik = source.get("cik", "")
                        ticker = source.get("tickers", [""])[0] if source.get("tickers") else ""
                        accession = source.get("adsh", "")
                        if cik and accession:
                            text = self._download_filing_text(
                                str(cik).zfill(10), accession, "", headers
                            )
                            if text:
                                filings.append({
                                    "cik": cik,
                                    "ticker": ticker,
                                    "filing_date": source.get("filedAt", "")[:10],
                                    "form_type": form_type,
                                    "accession_number": accession,
                                    "full_text": self._strip_html(text),
                                    "n_chars": len(text),
                                })
                            time.sleep(SEC_RATE_LIMIT_DELAY)
            except Exception as e:
                logger.warning(f"Full-text search failed for {form_type}: {e}")

        return filings

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------

    def _get_cached_filing(self, key: str) -> Optional[str]:
        """Retrieve a cached filing from disk."""
        cache_path = os.path.join(self._cache_dir, f"{key}.txt")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"Failed to read cached filing {key}: {e}")
        return None

    def _cache_filing(self, key: str, text: str):
        """Cache a filing to disk."""
        cache_path = os.path.join(self._cache_dir, f"{key}.txt")
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            logger.debug(f"Failed to cache filing {key}: {e}")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, raw_data: RawData) -> Tuple[bool, List[str]]:
        """Validate SEC filing data."""
        issues: List[str] = []
        valid, basic_issues = raw_data.validate()
        issues.extend(basic_issues)
        if not valid:
            return False, issues

        df = raw_data.records
        required_cols = ["cik", "ticker", "filing_date", "form_type", "accession_number"]
        for col in required_cols:
            if col not in df.columns:
                issues.append(f"Missing required column: {col}")

        if "full_text" not in df.columns:
            issues.append("Missing full_text column (filing text not downloaded)")
        elif df["full_text"].apply(lambda x: len(str(x)) if pd.notna(x) else 0).mean() < 100:
            issues.append("Average full_text length < 100 chars — likely download failure")

        return len(issues) == 0, issues
