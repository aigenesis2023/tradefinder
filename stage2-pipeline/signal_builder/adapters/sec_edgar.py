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
# The SEC Akamai WAF blocks non-browser User-Agent strings even when they
# comply with SEC's identification policy. Appending the tool identifier
# after Safari/537.36 mimics the Edge/Chrome extension pattern and passes
# the WAF, while still declaring our traffic as SEC requires.
# SEC-compliant User-Agent per https://www.sec.gov/privacy
# Format: OrganizationName ContactEmail
# The SEC explicitly requests: "declare your traffic by updating your
# User-Agent to include your organization name and contact email."
# Browser-mimetic strings are rejected by Akamai WAF as "Undeclared
# Automated Tool" — the SEC wants honest identification, not disguise.
_SEC_ORG_UA = (
    "TradeFinderResearch/1.0 (research@tradefinder.dev)"
)
SEC_USER_AGENT = _SEC_UA if _SEC_UA else _SEC_ORG_UA

# Rate limiting: SEC allows 10 requests/second, but Akamai WAF has
# undocumented burst limits that trigger at ~8 requests in rapid
# succession regardless of User-Agent. Using 2 req/s with upstream
# jitter keeps us safely under both thresholds. For batch runs
# exceeding ~20 tickers, consider longer cooldowns between batches.
SEC_RATE_LIMIT_DELAY = 1.0  # seconds between requests

