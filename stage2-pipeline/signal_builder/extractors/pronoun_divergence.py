"""
pronoun_divergence.py — Pronoun Divergence Extractor
=====================================================
Deterministic PPR (Pronoun Participation Ratio) extraction from Q&A
transcript sections, with per-ticker rolling baseline computation.

PPR = count('we'|'us'|'our'|'ours'|'ourselves') / count(all pronouns)

Signal = baseline_p10 - current_ppr  (positive = PPR dropped = bearish)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .linguistic import SignalExtractor
from ..base import RawData, SignalData, SignalMetadata, SignalExtractionError

logger = logging.getLogger(__name__)

# ── Pronoun regex patterns ──────────────────────────────────────────
_WE_RE = re.compile(r'\b(we|us|our|ours|ourselves)\b', re.IGNORECASE)
_THEY_RE = re.compile(r'\b(they|them|their|theirs|themselves)\b', re.IGNORECASE)
_I_RE = re.compile(r'\b(I|me|my|mine|myself)\b', re.IGNORECASE)
_YOU_RE = re.compile(r'\b(you|your|yours|yourself|yourselves)\b', re.IGNORECASE)
_HE_SHE_RE = re.compile(
    r'\b(he|she|him|her|his|hers|himself|herself)\b', re.IGNORECASE,
)
_IT_RE = re.compile(r'\b(it|its|itself)\b', re.IGNORECASE)


def compute_ppr(text: str) -> Optional[Dict[str, Any]]:
    """Compute PPR and pronoun counts from a text segment.

    Returns None if total pronouns < 5 (insufficient signal).
    """
    if not text or not isinstance(text, str):
        return None

    we_forms = len(_WE_RE.findall(text))
    they_forms = len(_THEY_RE.findall(text))
    i_forms = len(_I_RE.findall(text))
    you_forms = len(_YOU_RE.findall(text))
    he_she = len(_HE_SHE_RE.findall(text))
    it_forms = len(_IT_RE.findall(text))

    total = we_forms + they_forms + i_forms + you_forms + he_she + it_forms
    if total < 5:
        return None

    ppr = we_forms / total
    return {
        "ppr": round(ppr, 4),
        "n_we_forms": we_forms,
        "n_total_pronouns": total,
        "n_i_forms": i_forms,
        "n_they_forms": they_forms,
    }


class PronounDivergenceExtractor(SignalExtractor):
    """Deterministic PPR extraction with per-ticker rolling baseline.

    Computes PPR from Q&A transcript sections, builds per-ticker
    historical baseline (10th percentile), and signals when PPR
    drops below baseline.
    """

    MIN_BASELINE_OBSERVATIONS = 2
    BASELINE_PERCENTILE = 10.0

    @property
    def extractor_name(self) -> str:
        return "pronoun_divergence"

    @property
    def version(self) -> str:
        return "1.0.0"

    # Q&A section start/end patterns for finding transcripts in raw filings
    _QA_START_RE = re.compile(
        r"\n\s*(?:Questions?\s*(?:and|&)\s*Answers?|"
        r"Q\s*&?\s*A\s*Session|"
        r"Conference\s*Call\s*(?:Q&A|Questions)|"
        r"Operator\b)",
        re.IGNORECASE,
    )
    _QA_END_RE = re.compile(
        r"\n\s*(?:Copyright\s+(?:©|\(c\))|"
        r"END\s*OF\s*(?:TRANSCRIPT|CALL)|"
        r"\n-{5,}|"
        r"This\s+transcript\s+is\s+provided\s+by)",
        re.IGNORECASE,
    )

    def __init__(self, min_qa_length: int = 200):
        self._min_qa_length = min_qa_length

    # ── Q&A extraction from raw filing text ──────────────────────

    @classmethod
    def _extract_qa_from_text(cls, full_text: str) -> Optional[str]:
        """Extract the Q&A portion from a raw 8-K filing that contains
        an earnings call transcript.

        Searches for Q&A section headers and the conference-call
        operator, then extracts text from that point onward until
        a copyright notice or end-of-transcript marker.
        """
        if not full_text or not isinstance(full_text, str):
            return None

        # Find the Q&A section start
        start_match = cls._QA_START_RE.search(full_text)
        if not start_match:
            return None

        start_pos = start_match.start()
        after_start = full_text[start_pos:]

        # Find the end marker within the extracted section
        # (skip the Q&A header itself for end detection — check
        #  at least 200 chars in so we don't match the header)
        search_from = max(200, len(after_start) // 5)
        end_match = cls._QA_END_RE.search(after_start[search_from:])
        if end_match:
            qa_text = after_start[: search_from + end_match.start()]
        else:
            # No end marker — take up to 50KB (reasonable max for Q&A)
            qa_text = after_start[:50_000]

        # Must have enough pronoun content
        if len(qa_text) < 500:
            return None

        return qa_text.strip()

    # ── Main extraction ──────────────────────────────────────────

    def extract(
        self,
        raw_data: RawData,
        params: Optional[Dict[str, Any]] = None,
    ) -> SignalData:
        params = params or {}
        signal_name = params.get("signal_name", "ppr_divergence")
        higher_is_better = params.get("higher_is_better", False)

        df = raw_data.records.copy()

        # Prefer pre-extracted qa_section; fall back to extracting from full_text
        if "qa_section" in df.columns:
            has_qa = (df["has_qa"] == True) if "has_qa" in df.columns else (
                df["qa_section"].notna() & (df["qa_section"].str.len() >= self._min_qa_length)
            )
            n_pre_extracted = has_qa.sum()
            if n_pre_extracted >= 3:
                logger.info(
                    f"PronounDivergence: Using {n_pre_extracted} pre-extracted "
                    "Q&A sections from TranscriptExtractor"
                )
                df = df[has_qa].copy()
                df["_qa_text"] = df["qa_section"]
            else:
                logger.info(
                    f"PronounDivergence: Only {n_pre_extracted} pre-extracted Q&A "
                    "sections — extracting from full_text"
                )
                df["_qa_text"] = df["full_text"].apply(self._extract_qa_from_text)
        else:
            logger.info("PronounDivergence: No qa_section column — extracting from full_text")
            df["_qa_text"] = df["full_text"].apply(self._extract_qa_from_text)

        # Filter to rows with usable Q&A text
        mask = df["_qa_text"].notna() & (df["_qa_text"].str.len() >= self._min_qa_length)
        df = df[mask].copy()
        if df.empty:
            logger.info(
                "PronounDivergence: No rows with sufficient Q&A text "
                f"(min {self._min_qa_length} chars), falling back to synthetic"
            )
            return self._empty_signal(signal_name)

        n_transcripts = len(df)
        n_tickers_total = df["ticker"].nunique() if "ticker" in df.columns else 0
        logger.info(
            f"PronounDivergence: Processing {n_transcripts} transcripts "
            f"across {n_tickers_total} tickers"
        )

        # Compute PPR for each row
        ppr_results = []
        for idx, row in df.iterrows():
            ppr_data = compute_ppr(str(row["_qa_text"]))
            if ppr_data is None:
                continue
            ppr_data["signal_date"] = row.get("filing_date", None)
            ppr_data["ticker"] = row.get("ticker", "")
            ppr_data["_row_index"] = idx
            ppr_results.append(ppr_data)

        if not ppr_results:
            logger.info(
                "PronounDivergence: No transcripts with sufficient pronouns, "
                "falling back to synthetic"
            )
            return self._empty_signal(signal_name)

        ppr_df = pd.DataFrame(ppr_results)
        ppr_df["signal_date"] = pd.to_datetime(ppr_df["signal_date"], errors="coerce")
        ppr_df = ppr_df.dropna(subset=["signal_date"]).sort_values("signal_date")

        logger.info(
            f"PronounDivergence: Computed PPR for {len(ppr_df)} transcripts "
            f"across {ppr_df['ticker'].nunique()} tickers"
        )

        # Compute per-ticker rolling baseline and divergence signal
        signal_rows = []
        for ticker, grp in ppr_df.groupby("ticker"):
            grp = grp.sort_values("signal_date")
            ppr_values = grp["ppr"].values
            dates = grp["signal_date"].values

            for i in range(len(grp)):
                if i < self.MIN_BASELINE_OBSERVATIONS:
                    continue
                # Expanding window: all prior observations for this ticker
                prior_ppr = ppr_values[:i]
                if len(prior_ppr) < self.MIN_BASELINE_OBSERVATIONS:
                    continue
                baseline_p10 = np.percentile(prior_ppr, self.BASELINE_PERCENTILE)
                current_ppr = ppr_values[i]
                divergence = baseline_p10 - current_ppr
                signal_rows.append({
                    "signal_date": pd.Timestamp(dates[i]),
                    "ticker": ticker,
                    signal_name: round(divergence, 6),
                    "ppr": round(current_ppr, 4),
                    "baseline_p10": round(baseline_p10, 4),
                    "n_prior_obs": len(prior_ppr),
                    "n_we_forms": int(grp.iloc[i]["n_we_forms"]),
                    "n_total_pronouns": int(grp.iloc[i]["n_total_pronouns"]),
                })

        if not signal_rows:
            logger.info(
                "PronounDivergence: Insufficient per-ticker history for "
                "baseline computation, falling back to synthetic"
            )
            return self._empty_signal(signal_name)

        signal_df = pd.DataFrame(signal_rows)
        signal_df["signal_date"] = pd.to_datetime(signal_df["signal_date"])

        n_tickers = signal_df["ticker"].nunique()
        n_signals = len(signal_df)
        mean_div = signal_df[signal_name].mean()

        logger.info(
            f"PronounDivergence: {n_signals} signals across {n_tickers} tickers. "
            f"Mean divergence: {mean_div:.4f} "
            f"({(signal_df[signal_name] > 0).sum()} bearish / "
            f"{(signal_df[signal_name] <= 0).sum()} neutral)"
        )

        # Pivot to wide format (date x ticker)
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
                    "text_source": "qa_from_full_text",
                    "min_qa_length": self._min_qa_length,
                    "baseline_percentile": self.BASELINE_PERCENTILE,
                    "min_baseline_obs": self.MIN_BASELINE_OBSERVATIONS,
                    "n_transcripts_processed": len(ppr_df),
                    "n_signals_produced": n_signals,
                    "n_tickers": n_tickers,
                },
            ),
        )

    # ── Validation ────────────────────────────────────────────────

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
                f"Too few non-NaN signal values ({n_non_nan}). "
                f"Need at least 3 for any statistical test."
            )
            return False, issues

        if n_non_nan < 10:
            logger.warning(
                f"PronounDivergence: Only {n_non_nan} non-NaN signal values. "
                f"Statistical power will be very low."
            )

        return True, issues

    # ── Helpers ───────────────────────────────────────────────────

    def _empty_signal(self, signal_name: str) -> SignalData:
        """Return empty SignalData for when no signals can be extracted."""
        return SignalData(
            df=pd.DataFrame(),
            metadata=SignalMetadata(
                extractor_name=self.extractor_name,
                extractor_version=self.version,
                extractor_method="deterministic",
                parameters={"signal_name": signal_name, "empty": True},
            ),
        )
