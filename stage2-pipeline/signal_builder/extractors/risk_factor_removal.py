"""
risk_factor_removal.py — Risk Factor Removal Extractor
=======================================================

Detects risk factors that were present in a company's prior 10-K but
absent from the current 10-K. The market treats risk factor removal as
positive (fewer disclosed risks), but some removals are "dirty" —
management deleting risks that subsequently materialize.

Approach: deterministic text comparison of sequential 10-K Item 1A
sections. Groups filings by ticker, pairs sequential 10-Ks, extracts
risk factor items, and computes removal scores.

Signal = risk_factor_removal_score (higher = more removals = bearish).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .linguistic import SignalExtractor
from ..base import RawData, SignalData, SignalMetadata

logger = logging.getLogger(__name__)

# ── Risk factor item extraction ─────────────────────────────────────
# Risk factors in Item 1A are typically structured as:
#   - Numbered items: "1. ", "  1) ", "(1) "
#   - Bullet points: "• ", "  - ", "  * "
#   - Bold headings followed by paragraphs
#   - Paragraphs separated by blank lines or indentation

_ITEM_START_RE = re.compile(
    r'(?:^|\n)\s*'
    r'(?:'
    r'(?:\(\d{1,2}\)|\d{1,2}[.)]\s)'         # (1) or 1. or 1)
    r'|'
    r'(?:[•\-*]\s)'                              # bullet
    r'|'
    r'(?:(?:Risk|Factor|Item)\s+(?:relating|Related|Regarding))'  # named
    r')',
    re.IGNORECASE,
)

# Sub-heading patterns within risk factors that indicate a separate risk
_SUBHEAD_RE = re.compile(
    r'(?:^|\n)\s*(?:'
    r'(?:Risks?\s+(?:Related|Relating|Associated|from|of))'
    r'|'
    r'(?:(?:Legal|Regulatory|Operational|Financial|Market|Competition|'
    r'Cybersecurity|Technology|Supply\s*Chain|Macroeconomic|'
    r'Environmental|Climate|Reputation|Strategic|Compliance|'
    r'Litigation|Intellectual\s*Property|Data\s*Privacy|'
    r'Foreign\s*Exchange|Interest\s*Rate|Credit|Liquidity)'
    r'\s+Risks?)'
    r')',
    re.IGNORECASE,
)

# Patterns to strip: page headers, "Table of Contents", section numbers
_CLEANUP_RE = re.compile(
    r'(?:Table\s+of\s+Contents|ITEM\s+1A|RISK\s+FACTORS|'
    r'^\s*\d+\s*$|'
    r'Page\s+\d+)',
    re.IGNORECASE | re.MULTILINE,
)


def _split_risk_factors(text: str) -> List[str]:
    """Split a risk factors section into individual risk factor items.

    Uses heading patterns, numbered items, and paragraph breaks to
    identify risk factor boundaries. Returns a list of risk factor
    text blocks (trimmed, non-empty).
    """
    if not text or not isinstance(text, str):
        return []

    # Clean up (preserve newlines for item boundary detection)
    text = _CLEANUP_RE.sub(" ", text)
    text = re.sub(r'\n{3,}', '\n\n', text)   # collapse multiple newlines
    text = re.sub(r'[ \t]{2,}', ' ', text)   # collapse multiple spaces/tabs only

    # Strategy: find all potential section breaks
    # 1. Numbered items: (1), 1., 1)
    # 2. Bold/marked headings
    # 3. Double newlines (paragraph breaks)

    # First try: split on numbered/bulleted risk items
    splits = list(_ITEM_START_RE.finditer(text))
    if len(splits) >= 3:
        items = []
        for i, m in enumerate(splits):
            start = m.start()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
            item_text = text[start:end].strip()
            if len(item_text) >= 50:  # minimum viable risk factor
                items.append(item_text)
        if len(items) >= 3:
            return items

    # Second try: split on sub-headings
    splits = list(_SUBHEAD_RE.finditer(text))
    if len(splits) >= 3:
        items = []
        for i, m in enumerate(splits):
            start = m.start()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
            item_text = text[start:end].strip()
            if len(item_text) >= 50:
                items.append(item_text)
        if len(items) >= 3:
            return items

    # Fallback: split on paragraph breaks
    paras = [p.strip() for p in text.split('\n\n') if len(p.strip()) >= 100]
    if len(paras) >= 5:
        return paras

    return []


def _compute_risk_similarity(risk_a: str, risk_b: str) -> float:
    """Compute word-overlap similarity between two risk factor texts.

    Uses Jaccard similarity on significant words (≥4 chars).
    Returns 0.0 to 1.0.
    """
    def _words(s: str) -> set:
        return {w.lower() for w in re.findall(r'[a-z]{4,}', s.lower())}

    wa = _words(risk_a)
    wb = _words(risk_b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _detect_removed_risks(
    old_risks: List[str],
    new_risks: List[str],
    sim_threshold: float = 0.15,
) -> Tuple[int, int, int, List[float]]:
    """Detect which old risk factors were removed in the new filing.

    A risk factor is "removed" if its maximum similarity to any risk
    factor in the new filing is below sim_threshold.

    Returns:
        (n_removed, n_unchanged, n_added, removal_scores)
    """
    if not old_risks or not new_risks:
        return 0, 0, 0, []

    # Build similarity matrix
    sim_matrix = np.zeros((len(old_risks), len(new_risks)))
    for i, old_r in enumerate(old_risks):
        for j, new_r in enumerate(new_risks):
            sim_matrix[i, j] = _compute_risk_similarity(old_r, new_r)

    # Each old risk: max similarity to any new risk
    max_sims = sim_matrix.max(axis=1)
    removed_mask = max_sims < sim_threshold
    n_removed = int(removed_mask.sum())
    n_unchanged = len(old_risks) - n_removed

    # Added risks: new risks with low similarity to ALL old risks
    max_old_sims = sim_matrix.max(axis=0)
    n_added = int((max_old_sims < sim_threshold).sum())

    removal_scores = [float(1.0 - s) for s in max_sims]  # 1.0 = completely novel

    return n_removed, n_unchanged, n_added, removal_scores


class RiskFactorRemovalExtractor(SignalExtractor):
    """Extract risk factor removal signal from sequential 10-K pairs.

    Groups 10-K filings by ticker, pairs sequential filings, and
    detects risk factors present in the prior filing but absent from
    the current filing.
    """

    MIN_PAIR_OBSERVATIONS = 3
    MIN_SIM_THRESHOLD = 0.15

    @property
    def extractor_name(self) -> str:
        return "risk_factor_removal"

    @property
    def version(self) -> str:
        return "1.0.0"

    def __init__(self, sim_threshold: float = 0.15):
        self._sim_threshold = sim_threshold

    # ── Main extraction ─────────────────────────────────────────────

    def extract(
        self,
        raw_data: RawData,
        params: Optional[Dict[str, Any]] = None,
    ) -> SignalData:
        params = params or {}
        signal_name = params.get("signal_name", "risk_factor_removal_score")
        higher_is_better = params.get("higher_is_better", False)

        df = raw_data.records.copy()

        # Need risk_factors_text and filing metadata
        if "risk_factors_text" not in df.columns:
            logger.warning(
                "RiskFactorRemoval: no risk_factors_text column — "
                "using full_text as fallback"
            )
            if "full_text" in df.columns:
                df["risk_factors_text"] = df["full_text"]
            else:
                return self._empty_signal(signal_name)

        # Filter to 10-K only
        if "form_type" in df.columns:
            df = df[df["form_type"].str.upper().str.strip().isin(["10-K", "10-K/A"])].copy()
            if df.empty:
                logger.info("RiskFactorRemoval: no 10-K filings in data")
                return self._empty_signal(signal_name)

        # Must have filing_date for pairing
        if "filing_date" not in df.columns:
            logger.warning("RiskFactorRemoval: no filing_date column")
            return self._empty_signal(signal_name)

        df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
        df = df.dropna(subset=["filing_date", "risk_factors_text"])

        # Filter to rows with substantive risk factor sections
        df = df[df["risk_factors_text"].str.len() >= 500].copy()

        n_tickers = df["ticker"].nunique() if "ticker" in df.columns else 0
        logger.info(
            f"RiskFactorRemoval: {len(df)} 10-K filings across "
            f"{n_tickers} tickers"
        )

        if df.empty or n_tickers < self.MIN_PAIR_OBSERVATIONS:
            logger.info(
                "RiskFactorRemoval: insufficient data for pairing"
            )
            return self._empty_signal(signal_name)

        # Group by ticker, sort by filing_date, create sequential pairs
        signal_rows = []

        for ticker, grp in df.groupby("ticker"):
            grp = grp.sort_values("filing_date")
            if len(grp) < 2:
                continue

            # Extract risk items for each filing in this ticker's history
            # (cached per filing to avoid re-processing)
            ticker_risk_items: Dict[int, List[str]] = {}
            for idx, row in grp.iterrows():
                items = _split_risk_factors(str(row["risk_factors_text"]))
                if len(items) >= 3:
                    ticker_risk_items[idx] = items

            if len(ticker_risk_items) < 2:
                continue

            # Pair sequential filings that both have extractable risk items
            indices_with_items = list(ticker_risk_items.keys())
            for i in range(len(indices_with_items) - 1):
                old_idx = indices_with_items[i]
                new_idx = indices_with_items[i + 1]

                old_items = ticker_risk_items[old_idx]
                new_items = ticker_risk_items[new_idx]

                n_removed, n_unchanged, n_added, removal_scores = \
                    _detect_removed_risks(old_items, new_items, self._sim_threshold)

                new_row = grp.loc[new_idx]

                # Composite score: removed risk factors weighted by
                # how completely they were removed (1-similarity to best match)
                removal_score = float(np.mean(removal_scores)) if removal_scores else 0.0
                weighted_score = n_removed * removal_score

                signal_rows.append({
                    "signal_date": pd.Timestamp(new_row["filing_date"]),
                    "ticker": ticker,
                    signal_name: round(weighted_score, 6),
                    "n_removed": n_removed,
                    "n_added": n_added,
                    "n_unchanged": n_unchanged,
                    "n_old_items": len(old_items),
                    "n_new_items": len(new_items),
                    "mean_removal_similarity": round(float(1.0 - removal_score), 4),
                })

        if not signal_rows:
            logger.info(
                "RiskFactorRemoval: no 10-K pairs with extractable risk factors"
            )
            return self._empty_signal(signal_name)

        signal_df = pd.DataFrame(signal_rows)
        signal_df["signal_date"] = pd.to_datetime(signal_df["signal_date"])

        n_tickers_out = signal_df["ticker"].nunique()
        n_signals = len(signal_df)
        mean_score = signal_df[signal_name].mean()

        logger.info(
            f"RiskFactorRemoval: {n_signals} signal events across "
            f"{n_tickers_out} tickers. "
            f"Mean removal score: {mean_score:.4f}. "
            f"Mean removed per pair: {signal_df['n_removed'].mean():.1f}"
        )

        # Pivot to wide format
        wide_df = signal_df.pivot_table(
            index="signal_date", columns="ticker",
            values=signal_name, aggfunc="first",
        )
        wide_df.index = pd.DatetimeIndex(wide_df.index)

        return SignalData(
            df=wide_df,
            long_format=signal_df.copy(),
            metadata=SignalMetadata(
                extractor_name=self.extractor_name,
                extractor_version=self.version,
                extractor_method="deterministic",
                parameters={
                    "signal_name": signal_name,
                    "sim_threshold": self._sim_threshold,
                    "method": "sequential_10k_pair_diff",
                    "n_tickers": n_tickers_out,
                    "n_signals": n_signals,
                    "mean_n_removed": float(signal_df["n_removed"].mean()),
                    "mean_n_added": float(signal_df["n_added"].mean()),
                },
            ),
        )

    # ── Validation ───────────────────────────────────────────────────

    def validate_signal(
        self, signal: SignalData,
    ) -> Tuple[bool, List[str]]:
        issues = []
        df = signal.df if hasattr(signal, 'df') else signal

        if df is None or (hasattr(df, 'empty') and df.empty):
            issues.append("Signal DataFrame is empty")
            return False, issues

        if not isinstance(df, pd.DataFrame):
            issues.append(f"Signal is not a DataFrame: {type(df)}")
            return False, issues

        n_non_nan = int((~df.isna()).sum().sum())
        if n_non_nan < 3:
            issues.append(
                f"Too few non-NaN signal values ({n_non_nan})"
            )
            return False, issues

        return True, issues

    # ── Helpers ──────────────────────────────────────────────────────

    def _empty_signal(self, signal_name: str) -> SignalData:
        return SignalData(
            df=pd.DataFrame(),
            metadata=SignalMetadata(
                extractor_name=self.extractor_name,
                extractor_version=self.version,
                extractor_method="deterministic",
                parameters={"signal_name": signal_name, "empty": True},
            ),
        )