# Maximum number of filings to download per ticker per query.
# Set to 6 (1.5 years of quarterly data + annual reports). For cached runs
# (95%+ cache hit rate from pre-cached files), processing is near-instant.
# For first runs: 10-K HTML parsing takes ~30-120s per filing (10-30MB).
# Use precache_filings.py to pre-build the cache for bulk testing.
MAX_FILINGS_PER_TICKER = 6
# 8-K filings are much smaller (10-200KB vs 500KB-30MB for 10-Ks),
# so we can download more of them per ticker.
MAX_FILINGS_PER_TICKER_8K = 30


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
        """Load persisted CIK→ticker mapping from local caches.

        Uses two sources (in priority order):
        1. The adapter's own ticker→CIK map (_ticker_cik_map.json)
        2. The universe builder's company_tickers_cache.json (pre-seeded
           with 61 major tickers to survive SEC www.sec.gov blocks)
        """
        # Source 1: adapter's own cache
        try:
            if os.path.exists(self._ticker_name_cache_path):
                with open(self._ticker_name_cache_path) as f:
                    self._ci_k_mapping = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"CIK cache corrupted, will rebuild: {e}")

        # Source 2: universe builder's company tickers cache
        # (survives www.sec.gov blocks since it's pre-seeded)
        ct_cache_path = os.path.join(
            os.path.dirname(self._cache_dir), "company_tickers_cache.json"
        )
        try:
            if os.path.exists(ct_cache_path):
                with open(ct_cache_path) as f:
                    ct_data = json.load(f)
                for entry in ct_data.values():
                    ticker = entry.get("ticker", "").upper()
                    cik = entry.get("cik", "")
                    if ticker and cik and ticker not in self._ci_k_mapping:
                        # cik may already be 10-digit or not; normalize
                        cik_str = str(cik).zfill(10)
                        self._ci_k_mapping[ticker] = cik_str
                logger.debug(
                    f"Loaded {len(ct_data)} CIK entries from company_tickers_cache.json"
                )
        except (json.JSONDecodeError, IOError, ValueError) as e:
            logger.debug(f"Could not load company_tickers_cache.json: {e}")
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
            # Check data.sec.gov first (primary API endpoint, works with
            # browser UA even when www.sec.gov is rate-limited)
            resp = requests.get(
                f"{SEC_SUBMISSIONS_API}/CIK0000320193.json",
                headers=headers, timeout=15,
            )
            if resp.status_code == 200:
                # Also check if www.sec.gov (Archives) is reachable
                try:
                    www_resp = requests.get(
                        "https://www.sec.gov/",
                        headers=headers, timeout=10,
                    )
                    if www_resp.status_code == 200:
                        return True, "EDGAR fully accessible (data + archives)"
                    elif www_resp.status_code == 403:
                        return True, (
                            "EDGAR API accessible but www.sec.gov (Archives) "
                            "is rate-limited — filing text download disabled"
                        )
                except Exception:
                    pass
                return True, "EDGAR API accessible (data.sec.gov OK)"
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
        """Look up CIK number from ticker symbol (with caching).

        Checks:
        1. In-memory cache (populated from local JSON files at init)
        2. Local company_tickers_cache.json (if not in memory)
        3. SEC www.sec.gov HTTP request (last resort — may be blocked)
        """
        ticker_upper = ticker.upper()
        if ticker_upper in self._ci_k_mapping:
            return self._ci_k_mapping[ticker_upper]

        # Try the company_tickers_cache.json directly (handles edge case
        # where _load_cik_cache failed silently)
        ct_cache_path = os.path.join(
            os.path.dirname(self._cache_dir), "company_tickers_cache.json"
        )
        try:
            if os.path.exists(ct_cache_path):
                with open(ct_cache_path) as f:
                    ct_data = json.load(f)
                for entry in ct_data.values():
                    if entry.get("ticker", "").upper() == ticker_upper:
                        cik = str(entry.get("cik", "")).zfill(10)
                        if cik:
                            self._ci_k_mapping[ticker_upper] = cik
                            self._save_cik_cache()
                            return cik
        except (json.JSONDecodeError, IOError, ValueError):
            pass

        # HTTP fallback — only if not in cache
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
            elif resp.status_code == 403:
                logger.debug(f"SEC www.sec.gov blocked (403) during CIK lookup for {ticker}")
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

        # 8-Ks are much smaller/faster — use a higher per-ticker cap
        _is_8k_only = form_set == {"8-K"}
        _max_per_ticker = MAX_FILINGS_PER_TICKER_8K if _is_8k_only else MAX_FILINGS_PER_TICKER

        for i, acc in enumerate(accession_numbers):
            if downloaded >= _max_per_ticker:
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

            # Extract transcript from raw filing text (before HTML stripping,
            # since we need SEC document markup tags)
            transcript = None
            if filing_text and form == "8-K":
                transcript = self._extract_transcript_if_present(filing_text)

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
                "audit_report_text": sections.get("audit_report", ""),
                "cam_text": sections.get("cam", ""),
                "departure_text": sections.get("departure", ""),
                "earnings_release_text": sections.get("earnings_release", ""),
                "material_agreement_text": sections.get("material_agreement", ""),
                "transcript_text": transcript.get("full_transcript", "") if transcript else "",
                "qa_section": transcript.get("qa_section", "") if transcript else "",
                "has_qa": bool(transcript and transcript.get("has_qa")),
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

        Retries on network errors, 403 (rate-limit), 429, and 503 status.
        Backs off exponentially with jitter to avoid thundering herd.
        """
        import random
        import requests

        last_error = None
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code in (429, 503):
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.debug(
                        f"SEC {resp.status_code} for {url[-80:]}, "
                        f"backing off {wait:.1f}s (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait)
                    continue
                elif resp.status_code == 403:
                    # Akamai rate-limit block — check if retryable
                    body_snippet = resp.text[:500] if resp.text else ""
                    if "Request Rate Threshold Exceeded" in body_snippet:
                        wait = (4 ** attempt) + random.uniform(1, 3)
                        logger.warning(
                            f"SEC rate-limit block (403) for {url[-80:]}, "
                            f"backing off {wait:.0f}s (attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(wait)
                        continue
                    elif "Undeclared Automated Tool" in body_snippet:
                        logger.error(
                            f"SEC blocking UA as undeclared tool: {headers.get('User-Agent', '')[:100]}"
                        )
                        return None
                    else:
                        logger.debug(f"SEC 403 for {url[-80:]}")
                        return None
                elif resp.status_code == 404:
                    return None  # Not found, don't retry
                else:
                    logger.debug(f"SEC {resp.status_code} for {url[-80:]}")
                    return None
            except requests.exceptions.Timeout:
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.debug(
                    f"SEC timeout for {url[-80:]}, "
                    f"attempt {attempt + 1}/{max_retries}"
                )
                last_error = f"Timeout after {timeout}s"
                if attempt < max_retries - 1:
                    time.sleep(wait)
            except requests.exceptions.ConnectionError as e:
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.debug(
                    f"SEC connection error for {url[-80:]}, "
                    f"attempt {attempt + 1}/{max_retries}"
                )
                last_error = str(e)
                if attempt < max_retries - 1:
                    time.sleep(wait)
            except Exception as e:
                logger.debug(f"SEC fetch failed for {url[-80:]}: {e}")
                return None

        if last_error:
            logger.warning(
                f"SEC fetch failed after {max_retries} retries: {last_error}"
            )
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
            r"(?:ITEM|Item)\s*7[\.\s]\s*Management(?:’s|’s)?\s*Discussion",
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
        "audit_report": re.compile(
            r"(?:REPORT\s+OF\s+INDEPENDENT\s+REGISTERED\s+PUBLIC\s+ACCOUNTING\s+FIRM)"
            r"|(?:Report\s+of\s+Independent\s+Registered\s+Public\s+Accounting\s+Firm)",
            re.IGNORECASE,
        ),
        "cam": re.compile(
            r"(?:Critical\s+Audit\s+Matters?)"
            r"|(?:(?:The\s+)?(?:critical|Critical)\s+audit\s+matters?\s+(?:communicated|identified|are))",
            re.IGNORECASE,
        ),
    }

    # 8-K section patterns — Item-level extraction
    SECTION_PATTERNS_8K = {
        "departure": re.compile(
            r"(?:ITEM|Item)\s*5\.02[\.\s]?\s*(?:Departure|Election)",
            re.IGNORECASE,
        ),
        "earnings_release": re.compile(
            r"(?:ITEM|Item)\s*2\.02[\.\s]?\s*(?:Results|Disclosure)",
            re.IGNORECASE,
        ),
        "material_agreement": re.compile(
            r"(?:ITEM|Item)\s*1\.01[\.\s]?\s*(?:Entry|Material)",
            re.IGNORECASE,
        ),
        "other_events": re.compile(
            r"(?:ITEM|Item)\s*8\.01[\.\s]?\s*(?:Other|Events)",
            re.IGNORECASE,
        ),
        "amendments": re.compile(
            r"(?:ITEM|Item)\s*5\.03[\.\s]?\s*(?:Amendments|Amendment)",
            re.IGNORECASE,
        ),
        "regulation_fd": re.compile(
            r"(?:ITEM|Item)\s*7\.01[\.\s]?\s*(?:Regulation|Reg\s*FD)",
            re.IGNORECASE,
        ),
    }

    # Next-section markers for 8-K (items are numbered, e.g., Item 1.01, Item 2.02)
    _NEXT_SECTION_8K = re.compile(
        r"\n\s*(?:ITEM|Item)\s*\d+\.\d+\s",
    )

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
        For 8-K:  Item 5.02 (Departure of Directors), Item 2.02 (Results),
                  Item 1.01 (Material Agreements), Item 8.01 (Other Events).
        """
        form_upper = form_type.upper() if form_type else ""

        # Select the right pattern set
        if "8-K" in form_upper:
            patterns = cls.SECTION_PATTERNS_8K
            next_section = cls._NEXT_SECTION_8K
        elif "10-K" in form_upper or "10-Q" in form_upper:
            patterns = cls.SECTION_PATTERNS
            next_section = cls._NEXT_SECTION
        else:
            return {}

        sections: Dict[str, str] = {}

        for section_name, pattern in patterns.items():
            all_matches = list(pattern.finditer(clean_text))
            if not all_matches:
                continue

            match = all_matches[-1]
            start = match.start()

            remaining = clean_text[match.end():]
            next_match = next_section.search(remaining)
            if next_match:
                end = match.end() + next_match.start()
            else:
                end = min(start + 100000, len(clean_text))

            section_text = clean_text[start:end].strip()
            if len(section_text) > 100:
                sections[section_name] = section_text

        # Also include the full text as a fallback for LLM extraction
        if sections and len(clean_text) > 200:
            sections["full_text"] = clean_text

        return sections

    # ------------------------------------------------------------------
    # Transcript extraction
    # ------------------------------------------------------------------

    _transcript_extractor = None
    _transcript_extractor_failed = False

    @classmethod
    def _extract_transcript_if_present(cls, raw_filing_text: str) -> Optional[Dict[str, Any]]:
        """Extract earnings call transcript from raw SEC submission text.

        Operates on the raw .txt submission (BEFORE HTML stripping) because
        it needs SEC document markup tags (DOCUMENT, TYPE, TEXT, etc.).
        """
        if cls._transcript_extractor_failed:
            return None
        if cls._transcript_extractor is None:
            try:
                from signal_builder.extractors.transcript_extractor import (
                    TranscriptExtractor,
                )
                cls._transcript_extractor = TranscriptExtractor()
            except Exception as e:
                logger.warning(f"TranscriptExtractor not available: {e}")
                cls._transcript_extractor_failed = True
                return None
        try:
            return cls._transcript_extractor.extract_from_submission(raw_filing_text)
        except Exception as e:
            logger.debug(f"Transcript extraction failed: {e}")
            return None

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
