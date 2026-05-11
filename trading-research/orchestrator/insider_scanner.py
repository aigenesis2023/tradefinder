"""
Insider Scanner — detects open-market insider buying clusters via SEC EDGAR Form 4.

Free, no API key. SEC EDGAR has a 10 req/sec rate limit (well within our usage).

Cluster definition (per CLAUDE.md):
  - 3+ insiders buying open-market within a 14-day window
  - Each transaction > $100K
  - Buyers must be CEO, CFO, COO, Chairman, or Director (not routine employees)
  - Must be open-market purchase (code "P"), not automatic plan or compensation-related

Signal rationale:
  - Insiders at neglected companies have no incentive to buy unless they believe in the business
  - Clustered buying implies multiple executives acting on the same internal signal
  - Market doesn't notice quickly in stocks with < 8 analysts
  - Form 4 filed within 2 business days → information edge is short (1-10 day plays)

Data sources:
  - https://www.sec.gov/files/company_tickers.json  ← ticker→CIK bulk map (cached daily)
  - https://data.sec.gov/submissions/{CIK}.json     ← filing history per company
  - https://www.sec.gov/Archives/edgar/.../<accession>.txt ← Form 4 XML
"""

import re
import json
import time
import requests
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

EDGAR_HEADERS = {
    "User-Agent": "tradefinder-research leoduncan.elearning@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

CIK_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_ARCHIVE = "https://www.sec.gov/Archives/edgar/full-index/"

CACHE_DIR = Path(__file__).parent.parent / "cache"
CIK_CACHE_FILE = CACHE_DIR / "cik_map.json"
CIK_CACHE_TTL_HOURS = 24

# Cluster thresholds
MIN_TRANSACTION_USD = 100_000   # per-transaction minimum; cluster materiality (% of mktcap) filters large-cap noise
MIN_CLUSTER_INSIDERS = 3
CLUSTER_WINDOW_DAYS = 14

# Qualifying roles — exclude rank-and-file employee purchases
QUALIFYING_ROLES = {
    "ceo", "chief executive", "chief executive officer",
    "cfo", "chief financial", "chief financial officer",
    "coo", "chief operating", "chief operating officer",
    "chairman", "chair",
    "director", "board member",
    "president",
    "evp", "svp", "executive vice president", "senior vice president",
}


@dataclass
class InsiderTransaction:
    name: str
    role: str
    date: str          # YYYY-MM-DD
    shares: float
    price_per_share: float
    total_usd: float
    transaction_code: str   # "P" = open-market purchase


@dataclass
class InsiderCluster:
    ticker: str
    detected: bool
    transactions: list[InsiderTransaction] = field(default_factory=list)
    cluster_start: str = ""   # earliest transaction date
    cluster_end: str = ""     # latest transaction date
    total_usd: float = 0.0
    unique_insiders: int = 0
    notes: str = ""

    @property
    def days_since_last_buy(self) -> int:
        if not self.cluster_end:
            return 999
        try:
            dt = datetime.strptime(self.cluster_end, "%Y-%m-%d")
            return (datetime.utcnow() - dt).days
        except Exception:
            return 999


def _load_cik_map() -> dict[str, str]:
    """Returns {ticker: CIK_padded} mapping. Cached daily."""
    CACHE_DIR.mkdir(exist_ok=True)

    if CIK_CACHE_FILE.exists():
        age_hours = (time.time() - CIK_CACHE_FILE.stat().st_mtime) / 3600
        if age_hours < CIK_CACHE_TTL_HOURS:
            try:
                return json.loads(CIK_CACHE_FILE.read_text())
            except Exception:
                pass

    try:
        resp = requests.get(CIK_MAP_URL, headers=EDGAR_HEADERS, timeout=30)
        if resp.status_code != 200:
            return {}
        raw = resp.json()
        # raw = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
        mapping = {
            v["ticker"].upper(): str(v["cik_str"]).zfill(10)
            for v in raw.values()
            if "ticker" in v and "cik_str" in v
        }
        CIK_CACHE_FILE.write_text(json.dumps(mapping))
        return mapping
    except Exception:
        return {}


def _get_recent_form4_accessions(cik: str, days_back: int) -> list[str]:
    """Return list of recent Form 4 accession numbers for a CIK."""
    try:
        url = SUBMISSIONS_URL.format(cik=cik)
        resp = requests.get(url, headers=EDGAR_HEADERS, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        dates = filings.get("filingDate", [])

        cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        result = []
        for form, acc, date in zip(forms, accessions, dates):
            if form == "4" and date >= cutoff:
                result.append((acc, date))
        return result
    except Exception:
        return []


def _parse_form4_xml(cik: str, accession: str) -> list[InsiderTransaction]:
    """
    Download and parse a Form 4 XML filing.
    Returns list of qualifying open-market purchase transactions.
    """
    acc_clean = accession.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{accession}.txt"
    try:
        resp = requests.get(url, headers=EDGAR_HEADERS, timeout=15)
        if resp.status_code != 200:
            # Try the index to find the actual XML file
            index_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=1"
            return []
        content = resp.text
    except Exception:
        return []

    transactions = []

    # Extract reporting person name and title
    name_match = re.search(r'<rptOwnerName>(.*?)</rptOwnerName>', content)
    name = name_match.group(1).strip() if name_match else "Unknown"

    # Filter out institutional investors acting as board members (e.g. VC/PE fund).
    # These are funds/firms with board seats, not operators. Their buying motives are
    # structurally different (bridge financing, portfolio defense) and don't carry the
    # same informational signal as an executive buying their own company's stock.
    _ENTITY_SUFFIXES = (
        " llc", " lp", " inc", " corp", " ltd", " fund", " trust",
        " advisors", " partners", " capital", " management", " group",
        " holdings", " ventures", " associates",
    )
    name_lower = name.lower()
    if any(name_lower.endswith(sfx) or (sfx.strip() + " ") in name_lower for sfx in _ENTITY_SUFFIXES):
        return []

    title_match = re.search(r'<officerTitle>(.*?)</officerTitle>', content)
    role = title_match.group(1).strip() if title_match else ""

    # Check if role qualifies
    role_lower = role.lower()
    is_qualifying = any(q in role_lower for q in QUALIFYING_ROLES)
    # Also include if they're flagged as director or officer
    if not is_qualifying:
        if re.search(r'<isDirector>1</isDirector>', content):
            is_qualifying = True
            if not role:
                role = "Director"
        if re.search(r'<isOfficer>1</isOfficer>', content) and re.search(
            r'<officerTitle>(CEO|CFO|COO|President|Chairman)', content, re.IGNORECASE
        ):
            is_qualifying = True

    if not is_qualifying:
        return []

    # Build footnote id → text map for 10b5-1 plan detection
    footnote_map: dict[str, str] = {}
    for fn_id, fn_text in re.findall(
        r'<footnote id="(.*?)">(.*?)</footnote>', content, re.DOTALL
    ):
        footnote_map[fn_id] = fn_text.lower()

    # Parse non-derivative transactions (actual share purchases)
    nd_blocks = re.findall(
        r'<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>',
        content, re.DOTALL
    )

    for block in nd_blocks:
        # Transaction code must be "P" (open-market purchase)
        code_match = re.search(r'<transactionCode>(.*?)</transactionCode>', block)
        if not code_match or code_match.group(1).strip() != "P":
            continue

        # Skip 10b5-1 plan transactions — these are automatic/scheduled, not discretionary.
        # Form 4 discloses plan trades via footnotes referencing "10b5-1" or "rule 10b5".
        footnote_refs = re.findall(r'<footnoteId id="(.*?)"/>', block)
        is_10b51 = any(
            "10b5-1" in footnote_map.get(ref, "") or "rule 10b5" in footnote_map.get(ref, "")
            for ref in footnote_refs
        )
        if is_10b51:
            continue

        date_match = re.search(r'<transactionDate>.*?<value>(.*?)</value>', block, re.DOTALL)
        shares_match = re.search(r'<transactionShares>.*?<value>(.*?)</value>', block, re.DOTALL)
        price_match = re.search(r'<transactionPricePerShare>.*?<value>(.*?)</value>', block, re.DOTALL)

        if not date_match or not shares_match:
            continue

        try:
            date = date_match.group(1).strip()[:10]
            shares = float(shares_match.group(1).strip())
            price = float(price_match.group(1).strip()) if price_match else 0.0
            total = shares * price

            if total < MIN_TRANSACTION_USD:
                continue

            transactions.append(InsiderTransaction(
                name=name,
                role=role,
                date=date,
                shares=shares,
                price_per_share=price,
                total_usd=total,
                transaction_code="P",
            ))
        except (ValueError, AttributeError):
            continue

    return transactions


def scan_insider_buying(ticker: str, days_back: int = 30) -> InsiderCluster:
    """
    Scan SEC EDGAR for insider buying clusters for a given ticker.

    Returns InsiderCluster with detected=True if a qualifying cluster is found,
    i.e. 3+ different insiders made open-market purchases >$100K each within 14 days.
    """
    empty = InsiderCluster(ticker=ticker, detected=False)

    cik_map = _load_cik_map()
    cik = cik_map.get(ticker.upper())
    if not cik:
        empty.notes = "CIK not found"
        return empty

    accessions = _get_recent_form4_accessions(cik, days_back)
    if not accessions:
        return empty

    all_txns: list[InsiderTransaction] = []
    for acc, _date in accessions:
        txns = _parse_form4_xml(cik, acc)
        all_txns.extend(txns)
        time.sleep(0.1)  # respect EDGAR rate limit

    if not all_txns:
        return empty

    # Sort by date ascending
    all_txns.sort(key=lambda t: t.date)

    # Detect cluster: find any 14-day window with 2+ unique insiders buying
    best_cluster: list[InsiderTransaction] = []

    for i, anchor in enumerate(all_txns):
        window_end = (
            datetime.strptime(anchor.date, "%Y-%m-%d") + timedelta(days=CLUSTER_WINDOW_DAYS)
        ).strftime("%Y-%m-%d")

        window_txns = [t for t in all_txns if anchor.date <= t.date <= window_end]
        unique_names = {t.name for t in window_txns}

        if len(unique_names) >= MIN_CLUSTER_INSIDERS:
            if len(window_txns) > len(best_cluster):
                best_cluster = window_txns

    if not best_cluster or len({t.name for t in best_cluster}) < MIN_CLUSTER_INSIDERS:
        return empty

    return InsiderCluster(
        ticker=ticker,
        detected=True,
        transactions=best_cluster,
        cluster_start=min(t.date for t in best_cluster),
        cluster_end=max(t.date for t in best_cluster),
        total_usd=sum(t.total_usd for t in best_cluster),
        unique_insiders=len({t.name for t in best_cluster}),
    )
