"""
EDGAR quarterly Form 4 index downloader and pre-filter.

Downloads form.idx files from EDGAR's full-text search index.
These files list every filing by form type, company name, CIK, date, and path.
We use them to pre-filter CIKs with 2+ Form 4 filings in any 14-day window
BEFORE doing any expensive XML parsing.

No price data. No look-ahead. Pure filing metadata.
"""

import re
import time
import requests
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

EDGAR_HEADERS = {
    "User-Agent": "tradefinder-research leoduncan.elearning@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

CACHE_DIR = Path(__file__).parent / "cache" / "edgar_index"

# Matches: <CIK> <YYYY-MM-DD> <edgar/data/...> at end of each data line
_LINE_RE = re.compile(r"(\d{1,10})\s+(\d{4}-\d{2}-\d{2})\s+(edgar/data/\S+)")


@dataclass
class Form4Filing:
    cik: str           # zero-padded 10-digit CIK
    company_name: str
    filing_date: str   # YYYY-MM-DD
    accession: str     # dashed format: 0001234567-22-000001
    filename: str      # full edgar/data/... path


def _parse_index_content(content: str) -> list[Form4Filing]:
    """Parse a form.idx file and return Form 4 / Form 4/A filings."""
    filings = []
    in_data = False
    for line in content.splitlines():
        if line.startswith("---"):
            in_data = True
            continue
        if not in_data or len(line) < 20:
            continue
        form_type = line.split()[0] if line.strip() else ""
        if form_type not in ("4", "4/A"):
            continue
        m = _LINE_RE.search(line)
        if not m:
            continue
        cik = m.group(1).zfill(10)
        filing_date = m.group(2)
        filename = m.group(3)
        # Company name: everything between form_type and the CIK match
        company = line[len(form_type):m.start()].strip()
        # Normalize accession: extract from filename
        acc_raw = filename.split("/")[-1].replace(".txt", "")
        if len(acc_raw) == 18 and "-" not in acc_raw:
            acc = f"{acc_raw[:10]}-{acc_raw[10:12]}-{acc_raw[12:]}"
        else:
            acc = acc_raw
        filings.append(Form4Filing(
            cik=cik,
            company_name=company,
            filing_date=filing_date,
            accession=acc,
            filename=filename,
        ))
    return filings


def download_quarter_index(year: int, quarter: str) -> list[Form4Filing]:
    """
    Download and parse the EDGAR form.idx for a given quarter.
    Returns all Form 4 and Form 4/A filings. Caches raw file locally.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{year}_{quarter}_form.idx"

    if not cache_file.exists():
        url = f"https://www.sec.gov/Archives/edgar/full-index/{year}/{quarter}/form.idx"
        print(f"  [Index] Downloading {year}/{quarter} ...")
        try:
            resp = requests.get(url, headers=EDGAR_HEADERS, timeout=60)
            if resp.status_code != 200:
                print(f"  [Index] HTTP {resp.status_code} for {year}/{quarter}")
                return []
            cache_file.write_bytes(resp.content)
            time.sleep(0.5)
        except Exception as e:
            print(f"  [Index] Error: {e}")
            return []

    try:
        content = cache_file.read_text(encoding="latin-1", errors="replace")
    except Exception as e:
        print(f"  [Index] Read error: {e}")
        return []

    return _parse_index_content(content)


def get_form4_filings(start_date: date, end_date: date) -> list[Form4Filing]:
    """Return all Form 4 filings between start_date and end_date (inclusive)."""
    quarters_needed: set[tuple[int, str]] = set()
    d = start_date.replace(day=1)
    while d <= end_date:
        q = (d.month - 1) // 3 + 1
        quarters_needed.add((d.year, f"QTR{q}"))
        m = d.month + 3
        y = d.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        d = d.replace(year=y, month=m, day=1)

    all_filings: list[Form4Filing] = []
    for year, quarter in sorted(quarters_needed):
        for f in download_quarter_index(year, quarter):
            if start_date.isoformat() <= f.filing_date <= end_date.isoformat():
                all_filings.append(f)

    return all_filings


def prefilter_clusters(
    filings: list[Form4Filing],
    cluster_window_days: int = 14,
    min_filings: int = 2,
) -> dict[str, list[Form4Filing]]:
    """
    Fast metadata-only pass: return company CIKs that have 2+ Form 4 filings
    within any cluster_window_days window.

    This is purely a count check — we cannot determine from the index whether
    the filings are from different insiders (that requires parsing the XML).
    The XML parse in Phase 2 is the authoritative filter for distinct reporters.

    Note: accession number prefixes are the SUBMITTER's CIK, not the insider's CIK.
    Most companies use a shared filing agent, so all insiders share the same
    submitter CIK — using accession prefixes as a "different person" proxy is wrong.

    Returns {company_cik: [filings inside at least one qualifying window]}.
    Does NOT parse XML.
    """
    from collections import defaultdict
    by_cik: dict[str, list[Form4Filing]] = defaultdict(list)
    for f in filings:
        by_cik[f.cik].append(f)

    qualifying: dict[str, list[Form4Filing]] = {}
    for cik, cik_filings in by_cik.items():
        sorted_f = sorted(cik_filings, key=lambda x: x.filing_date)
        in_window: set[str] = set()
        for anchor in sorted_f:
            anchor_date = date.fromisoformat(anchor.filing_date)
            cutoff = (anchor_date + timedelta(days=cluster_window_days)).isoformat()
            window = [f for f in sorted_f if anchor.filing_date <= f.filing_date <= cutoff]
            if len(window) >= min_filings:
                for f in window:
                    in_window.add(f.accession)
        if in_window:
            qualifying[cik] = [f for f in cik_filings if f.accession in in_window]

    return qualifying
