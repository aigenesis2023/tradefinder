"""
contamination.py — Temporal Contamination Detector
==================================================

Detects and documents the risk that LLM training-data memorization
contaminates backtest results, producing "profit mirages" that vanish
once the model's knowledge cutoff passes.

The problem: When an LLM processes a historical document (e.g., a 2019
FDA briefing document), it may already "know" the outcome because that
outcome was in its training data. The model doesn't need to analyze
language — it can simply recall the drug was approved.

Three detection mechanisms:
  1. Knowledge cutoff verification — flag documents that predate the LLM cutoff
  2. Placebo test — swap document text, verify signal predictiveness drops
  3. Pre/post cutoff comparison — compare signal strength across cutoff boundary

Integration: Called by SignalBuilder.build() after signal extraction,
before saving. If contamination risk is HIGH and no post-cutoff data exists,
the verdict is capped at INCONCLUSIVE.

For deterministic extractors (keyword/regex): contamination risk is LOW
for the extraction itself. But if the pipeline EVER uses an LLM for extraction,
contamination detection becomes critical.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ============================================================================
# Knowledge cutoff — the LLM's training data deadline
# ============================================================================
# This is the documented cutoff date for the LLM used in extraction.
# Any document dated BEFORE this date is potentially in the model's training
# corpus, so the model may "know" the outcome without analyzing the text.
#
# Default: GPT-4 / Claude 3.5 class models (late 2023 cutoff).
# Adjust for your specific model. When a model is fine-tuned or uses RAG,
# the cutoff may differ.
# ============================================================================

DEFAULT_KNOWLEDGE_CUTOFF = "2023-10-01"


@dataclass
class ContaminationReport:
    """Complete contamination assessment for a signal file."""

    contamination_risk: str  # HIGH | MEDIUM | LOW | CLEAN
    contamination_rationale: str
    knowledge_cutoff_date: str

    # Event counts by cutoff
    pre_cutoff_events: int = 0
    post_cutoff_events: int = 0

    # Placebo test
    placebo_test_result: str = "NOT_RUN"  # PASS | FAIL | NOT_RUN
    placebo_original_predictiveness: Optional[float] = None
    placebo_swapped_predictiveness: Optional[float] = None
    placebo_predictiveness_drop_pct: Optional[float] = None
    placebo_n_swaps: int = 0

    # Pre/post cutoff comparison
    pre_cutoff_auc: Optional[float] = None
    post_cutoff_auc: Optional[float] = None
    pre_cutoff_sharpe: Optional[float] = None
    post_cutoff_sharpe: Optional[float] = None
    cutoff_comparison_result: str = "NOT_RUN"  # CONSISTENT | DEGRADED | INCONCLUSIVE

    # Extraction method context
    extraction_method: str = "deterministic"
    llm_used_for_extraction: bool = False

    # Warnings and details
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ContaminationReport":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class PlaceboTextSwapper:
    """Swaps document text between records to create placebo controls.

    For a random subset of test cases, swaps the actual document text with
    text from a DIFFERENT document (same domain, adjacent date, different
    outcome). If the signal still predicts the original outcome, the signal
    is leaking from training data rather than extracting from text.
    """

    def __init__(self, seed: int = 42):
        self._seed = seed
        self._rng = random.Random(seed)

    def swap(
        self,
        documents: pd.DataFrame,
        text_columns: List[str],
        date_column: str,
        outcome_column: str,
        swap_fraction: float = 0.2,
    ) -> Tuple[pd.DataFrame, List[int], Dict[int, int]]:
        """Swap text between documents with different outcomes.

        Args:
            documents: DataFrame with document records.
            text_columns: Columns containing text to swap.
            date_column: Column with document dates.
            outcome_column: Column with outcome (must differ between swapped pairs).
            swap_fraction: Fraction of documents to swap (default 0.2 = 20%).

        Returns:
            Tuple of (modified_df, swapped_indices, swap_map).
            swap_map maps original_index -> swapped_from_index.
        """
        df = documents.copy()
        n = len(df)
        n_swaps = max(1, int(n * swap_fraction))

        # Ensure we have the outcome column
        if outcome_column not in df.columns:
            logger.warning(
                f"Outcome column '{outcome_column}' not found. "
                f"Cannot perform placebo swap. Columns: {list(df.columns)}"
            )
            return df, [], {}

        # Group by outcome so we can swap across outcomes
        outcomes = df[outcome_column].unique()
        if len(outcomes) < 2:
            logger.warning(
                f"Only one outcome value found in '{outcome_column}' "
                f"({outcomes[0]}). Cannot swap across outcomes."
            )
            return df, [], {}

        # Select indices to swap
        available_indices = list(range(n))
        self._rng.shuffle(available_indices)
        swap_candidates = available_indices[:n_swaps]

        swapped = []
        swap_map = {}
        used_as_source = set()

        for idx in swap_candidates:
            orig_outcome = df.loc[idx, outcome_column]

            # Find candidate with DIFFERENT outcome, similar date, not yet used as source
            candidates = []
            for j in range(n):
                if j == idx:
                    continue
                if j in used_as_source:
                    continue
                if df.loc[j, outcome_column] == orig_outcome:
                    continue
                candidates.append(j)

            if not candidates:
                continue

            self._rng.shuffle(candidates)

            # Prefer candidates close in time
            if date_column in df.columns:
                try:
                    orig_date = pd.Timestamp(df.loc[idx, date_column])
                    candidates.sort(
                        key=lambda j: abs(
                            (pd.Timestamp(df.loc[j, date_column]) - orig_date).days
                        )
                    )
                except Exception:
                    pass

            swap_source = candidates[0]

            # Swap text columns
            for col in text_columns:
                if col in df.columns:
                    orig_text = df.loc[idx, col]
                    source_text = df.loc[swap_source, col]
                    df.loc[idx, col] = source_text
                    df.loc[swap_source, col] = orig_text

            swapped.append(idx)
            swap_map[idx] = swap_source
            used_as_source.add(swap_source)

        logger.info(
            f"Placebo text swap: {len(swapped)}/{n} documents swapped "
            f"({len(swapped)/n*100:.1f}%) across {len(outcomes)} outcome groups"
        )

        return df, swapped, swap_map


class ContaminationDetector:
    """Detect and document temporal contamination risk in signal extraction.

    Three-pronged approach:
    1. Knowledge cutoff verification
    2. Placebo test (text swapping)
    3. Pre/post cutoff performance comparison

    Usage:
        detector = ContaminationDetector(knowledge_cutoff_date="2023-10-01")
        report = detector.detect(
            raw_data=data,
            signal_df=signal_df,
            date_column="pdufa_date",
            outcome_column="decision",
        )
        # report.contamination_risk -> "LOW" | "MEDIUM" | "HIGH" | "CLEAN"
    """

    def __init__(
        self,
        knowledge_cutoff_date: str = DEFAULT_KNOWLEDGE_CUTOFF,
        extraction_method: str = "deterministic",
        llm_used: bool = False,
        seed: int = 42,
    ):
        """
        Args:
            knowledge_cutoff_date: The LLM's training data cutoff (YYYY-MM-DD).
            extraction_method: 'deterministic' or 'llm_temperature_zero' or 'llm_sampled'.
            llm_used: Whether LLM was used for extraction (vs. keyword/regex).
            seed: Random seed for placebo swapping.
        """
        self.knowledge_cutoff_date = knowledge_cutoff_date
        self.extraction_method = extraction_method
        self.llm_used = llm_used
        self._seed = seed
        self._rng = random.Random(seed)
        self._swapper = PlaceboTextSwapper(seed=seed)

        # Build cutoff Timestamp once
        try:
            self._cutoff_ts = pd.Timestamp(knowledge_cutoff_date)
        except Exception:
            logger.warning(
                f"Invalid knowledge_cutoff_date '{knowledge_cutoff_date}'. "
                f"Using default: {DEFAULT_KNOWLEDGE_CUTOFF}"
            )
            self._cutoff_ts = pd.Timestamp(DEFAULT_KNOWLEDGE_CUTOFF)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def detect(
        self,
        raw_data: "RawData",
        signal_df: Optional[pd.DataFrame] = None,
        date_column: str = "",
        outcome_column: str = "",
        signal_column: str = "",
        text_columns: Optional[List[str]] = None,
        run_placebo: bool = False,
        **kwargs,
    ) -> ContaminationReport:
        """Run the full contamination detection suite.

        Args:
            raw_data: The RawData container with document records.
            signal_df: The extracted signal DataFrame (optional, for comparison tests).
            date_column: Column with event dates.
            outcome_column: Column with known outcomes (for predictiveness tests).
            signal_column: Column with computed signal values.
            text_columns: Columns containing document text (for placebo swap).
            run_placebo: Whether to run the computationally expensive placebo test.

        Returns:
            ContaminationReport with risk assessment.
        """
        warnings: List[str] = []
        details: Dict[str, Any] = {}

        df = raw_data.records if raw_data is not None and hasattr(raw_data, 'records') else None
        if df is None or df.empty:
            return ContaminationReport(
                contamination_risk="LOW",
                contamination_rationale=(
                    "No document data available for contamination check. "
                    "Risk assessment defaulting to LOW."
                ),
                knowledge_cutoff_date=self.knowledge_cutoff_date,
                warnings=["No data for contamination analysis"],
            )

        # Auto-detect columns if not specified
        date_column = date_column or self._find_date_column(df)
        outcome_column = outcome_column or self._find_outcome_column(df)
        text_columns = text_columns or self._find_text_columns(df)

        # === Check 1: Knowledge cutoff verification ===
        pre_cutoff, post_cutoff = self._split_by_cutoff(df, date_column)
        n_pre = len(pre_cutoff)
        n_post = len(post_cutoff)

        details["pre_cutoff_events"] = n_pre
        details["post_cutoff_events"] = n_post
        details["fraction_pre_cutoff"] = n_pre / max(n_pre + n_post, 1)

        if n_pre > 0 and n_post == 0:
            warnings.append(
                f"ALL {n_pre} events predate the knowledge cutoff "
                f"({self.knowledge_cutoff_date}). "
                f"LLM may have memorized all outcomes. Signal may be contaminated."
            )
        elif n_pre > 0:
            warnings.append(
                f"{n_pre}/{n_pre + n_post} events ({n_pre/(n_pre+n_post)*100:.0f}%) "
                f"predate the knowledge cutoff ({self.knowledge_cutoff_date})."
            )

        # === Check 2: Placebo test (optional, computationally expensive) ===
        placebo_result = "NOT_RUN"
        placebo_orig = None
        placebo_swapped = None
        placebo_drop = None
        n_swaps = 0

        if run_placebo and text_columns and outcome_column:
            try:
                (
                    placebo_result,
                    placebo_orig,
                    placebo_swapped,
                    placebo_drop,
                    n_swaps,
                ) = self._run_placebo_test(
                    df, text_columns, date_column, outcome_column, signal_column
                )
            except Exception as e:
                logger.warning(f"Placebo test failed: {e}")
                warnings.append(f"Placebo test error: {e}")

        # === Check 3: Pre/post cutoff comparison ===
        cutoff_result = "NOT_RUN"
        pre_auc = None
        post_auc = None
        pre_sharpe = None
        post_sharpe = None

        if n_pre >= 10 and n_post >= 10 and signal_column and outcome_column:
            try:
                (
                    cutoff_result,
                    pre_auc,
                    post_auc,
                    pre_sharpe,
                    post_sharpe,
                ) = self._compare_cutoff_performance(
                    df, signal_df, date_column, outcome_column, signal_column
                )
            except Exception as e:
                logger.warning(f"Cutoff comparison failed: {e}")
                warnings.append(f"Cutoff comparison error: {e}")

        # === Compute overall risk assessment ===
        risk, rationale = self._assess_risk(
            n_pre=n_pre,
            n_post=n_post,
            placebo_result=placebo_result,
            cutoff_result=cutoff_result,
            llm_used=self.llm_used,
            extraction_method=self.extraction_method,
        )

        return ContaminationReport(
            contamination_risk=risk,
            contamination_rationale=rationale,
            knowledge_cutoff_date=self.knowledge_cutoff_date,
            pre_cutoff_events=n_pre,
            post_cutoff_events=n_post,
            placebo_test_result=placebo_result,
            placebo_original_predictiveness=placebo_orig,
            placebo_swapped_predictiveness=placebo_swapped,
            placebo_predictiveness_drop_pct=placebo_drop,
            placebo_n_swaps=n_swaps,
            pre_cutoff_auc=pre_auc,
            post_cutoff_auc=post_auc,
            pre_cutoff_sharpe=pre_sharpe,
            post_cutoff_sharpe=post_sharpe,
            cutoff_comparison_result=cutoff_result,
            extraction_method=self.extraction_method,
            llm_used_for_extraction=self.llm_used,
            warnings=warnings,
            details=details,
        )

    # ------------------------------------------------------------------
    # Internal: cutoff splitting
    # ------------------------------------------------------------------

    def _split_by_cutoff(
        self, df: pd.DataFrame, date_column: str
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Split DataFrame into pre-cutoff and post-cutoff subsets."""
        if date_column not in df.columns:
            logger.warning(f"Date column '{date_column}' not found. Cannot split by cutoff.")
            return pd.DataFrame(), pd.DataFrame()

        try:
            dates = pd.to_datetime(df[date_column], errors="coerce")
            pre_mask = dates < self._cutoff_ts
            post_mask = dates >= self._cutoff_ts
            return df[pre_mask].copy(), df[post_mask].copy()
        except Exception as e:
            logger.warning(f"Date parsing failed for column '{date_column}': {e}")
            return pd.DataFrame(), pd.DataFrame()

    # ------------------------------------------------------------------
    # Internal: placebo test
    # ------------------------------------------------------------------

    def _run_placebo_test(
        self,
        df: pd.DataFrame,
        text_columns: List[str],
        date_column: str,
        outcome_column: str,
        signal_column: str,
    ) -> Tuple[str, Optional[float], Optional[float], Optional[float], int]:
        """Run the placebo text swap test.

        Returns:
            (result, original_predictiveness, swapped_predictiveness,
             predictiveness_drop_pct, n_swaps)
        """
        # 1. Compute baseline predictiveness
        baseline = self._compute_signal_predictiveness(
            df, outcome_column, signal_column
        )

        # 2. Swap text and recompute
        swapped_df, swapped_indices, swap_map = self._swapper.swap(
            df, text_columns, date_column, outcome_column, swap_fraction=0.2
        )

        swapped_predictiveness = self._compute_signal_predictiveness(
            swapped_df, outcome_column, signal_column
        )

        n_swaps = len(swapped_indices)

        # 3. Compare
        if baseline is not None and swapped_predictiveness is not None:
            drop_pct = (
                (baseline - swapped_predictiveness) / max(abs(baseline), 1e-10) * 100
            )
        else:
            drop_pct = None

        # Interpretation
        if drop_pct is None:
            result = "NOT_RUN"
        elif drop_pct > 50:
            # Large drop = signal is genuinely text-derived (good)
            result = "PASS"
        elif drop_pct > 20:
            result = "PASS"  # Moderate drop still suggests text dependency
        else:
            # Small or no drop = signal is NOT from text; possible contamination
            result = "FAIL"

        logger.info(
            f"Placebo test: baseline={baseline:.4f}, swapped={swapped_predictiveness:.4f}, "
            f"drop={drop_pct:.1f}%, result={result}"
        )

        return result, baseline, swapped_predictiveness, drop_pct, n_swaps

    def _compute_signal_predictiveness(
        self,
        df: pd.DataFrame,
        outcome_column: str,
        signal_column: str,
    ) -> Optional[float]:
        """Compute a simple predictiveness metric (correlation or AUC).

        For binary outcomes: AUC. For continuous: Spearman correlation.
        """
        if outcome_column not in df.columns:
            return None

        if signal_column not in df.columns:
            # No signal column; try reasonable defaults
            for col in ["composite_score", "benefit_hedge_density"]:
                if col in df.columns:
                    signal_column = col
                    break
            else:
                return None

        signal_vals = df[signal_column]
        outcome_vals = df[outcome_column]

        # Drop NaN
        valid = signal_vals.notna() & outcome_vals.notna()
        signal_vals = signal_vals[valid]
        outcome_vals = outcome_vals[valid]

        if len(signal_vals) < 5:
            return None

        # Binary outcomes -> AUC
        unique_outcomes = outcome_vals.unique()
        if len(unique_outcomes) == 2:
            try:
                # Convert to binary
                positive = unique_outcomes[1] if len(unique_outcomes) > 1 else unique_outcomes[0]
                binary = (outcome_vals == positive).astype(int)
                from sklearn.metrics import roc_auc_score
                auc = roc_auc_score(binary, signal_vals)
                return float(auc) if not np.isnan(auc) else None
            except ImportError:
                # Manual AUC approximation using rank-sum
                return self._manual_auc(binary, signal_vals)

        # Continuous -> absolute Spearman correlation
        try:
            corr = signal_vals.corr(outcome_vals, method="spearman")
            return float(abs(corr)) if not np.isnan(corr) else None
        except Exception:
            return None

    @staticmethod
    def _manual_auc(binary: np.ndarray, scores: np.ndarray) -> Optional[float]:
        """Compute AUC using the Mann-Whitney U statistic (no sklearn needed)."""
        pos = scores[binary == 1]
        neg = scores[binary == 0]
        if len(pos) == 0 or len(neg) == 0:
            return None
        n_pos, n_neg = len(pos), len(neg)
        # Count pairwise comparisons where pos > neg
        u = 0
        for p in pos:
            u += np.sum(p > neg) + 0.5 * np.sum(p == neg)
        auc = u / (n_pos * n_neg)
        return float(auc)

    # ------------------------------------------------------------------
    # Internal: pre/post cutoff comparison
    # ------------------------------------------------------------------

    def _compare_cutoff_performance(
        self,
        df: pd.DataFrame,
        signal_df: Optional[pd.DataFrame],
        date_column: str,
        outcome_column: str,
        signal_column: str,
    ) -> Tuple[str, Optional[float], Optional[float], Optional[float], Optional[float]]:
        """Compare signal predictiveness before vs. after the knowledge cutoff."""
        pre_df, post_df = self._split_by_cutoff(df, date_column)

        if pre_df.empty or post_df.empty:
            return "NOT_RUN", None, None, None, None

        pre_auc = self._compute_signal_predictiveness(pre_df, outcome_column, signal_column)
        post_auc = self._compute_signal_predictiveness(post_df, outcome_column, signal_column)

        pre_sharpe = None
        post_sharpe = None

        # If we have a signal DataFrame, compute Sharpe by period
        if signal_df is not None and not signal_df.empty:
            try:
                pre_sharpe = self._compute_period_sharpe(signal_df, pre_df, date_column)
                post_sharpe = self._compute_period_sharpe(signal_df, post_df, date_column)
            except Exception as e:
                logger.debug(f"Period Sharpe computation failed: {e}")

        # Determine result
        if pre_auc is None or post_auc is None:
            result = "INCONCLUSIVE"
        elif post_auc >= pre_auc * 0.8:
            result = "CONSISTENT"  # Signal works post-cutoff too — genuine
        elif post_auc >= pre_auc * 0.5:
            result = "DEGRADED"    # Signal weakened but not vanished
        else:
            result = "DEGRADED"    # Signal heavily degraded — contamination likely

        logger.info(
            f"Cutoff comparison: pre-AUC={pre_auc:.4f}, post-AUC={post_auc:.4f}, "
            f"result={result}"
        )

        return result, pre_auc, post_auc, pre_sharpe, post_sharpe

    def _compute_period_sharpe(
        self,
        signal_df: pd.DataFrame,
        event_subset: pd.DataFrame,
        date_column: str,
        annualization: float = 252.0,
    ) -> Optional[float]:
        """Compute annualized Sharpe for a subset of events."""
        if date_column not in event_subset.columns:
            return None

        # Get event dates from the subset
        event_dates = pd.to_datetime(event_subset[date_column], errors="coerce").dropna()

        if len(event_dates) < 2:
            return None

        # Align signal data to event dates
        signal_index = pd.to_datetime(signal_df.index)
        aligned_signals = []
        for d in event_dates:
            nearby = signal_index[signal_index >= d]
            if len(nearby) > 0:
                aligned_signals.append(nearby[0])
            else:
                nearby = signal_index[signal_index <= d]
                if len(nearby) > 0:
                    aligned_signals.append(nearby[-1])

        if len(aligned_signals) < 2:
            return None

        # Get signal values at those dates
        signal_values = signal_df.loc[aligned_signals]
        # Compute daily returns as signal difference (proxy)
        daily_mean = signal_values.mean(axis=1)
        returns = daily_mean.diff().dropna()

        if len(returns) < 2 or returns.std() == 0:
            return None

        sharpe = returns.mean() / returns.std() * np.sqrt(annualization)
        return float(sharpe)

    # ------------------------------------------------------------------
    # Internal: risk assessment
    # ------------------------------------------------------------------

    def _assess_risk(
        self,
        n_pre: int,
        n_post: int,
        placebo_result: str,
        cutoff_result: str,
        llm_used: bool,
        extraction_method: str,
    ) -> Tuple[str, str]:
        """Determine the overall contamination risk level.

        Returns:
            (risk_level, rationale)
        """
        # If the extractor is deterministic (keyword/regex), contamination
        # from training data memorization cannot affect the extraction itself.
        # Risk is ONLY from LLM-based steps.
        if extraction_method == "deterministic" and not llm_used:
            return "CLEAN", (
                f"Extraction method is deterministic (keyword/regex). "
                f"No LLM was used for signal extraction, so training-data "
                f"contamination cannot affect the signal values. "
                f"({n_pre} pre-cutoff, {n_post} post-cutoff events)"
            )

        # LLM-based extraction: evaluate risk
        risk_factors = 0
        reasons = []

        if n_post == 0 and n_pre > 0:
            risk_factors += 2
            reasons.append(
                f"No post-cutoff events available (0/{n_pre + n_post}). "
                f"All data predates the {self.knowledge_cutoff_date} cutoff."
            )

        if n_pre > n_post * 3 and n_post > 0:
            risk_factors += 1
            reasons.append(
                f"Pre-cutoff events ({n_pre}) outnumber post-cutoff ({n_post}) "
                f"by {n_pre/max(n_post,1):.0f}x. Cutoff comparison underpowered."
            )

        if placebo_result == "FAIL":
            risk_factors += 2
            reasons.append(
                "Placebo test FAILED: swapping document text did not "
                "materially reduce signal predictiveness. Signal may be "
                "leaking from training data rather than text analysis."
            )

        if cutoff_result == "DEGRADED":
            risk_factors += 1
            reasons.append(
                "Pre/post cutoff comparison shows signal DEGRADED after cutoff. "
                "Signal may partially depend on pre-cutoff memorization."
            )

        # Map risk factors to level
        if risk_factors >= 3:
            risk = "HIGH"
        elif risk_factors >= 2:
            risk = "MEDIUM"
        elif risk_factors >= 1:
            risk = "LOW"
        else:
            risk = "LOW" if llm_used else "CLEAN"

        if not reasons:
            reasons.append(
                f"Post-cutoff data available ({n_post} events). "
                f"No contamination indicators detected."
                + (" (LLM used for extraction)" if llm_used else "")
            )

        rationale = " | ".join(reasons)
        return risk, rationale

    # ------------------------------------------------------------------
    # Column detection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_date_column(df: pd.DataFrame) -> str:
        """Find a date column in the DataFrame."""
        for col in [
            "pdufa_date", "advisory_committee_date", "submission_date",
            "filing_date", "date", "acceptance_date", "period_end_date",
            "known_date", "document_date", "event_date",
        ]:
            if col in df.columns:
                return col
        return ""

    @staticmethod
    def _find_outcome_column(df: pd.DataFrame) -> str:
        """Find an outcome column in the DataFrame."""
        for col in ["decision", "outcome", "label", "target", "actual", "result"]:
            if col in df.columns:
                return col
        return ""

    @staticmethod
    def _find_text_columns(df: pd.DataFrame) -> List[str]:
        """Find text content columns in the DataFrame."""
        text_cols = []
        for col in df.columns:
            col_lower = col.lower()
            if "text" in col_lower or "document" in col_lower or "description" in col_lower:
                # Exclude non-text columns
                if "date" not in col_lower and "id" not in col_lower and "type" not in col_lower:
                    text_cols.append(col)
        return text_cols

    # ------------------------------------------------------------------
    # Utility: apply contamination verdict cap
    # ------------------------------------------------------------------

    @staticmethod
    def cap_verdict(
        original_verdict: str,
        contamination_risk: str,
    ) -> str:
        """Cap a verdict based on contamination risk.

        If contamination risk is HIGH and no post-cutoff data exists,
        cap the verdict at INCONCLUSIVE. SURVIVED -> INCONCLUSIVE,
        BROKEN stays BROKEN (broken from contaminated data is still broken).
        """
        from signal_builder.base import Verdict

        if contamination_risk != "HIGH":
            return original_verdict

        # Only cap positive or inconclusive verdicts
        # BROKEN or UNTESTABLE stay as-is (contamination doesn't make them better)
        cap_map = {
            Verdict.SURVIVED.value: Verdict.INCONCLUSIVE.value,
            Verdict.SURVIVED_WARNING.value: Verdict.INCONCLUSIVE.value,
            Verdict.INCONCLUSIVE.value: Verdict.INCONCLUSIVE.value,
        }

        capped = cap_map.get(original_verdict, original_verdict)
        if capped != original_verdict:
            logger.warning(
                f"ContaminationDetector: Capping verdict {original_verdict} -> {capped} "
                f"(contamination risk HIGH, no clean data available)"
            )

        return capped

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: ContaminationReport, path: str) -> str:
        """Save contamination report to a JSON file."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(report.to_dict(), f, indent=2, default=str)
        return path

    @classmethod
    def load_report(cls, path: str) -> ContaminationReport:
        """Load a contamination report from a JSON file."""
        with open(path, "r") as f:
            data = json.load(f)
        return ContaminationReport.from_dict(data)
