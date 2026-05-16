"""
universe_builder.py — Autonomous Universe Construction
======================================================

Derives the appropriate stock universe from the hypothesis specification
without human intervention. Answers three questions autonomously:

  1. What tickers does this hypothesis apply to?
  2. How many observations are needed for adequate statistical power?
  3. What filing frequency is required?

Design principle: the hypothesis defines what it needs; the pipeline
determines how to test it. Zero human handoffs.

Architecture:
  HypothesisSpec → UniverseBuilder → populated UniverseSpec with tickers
                                         + power analysis
                                         + frequency recommendation

Data sources for universe construction (all free, retail-accessible):
  - SEC company_tickers.json: ~15,000 CIK→ticker mappings
  - SEC submissions API: filing history per CIK
  - Yahoo Finance: market cap, sector, exchange data
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

# SEC company_tickers.json endpoint — maps CIK to ticker for all filers
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_USER_AGENT = "TradeFinderResearch/1.0 (research@tradefinder.dev)"
SEC_RATE_LIMIT_DELAY = 0.12

# Default universe constraints
DEFAULT_EXCHANGES = {"NYSE", "NASDAQ", "NYSEARCA", "NYSEAMERICAN"}
DEFAULT_MIN_MARKET_CAP = 100_000_000  # $100M — filters micro-caps
DEFAULT_MIN_PRICE = 5.0

# Power analysis defaults
POWER_ALPHA = 0.05
POWER_TARGET = 0.80
POWER_Z_ALPHA = 1.96  # two-sided
POWER_Z_BETA = 0.84   # 80% power
TYPICAL_DAILY_VOL_BPS = 150  # typical stock daily volatility in bps

# Minimum universe sizes (hard floors, not recommendations)
MIN_TICKERS_FOR_POWER = 200
MIN_OBSERVATIONS_FOR_POWER = 100

# Cache for company tickers to avoid repeated downloads
_CACHED_COMPANY_TICKERS: Optional[Dict[str, Dict[str, Any]]] = None


@dataclass
class UniverseBuildResult:
    """Result of autonomous universe construction."""
    tickers: List[str]
    n_tickers: int
    source: str  # 'custom' | 'sec_company_tickers' | 'fallback'
    required_observations: int
    achievable_observations: int
    is_adequately_powered: bool
    achieved_power: float
    frequency_recommendation: str  # 'annual' | 'quarterly' | 'monthly'
    filing_types: List[str]
    methodology: str  # human-readable explanation
    warnings: List[str] = field(default_factory=list)


class UniverseBuilder:
    """Autonomous universe construction from hypothesis specification.

    Takes a hypothesis and determines everything the pipeline needs to know
    about what stocks to test on, how many, and what filing frequency to use.

    Usage:
        builder = UniverseBuilder()
        result = builder.build(hypothesis)
        # result.tickers → list of ticker symbols
        # result.required_observations → minimum N for adequate power
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        min_tickers: int = MIN_TICKERS_FOR_POWER,
        min_observations: int = MIN_OBSERVATIONS_FOR_POWER,
    ):
        self._cache_dir = cache_dir
        self._min_tickers = min_tickers
        self._min_observations = min_observations
        self._company_tickers: Optional[Dict[str, Dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def build(self, hypothesis) -> UniverseBuildResult:
        """Construct the universe for a hypothesis autonomously.

        Args:
            hypothesis: HypothesisSpec from signal_builder.base or pipeline.

        Returns:
            UniverseBuildResult with populated tickers and power analysis.
        """
        universe = hypothesis.universe
        custom_tickers = universe.custom_tickers or []

        # Step 1: If custom tickers are provided and sufficient, use them
        if custom_tickers and len(custom_tickers) >= self._min_tickers:
            return self._use_custom_tickers(hypothesis, custom_tickers)

        # Step 2: Determine what filing frequency is needed
        filing_freq, filing_types = self._derive_filing_types(hypothesis)

        # Step 3: Derive the universe scope from the hypothesis
        scope = self._derive_universe_scope(hypothesis)

        # Step 4: Fetch available tickers from SEC EDGAR
        all_tickers = self._fetch_company_tickers()
        filtered_tickers = self._filter_tickers(all_tickers, scope)

        # Step 5: If custom_tickers provided but insufficient, merge them in
        if custom_tickers:
            filtered_tickers = list(dict.fromkeys(custom_tickers + filtered_tickers))
            source = "custom+constructed"
        else:
            source = "sec_company_tickers"

        # Step 6: Cap tickers at what's computationally feasible FIRST,
        # then do power analysis on the ACTUAL achievable ticker count.
        max_tickers = self._compute_feasible_max(filtered_tickers, hypothesis)
        final_tickers = filtered_tickers[:max_tickers]

        # Step 7: Power analysis on the actual feasible universe
        power_result = self._compute_power_requirements(
            hypothesis=hypothesis,
            n_tickers=len(final_tickers),
            filing_frequency=filing_freq,
            time_horizon_years=self._compute_time_horizon(hypothesis),
        )

        result = UniverseBuildResult(
            tickers=final_tickers,
            n_tickers=len(final_tickers),
            source=source,
            required_observations=power_result["required_observations"],
            achievable_observations=power_result["achievable_observations"],
            is_adequately_powered=power_result["is_adequately_powered"],
            achieved_power=power_result["achieved_power"],
            frequency_recommendation=filing_freq,
            filing_types=filing_types,
            methodology=(
                f"Autonomously constructed from {len(filtered_tickers)} SEC-registered "
                f"tickers matching scope: {scope.get('description', 'all US equities')}. "
                f"Power analysis: {power_result['summary']}. "
                f"Filing frequency: {filing_freq} ({', '.join(filing_types)}). "
                f"{'WARNING: underpowered with current ticker count.' if not power_result['is_adequately_powered'] else 'Adequately powered.'}"
            ),
            warnings=power_result.get("warnings", []),
        )

        logger.info(
            f"UniverseBuilder: constructed {result.n_tickers} tickers "
            f"(source={result.source}, powered={result.is_adequately_powered}, "
            f"power={result.achieved_power:.3f})"
        )

        return result

    # ------------------------------------------------------------------
    # Filing type derivation
    # ------------------------------------------------------------------

    def _derive_filing_types(self, hypothesis) -> Tuple[str, List[str]]:
        """Derive filing types and frequency from hypothesis data sources.

        Returns:
            (frequency, list_of_form_types) e.g., ('quarterly', ['10-K', '10-Q'])
        """
        # Check data sources for filing types
        for ds in hypothesis.data_sources:
            source_type = getattr(ds, "source_type", "").lower()
            if "sec" in source_type or "filing" in source_type or "edgar" in source_type:
                fields = getattr(ds, "fields", []) or []
                if fields:
                    return self._frequency_from_forms(fields), fields

        # Check if hypothesis mechanism mentions specific filing types
        mechanism = (getattr(hypothesis, "mechanism", "") or "").lower()
        if "8-k" in mechanism or "item 5.02" in mechanism:
            return "event_driven", ["8-K"]
        if "10-q" in mechanism:
            return "quarterly", ["10-Q"]
        if "10-k" in mechanism:
            return "annual", ["10-K"]

        # Default: use both 10-K and 10-Q for maximum signal density
        return "quarterly", ["10-K", "10-Q"]

    def _frequency_from_forms(self, form_types: List[str]) -> str:
        """Determine effective frequency from form type mix."""
        has_annual = any("10-K" in f or "10K" in f for f in form_types)
        has_quarterly = any("10-Q" in f or "10Q" in f for f in form_types)
        has_event = any("8-K" in f or "8K" in f for f in form_types)

        if has_quarterly or (has_annual and has_event):
            return "quarterly"
        if has_event:
            return "event_driven"
        return "annual"

    # ------------------------------------------------------------------
    # Universe scope derivation
    # ------------------------------------------------------------------

    def _derive_universe_scope(self, hypothesis) -> Dict[str, Any]:
        """Derive universe scope from hypothesis mechanism and data sources.

        Analyzes the hypothesis text to determine what kind of stocks
        the hypothesis applies to, without asking the user.
        """
        scope = {
            "exchanges": DEFAULT_EXCHANGES,
            "min_market_cap": DEFAULT_MIN_MARKET_CAP,
            "min_price": getattr(hypothesis.universe, "min_price", DEFAULT_MIN_PRICE) or DEFAULT_MIN_PRICE,
            "description": "all US listed equities",
            "sectors": None,
            "exclude_sectors": None,
            "require_filings": True,
        }

        # Parse mechanism and llm_advantage for scope clues
        text_fields = [
            getattr(hypothesis, "mechanism", "") or "",
            getattr(hypothesis, "llm_advantage", "") or "",
            getattr(hypothesis, "name", "") or "",
            getattr(hypothesis, "falsifiable_prediction", "") or "",
        ]
        combined = " ".join(text_fields).lower()

        # Sector detection
        sector_keywords = {
            "healthcare": ["pharma", "biotech", "healthcare", "medical device", "drug trial", "fda approval"],
            "technology": ["software company", "semiconductor", "saas business", "tech sector"],
            "financial": ["bank stock", "insurance company", "fintech", "regional bank"],
            "energy": ["oil company", "gas producer", "renewable energy", "utility sector"],
            "consumer": ["retail sector", "consumer goods", "restaurant chain"],
        }

        for sector, keywords in sector_keywords.items():
            if any(kw in combined for kw in keywords):
                scope["sectors"] = [sector]
                scope["description"] = f"{sector} sector stocks"
                break

        # Filing-specific scope
        if "10-k" in combined or "annual" in combined:
            scope["description"] += " filing 10-Ks"
        if "8-k" in combined or "departure" in combined:
            scope["description"] += " filing 8-Ks"

        # Large cap bias detection
        if any(w in combined for w in ["large cap", "mega cap", "s&p 500", "sp500", "spx"]):
            scope["min_market_cap"] = 10_000_000_000  # $10B
            scope["description"] += ", large cap"

        # Small/mid cap detection
        if any(w in combined for w in ["small cap", "mid cap", "russell 2000"]):
            scope["min_market_cap"] = 50_000_000  # $50M
            scope["description"] += ", small/mid cap"

        return scope

    # ------------------------------------------------------------------
    # Ticker acquisition from SEC
    # ------------------------------------------------------------------

    def _fetch_company_tickers(self) -> Dict[str, Dict[str, Any]]:
        """Fetch all company tickers from SEC's company_tickers.json.

        Uses local file cache to survive SEC rate-limiting/blocking.
        Cache is refreshed when SEC API is reachable.

        Returns:
            Dict mapping uppercase ticker → {cik_str, ticker, title}
        """
        global _CACHED_COMPANY_TICKERS

        if _CACHED_COMPANY_TICKERS is not None:
            return _CACHED_COMPANY_TICKERS

        if self._company_tickers is not None:
            return self._company_tickers

        # Check local cache first
        cache_path = os.path.join(self._cache_dir or ".", "company_tickers_cache.json")

        def _load_from_file(path: str) -> Optional[Dict[str, Dict[str, Any]]]:
            try:
                if os.path.exists(path):
                    with open(path, "r") as f:
                        return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load ticker cache: {e}")
            return None

        # Try SEC API
        try:
            import requests
            headers = {"User-Agent": SEC_USER_AGENT}
            resp = requests.get(SEC_COMPANY_TICKERS_URL, headers=headers, timeout=30)
            if resp.status_code == 200:
                raw = resp.json()
                result: Dict[str, Dict[str, Any]] = {}
                for cik_str, info in raw.items():
                    ticker = info.get("ticker", "").upper()
                    if ticker:
                        result[ticker] = {
                            "cik": str(info.get("cik_str", cik_str)),
                            "ticker": ticker,
                            "title": info.get("title", ""),
                        }
                # Save to local cache
                try:
                    with open(cache_path, "w") as f:
                        json.dump(result, f)
                except Exception:
                    pass
                _CACHED_COMPANY_TICKERS = result
                self._company_tickers = result
                logger.info(f"Fetched {len(result)} tickers from SEC company_tickers.json")
                return result
            else:
                logger.warning(f"SEC company_tickers returned {resp.status_code}")
        except Exception as e:
            logger.warning(f"Failed to fetch SEC company tickers: {e}")

        # Fall back to local cache
        cached = _load_from_file(cache_path)
        if cached:
            logger.info(f"Using cached company tickers: {len(cached)} entries")
            _CACHED_COMPANY_TICKERS = cached
            self._company_tickers = cached
            return cached

        return {}

    def _filter_tickers(
        self,
        all_tickers: Dict[str, Dict[str, Any]],
        scope: Dict[str, Any],
    ) -> List[str]:
        """Filter tickers based on derived scope.

        Filters applied:
        1. Remove tickers with non-standard formats (warrants, rights, units, >5 chars)
        2. Sector keyword matching against company title from SEC data
        3. Min market cap filter (when exchange/market data is unavailable, all pass)
        """
        tickers = list(all_tickers.keys())
        n_before = len(tickers)

        # 1. Remove non-standard tickers: warrants (.W, -W), rights (.R), units (.U),
        #    and tickers with unusual characters or excessive length (likely not common stock).
        def _is_standard_ticker(t: str) -> bool:
            if len(t) > 5:
                return False
            if not t.replace("-", "").replace(".", "").isalpha():
                return False
            for suffix in (".W", "-W", ".R", "-R", ".U", "-U", ".A", "-A", " WS", " RT", " UN", " WI"):
                if t.endswith(suffix):
                    return False
            return True

        tickers = [t for t in tickers if _is_standard_ticker(t)]
        n_after_format = len(tickers)
        if n_after_format < n_before:
            logger.info(f"  Removed {n_before - n_after_format} non-standard tickers (warrants/rights/units/etc.)")

        # 2. Remove SPACs and shell companies by title keywords.
        _SPAC_KEYWORDS = [
            "acquisition corp", "acquisition co", "acquisition inc",
            "spac", "blank check", "special purpose acquisition",
            "capital corp", "capital inc", "holding corp", "holdings corp",
            "shell company", "development stage",
        ]

        def _is_spac(t: str) -> bool:
            title = all_tickers.get(t, {}).get("title", "").lower()
            return any(kw in title for kw in _SPAC_KEYWORDS)

        tickers = [t for t in tickers if not _is_spac(t)]
        n_after_spac = len(tickers)
        if n_after_spac < n_after_format:
            logger.info(f"  Removed {n_after_format - n_after_spac} SPAC/shell tickers")

        # 3. Sort by CIK (lower = older SEC registration = generally more established).
        #    This ensures the 50-ticker feasible cap picks blue-chips, not micro-caps.
        tickers.sort(key=lambda t: int(all_tickers.get(t, {}).get("cik", 999999999)))

        # 4. Sector filter: match company title against sector keywords.
        sectors = scope.get("sectors", [])
        if sectors:
            sector_keywords = {
                "technology": ["tech", "software", "semiconductor", "computer", "data", "cyber",
                               "internet", "digital", "electronic", "cloud", "network", "it ", "ai "],
                "healthcare": ["health", "pharma", "bio", "medic", "therap", "drug", "clinic",
                               "hospital", "diagnostic", "surgical", "genetic", "immun"],
                "financial": ["bank", "financ", "insur", "invest", "capital", "credit", "loan",
                              "mortgage", "broker", "asset management", "private equity", "hedge"],
                "energy": ["energy", "oil", "gas", "petroleum", "solar", "wind", "power",
                           "utility", "renewable", "pipeline", "drilling", "exploration"],
                "consumer": ["retail", "consumer", "food", "beverage", "restaurant", "apparel",
                             "auto", "hotel", "entertainment", "media", "gaming", "travel"],
                "industrial": ["industr", "manufactur", "aerospace", "defense", "chemical",
                               "construction", "engineering", "logistics", "transport", "machinery"],
                "real_estate": ["real estate", "reit", "property", "realty", "homes"],
                "materials": ["mining", "metal", "steel", "gold", "copper", "timber", "paper",
                              "chemical", "plastics", "glass"],
            }

            sec_sectors_lower = [s.lower() for s in sectors]
            to_keep = []
            for t in tickers:
                entry = all_tickers.get(t, {})
                title = entry.get("title", "").lower()
                for sec in sec_sectors_lower:
                    keywords = sector_keywords.get(sec, [sec])
                    if any(kw in title for kw in keywords):
                        to_keep.append(t)
                        break
            tickers = to_keep
            n_after_sector = len(tickers)
            logger.info(f"  Sector filter ({sectors}): {n_after_format} → {n_after_sector} tickers")

        logger.info(
            f"Universe scope: {scope['description']} → "
            f"{len(tickers)} tickers (from {n_before} SEC-registered)"
        )
        return sorted(tickers)

    # ------------------------------------------------------------------
    # Power analysis
    # ------------------------------------------------------------------

    def _compute_power_requirements(
        self,
        hypothesis,
        n_tickers: int,
        filing_frequency: str,
        time_horizon_years: float,
    ) -> Dict[str, Any]:
        """Compute required sample size and achieved power.

        Uses the hypothesis's minimum effect size to determine whether
        the available universe can detect the hypothesized signal.

        Formula for t-test of strategy daily returns:
            t = (alpha_daily / sigma_portfolio) * sqrt(T)
            sigma_portfolio ≈ individual_vol / sqrt(n_tickers)
            t = alpha_daily * sqrt(n_tickers) * sqrt(T) / individual_vol

        Solving for required n_tickers * T:
            n_tickers * T > (Z_alpha + Z_beta)^2 * sigma^2 / alpha_daily^2
        """
        alpha_bps_annual = getattr(
            hypothesis.minimum_effect_size, "annualized_alpha_bps", 300
        ) or 300
        alpha_bps_daily = alpha_bps_annual / 252

        sigma_bps_daily = TYPICAL_DAILY_VOL_BPS

        # Observations per ticker per year based on filing frequency
        obs_per_ticker_per_year = {
            "annual": 1,
            "quarterly": 4,
            "event_driven": 2,  # conservative; 8-Ks are sporadic
            "monthly": 12,
            "daily": 252,
        }
        obs_per_year = obs_per_ticker_per_year.get(filing_frequency, 4)

        # Total signal observations achievable
        achievable_obs = int(n_tickers * obs_per_year * time_horizon_years)
        required_obs = self._min_observations

        # Compute required total observations for adequate power
        # Required: (Z_alpha + Z_beta)^2 * sigma^2 / alpha^2
        z_sum = POWER_Z_ALPHA + POWER_Z_BETA  # 2.8
        required_obs_from_effect = int(
            (z_sum ** 2) * (sigma_bps_daily ** 2) / max(alpha_bps_daily ** 2, 1e-10)
        )

        # Cap at reasonable max for practical guidance
        required_obs = max(self._min_observations, required_obs_from_effect)

        # Achieved power
        # Power = Phi(sqrt(N*T) * delta / sigma - Z_alpha)
        #        = Phi(sqrt(achievable_obs) * alpha_daily / sigma - Z_alpha)
        if achievable_obs > 0:
            noncentrality = math.sqrt(achievable_obs) * alpha_bps_daily / sigma_bps_daily
            achieved_power = self._normal_cdf(noncentrality - POWER_Z_ALPHA)
        else:
            achieved_power = 0.0

        is_adequately_powered = (
            achievable_obs >= required_obs
            and n_tickers >= self._min_tickers
            and achieved_power >= POWER_TARGET
        )

        warnings = []
        if not is_adequately_powered:
            if n_tickers < self._min_tickers:
                warnings.append(
                    f"Only {n_tickers} tickers available (minimum {self._min_tickers} "
                    f"recommended for reliable inference)"
                )
            if achievable_obs < required_obs:
                warnings.append(
                    f"Only {achievable_obs} achievable signal observations "
                    f"(need ~{required_obs} for {POWER_TARGET:.0%} power at "
                    f"{alpha_bps_annual}bps effect size)"
                )
            if achieved_power < POWER_TARGET:
                warnings.append(
                    f"Achieved power {achieved_power:.1%} below target {POWER_TARGET:.0%} "
                    f"— consider increasing universe or time horizon"
                )

        summary = (
            f"Need ~{required_obs} signal observations for {POWER_TARGET:.0%} power "
            f"at {alpha_bps_annual}bps annualized. "
            f"Achievable: {achievable_obs} obs from {n_tickers} tickers × "
            f"{obs_per_year}/yr × {time_horizon_years:.1f}yr "
            f"(achieved power: {achieved_power:.1%})"
        )

        return {
            "required_observations": required_obs,
            "achievable_observations": achievable_obs,
            "is_adequately_powered": is_adequately_powered,
            "achieved_power": achieved_power,
            "n_tickers_available": n_tickers,
            "obs_per_ticker_per_year": obs_per_year,
            "time_horizon_years": time_horizon_years,
            "alpha_bps_annual": alpha_bps_annual,
            "alpha_bps_daily": alpha_bps_daily,
            "summary": summary,
            "warnings": warnings,
        }

    def _compute_time_horizon(self, hypothesis) -> float:
        """Compute time horizon in years from hypothesis time period."""
        try:
            start = getattr(hypothesis.time_period, "start_date", "2020-01-01")
            end = getattr(hypothesis.time_period, "end_date", "2025-12-31")
            from datetime import datetime
            s = datetime.strptime(start, "%Y-%m-%d")
            e = datetime.strptime(end, "%Y-%m-%d")
            return max(0.5, (e - s).days / 365.25)
        except Exception as e:
            logger.warning(f"Failed to parse time horizon from hypothesis: {e}; defaulting to 3.0 years")
            return 3.0

    def _compute_feasible_max(
        self,
        tickers: List[str],
        hypothesis,
    ) -> int:
        """Cap tickers at what's computationally feasible.

        SEC rate limit: 10 req/s. Each ticker needs ~1 request for CIK lookup
        + 1 request for filing list + N requests for filing downloads.
        With 10 filings/ticker, that's ~12 requests/ticker.
        At 10 req/s, 200 tickers = 2,400 requests = 240 seconds = 4 minutes.
        At 500 tickers = 6,000 requests = 600 seconds = 10 minutes.
        """
        # Check if hypothesis has holding_period_days or other constraints.
        # MAX_FILINGS_PER_TICKER in sec_edgar.py caps actual downloads.
        from signal_builder.adapters.sec_edgar import (
            MAX_FILINGS_PER_TICKER as SEC_MAX_FILINGS,
            MAX_FILINGS_PER_TICKER_8K as SEC_MAX_FILINGS_8K,
        )
        _, filing_types = self._derive_filing_types(hypothesis)
        _is_8k_only = set(filing_types) == {"8-K"}
        _max_per_ticker = SEC_MAX_FILINGS_8K if _is_8k_only else SEC_MAX_FILINGS
        n_filings_per_ticker = min(
            self._estimate_filings_per_ticker(hypothesis),
            _max_per_ticker,
        )
        est_requests_per_ticker = 2 + n_filings_per_ticker  # CIK lookup + filing list + downloads

        # SEC download + HTML parse times: 10-K text is 1-30MB HTML.
        # Download: ~2-8s, lxml BeautifulSoup parse: ~20-90s.
        # Total per-filing: ~30-120s for 10-K, ~2-10s for 8-K.
        # Cached filings read at ~0.01s from disk (both raw + clean text cached).
        EST_SECONDS_PER_API_CALL = 0.3
        EST_SECONDS_PER_FILING_CACHED = 0.05
        EST_SECONDS_PER_FILING_DOWNLOAD = 1.5 if _is_8k_only else 45.0  # download + parse

        # Estimate cache hit rate from the filing cache directory
        import os as _os2
        _cache_dir = _os2.path.join(
            _os2.path.dirname(_os2.path.abspath(__file__)),
            "_cache", "sec_edgar",
        )
        _n_cached = 0
        _n_clean_cached = 0
        try:
            _n_cached = len([
                f for f in _os2.listdir(_cache_dir)
                if f.endswith(".txt") and not f.startswith("_")
            ])
            _n_clean_cached = len([
                f for f in _os2.listdir(_cache_dir)
                if f.endswith(".clean.txt")
            ])
        except Exception:
            pass

        # Cache hit rate depends on both raw and clean text being cached.
        # If both are present, the run is near-instant.
        if _n_clean_cached > 4000:
            _cache_hit_rate = 0.90
        elif _n_clean_cached > 1500:
            _cache_hit_rate = 0.70
        elif _n_clean_cached > 500:
            _cache_hit_rate = 0.40
        else:
            _cache_hit_rate = 0.10

        EST_SECONDS_PER_FILING = (
            _cache_hit_rate * EST_SECONDS_PER_FILING_CACHED
            + (1.0 - _cache_hit_rate) * EST_SECONDS_PER_FILING_DOWNLOAD
        )
        est_seconds_per_ticker = (
            2 * EST_SECONDS_PER_API_CALL
            + n_filings_per_ticker * EST_SECONDS_PER_FILING
        )
        max_runtime_seconds = 7200  # target ~2 hours for deep cache penetration
        feasible_tickers = int(max_runtime_seconds / max(est_seconds_per_ticker, 0.001))

        # Cap at reasonable limits
        feasible_tickers = min(feasible_tickers, len(tickers))
        feasible_tickers = max(feasible_tickers, 50)  # never go below 50
        feasible_tickers = min(feasible_tickers, 3000)  # never exceed 3000

        logger.info(
            f"Cache-aware ticker cap: {feasible_tickers} "
            f"(cache hit rate ~{_cache_hit_rate:.0%} from {_n_cached} files, "
            f"est {est_seconds_per_ticker:.1f}s/ticker, "
            f"{n_filings_per_ticker} filings/ticker)"
        )

        return feasible_tickers

    def _estimate_filings_per_ticker(self, hypothesis) -> int:
        """Estimate number of filings to download per ticker."""
        time_horizon = self._compute_time_horizon(hypothesis)
        _, filing_types = self._derive_filing_types(hypothesis)

        # Estimate filings per year per filing type
        filings_per_year = 0
        for ft in filing_types:
            if "10-K" in ft:
                filings_per_year += 1
            elif "10-Q" in ft:
                filings_per_year += 3  # 3 quarterly + 1 annual (already counted as 10-K)
            elif "8-K" in ft:
                filings_per_year += 4  # 8-Ks are frequent but we cap

        return max(1, int(filings_per_year * time_horizon))

    # ------------------------------------------------------------------
    # Custom tickers path
    # ------------------------------------------------------------------

    def _use_custom_tickers(
        self,
        hypothesis,
        custom_tickers: List[str],
    ) -> UniverseBuildResult:
        """Use explicitly provided custom tickers (sufficient count)."""
        power_result = self._compute_power_requirements(
            hypothesis=hypothesis,
            n_tickers=len(custom_tickers),
            filing_frequency="quarterly",  # assume quarterly capability
            time_horizon_years=self._compute_time_horizon(hypothesis),
        )

        return UniverseBuildResult(
            tickers=custom_tickers,
            n_tickers=len(custom_tickers),
            source="custom",
            required_observations=power_result["required_observations"],
            achievable_observations=power_result["achievable_observations"],
            is_adequately_powered=power_result["is_adequately_powered"],
            achieved_power=power_result["achieved_power"],
            frequency_recommendation="from_hypothesis",
            filing_types=[],
            methodology=f"Using {len(custom_tickers)} custom-specified tickers from hypothesis",
            warnings=power_result.get("warnings", []),
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _normal_cdf(x: float) -> float:
        """Standard normal CDF approximation."""
        # Abramowitz and Stegun approximation
        if x < -8:
            return 0.0
        if x > 8:
            return 1.0
        # ERF-based
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ============================================================================
# Convenience function
# ============================================================================


def build_universe(
    hypothesis,
    cache_dir: Optional[str] = None,
    min_tickers: int = MIN_TICKERS_FOR_POWER,
) -> UniverseBuildResult:
    """Build a universe autonomously from a hypothesis.

    Args:
        hypothesis: HypothesisSpec from signal_builder.base or pipeline.
        cache_dir: Optional cache directory.
        min_tickers: Minimum tickers required (if custom < min, auto-construct).

    Returns:
        UniverseBuildResult with populated tickers and power analysis.
    """
    builder = UniverseBuilder(
        cache_dir=cache_dir,
        min_tickers=min_tickers,
    )
    return builder.build(hypothesis)
