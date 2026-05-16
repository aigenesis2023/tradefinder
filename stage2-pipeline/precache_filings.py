"""
precache_filings.py — Bulk SEC Filing Pre-Caching
==================================================

Downloads SEC filings for hundreds of tickers in parallel using the
DownloadPool, populating the filing cache so that subsequent hypothesis
tests run near-instantly from cache.

Uses the SECEdgarAdapter's public acquire() interface (one ticker per
worker) so download logic stays identical to the main pipeline path.

Target: 200-500 tickers with 6-12 filings each (10-K, 10-Q, 8-K).
This increases statistical power from ~5% (50 tickers) to ~30-50%.

Usage:
    python precache_filings.py --tickers 300 --filings-per-ticker 8
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Path setup
_PARENT = os.path.dirname(os.path.abspath(__file__))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

import requests
from signal_builder.download_pool import DownloadPool, PoolResult
from signal_builder.adapters.sec_edgar import SECEdgarAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("precache")

# SEC endpoints
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# Filtering — SPAC/shell detection patterns
EXCLUDE_PATTERNS = [
    "SPAC", "ACQUISITION CORP", "ACQUISITION CO", "BLANK CHECK",
    "TRUST", "BIOTECH ACQUISITION", "CAPITAL CORP", "GROWTH CORP",
    "SPONSORED BY",
]


def _is_spac_or_shell(title: str) -> bool:
    upper = title.upper()
    for pattern in EXCLUDE_PATTERNS:
        if pattern in upper:
            return True
    return False


def download_company_tickers(cache_path: str) -> Dict[str, Any]:
    """Download the full SEC company_tickers.json (~15K tickers)."""
    headers = {"User-Agent": "TradeFinderResearch/1.0 (research@tradefinder.dev)"}
    resp = requests.get(SEC_COMPANY_TICKERS_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    with open(cache_path, "w") as f:
        json.dump(data, f)
    logger.info(f"Downloaded {len(data)} tickers from SEC -> {cache_path}")
    return data


def filter_tickers(
    all_tickers: Dict[str, Any],
    target_count: int = 500,
) -> List[str]:
    """Filter tickers: remove SPACs/shells, foreign OTC, sort by CIK ascending.

    Heuristics for US-listed operating companies:
    - Ticker length: US-exchange tickers are 1-5 chars. OTC/foreign are
      typically 5 chars ending in F or Y (ADRs, foreign ordinaries).
    - CIK range: lower CIKs (assigned earlier) = older, established
      US companies. Higher CIKs = recent IPOs, SPACs, foreign filers.
    - Title: SPAC/shell detection by name pattern.

    Returns list of ticker symbols.
    """
    filtered = []
    for entry in all_tickers.values():
        ticker = entry.get("ticker", "").strip().upper()
        title = entry.get("title", "").strip()
        cik = str(entry.get("cik_str", entry.get("cik", ""))).zfill(10)

        if not ticker or not cik:
            continue
        if _is_spac_or_shell(title):
            continue

        # Filter OTC/foreign tickers: ADRs end in Y, foreign ordinaries
        # end in F, and multi-letter OTC tickers are mostly non-operating.
        if len(ticker) == 5 and (ticker.endswith("Y") or ticker.endswith("F")):
            continue
        # Very long tickers are OTC/pink-sheet symbols
        if len(ticker) > 5:
            continue

        # Convert CIK to int for numeric sort
        try:
            cik_int = int(cik)
        except ValueError:
            cik_int = 0

        filtered.append((ticker, cik_int, title))

    # Sort by CIK ascending: oldest/most-established filers first.
    # These are overwhelmingly US-listed operating companies.
    filtered.sort(key=lambda x: x[1])
    logger.info(
        f"Filtered {len(filtered)}/{len(all_tickers)} tickers "
        f"(removed {len(all_tickers) - len(filtered)} SPACs/shells/OTC)"
    )
    return [t for t, _, _ in filtered[:target_count]]


@dataclass
class TickerWorkItem:
    ticker: str
    form_types: List[str]
    start_date: str
    end_date: str
    cache_dir_override: Optional[str] = None
    max_per_ticker: int = 6


def _download_and_cache_one_ticker(work: TickerWorkItem) -> Dict[str, Any]:
    """Lightweight: download filing text and cache to disk. No DataFrame build.

    Uses the adapter's internal _download_filing_text and _get_or_make_clean_text
    methods so cache files are identical to the main pipeline path. Returns
    immediately after caching — does NOT accumulate filings in memory.
    """
    import requests as req

    SEC_SUBMISSIONS_API = "https://data.sec.gov/submissions"
    SEC_USER_AGENT = "TradeFinderResearch/1.0 (research@tradefinder.dev)"

    result = {
        "ticker": work.ticker,
        "n_downloaded": 0,
        "n_cached": 0,
        "error": None,
    }

    try:
        adapter = SECEdgarAdapter(cache_dir=work.cache_dir_override)
        headers = {"User-Agent": SEC_USER_AGENT}

        # Look up CIK
        cik = adapter._lookup_cik(work.ticker)
        if not cik:
            result["error"] = "CIK lookup failed"
            return result
        cik_stripped = cik.lstrip("0")

        # Get filing list
        submissions_url = f"{SEC_SUBMISSIONS_API}/CIK{cik}.json"
        resp = req.get(submissions_url, headers=headers, timeout=30)
        if resp.status_code != 200:
            result["error"] = f"Submissions API HTTP {resp.status_code}"
            return result

        data = resp.json()
        recent = data.get("filings", {}).get("recent", {})
        if not recent:
            result["error"] = "No recent filings"
            return result

        accession_numbers = recent.get("accessionNumber", [])
        form_list = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])

        form_set = set(f.upper() for f in work.form_types)
        downloaded = 0

        for i, acc in enumerate(accession_numbers):
            if downloaded >= work.max_per_ticker:
                break

            form = (form_list[i] if i < len(form_list) else "").upper()
            date = filing_dates[i] if i < len(filing_dates) else ""
            primary = primary_docs[i] if i < len(primary_docs) else ""

            # Match 10-K, 10-K/A, 10-Q, 10-Q/A etc.
            form_match = any(form.startswith(f) for f in form_set)
            if not form_match:
                continue
            if date and (date < work.start_date or date > work.end_date):
                continue

            # Download filing text (hits cache if clean text already exists)
            acc_no_dashes = acc.replace("-", "")
            cache_key = f"{cik_stripped}_{acc_no_dashes}"
            clean_cache_path = os.path.join(adapter._cache_dir, f"{cache_key}.clean.txt")

            if os.path.exists(clean_cache_path):
                result["n_cached"] += 1
                downloaded += 1
                continue

            filing_text = adapter._download_filing_text(
                cik_stripped, acc, primary, headers
            )
            if not filing_text:
                continue

            # Parse and cache clean text (this is the expensive step that
            # the main pipeline would do — we cache it so future runs skip
            # BeautifulSoup parsing entirely)
            try:
                adapter._get_or_make_clean_text(cache_key, filing_text)
                result["n_downloaded"] += 1
            except Exception:
                # Raw text is cached even if clean parsing fails
                result["n_downloaded"] += 1

            # Delete raw HTML file — only keep the clean text
            raw_cache_path = os.path.join(adapter._cache_dir, f"{cache_key}.txt")
            if os.path.exists(raw_cache_path):
                try:
                    os.remove(raw_cache_path)
                except OSError:
                    pass

            downloaded += 1

            # Brief pause between filings (rate limit is handled by
            # DownloadPool's TokenBucket, this is just intra-ticker courtesy)
            time.sleep(0.1)

    except Exception as e:
        result["error"] = str(e)[:300]

    return result


def main():
    parser = argparse.ArgumentParser(description="Bulk SEC filing pre-caching")
    parser.add_argument(
        "--tickers", type=int, default=300,
        help="Number of tickers to cache (default: 300)"
    )
    parser.add_argument(
        "--form-types", type=str, default="10-K,10-Q",
        help="Form types to download (default: 10-K,10-Q)"
    )
    parser.add_argument(
        "--start-date", type=str, default="2020-01-01",
    )
    parser.add_argument(
        "--end-date", type=str, default="2025-05-01",
    )
    parser.add_argument(
        "--workers", type=int, default=4,
        help="Parallel download workers (default: 4)"
    )
    parser.add_argument(
        "--rate-limit", type=float, default=6.0,
        help="Max requests/second (default: 6, SEC allows 10)"
    )
    parser.add_argument(
        "--ticker-list", type=str, default=None,
        help="Path to file with ticker list (one per line). Overrides --tickers count."
    )
    parser.add_argument(
        "--max-per-ticker", type=int, default=6,
        help="Max filings to cache per ticker (default: 6)"
    )
    args = parser.parse_args()

    # Locate cache directory
    adapter = SECEdgarAdapter()
    cache_dir = adapter._cache_dir
    parent_cache = os.path.dirname(cache_dir)

    # Load or download full company tickers
    ct_path = os.path.join(parent_cache, "company_tickers_full.json")
    if os.path.exists(ct_path):
        logger.info(f"Loading cached company tickers from {ct_path}")
        with open(ct_path) as f:
            all_tickers = json.load(f)
    else:
        logger.info("Downloading full SEC company_tickers.json...")
        all_tickers = download_company_tickers(ct_path)

    # Get ticker list
    if args.ticker_list:
        with open(args.ticker_list) as f:
            target_tickers = [
                line.strip().upper()
                for line in f if line.strip() and not line.startswith("#")
            ]
        logger.info(f"Loaded {len(target_tickers)} tickers from {args.ticker_list}")
    else:
        target_tickers = filter_tickers(all_tickers, target_count=args.tickers)

    form_types = [f.strip() for f in args.form_types.split(",")]

    # Count existing cache state
    cache_files = [f for f in os.listdir(cache_dir) if f.endswith(".txt") and not f.startswith("_")]
    logger.info(f"Cache before: {len(cache_files)} files in {cache_dir}")

    # Build work items
    work_items = []
    for ticker in target_tickers:
        work_items.append(TickerWorkItem(
            ticker=ticker,
            form_types=form_types,
            start_date=args.start_date,
            end_date=args.end_date,
            cache_dir_override=cache_dir,
            max_per_ticker=args.max_per_ticker,
        ))

    logger.info(
        f"Pre-caching {len(work_items)} tickers "
        f"({args.form_types}, {args.start_date} to {args.end_date})"
    )
    logger.info(
        f"Parallelism: {args.workers} workers, {args.rate_limit} req/s"
    )

    t0 = time.monotonic()

    with DownloadPool(
        max_workers=args.workers,
        rate_limit=args.rate_limit,
        retries=1,
    ) as pool:
        results: List[PoolResult] = pool.map(
            _download_and_cache_one_ticker,
            work_items,
            desc=f"pre-caching {len(work_items)} tickers",
        )

    elapsed = time.monotonic() - t0

    # Summarize
    total_downloaded = 0
    total_cached = 0
    total_errors = 0
    tickers_with_data = 0

    for r in results:
        if r.success and r.result:
            data = r.result
            nd = data.get("n_downloaded", 0)
            nc = data.get("n_cached", 0)
            total_downloaded += nd
            total_cached += nc
            if nd + nc > 0:
                tickers_with_data += 1
            if data.get("error"):
                total_errors += 1
        elif r.error:
            total_errors += 1

    # Count cache files after
    cache_files_after = [f for f in os.listdir(cache_dir) if f.endswith(".txt") and not f.startswith("_")]
    new_files = len(cache_files_after) - len(cache_files)

    logger.info("=" * 60)
    logger.info(f"Pre-caching complete in {elapsed:.0f}s ({elapsed/60:.1f}m)")
    logger.info(f"  Tickers attempted: {len(work_items)}")
    logger.info(f"  Tickers with data: {tickers_with_data}")
    logger.info(f"  Total new downloads: {total_downloaded}")
    logger.info(f"  Total cache hits: {total_cached}")
    logger.info(f"  New cache files: {new_files}")
    logger.info(f"  Total cache files now: {len(cache_files_after)}")
    logger.info(f"  Errors: {total_errors}")
    if total_errors > 0:
        logger.info(f"  Errors encountered: {total_errors}")
    logger.info(f"  Avg time/ticker: {elapsed/max(1,len(work_items)):.1f}s")
    logger.info("=" * 60)

    if tickers_with_data >= 100:
        logger.info(
            "SUFFICIENT: Cache has enough tickers for reasonable statistical power. "
            "Raise MAX_FILINGS_PER_TICKER to 8-12 in sec_edgar.py for cached runs."
        )
    else:
        logger.warning(
            f"INSUFFICIENT: Only {tickers_with_data} tickers with data. "
            "Run again with more tickers or check network."
        )


if __name__ == "__main__":
    main()
