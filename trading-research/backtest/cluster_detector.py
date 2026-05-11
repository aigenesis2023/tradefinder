"""
Historical insider buying cluster detector.

Filters are a read-only copy of live insider_scanner.py.
DO NOT change thresholds here independently — they must match the live pipeline exactly.

Temporal constraint: only processes Form 4s where filing_date <= as_of_date.
Transaction dates are embedded in the filing itself and are always <= filing_date
(EDGAR requires this by law — Form 4 must be filed within 2 business days of the transaction).

No price data of any kind in this module.
"""

import re
import time
import requests
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

EDGAR_HEADERS = {
    "User-Agent": "tradefinder-research leoduncan.elearning@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

# ── Parameters locked to live pipeline (insider_scanner.py) ──────────────────
MIN_TRANSACTION_USD = 100_000
MIN_CLUSTER_INSIDERS = 2
CLUSTER_WINDOW_DAYS = 14

QUALIFYING_ROLES = {
    "ceo", "chief executive", "chief executive officer",
    "cfo", "chief financial", "chief financial officer",
    "coo", "chief operating", "chief operating officer",
    "chairman", "chair",
    "director", "board member",
    "president",
    "evp", "svp", "executive vice president", "senior vice president",
}

_ENTITY_SUFFIXES = (
    " llc", " lp", " inc", " corp", " ltd", " fund", " trust",
    " advisors", " partners", " capital", " management", " group",
    " holdings", " ventures", " associates",
)

XML_CACHE_DIR = Path(__file__).parent / "cache" / "form4_xml"


@dataclass
class BtTransaction:
    name: str
    role: str
    transaction_date: str  # YYYY-MM-DD — date of actual transaction
    filing_date: str       # YYYY-MM-DD — date Form 4 was filed (our discovery date)
    shares: float
    price_per_share: float
    total_usd: float


@dataclass
class BtCluster:
    cik: str
    ticker: str
    company_name: str
    signal_date: str    # latest filing_date in cluster — when we would have known
    cluster_start: str  # earliest transaction date
    cluster_end: str    # latest transaction date
    total_usd: float
    unique_insiders: int
    transactions: list[BtTransaction] = field(default_factory=list)


def _fetch_form4_xml(cik: str, accession: str, filename: str) -> str | None:
    """Fetch Form 4 text from EDGAR or local cache."""
    XML_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_acc = accession.replace("-", "")
    cache_file = XML_CACHE_DIR / f"{safe_acc}.txt"

    if cache_file.exists():
        try:
            return cache_file.read_text(encoding="latin-1", errors="replace")
        except Exception:
            pass

    url = f"https://www.sec.gov/Archives/{filename}"
    try:
        resp = requests.get(url, headers=EDGAR_HEADERS, timeout=20)
        if resp.status_code == 200:
            cache_file.write_bytes(resp.content)
            time.sleep(0.11)  # respect EDGAR 10 req/sec
            return resp.text
    except Exception:
        pass
    return None


def _parse_form4_content(content: str, filing_date: str) -> list[BtTransaction]:
    """
    Parse Form 4 XML. Returns qualifying open-market purchase transactions.
    Logic is identical to live insider_scanner.py._parse_form4_xml().
    """
    name_match = re.search(r"<rptOwnerName>(.*?)</rptOwnerName>", content)
    name = name_match.group(1).strip() if name_match else "Unknown"

    name_lower = name.lower()
    if any(name_lower.endswith(s.strip()) or (s.strip() + " ") in name_lower for s in _ENTITY_SUFFIXES):
        return []

    title_match = re.search(r"<officerTitle>(.*?)</officerTitle>", content)
    role = title_match.group(1).strip() if title_match else ""
    role_lower = role.lower()

    is_qualifying = any(q in role_lower for q in QUALIFYING_ROLES)
    if not is_qualifying:
        if re.search(r"<isDirector>1</isDirector>", content):
            is_qualifying = True
            if not role:
                role = "Director"
        if re.search(r"<isOfficer>1</isOfficer>", content) and re.search(
            r"<officerTitle>(CEO|CFO|COO|President|Chairman)", content, re.IGNORECASE
        ):
            is_qualifying = True
    if not is_qualifying:
        return []

    footnote_map: dict[str, str] = {}
    for fn_id, fn_text in re.findall(
        r'<footnote id="(.*?)">(.*?)</footnote>', content, re.DOTALL
    ):
        footnote_map[fn_id] = fn_text.lower()

    nd_blocks = re.findall(
        r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>",
        content, re.DOTALL
    )

    txns = []
    for block in nd_blocks:
        code_match = re.search(r"<transactionCode>(.*?)</transactionCode>", block)
        if not code_match or code_match.group(1).strip() != "P":
            continue

        refs = re.findall(r'<footnoteId id="(.*?)"/>', block)
        is_10b51 = any(
            "10b5-1" in footnote_map.get(r, "") or "rule 10b5" in footnote_map.get(r, "")
            for r in refs
        )
        if is_10b51:
            continue

        date_m = re.search(r"<transactionDate>.*?<value>(.*?)</value>", block, re.DOTALL)
        shares_m = re.search(r"<transactionShares>.*?<value>(.*?)</value>", block, re.DOTALL)
        price_m = re.search(r"<transactionPricePerShare>.*?<value>(.*?)</value>", block, re.DOTALL)

        if not date_m or not shares_m:
            continue
        try:
            txn_date = date_m.group(1).strip()[:10]
            shares = float(shares_m.group(1).strip())
            price = float(price_m.group(1).strip()) if price_m else 0.0
            total = shares * price
            if total < MIN_TRANSACTION_USD:
                continue
            txns.append(BtTransaction(
                name=name, role=role,
                transaction_date=txn_date,
                filing_date=filing_date,
                shares=shares, price_per_share=price, total_usd=total,
            ))
        except (ValueError, AttributeError):
            continue

    return txns


def detect_clusters_for_cik(
    cik: str,
    company_name: str,
    filings: list,
    as_of_date: date,
    ticker: str = "",
) -> list[BtCluster]:
    """
    Parse Form 4 XMLs for a CIK (filed on or before as_of_date) and find
    all qualifying insider buying clusters.

    Temporal constraint: only uses filings with filing_date <= as_of_date.
    signal_date = latest filing_date in the cluster window (when we would have known).
    """
    all_txns: list[BtTransaction] = []
    for filing in filings:
        if filing.filing_date > as_of_date.isoformat():
            continue
        content = _fetch_form4_xml(cik, filing.accession, filing.filename)
        if not content:
            continue
        txns = _parse_form4_content(content, filing.filing_date)
        all_txns.extend(txns)

    if not all_txns:
        return []

    all_txns.sort(key=lambda t: t.transaction_date)

    clusters: list[BtCluster] = []
    seen_cluster_ends: set[str] = set()

    for anchor in all_txns:
        window_end = (
            datetime.strptime(anchor.transaction_date, "%Y-%m-%d")
            + timedelta(days=CLUSTER_WINDOW_DAYS)
        ).strftime("%Y-%m-%d")

        window = [t for t in all_txns if anchor.transaction_date <= t.transaction_date <= window_end]
        unique_names = {t.name for t in window}
        if len(unique_names) < MIN_CLUSTER_INSIDERS:
            continue

        cluster_end = max(t.transaction_date for t in window)
        if cluster_end in seen_cluster_ends:
            continue
        seen_cluster_ends.add(cluster_end)

        # signal_date = when we would have known (latest Form 4 filing date in window)
        signal_date = max(t.filing_date for t in window)
        if signal_date > as_of_date.isoformat():
            continue

        clusters.append(BtCluster(
            cik=cik,
            ticker=ticker,
            company_name=company_name,
            signal_date=signal_date,
            cluster_start=min(t.transaction_date for t in window),
            cluster_end=cluster_end,
            total_usd=sum(t.total_usd for t in window),
            unique_insiders=len(unique_names),
            transactions=window,
        ))

    return clusters
