"""
survivorship.py — Survivorship Bias Guard
==========================================

Detects, documents, and quantifies survivorship bias in backtest universes.

The problem: A backtest that only includes currently traded stocks misses
every company that went to zero, systematically inflating returns. Without
delisted stock inclusion, verdicts can have the wrong sign.

Core capabilities:
  1. Delisted stock detection (SEC Form 25, Form 15)
  2. Delisting return estimation by reason (bankruptcy, acquisition, etc.)
  3. Universe validation: verify full universe includes delisted stocks
  4. Bias impact estimation: quantify return inflation from survivor-only data
  5. Confidence capping: if delisted data is missing, cap verdict appropriately
  6. Ticker reuse detection: CIK-based verification of ticker identity over time

Integration: Called by SignalBuilder and Pipeline during universe construction.
Results are embedded in signal file metadata AND the pipeline audit trail.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class DelistingReason(str, Enum):
    BANKRUPTCY = "bankruptcy"
    ACQUISITION = "acquisition"
    EXCHANGE_DELISTING = "exchange_delisting"  # Moved to OTC
    GOING_PRIVATE = "going_private"
    MERGER = "merger"
    REGULATORY = "regulatory"
    VOLUNTARY = "voluntary"
    UNKNOWN = "unknown"


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass
class DelistedStock:
    """Record of a delisted stock with estimated delisting return."""

    ticker: str
    cik: str = ""
    company_name: str = ""
    delisting_date: str = ""          # YYYY-MM-DD
    reason: DelistingReason = DelistingReason.UNKNOWN
    last_traded_price: Optional[float] = None
    last_traded_date: str = ""
    estimated_delisting_return: Optional[float] = None  # e.g., -1.0 = total loss
    return_estimation_method: str = ""  # e.g., "last_price_to_zero", "acquisition_premium"
    return_uncertainty: str = "LOW"     # LOW | MEDIUM | HIGH
    form_type: str = ""                 # "25" or "15"
    source: str = ""                    # "sec_edgar", "yahoo", "manual"
    notes: str = ""
    data_gaps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["reason"] = self.reason.value if isinstance(self.reason, DelistingReason) else self.reason
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DelistedStock":
        reason = d.get("reason", "unknown")
        if isinstance(reason, str):
            try:
                reason = DelistingReason(reason)
            except ValueError:
                reason = DelistingReason.UNKNOWN
        return cls(
            ticker=d.get("ticker", ""),
            cik=d.get("cik", ""),
            company_name=d.get("company_name", ""),
            delisting_date=d.get("delisting_date", ""),
            reason=reason,
            last_traded_price=d.get("last_traded_price"),
            last_traded_date=d.get("last_traded_date", ""),
            estimated_delisting_return=d.get("estimated_delisting_return"),
            return_estimation_method=d.get("return_estimation_method", ""),
            return_uncertainty=d.get("return_uncertainty", "LOW"),
            form_type=d.get("form_type", ""),
            source=d.get("source", ""),
            notes=d.get("notes", ""),
            data_gaps=d.get("data_gaps", []),
        )


@dataclass
class SurvivorshipBiasReport:
    """Complete survivorship bias assessment."""

    # Universe composition
    total_tickers_in_universe: int = 0
    active_tickers: int = 0
    delisted_tickers: int = 0
    delisted_with_returns: int = 0
    delisted_missing_returns: int = 0

    # Bias impact
    survivor_only_annualized_return_bps: Optional[float] = None
    full_universe_annualized_return_bps: Optional[float] = None
    survivorship_bias_bps: Optional[float] = None  # Positive = survivor-only inflated
    bias_assessment: str = "NOT_COMPUTED"  # NEGLIGIBLE | MODERATE | SIGNIFICANT | NOT_COMPUTED

    # Confidence
    verdict_confidence_cap: str = "NONE"  # NONE | INCONCLUSIVE | SURVIVED_WARNING
    can_test_reliably: bool = True

    # Ticker reuse
    ticker_reuse_events: List[Dict[str, str]] = field(default_factory=list)
    n_ticker_reuse_events: int = 0

    # Delisted stock registry
    delisted_stocks: List[DelistedStock] = field(default_factory=list)

    # Data quality
    data_completeness: str = "FULL"  # FULL | PARTIAL | MINIMAL | NONE
    warnings: List[str] = field(default_factory=list)
    universe_period: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["delisted_stocks"] = [ds.to_dict() if hasattr(ds, 'to_dict') else ds for ds in self.delisted_stocks]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SurvivorshipBiasReport":
        stocks = []
        for ds in d.get("delisted_stocks", []):
            if isinstance(ds, DelistedStock):
                stocks.append(ds)
            else:
                stocks.append(DelistedStock.from_dict(ds))
        return cls(
            total_tickers_in_universe=d.get("total_tickers_in_universe", 0),
            active_tickers=d.get("active_tickers", 0),
            delisted_tickers=d.get("delisted_tickers", 0),
            delisted_with_returns=d.get("delisted_with_returns", 0),
            delisted_missing_returns=d.get("delisted_missing_returns", 0),
            survivor_only_annualized_return_bps=d.get("survivor_only_annualized_return_bps"),
            full_universe_annualized_return_bps=d.get("full_universe_annualized_return_bps"),
            survivorship_bias_bps=d.get("survivorship_bias_bps"),
            bias_assessment=d.get("bias_assessment", "NOT_COMPUTED"),
            verdict_confidence_cap=d.get("verdict_confidence_cap", "NONE"),
            can_test_reliably=d.get("can_test_reliably", True),
            ticker_reuse_events=d.get("ticker_reuse_events", []),
            n_ticker_reuse_events=d.get("n_ticker_reuse_events", 0),
            delisted_stocks=stocks,
            data_completeness=d.get("data_completeness", "FULL"),
            warnings=d.get("warnings", []),
            universe_period=d.get("universe_period", ""),
        )


# ============================================================================
# SurvivorshipGuard
# ============================================================================


class SurvivorshipGuard:
    """Guard against survivorship bias in backtest universes.

    Detects delisted stocks, estimates delisting returns, validates
    universe construction, and quantifies the bias impact.

    Usage:
        guard = SurvivorshipGuard()
        report = guard.validate_universe(
            universe_df, start_date, end_date,
            universe_type="sp500"
        )
        # Check report.can_test_reliably for go/no-go
    """

    # Known delisting thresholds by universe type
    # Smaller universes have fewer delistings, making bias more detectable
    UNIVERSE_SIZE_THRESHOLDS = {
        "sp500": 500,
        "sp1500": 1500,
        "russell3000": 3000,
        "all_us": 6000,
        "custom": None,
    }

    # Default delisting returns by reason (conservative estimates)
    DEFAULT_DELISTING_RETURNS = {
        DelistingReason.BANKRUPTCY: -0.95,          # 95% loss (some recovery possible)
        DelistingReason.ACQUISITION: None,           # Must be fetched from M&A data
        DelistingReason.EXCHANGE_DELISTING: None,    # Would need OTC data
        DelistingReason.GOING_PRIVATE: None,         # Must be fetched from buyout price
        DelistingReason.MERGER: None,                 # Must be fetched from merger data
        DelistingReason.REGULATORY: -0.90,           # Severe but not total loss
        DelistingReason.VOLUNTARY: None,              # Context-dependent
        DelistingReason.UNKNOWN: -0.50,              # Highly uncertain
    }

    def __init__(
        self,
        fmp_api_key: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ):
        self._fmp_api_key = fmp_api_key
        self._cache_dir = cache_dir
        self._delisted_registry: List[DelistedStock] = []
        self._loaded_from_cache = False

    # ------------------------------------------------------------------
    # Main entry point: universe validation
    # ------------------------------------------------------------------

    def validate_universe(
        self,
        universe_df: pd.DataFrame,
        start_date: str,
        end_date: str,
        universe_type: str = "sp500",
        signal_df: Optional[pd.DataFrame] = None,
        price_df: Optional[pd.DataFrame] = None,
    ) -> SurvivorshipBiasReport:
        """Validate a backtest universe for survivorship bias.

        Args:
            universe_df: Universe DataFrame with ticker, date, is_delisted columns.
            start_date: Start of test period (YYYY-MM-DD).
            end_date: End of test period (YYYY-MM-DD).
            universe_type: Type of universe (sp500, all_us, custom).
            signal_df: Optional signal data for bias impact estimation.
            price_df: Optional price data for bias impact estimation.

        Returns:
            SurvivorshipBiasReport with complete assessment.
        """
        warnings: List[str] = []
        universe_period = f"{start_date} to {end_date}"

        # 1. Count universe composition
        total_tickers = 0
        active_tickers = 0
        delisted_tickers = 0

        if "ticker" in universe_df.columns:
            # Check for delisting flags
            if "is_delisted" in universe_df.columns:
                total_tickers = universe_df["ticker"].nunique()
                delisted_mask = universe_df["is_delisted"] == True  # noqa: E712
                delisted_set = set(universe_df.loc[delisted_mask, "ticker"].unique())
                active_set = set(universe_df.loc[~delisted_mask, "ticker"].unique()) if ~delisted_mask.any() else set()
                active_set -= delisted_set  # Active = never delisted
                delisted_tickers = len(delisted_set)
                active_tickers = total_tickers - delisted_tickers
            else:
                total_tickers = universe_df["ticker"].nunique()
                active_tickers = total_tickers
                warnings.append(
                    "Universe DataFrame missing 'is_delisted' column. "
                    "Cannot distinguish active vs. delisted. Assuming all active "
                    "(survivorship bias unchecked)."
                )
        else:
            total_tickers = len(universe_df)
            warnings.append("Universe DataFrame missing 'ticker' column.")

        # 2. Load delisted stock registry
        delisted_stocks = self._get_delisted_stocks(
            start_date, end_date, universe_type
        )

        # 3. Check data completeness
        delisted_with_returns = sum(
            1 for ds in delisted_stocks
            if ds.estimated_delisting_return is not None
        )
        delisted_missing = len(delisted_stocks) - delisted_with_returns

        if delisted_missing > 0:
            warnings.append(
                f"{delisted_missing}/{len(delisted_stocks)} delisted stocks "
                f"have missing return estimates."
            )

        # Determine data completeness
        if len(delisted_stocks) == 0:
            data_completeness = "FULL"  # No delistings in period
        elif delisted_missing == 0:
            data_completeness = "FULL"
        elif delisted_missing <= delisted_with_returns:
            data_completeness = "PARTIAL"
        elif delisted_with_returns > 0:
            data_completeness = "MINIMAL"
        else:
            data_completeness = "NONE"

        if data_completeness == "NONE" and delisted_stocks:
            warnings.append(
                "CRITICAL: No delisting return data available for any delisted stock. "
                "Survivorship bias cannot be quantified."
            )

        # 4. Estimate bias impact
        bias_bps = None
        survivor_return = None
        full_return = None
        bias_assessment = "NOT_COMPUTED"

        if signal_df is not None and price_df is not None and not signal_df.empty:
            try:
                survivor_return, full_return, bias_bps = self._estimate_bias_impact(
                    universe_df, signal_df, price_df, delisted_stocks
                )
                bias_assessment = self._classify_bias(bias_bps, universe_type)
            except Exception as e:
                logger.warning(f"Bias impact estimation failed: {e}")
                warnings.append(f"Bias impact estimation error: {e}")
        else:
            bias_assessment = self._classify_bias_from_counts(
                active_tickers, delisted_tickers, universe_type
            )

        # 5. Check ticker reuse
        ticker_reuse_events = self._detect_ticker_reuse(universe_df)
        n_reuse = len(ticker_reuse_events)
        if n_reuse > 0:
            warnings.append(
                f"TICKER REUSE DETECTED: {n_reuse} instances where a ticker symbol "
                f"may refer to different companies over time."
            )

        # 6. Determine confidence cap
        confidence_cap = "NONE"
        can_test = True

        if data_completeness == "NONE" and delisted_tickers > 0:
            # No delisting return data at all
            universe_size = self.UNIVERSE_SIZE_THRESHOLDS.get(universe_type, 0) or total_tickers
            if universe_size >= 500:
                # Large universe: survivorship bias affects every stock.
                # Without delisted returns, cannot be confident.
                confidence_cap = "INCONCLUSIVE"
                can_test = False
                warnings.append(
                    f"CONFIDENCE CAPPED TO INCONCLUSIVE: Universe size ({universe_size}) "
                    f"requires delisted stock data to control survivorship bias. "
                    f"No delisting return data available for any of {len(delisted_stocks)} "
                    f"delisted stocks."
                )
            elif universe_size < 500:
                # Smaller universe: survivorship bias may be manageable
                confidence_cap = "SURVIVED_WARNING"
                warnings.append(
                    f"Universe size ({universe_size}) < 500. Survivorship bias may be "
                    f"less severe, but {len(delisted_stocks)} delisted stocks lack return "
                    f"data. Results should be treated with caution."
                )
        elif data_completeness == "MINIMAL" and delisted_tickers > 5:
            confidence_cap = "SURVIVED_WARNING"
            warnings.append(
                f"MINIMAL delisting return data (only {delisted_with_returns}/{len(delisted_stocks)} "
                f"stocks have return estimates). Survivorship bias estimate is uncertain."
            )
        elif ticker_reuse_events:
            confidence_cap = "SURVIVED_WARNING"

        # 7. Assemble report
        report = SurvivorshipBiasReport(
            total_tickers_in_universe=total_tickers,
            active_tickers=active_tickers,
            delisted_tickers=delisted_tickers,
            delisted_with_returns=delisted_with_returns,
            delisted_missing_returns=delisted_missing,
            survivor_only_annualized_return_bps=survivor_return,
            full_universe_annualized_return_bps=full_return,
            survivorship_bias_bps=bias_bps,
            bias_assessment=bias_assessment,
            verdict_confidence_cap=confidence_cap,
            can_test_reliably=can_test,
            ticker_reuse_events=ticker_reuse_events,
            n_ticker_reuse_events=n_reuse,
            delisted_stocks=delisted_stocks,
            data_completeness=data_completeness,
            warnings=warnings,
            universe_period=universe_period,
        )

        # Log summary
        logger.info(
            f"SurvivorshipGuard: {total_tickers} tickers ({active_tickers} active, "
            f"{delisted_tickers} delisted) | Bias: {bias_assessment} | "
            f"Confidence cap: {confidence_cap} | "
            f"Reliable: {can_test}"
        )

        return report

    # ------------------------------------------------------------------
    # Delisted stock registry
    # ------------------------------------------------------------------

    def _get_delisted_stocks(
        self,
        start_date: str,
        end_date: str,
        universe_type: str,
    ) -> List[DelistedStock]:
        """Retrieve delisted stocks for the universe period.

        Attempts SEC EDGAR lookup first, then falls back to a built-in
        registry of known major delistings.
        """
        # Try loading from cache first
        if self._loaded_from_cache:
            return self._delisted_registry

        delisted = []

        # Attempt SEC EDGAR lookup for Form 25/15 filings
        try:
            edgar_delisted = self._query_sec_edgar_delistings(start_date, end_date)
            delisted.extend(edgar_delisted)
        except Exception as e:
            logger.debug(f"SEC EDGAR delisting query failed (non-fatal): {e}")

        # Supplement with known delistings from built-in registry
        known = self._get_known_delistings(start_date, end_date, universe_type)
        existing_tickers = {d.ticker.upper() for d in delisted}
        for k in known:
            if k.ticker.upper() not in existing_tickers:
                delisted.append(k)

        # Estimate missing returns
        for ds in delisted:
            if ds.estimated_delisting_return is None:
                self._estimate_delisting_return(ds)

        self._delisted_registry = delisted
        self._loaded_from_cache = True

        logger.info(
            f"Delisted stock registry: {len(delisted)} stocks "
            f"({sum(1 for d in delisted if d.estimated_delisting_return is not None)} "
            f"with return estimates)"
        )

        return delisted

    def _query_sec_edgar_delistings(
        self, start_date: str, end_date: str
    ) -> List[DelistedStock]:
        """Query SEC EDGAR for Form 25 and Form 15 filings.

        Form 25: Notification of removal from listing and/or registration.
        Form 15: Certification and notice of termination of registration.
        """
        delisted = []

        try:
            import requests

            # SEC EDGAR full-text search for Form 25
            # This uses the SEC's submissions API
            start = start_date.replace("-", "")
            end = end_date.replace("-", "")

            for form_type in ["25", "15"]:
                url = (
                    f"https://efts.sec.gov/LATEST/search-index?dateRange=custom"
                    f"&startdt={start}&enddt={end}"
                    f"&forms={form_type}"
                )
                # Note: SEC EDGAR full-text search has rate limits and may require
                # user-agent headers. The free tier is limited.
                try:
                    headers = {
                        "User-Agent": "TradeFinder/1.0 (retail research; contact@example.com)",
                        "Accept": "application/json",
                    }
                    resp = requests.get(url, headers=headers, timeout=30)
                    if resp.status_code == 200:
                        data = resp.json()
                        hits = data.get("hits", {}).get("hits", [])
                        for hit in hits:
                            source = hit.get("_source", {})
                            cik = source.get("cik", "")
                            company = source.get("company_name", "")
                            filing_date = source.get("file_date", "")[:10]

                            # Determine reason from form description
                            reason = self._infer_delisting_reason(
                                source.get("form_description", ""),
                                source.get("items_desc", ""),
                            )

                            delisted.append(DelistedStock(
                                ticker="",  # Ticker not directly available; needs CIK mapping
                                cik=str(cik),
                                company_name=company,
                                delisting_date=filing_date,
                                reason=reason,
                                form_type=form_type,
                                source="sec_edgar",
                                data_gaps=["Ticker symbol not in SEC EDGAR hit; needs CIK mapping"],
                            ))
                except Exception as e:
                    logger.debug(f"SEC EDGAR form {form_type} query: {e}")

        except ImportError:
            logger.debug("requests not installed; skipping SEC EDGAR query")
        except Exception as e:
            logger.debug(f"SEC EDGAR delisting query: {e}")

        return delisted

    def _get_known_delistings(
        self, start_date: str, end_date: str, universe_type: str
    ) -> List[DelistedStock]:
        """Return a built-in registry of known major delistings.

        This is a static reference set for well-known delistings that
        affect retail universes. It is NOT exhaustive — it covers the
        largest, most impactful delistings that would most distort
        survivorship-biased backtests.

        In production, this registry would be maintained and updated
        from SEC EDGAR data dumps.
        """
        # This is a reference set for pipeline testing, not exhaustive data
        # Major delistings 2018-2025 from S&P 500 / large-cap space
        known = [
            # Bankruptcy / distress
            DelistedStock(
                ticker="GE", cik="", company_name="General Electric (restructured)",
                delisting_date="2024-04-02", reason=DelistingReason.REGULATORY,
                estimated_delisting_return=None,
                return_estimation_method="", notes="GE Vernova spin-off; old GE entity restructured",
            ),
            DelistedStock(
                ticker="HTZ", cik="", company_name="Hertz Global Holdings",
                delisting_date="2020-10-30", reason=DelistingReason.BANKRUPTCY,
                estimated_delisting_return=-0.95,
                return_estimation_method="bankruptcy_zero_recovery",
            ),
            DelistedStock(
                ticker="JCP", cik="", company_name="JCPenney",
                delisting_date="2020-05-15", reason=DelistingReason.BANKRUPTCY,
                estimated_delisting_return=-0.95,
                return_estimation_method="bankruptcy_zero_recovery",
            ),
            # Acquisitions
            DelistedStock(
                ticker="SIVB", cik="", company_name="SVB Financial Group",
                delisting_date="2023-03-10", reason=DelistingReason.REGULATORY,
                estimated_delisting_return=-0.90,
                return_estimation_method="receivership_estimate",
            ),
            DelistedStock(
                ticker="FRC", cik="", company_name="First Republic Bank",
                delisting_date="2023-05-01", reason=DelistingReason.REGULATORY,
                estimated_delisting_return=-0.85,
                return_estimation_method="fdic_receivership_estimate",
            ),
            DelistedStock(
                ticker="TWTR", cik="", company_name="Twitter Inc.",
                delisting_date="2022-10-28", reason=DelistingReason.GOING_PRIVATE,
                estimated_delisting_return=None,
                return_estimation_method="",
                notes="Taken private at $54.20/sh. Return depends on entry price.",
            ),
        ]

        # Filter to period
        period_start = pd.Timestamp(start_date)
        period_end = pd.Timestamp(end_date)

        filtered = []
        for ds in known:
            try:
                ds_date = pd.Timestamp(ds.delisting_date)
                if period_start <= ds_date <= period_end:
                    filtered.append(ds)
            except Exception:
                filtered.append(ds)  # Include if date can't be parsed

        return filtered

    def _infer_delisting_reason(
        self, form_description: str, items_desc: str
    ) -> DelistingReason:
        """Infer delisting reason from SEC form metadata."""
        combined = (form_description + " " + items_desc).lower()
        if "bankrupt" in combined or "chapter 11" in combined:
            return DelistingReason.BANKRUPTCY
        if "acquisition" in combined or "acquired" in combined:
            return DelistingReason.ACQUISITION
        if "merger" in combined:
            return DelistingReason.MERGER
        if "exchange" in combined and ("delist" in combined or "remov" in combined):
            return DelistingReason.EXCHANGE_DELISTING
        if "going private" in combined or "private transaction" in combined:
            return DelistingReason.GOING_PRIVATE
        if "regulatory" in combined or "sec" in combined:
            return DelistingReason.REGULATORY
        if "voluntary" in combined:
            return DelistingReason.VOLUNTARY
        return DelistingReason.UNKNOWN

    def _estimate_delisting_return(self, stock: DelistedStock) -> None:
        """Estimate the delisting return for a stock if not already set.

        Uses conservative default returns by delisting reason.
        For acquisition/merger/go-private events, the actual return
        depends on the transaction price and cannot be defaulted.
        """
        default = self.DEFAULT_DELISTING_RETURNS.get(stock.reason)

        if default is not None:
            stock.estimated_delisting_return = default
            stock.return_estimation_method = f"default_by_reason_{stock.reason.value}"
            stock.return_uncertainty = "HIGH" if stock.reason == DelistingReason.UNKNOWN else "MEDIUM"
        elif stock.reason in (DelistingReason.ACQUISITION, DelistingReason.MERGER, DelistingReason.GOING_PRIVATE):
            # These require transaction-specific data
            stock.estimated_delisting_return = None
            stock.return_estimation_method = ""
            stock.return_uncertainty = "HIGH"
            stock.data_gaps.append(
                f"Acquisition/merger premium not available for {stock.ticker}. "
                f"Delisting return cannot be estimated without transaction data."
            )
        else:
            stock.estimated_delisting_return = None
            stock.return_estimation_method = "unable_to_estimate"
            stock.return_uncertainty = "HIGH"

    # ------------------------------------------------------------------
    # Bias impact estimation
    # ------------------------------------------------------------------

    def _estimate_bias_impact(
        self,
        universe_df: pd.DataFrame,
        signal_df: pd.DataFrame,
        price_df: pd.DataFrame,
        delisted_stocks: List[DelistedStock],
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Estimate the impact of survivorship bias on backtest returns.

        Computes two versions:
        1. Survivor-only: using only currently active tickers
        2. Full universe: including delisted stocks with estimated returns

        Returns:
            (survivor_return_bps, full_universe_return_bps, bias_bps)
        """
        # This is a comparative estimation, not a full backtest rerun.
        # The full backtest system (pipeline.py) handles the actual computation.
        # Here we estimate the magnitude of the bias.

        # 1. Identify survivor-only vs. full ticker sets
        if "is_delisted" not in universe_df.columns:
            return None, None, None

        survivor_tickers = set(
            universe_df.loc[~universe_df["is_delisted"], "ticker"].unique()
        )
        all_tickers = set(universe_df["ticker"].unique())
        delisted_tickers = all_tickers - survivor_tickers

        # 2. Compute survivor-only portfolio returns from signal
        signal_tickers = set(signal_df.columns) if isinstance(signal_df, pd.DataFrame) else set()
        survivor_signal_tickers = signal_tickers & survivor_tickers

        if len(survivor_signal_tickers) < 2:
            return None, None, None

        # Simple long-short: top vs. bottom quintile
        def compute_mean_spread(signal, tickers, holding_days=21):
            """Compute the mean return spread between top and bottom quintiles."""
            if tickers:
                cols = [t for t in tickers if t in signal.columns]
                if len(cols) >= 5:
                    signals_at_t = signal[cols].iloc[-1] if len(signal) > 0 else pd.Series()
                    if len(signals_at_t) >= 5:
                        n_top = max(1, len(cols) // 5)
                        top = signals_at_t.nlargest(n_top).index
                        bottom = signals_at_t.nsmallest(n_top).index

                        # Approximate alpha: signal spread
                        top_signal = signals_at_t[top].mean()
                        bottom_signal = signals_at_t[bottom].mean()
                        spread = top_signal - bottom_signal
                        # Convert spread to bps/day (rough scale)
                        return float(spread * 10)  # Heuristic
            return 0.0

        survivor_spread = compute_mean_spread(signal_df, survivor_signal_tickers)

        # 3. Adjust for delisted stocks
        delisting_penalty_bps = 0.0
        for ds in delisted_stocks:
            if ds.ticker.upper() in delisted_tickers and ds.estimated_delisting_return is not None:
                delisting_penalty_bps += abs(ds.estimated_delisting_return) * 10000 / max(len(all_tickers), 1)

        full_universe_spread = survivor_spread - delisting_penalty_bps

        # Annualize (heuristic)
        survivor_annual = survivor_spread * 252 if survivor_spread else None
        full_annual = full_universe_spread * 252 if full_universe_spread else None
        bias = (survivor_annual - full_annual) if (survivor_annual is not None and full_annual is not None) else None

        return survivor_annual, full_annual, bias

    def _classify_bias(self, bias_bps: Optional[float], universe_type: str) -> str:
        """Classify the severity of survivorship bias."""
        if bias_bps is None:
            return "NOT_COMPUTED"
        abs_bias = abs(bias_bps)
        if abs_bias < 10:
            return "NEGLIGIBLE"
        elif abs_bias < 50:
            return "MODERATE"
        elif abs_bias < 200:
            return "SIGNIFICANT"
        else:
            return "SEVERE"

    def _classify_bias_from_counts(
        self, active: int, delisted: int, universe_type: str
    ) -> str:
        """Classify bias severity when price data is not available."""
        if delisted == 0:
            return "NEGLIGIBLE"
        total = active + delisted
        delisted_pct = delisted / max(total, 1) * 100

        if delisted_pct < 1:
            return "NEGLIGIBLE"
        elif delisted_pct < 5:
            return "MODERATE"
        elif delisted_pct < 10:
            return "SIGNIFICANT"
        else:
            return "SEVERE"

    # ------------------------------------------------------------------
    # Ticker reuse detection
    # ------------------------------------------------------------------

    def _detect_ticker_reuse(
        self, universe_df: pd.DataFrame
    ) -> List[Dict[str, str]]:
        """Detect instances where a ticker symbol may have been recycled.

        Uses CIK-to-ticker mapping to verify that the current company
        associated with a ticker matches the company that held that ticker
        during the test period.
        """
        reuse_events = []

        # Only check if we have CIK data
        if "cik" not in universe_df.columns and "entity_id" not in universe_df.columns:
            return reuse_events

        id_col = "cik" if "cik" in universe_df.columns else "entity_id"
        if "ticker" not in universe_df.columns or "company_name" not in universe_df.columns:
            return reuse_events

        # Group by ticker, check for multiple CIKs over time
        for ticker, group in universe_df.groupby("ticker"):
            # Get unique CIKs and company names
            unique_ciks = group[id_col].dropna().unique()
            unique_names = group["company_name"].dropna().unique()

            if len(unique_ciks) > 1:
                reuse_events.append({
                    "ticker": ticker,
                    "ciks": [str(c) for c in unique_ciks],
                    "companies": list(unique_names),
                    "detection": "Multiple CIKs associated with same ticker",
                })

        return reuse_events

    # ------------------------------------------------------------------
    # Universe reporting
    # ------------------------------------------------------------------

    def format_universe_report(self, report: SurvivorshipBiasReport) -> str:
        """Format a human-readable universe report string."""
        lines = [
            f"Universe at {report.universe_period}: "
            f"{report.total_tickers_in_universe} stocks "
            f"({report.active_tickers} active + {report.delisted_tickers} subsequently delisted)",
        ]

        if report.survivorship_bias_bps is not None:
            lines.append(
                f"Survivorship bias: {'inflates' if report.survivorship_bias_bps > 0 else 'deflates'} "
                f"annualized returns by ~{abs(report.survivorship_bias_bps):.0f} bps"
            )

        lines.append(f"Bias severity: {report.bias_assessment}")
        lines.append(f"Data completeness: {report.data_completeness}")

        if report.delisted_stocks:
            lines.append(f"Delisted stocks in period: {len(report.delisted_stocks)}")
            for ds in report.delisted_stocks[:5]:
                ret_str = (
                    f"{ds.estimated_delisting_return*100:.0f}%"
                    if ds.estimated_delisting_return is not None
                    else "UNKNOWN"
                )
                lines.append(
                    f"  - {ds.ticker} ({ds.reason.value}): est. return {ret_str} "
                    f"[{ds.return_uncertainty} uncertainty]"
                )
            if len(report.delisted_stocks) > 5:
                lines.append(f"  ... and {len(report.delisted_stocks) - 5} more")

        if report.ticker_reuse_events:
            lines.append(f"Ticker reuse events: {len(report.ticker_reuse_events)}")
            for event in report.ticker_reuse_events[:3]:
                lines.append(f"  - {event['ticker']}: {event['detection']}")

        for w in report.warnings:
            lines.append(f"WARNING: {w}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: SurvivorshipBiasReport, path: str) -> str:
        """Save survivorship bias report to JSON."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(report.to_dict(), f, indent=2, default=str)
        return path

    @classmethod
    def load_report(cls, path: str) -> SurvivorshipBiasReport:
        """Load a survivorship bias report from JSON."""
        with open(path, "r") as f:
            data = json.load(f)
        return SurvivorshipBiasReport.from_dict(data)

    # ------------------------------------------------------------------
    # Static utility: apply confidence cap
    # ------------------------------------------------------------------

    @staticmethod
    def cap_verdict(
        original_verdict: str,
        survivorship_report: SurvivorshipBiasReport,
    ) -> Tuple[str, str]:
        """Apply confidence capping based on survivorship bias assessment.

        Returns:
            (capped_verdict, reason_addition)
        """
        cap = survivorship_report.verdict_confidence_cap

        if cap == "INCONCLUSIVE":
            from signal_builder.base import Verdict
            capped = Verdict.INCONCLUSIVE.value
            reason_add = (
                f" | SURVIVORSHIP BIAS: Verdict capped to INCONCLUSIVE. "
                f"{survivorship_report.delisted_missing_returns}/{len(survivorship_report.delisted_stocks)} "
                f"delisted stocks have missing return estimates. "
                f"Bias assessment: {survivorship_report.bias_assessment}."
            )
            return capped, reason_add

        elif cap == "SURVIVED_WARNING":
            if original_verdict in ("SURVIVED", "SURVIVED_WARNING"):
                reason_add = (
                    f" | SURVIVORSHIP BIAS WARNING: "
                    f"{survivorship_report.delisted_missing_returns}/{len(survivorship_report.delisted_stocks)} "
                    f"delisted stocks have uncertain return estimates. "
                    f"Bias assessment: {survivorship_report.bias_assessment}. "
                    f"Results may be inflated."
                )
                return "SURVIVED_WARNING", reason_add
            return original_verdict, ""

        return original_verdict, ""
