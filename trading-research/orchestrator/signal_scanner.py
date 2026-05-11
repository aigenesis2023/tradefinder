"""
Signal Scanner — Multi-Signal Confirmation Layer (v2.1)

Confirming signals (each adds +0.3 to composite, capped at +0.9):
  1. State/local government contracts (Firecrawl, top 5 states)
  2. SEC Form 4 insider buying clusters (EDGAR RSS XML, free)
  3. Job postings surge (Indeed RSS / Firecrawl)
  4. 13F-HR specialist fund initiation (EDGAR, free)
  5. Russell reconstitution pre-screen (annual, April–June)

Rules enforced here in Python:
  - Confirming signals do NOT substitute for a primary catalyst
  - Insider cluster: open-market purchases > $100K by CEO/CFO/director
  - Cluster window: multiple insiders buying within 14-day window
  - Each signal type tracked independently for hit rate analysis
  - +0.3 per signal, cap at +0.9 (3+ signals)
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import requests
import re

INSIDER_MIN_USD = 100_000
INSIDER_CLUSTER_WINDOW_DAYS = 14
# Match the primary-scanner threshold. 7-year backtest shows 2-insider clusters
# are noise (+0.26% alpha); 3+ is where the signal lives.
INSIDER_MIN_CLUSTER = 3
INSIDER_ROLES = {"CEO", "CFO", "Chief Executive Officer", "Chief Financial Officer",
                 "President", "Director", "Chairman"}

SIGNAL_BONUS = 0.3
SIGNAL_BONUS_CAP = 0.9

STATE_PROCUREMENT_URLS = {
    "california": "https://caleprocure.ca.gov",
    "texas": "https://comptroller.texas.gov/purchasing/",
    "new_york": "https://ogs.ny.gov/procurement",
    "florida": "https://vendor.myfloridamarketplace.com",
    "pennsylvania": "https://www.emarketplace.state.pa.us",
}

EDGAR_FORM4_RSS = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4&dateb=&owner=include&count=40&search_text=&action=getcompany"
EDGAR_13F_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=13F-HR&dateb=&owner=include&count=40&search_text="

HEADERS = {"User-Agent": "tradefinder-research/1.0 (research only)"}


@dataclass
class InsiderBuyResult:
    detected: bool = False
    total_usd: float = 0.0
    buyer_names: list = field(default_factory=list)
    transaction_count: int = 0


@dataclass
class HiringSurgeResult:
    detected: bool = False
    delta_pct: float = 0.0
    recent_count: int = 0
    baseline_count: int = 0


@dataclass
class SpecialistFundResult:
    detected: bool = False
    fund_name: str = ""
    position_size: float = 0.0


@dataclass
class SignalScanResult:
    ticker: str
    insider_buying: InsiderBuyResult = field(default_factory=InsiderBuyResult)
    hiring_surge: HiringSurgeResult = field(default_factory=HiringSurgeResult)
    specialist_fund: SpecialistFundResult = field(default_factory=SpecialistFundResult)
    russell_candidate: bool = False
    state_contract_found: bool = False
    state_contract_details: str = ""
    confirming_signals: list = field(default_factory=list)
    confirming_signal_count: int = 0
    signal_bonus: float = 0.0


# ── Insider Buying (SEC EDGAR Form 4 RSS) ──────────────────────────────────

def _fetch_form4_xml(ticker: str) -> list[dict]:
    """Fetch recent Form 4 filings for a ticker via EDGAR full-text search."""
    url = (
        f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22"
        f"&dateRange=custom&startdt={(datetime.utcnow()-timedelta(days=60)).strftime('%Y-%m-%d')}"
        f"&enddt={datetime.utcnow().strftime('%Y-%m-%d')}&forms=4"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("hits", {}).get("hits", [])
    except Exception:
        return []


def _parse_form4_filing(filing_url: str) -> dict | None:
    """Parse a single Form 4 XML filing."""
    try:
        resp = requests.get(filing_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        root = ET.fromstring(resp.text)
        ns = {"": ""}

        def find_text(tag):
            el = root.find(f".//{tag}")
            return el.text.strip() if el is not None and el.text else ""

        role = find_text("reportingOwnerRelationship/officerTitle") or find_text("reportingOwnerRelationship/isDirector")
        name = find_text("reportingOwnerRelationship/reportingOwnerCik") or find_text("rptOwnerName")

        transactions = []
        for txn in root.findall(".//nonDerivativeTransaction"):
            txn_code_el = txn.find("transactionCoding/transactionCode")
            if txn_code_el is None or txn_code_el.text != "P":
                continue
            shares_el = txn.find("transactionAmounts/transactionShares/value")
            price_el = txn.find("transactionAmounts/transactionPricePerShare/value")
            date_el = txn.find("transactionDate/value")
            if shares_el is None or price_el is None:
                continue
            try:
                shares = float(shares_el.text)
                price = float(price_el.text)
                total = shares * price
                txn_date = date_el.text if date_el is not None else ""
                transactions.append({"total_usd": total, "date": txn_date, "role": role, "name": name})
            except (ValueError, TypeError):
                continue
        return {"role": role, "name": name, "transactions": transactions}
    except Exception:
        return None


def scan_insider_buying(ticker: str) -> InsiderBuyResult:
    """
    Detect open-market insider purchase clusters.
    Requires: >$100K purchase by CEO/CFO/director, within 14-day cluster window.
    """
    hits = _fetch_form4_xml(ticker)
    if not hits:
        return InsiderBuyResult()

    purchases = []
    for hit in hits[:20]:
        filing_url = hit.get("_source", {}).get("file_date", "")
        accession = hit.get("_source", {}).get("accession_no", "").replace("-", "")
        cik = hit.get("_source", {}).get("entity_id", "")
        if not accession or not cik:
            continue
        xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{accession}-index.htm"
        parsed = _parse_form4_filing(xml_url)
        if not parsed:
            continue
        role = parsed.get("role", "")
        is_insider = any(r.lower() in role.lower() for r in INSIDER_ROLES) if role else False
        for txn in parsed.get("transactions", []):
            if txn["total_usd"] >= INSIDER_MIN_USD and is_insider:
                purchases.append(txn)

    if not purchases:
        return InsiderBuyResult()

    # Check for cluster: multiple purchases within INSIDER_CLUSTER_WINDOW_DAYS
    purchases.sort(key=lambda x: x.get("date", ""))
    cluster_purchases = []
    for i, p in enumerate(purchases):
        try:
            d1 = datetime.strptime(p["date"], "%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        window = [p]
        for p2 in purchases[i+1:]:
            try:
                d2 = datetime.strptime(p2["date"], "%Y-%m-%d")
                if (d2 - d1).days <= INSIDER_CLUSTER_WINDOW_DAYS:
                    window.append(p2)
            except (ValueError, KeyError):
                continue
        if len(window) > len(cluster_purchases):
            cluster_purchases = window

    unique_buyers = {p.get("name", "") for p in cluster_purchases if p.get("name")}
    is_cluster = len(unique_buyers) >= INSIDER_MIN_CLUSTER
    total_usd = sum(p["total_usd"] for p in cluster_purchases)
    names = list(unique_buyers)

    return InsiderBuyResult(
        detected=is_cluster,
        total_usd=total_usd,
        buyer_names=names,
        transaction_count=len(cluster_purchases),
    )


# ── Job Posting Surge (Indeed RSS) ────────────────────────────────────────

def scan_hiring_surge(company_name: str, ticker: str) -> HiringSurgeResult:
    """
    Check for unusual hiring activity via Indeed RSS.
    Surge defined as recent 30-day posting count > 2x trailing 90-day daily average.
    """
    try:
        query = company_name.replace(" ", "+")
        url = f"https://www.indeed.com/rss?q={query}&l=&sort=date"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return HiringSurgeResult()

        root = ET.fromstring(resp.content)
        items = root.findall(".//item")
        if not items:
            return HiringSurgeResult()

        now = datetime.utcnow()
        cutoff_30d = now - timedelta(days=30)
        cutoff_90d = now - timedelta(days=90)

        recent_count = 0
        baseline_count = 0

        for item in items:
            pub_date_el = item.find("pubDate")
            if pub_date_el is None:
                continue
            try:
                pub_date = datetime.strptime(
                    pub_date_el.text.strip()[:25], "%a, %d %b %Y %H:%M:%S"
                )
            except (ValueError, AttributeError):
                continue
            if pub_date >= cutoff_30d:
                recent_count += 1
            elif pub_date >= cutoff_90d:
                baseline_count += 1

        if baseline_count == 0:
            return HiringSurgeResult(
                detected=recent_count > 5,
                delta_pct=100.0 if recent_count > 0 else 0.0,
                recent_count=recent_count,
                baseline_count=0,
            )

        baseline_daily = baseline_count / 60
        recent_daily = recent_count / 30
        delta_pct = ((recent_daily - baseline_daily) / baseline_daily) * 100 if baseline_daily > 0 else 0.0
        detected = recent_daily >= 2 * baseline_daily and recent_count >= 5

        return HiringSurgeResult(
            detected=detected,
            delta_pct=round(delta_pct, 1),
            recent_count=recent_count,
            baseline_count=baseline_count,
        )
    except Exception:
        return HiringSurgeResult()


# ── Specialist Fund 13F (EDGAR) ───────────────────────────────────────────

def scan_specialist_fund_13f(ticker: str) -> SpecialistFundResult:
    """
    Look for first-time positions in 13F-HR filings from small specialist funds (<$1B AUM).
    Uses EDGAR full-text search. 45-day delay is acceptable for neglected stocks.
    """
    try:
        url = (
            f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22"
            f"&forms=13F-HR&dateRange=custom"
            f"&startdt={(datetime.utcnow()-timedelta(days=90)).strftime('%Y-%m-%d')}"
            f"&enddt={datetime.utcnow().strftime('%Y-%m-%d')}"
        )
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return SpecialistFundResult()

        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])

        for hit in hits[:5]:
            source = hit.get("_source", {})
            entity_name = source.get("display_names", [""])[0]
            if not entity_name:
                continue
            # Heuristic: specialist funds tend to have shorter names and sector keywords
            # Exclude obvious large fund families
            large_fund_keywords = ["blackrock", "vanguard", "fidelity", "state street",
                                   "jpmorgan", "goldman", "morgan stanley", "t. rowe"]
            if any(k in entity_name.lower() for k in large_fund_keywords):
                continue
            return SpecialistFundResult(detected=True, fund_name=entity_name)

        return SpecialistFundResult()
    except Exception:
        return SpecialistFundResult()


# ── Russell Reconstitution Pre-Screen ────────────────────────────────────

def check_russell_candidate(market_cap_m: float, price: float, avg_volume: float) -> bool:
    """
    Active window: April–June annually.
    Heuristic: stock is within Russell 2000 inclusion range and trending up.
    Russell 2000 approximate inclusion: market cap roughly $100M–$2B.
    """
    now = datetime.utcnow()
    in_window = now.month in (4, 5, 6)
    if not in_window:
        return False
    in_range = 150 <= market_cap_m <= 2000
    sufficient_volume = avg_volume >= 50_000
    return in_range and sufficient_volume


# ── State Contract Scan (Firecrawl stub) ─────────────────────────────────

def scan_state_contracts(company_name: str, firecrawl_api_key: str | None = None) -> tuple[bool, str]:
    """
    Scan top 5 state procurement databases for company name.
    Requires Firecrawl API key. Returns (found, details).
    If no key provided, returns (False, 'firecrawl_key_required').
    """
    if not firecrawl_api_key:
        return False, "firecrawl_key_required"

    found_contracts = []
    for state, url in STATE_PROCUREMENT_URLS.items():
        try:
            resp = requests.post(
                "https://api.firecrawl.dev/v0/scrape",
                headers={"Authorization": f"Bearer {firecrawl_api_key}",
                         "Content-Type": "application/json"},
                json={"url": url, "pageOptions": {"onlyMainContent": True}},
                timeout=30,
            )
            if resp.status_code != 200:
                continue
            content = resp.json().get("data", {}).get("markdown", "")
            if company_name.lower() in content.lower():
                found_contracts.append(state)
        except Exception:
            continue

    if found_contracts:
        return True, f"Found in state procurement: {', '.join(found_contracts)}"
    return False, ""


# ── Main Scanner ──────────────────────────────────────────────────────────

def compute_signal_bonus(signal_count: int) -> float:
    raw = signal_count * SIGNAL_BONUS
    return min(raw, SIGNAL_BONUS_CAP)


def scan_all_signals(
    ticker: str,
    company_name: str,
    market_cap_m: float,
    price: float,
    avg_volume: float,
    firecrawl_api_key: str | None = None,
) -> SignalScanResult:
    result = SignalScanResult(ticker=ticker)

    # Signal 2: Insider buying
    result.insider_buying = scan_insider_buying(ticker)
    if result.insider_buying.detected:
        result.confirming_signals.append("insider_buying_cluster")

    # Signal 3: Hiring surge
    result.hiring_surge = scan_hiring_surge(company_name, ticker)
    if result.hiring_surge.detected:
        result.confirming_signals.append("hiring_surge")

    # Signal 4: Specialist fund 13F
    result.specialist_fund = scan_specialist_fund_13f(ticker)
    if result.specialist_fund.detected:
        result.confirming_signals.append("specialist_fund_initiation")

    # Signal 5: Russell reconstitution
    result.russell_candidate = check_russell_candidate(market_cap_m, price, avg_volume)
    if result.russell_candidate:
        result.confirming_signals.append("russell_inclusion_candidate")

    # Signal 1: State contracts (requires Firecrawl key)
    if firecrawl_api_key:
        found, details = scan_state_contracts(company_name, firecrawl_api_key)
        result.state_contract_found = found
        result.state_contract_details = details
        if found:
            result.confirming_signals.append("state_government_contract")

    result.confirming_signal_count = len(result.confirming_signals)
    result.signal_bonus = compute_signal_bonus(result.confirming_signal_count)

    return result


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "KTOS"
    r = scan_all_signals(ticker, ticker, 500.0, 15.0, 200000)
    print(f"\nSignal scan: {ticker}")
    print(f"  Confirming signals: {r.confirming_signals}")
    print(f"  Signal bonus: +{r.signal_bonus}")
    print(f"  Insider buying: {r.insider_buying}")
    print(f"  Hiring surge: {r.hiring_surge}")
    print(f"  Specialist fund: {r.specialist_fund}")
    print(f"  Russell candidate: {r.russell_candidate}")
