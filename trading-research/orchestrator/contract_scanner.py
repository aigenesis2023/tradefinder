"""
Contract Scanner — given a company name, find recent USAspending.gov awards.

Used by the new discovery flow: start from neglected public tickers,
look up whether they have received material government contracts recently.
"""

import re
import requests
from datetime import datetime, timedelta

USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
AWARD_TYPES = ["A", "B", "C", "D"]
HEADERS = {"User-Agent": "tradefinder-research/1.0", "Content-Type": "application/json"}

# Strip legal suffixes before searching — USAspending names are inconsistent
_LEGAL_SUFFIXES = re.compile(
    r"\b(inc\.?|corp\.?|corporation|llc|ltd\.?|co\.?|company|holdings?|"
    r"group|international|technologies|solutions|systems|services|associates)\b",
    re.IGNORECASE,
)

MIN_SEARCH_TERM_LEN = 5  # prevent ambiguous matches like "NI" or "Niu"

# Words that are too generic to use as a sole search term
_GENERIC_ALONE = {
    "outdoor", "global", "national", "american", "united", "first", "new",
    "general", "digital", "data", "cloud", "capital", "strategic", "advanced",
    "premier", "prime", "elite", "universal", "integrated", "dynamic",
    "energy", "bio", "tech", "health", "financial", "medical", "resource",
    "resources", "power", "fund", "ventures", "partners", "management",
}


def _search_name(company_name: str) -> str:
    """
    Return a search term that matches USAspending's name format.
    Strips legal suffixes and punctuation, returns first 2-3 significant words.
    Returns empty string if result would cause too many false positives.
    """
    # Strip legal suffixes
    cleaned = _LEGAL_SUFFIXES.sub("", company_name)
    # Strip punctuation from each word, keep alphanumeric + hyphens only
    words = []
    for w in cleaned.split():
        w = re.sub(r"[^a-zA-Z0-9\-]", "", w)
        if len(w) >= 2:  # include 2-char abbreviations like "TC", "KA"
            words.append(w)

    if not words:
        return ""

    term = " ".join(words[:3]).strip()

    if len(term) < MIN_SEARCH_TERM_LEN:
        return ""

    # Single generic word → too many false positives
    if len(words) == 1 and words[0].lower() in _GENERIC_ALONE:
        return ""

    return term


def scan_contracts(
    company_name: str,
    days_back: int = 90,
    min_amount: float = 500_000,
) -> list[dict]:
    """
    Search USAspending for recent federal contract awards to this company.
    Returns list of award dicts sorted by date descending.
    Returns [] if no awards, API error, or company name too ambiguous to search.
    """
    search_term = _search_name(company_name)
    if not search_term:
        return []

    date_from = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_to = datetime.utcnow().strftime("%Y-%m-%d")

    payload = {
        "filters": {
            "award_type_codes": AWARD_TYPES,
            "time_period": [{"start_date": date_from, "end_date": date_to}],
            "award_amounts": [{"lower_bound": min_amount}],
            "recipient_search_text": [search_term],
        },
        "fields": [
            "Award ID", "Recipient Name", "Award Amount",
            "Base Obligation Date", "Description", "Recipient UEI",
        ],
        "page": 1,
        "limit": 10,
        "sort": "Base Obligation Date",
        "order": "desc",
    }

    try:
        resp = requests.post(USASPENDING_URL, json=payload, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return []
        results = [
            {
                "company_name": r.get("Recipient Name", ""),
                "contract_value_usd": float(r.get("Award Amount") or 0),
                "catalyst_date": (r.get("Base Obligation Date") or "")[:10],
                "description": r.get("Description") or "",
                "award_id": r.get("Award ID", ""),
                "uei": r.get("Recipient UEI", ""),
            }
            for r in resp.json().get("results", [])
        ]
        # USAspending time_period filters on action date but returns Base Obligation Date.
        # Post-filter: only contracts genuinely within our date window.
        results = [r for r in results if r["catalyst_date"] >= date_from]
        # Post-filter: recipient name must actually resemble the company we searched for.
        # USAspending fuzzy text search can match unrelated companies (e.g. "Enova" → "Renovation").
        results = [r for r in results if _names_match(search_term, r["company_name"])]
        return results
    except Exception:
        return []


def _names_match(search_term: str, recipient_name: str) -> bool:
    """
    Return True only if EVERY significant word in search_term appears as a whole-word
    match in recipient_name. The previous logic accepted any single shared word,
    which produced misattribution like Enova International being credited with a
    Forest Service "Bunkhouse Renovations" award because both names share the
    word "International" (or similar). Requiring full coverage of significant
    words eliminates this class of false positive at the cost of missing matches
    where USAspending records a name variant — the wrong-attribution failure
    mode is more expensive (wastes pipeline LLM budget) than the missed match.
    """
    search_words = {w.lower() for w in search_term.split() if len(w) >= 4}
    if not search_words:
        return False
    recipient_lower = recipient_name.lower()
    return all(
        re.search(r'\b' + re.escape(word) + r'\b', recipient_lower)
        for word in search_words
    )
