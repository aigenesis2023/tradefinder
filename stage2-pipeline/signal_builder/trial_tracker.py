"""
trial_tracker.py — Cumulative False Discovery Rate Tracker
===========================================================

Tracks EVERY hypothesis test across the entire multi-agent investigation
to prevent the cumulative false discovery rate from drifting upward with
each BROKEN -> refine -> retest cycle.

The problem: The pipeline applies Bonferroni and FDR corrections within
each individual hypothesis test. But when the loop runs — Stage 1 generates,
tests, refines, retests — each iteration adds to the family of tests.
Without tracking the TOTAL number of trials, the effective false discovery
rate drifts upward with each cycle. The literature shows this is THE
mechanism by which multi-agent systems find spurious patterns.

Core capabilities:
  1. Persistent trial log (trial_family.json)
  2. Family-wise error correction across ALL trials
  3. Hard refinement cap enforcement (max 3 submissions per hypothesis)
  4. Global cap enforcement (terminate if zero SURVIVED per cycle)
  5. Honest reporting: investigation-wide significance in every verdict

Integration: Initialized at loop start, passed through to signal builder
and pipeline. Every verdict output includes investigation-wide context.

Usage:
    tracker = TrialTracker("trial_family.json")
    tracker.record_trial_start(hypothesis_uuid, submission_number)
    # ... run pipeline ...
    tracker.record_trial_end(hypothesis_uuid, verdict, p_value, test_statistic)

    # Check global significance
    context = tracker.get_investigation_context(hypothesis_uuid)
    # context tells you: trial 12 of 31, family-wise threshold p < 0.0016, etc.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid as uuid_lib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

MAX_REFINEMENTS_PER_HYPOTHESIS = 3  # From the investigation plan
DEFAULT_ALPHA = 0.05


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass
class TrialRecord:
    """Record of a single hypothesis test."""

    hypothesis_uuid: str
    hypothesis_name: str
    submission_number: int
    verdict: str = ""  # SURVIVED | SURVIVED_WARNING | BROKEN | INCONCLUSIVE | UNTESTABLE | ARCHIVED
    timestamp_start: str = ""
    timestamp_end: str = ""
    p_value: Optional[float] = None
    test_statistic: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    annualized_alpha_bps: Optional[float] = None
    source_agent: str = ""
    trial_index: int = 0  # Position in the overall trial sequence
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TrialRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class InvestigationContext:
    """Investigation-wide statistical context for a single verdict.

    This is what gets embedded in every verdict to prevent the most
    common form of false confidence: reporting individual-test p-values
    as if they were the only test run.
    """

    trial_index: int = 0
    total_trials: int = 0
    total_hypotheses: int = 0
    total_broken_refine_cycles: int = 0
    bonferroni_threshold: float = DEFAULT_ALPHA
    bh_fdr_threshold: Optional[float] = None
    survives_family_wise_correction: bool = False
    fdr_rank: Optional[int] = None
    honest_report: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "InvestigationContext":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class TrialTracker:
    """Tracks cumulative false discovery rate across the entire investigation.

    Maintains a persistent trial family file that records every hypothesis
    test, enabling family-wise error correction and honest reporting.

    Usage:
        tracker = TrialTracker("path/to/trial_family.json")
        tracker.record_trial_start(uuid, submission_num)
        # ... run pipeline ...
        tracker.record_trial_end(uuid, verdict, p_value, sharpe)
        context = tracker.get_investigation_context(uuid)
    """

    def __init__(
        self,
        trial_family_path: str = "trial_family.json",
        investigation_id: Optional[str] = None,
        alpha: float = DEFAULT_ALPHA,
    ):
        """
        Args:
            trial_family_path: Path to the persistent trial family JSON file.
            investigation_id: Unique investigation ID. Auto-generated if None.
            alpha: Family-wise significance level (default 0.05).
        """
        self.trial_family_path = os.path.abspath(trial_family_path)
        self.alpha = alpha

        # Load or create investigation state
        if os.path.exists(self.trial_family_path):
            self._state = self._load()
            self.investigation_id = self._state.get(
                "investigation_id", investigation_id or str(uuid_lib.uuid4())[:8]
            )
        else:
            self.investigation_id = investigation_id or str(uuid_lib.uuid4())[:8]
            self._state = self._initialize_state()

        # Derived convenience accessors
        self._trials: List[TrialRecord] = []
        self._load_trials_from_state()

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _initialize_state(self) -> Dict[str, Any]:
        """Create a fresh investigation state."""
        return {
            "investigation_id": self.investigation_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total_hypotheses_tested": 0,
            "total_tests_run": 0,
            "total_broken_refine_cycles": 0,
            "total_survived": 0,
            "total_survived_warning": 0,
            "total_broken": 0,
            "total_inconclusive": 0,
            "total_untestable": 0,
            "total_archived": 0,
            "trials": [],
            "verdict_counts_by_cycle": {},  # e.g., {"1": {"BROKEN": 3, "SURVIVED": 1}}
            "termination_history": [],
            "notes": "",
        }

    def _load(self) -> Dict[str, Any]:
        """Load investigation state from file."""
        try:
            with open(self.trial_family_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.warning(f"Could not load trial family file: {e}. Starting fresh.")
            return self._initialize_state()

    def _save(self) -> None:
        """Persist the investigation state to disk."""
        os.makedirs(os.path.dirname(self.trial_family_path) or ".", exist_ok=True)

        self._state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._state["trials"] = [t.to_dict() for t in self._trials]

        with open(self.trial_family_path, "w") as f:
            json.dump(self._state, f, indent=2, default=str)

    def _load_trials_from_state(self) -> None:
        """Parse trial records from the raw state dict."""
        self._trials = []
        for t_dict in self._state.get("trials", []):
            self._trials.append(TrialRecord.from_dict(t_dict))

    # ------------------------------------------------------------------
    # Trial lifecycle
    # ------------------------------------------------------------------

    def record_trial_start(
        self,
        hypothesis_uuid: str,
        submission_number: int,
        hypothesis_name: str = "",
        source_agent: str = "",
    ) -> Optional[str]:
        """Record the start of a hypothesis test.

        Performs pre-flight checks:
        - Refinement cap: max 3 submissions per hypothesis UUID
        - Returns None (block) if the hypothesis is archived.

        Returns:
            trial_uuid if allowed, None if blocked (refinement cap reached).
        """
        # Check refinement cap
        submissions_for_uuid = [
            t for t in self._trials
            if t.hypothesis_uuid == hypothesis_uuid
        ]
        n_previous = len(submissions_for_uuid)

        if n_previous >= MAX_REFINEMENTS_PER_HYPOTHESIS:
            logger.warning(
                f"HYPOTHESIS {hypothesis_uuid}: Refinement cap reached "
                f"({n_previous} previous submissions). ARCHIVED."
            )
            # Record the blocked submission
            blocked_trial = TrialRecord(
                hypothesis_uuid=hypothesis_uuid,
                hypothesis_name=hypothesis_name,
                submission_number=submission_number,
                verdict="ARCHIVED (REFINEMENT CAP REACHED)",
                timestamp_start=datetime.now(timezone.utc).isoformat(),
                timestamp_end=datetime.now(timezone.utc).isoformat(),
                source_agent=source_agent,
                trial_index=len(self._trials) + 1,
                notes=f"Blocked: {n_previous} prior submissions exist. Max is {MAX_REFINEMENTS_PER_HYPOTHESIS}.",
            )
            self._trials.append(blocked_trial)
            self._state["total_archived"] = self._state.get("total_archived", 0) + 1
            self._save()
            return None

        # Create trial record
        trial_index = len(self._trials) + 1
        trial = TrialRecord(
            hypothesis_uuid=hypothesis_uuid,
            hypothesis_name=hypothesis_name,
            submission_number=submission_number,
            timestamp_start=datetime.now(timezone.utc).isoformat(),
            source_agent=source_agent,
            trial_index=trial_index,
        )

        self._trials.append(trial)
        self._state["total_tests_run"] = len(self._trials)

        # Track unique hypotheses
        unique_uuids = set(t.hypothesis_uuid for t in self._trials if t.verdict != "ARCHIVED (REFINEMENT CAP REACHED)")
        self._state["total_hypotheses_tested"] = len(unique_uuids)

        logger.info(
            f"TrialTracker: Starting trial #{trial_index} — "
            f"{hypothesis_name} (submission {submission_number})"
        )

        return f"{hypothesis_uuid}_{submission_number}_{trial_index}"

    def record_trial_end(
        self,
        hypothesis_uuid: str,
        submission_number: int,
        verdict: str,
        p_value: Optional[float] = None,
        test_statistic: Optional[float] = None,
        sharpe_ratio: Optional[float] = None,
        annualized_alpha_bps: Optional[float] = None,
        notes: str = "",
    ) -> None:
        """Record the end of a hypothesis test with its verdict.

        Args:
            hypothesis_uuid: The hypothesis UUID.
            submission_number: Which submission this is (1, 2, or 3).
            verdict: SURVIVED | SURVIVED_WARNING | BROKEN | INCONCLUSIVE | UNTESTABLE.
            p_value: The primary test p-value.
            test_statistic: The primary test statistic.
            sharpe_ratio: Sharpe ratio from backtest.
            annualized_alpha_bps: Annualized alpha in bps.
            notes: Any additional notes.
        """
        # Find the matching trial record
        matching = [
            t for t in self._trials
            if t.hypothesis_uuid == hypothesis_uuid
            and t.submission_number == submission_number
            and not t.timestamp_end
        ]

        if not matching:
            logger.warning(
                f"No open trial found for {hypothesis_uuid} "
                f"submission {submission_number}. Creating new record."
            )
            # Create a new trial record if none exists
            trial = TrialRecord(
                hypothesis_uuid=hypothesis_uuid,
                hypothesis_name="",
                submission_number=submission_number,
                trial_index=len(self._trials) + 1,
            )
            self._trials.append(trial)
        else:
            trial = matching[0]

        # Update the trial record
        trial.timestamp_end = datetime.now(timezone.utc).isoformat()
        trial.verdict = verdict
        trial.p_value = p_value
        trial.test_statistic = test_statistic
        trial.sharpe_ratio = sharpe_ratio
        trial.annualized_alpha_bps = annualized_alpha_bps
        if notes:
            trial.notes = notes

        # Update aggregate counts
        verdict_key = verdict.lower()
        if verdict_key.startswith("survived_warning") or "SURVIVED_WARNING" in verdict:
            self._state["total_survived_warning"] = self._state.get("total_survived_warning", 0) + 1
        elif verdict_key.startswith("survived") or "SURVIVED" in verdict:
            self._state["total_survived"] = self._state.get("total_survived", 0) + 1
        elif "BROKEN" in verdict:
            self._state["total_broken"] = self._state.get("total_broken", 0) + 1
            # Track refine cycles
            n_submissions = sum(
                1 for t in self._trials
                if t.hypothesis_uuid == hypothesis_uuid
            )
            if n_submissions > 1:
                self._state["total_broken_refine_cycles"] = (
                    self._state.get("total_broken_refine_cycles", 0) + 1
                )
        elif "INCONCLUSIVE" in verdict:
            self._state["total_inconclusive"] = self._state.get("total_inconclusive", 0) + 1
        elif "UNTESTABLE" in verdict:
            self._state["total_untestable"] = self._state.get("total_untestable", 0) + 1

        self._state["total_tests_run"] = len(
            [t for t in self._trials if "ARCHIVED" not in t.verdict.upper().replace(" (REFINEMENT CAP REACHED)", "")]
        )

        self._save()

        # Generate honest report
        context = self.get_investigation_context(hypothesis_uuid)
        logger.info(f"TrialTracker: {context.honest_report}")

    # ------------------------------------------------------------------
    # Investigation-wide context
    # ------------------------------------------------------------------

    def get_investigation_context(
        self,
        hypothesis_uuid: Optional[str] = None,
    ) -> InvestigationContext:
        """Get the investigation-wide statistical context.

        Computes family-wise error correction across ALL trials and
        generates an honest report suitable for embedding in every verdict.

        Args:
            hypothesis_uuid: If provided, compute context relative to this
                             specific hypothesis's position in the trial sequence.

        Returns:
            InvestigationContext with family-wise correction and honest report.
        """
        # Get all non-archived trials with p-values
        active_trials = [
            t for t in self._trials
            if t.p_value is not None
            and "ARCHIVED" not in t.verdict.upper().replace(" (REFINEMENT CAP REACHED)", "")
        ]

        total_trials = len([
            t for t in self._trials
            if "ARCHIVED" not in t.verdict.upper().replace(" (REFINEMENT CAP REACHED)", "")
        ])

        total_hypotheses = len(set(
            t.hypothesis_uuid for t in self._trials
            if "ARCHIVED" not in t.verdict.upper().replace(" (REFINEMENT CAP REACHED)", "")
        ))

        total_refine_cycles = self._state.get("total_broken_refine_cycles", 0)

        # Bonferroni correction
        bonferroni_threshold = self.alpha / max(total_trials, 1)

        # Benjamini-Hochberg FDR
        bh_threshold = None
        fdr_rank = None
        survives_family_wise = False

        if hypothesis_uuid:
            # Find this hypothesis's trial
            this_trial = None
            for t in self._trials:
                if t.hypothesis_uuid == hypothesis_uuid and t.p_value is not None:
                    this_trial = t
                    break

            if this_trial and this_trial.p_value is not None and active_trials:
                # Sort all p-values
                all_p_values = sorted([t.p_value for t in active_trials if t.p_value is not None])
                m = len(all_p_values)

                if m > 0:
                    # Compute BH thresholds
                    ranks = np.arange(1, m + 1)
                    bh_thresholds = ranks * self.alpha / m

                    # Find BH threshold for FDR control
                    significant_bh = [
                        p <= thresh for p, thresh in zip(all_p_values, bh_thresholds)
                    ]
                    bh_cutoff_idx = None
                    for i in range(m - 1, -1, -1):
                        if all_p_values[i] <= bh_thresholds[i]:
                            bh_cutoff_idx = i
                            break

                    if bh_cutoff_idx is not None:
                        bh_threshold = bh_thresholds[bh_cutoff_idx]
                    else:
                        bh_threshold = bh_thresholds[0] if len(bh_thresholds) > 0 else self.alpha

                    # Find this p-value's rank
                    p_val = this_trial.p_value
                    fdr_rank = sum(1 for p in all_p_values if p <= p_val)

                    # Survives Bonferroni?
                    survives_family_wise = p_val <= bonferroni_threshold

        # Generate honest report
        trial_index = 0
        this_p_value = None
        if hypothesis_uuid:
            for t in self._trials:
                if t.hypothesis_uuid == hypothesis_uuid and t.p_value is not None:
                    trial_index = t.trial_index
                    this_p_value = t.p_value
                    break

        honest_parts = []
        if total_trials > 0:
            if trial_index > 0:
                honest_parts.append(
                    f"This hypothesis is trial {trial_index} of {total_trials} "
                    f"in this investigation."
                )
            else:
                honest_parts.append(
                    f"Total trials in investigation: {total_trials} "
                    f"(hypotheses: {total_hypotheses})."
                )

            honest_parts.append(
                f"Bonferroni-adjusted significance threshold: "
                f"p < {bonferroni_threshold:.6f}"
            )

            if bh_threshold is not None and fdr_rank is not None:
                honest_parts.append(
                    f"Benjamini-Hochberg FDR threshold: p < {bh_threshold:.6f} "
                    f"(rank {fdr_rank}/{len(active_trials)})."
                )

            if this_p_value is not None:
                if this_p_value <= bonferroni_threshold:
                    honest_parts.append(
                        f"Unadjusted p-value: {this_p_value:.4f}. "
                        f"SURVIVES family-wise Bonferroni correction."
                    )
                else:
                    honest_parts.append(
                        f"Unadjusted p-value for this test: {this_p_value:.4f}. "
                        f"The unadjusted result is nominally significant but "
                        f"does NOT survive family-wise correction."
                    )

            if total_refine_cycles > 0:
                honest_parts.append(
                    f"Investigation includes {total_refine_cycles} BROKEN->refine->retest "
                    f"cycles, each adding to the multiple-comparison burden."
                )

        if not honest_parts:
            honest_parts.append("No trials recorded yet.")

        honest_report = " | ".join(honest_parts)

        return InvestigationContext(
            trial_index=trial_index,
            total_trials=total_trials,
            total_hypotheses=total_hypotheses,
            total_broken_refine_cycles=total_refine_cycles,
            bonferroni_threshold=bonferroni_threshold,
            bh_fdr_threshold=bh_threshold,
            survives_family_wise_correction=survives_family_wise,
            fdr_rank=fdr_rank,
            honest_report=honest_report,
        )

    # ------------------------------------------------------------------
    # Global cap enforcement
    # ------------------------------------------------------------------

    def check_cycle_termination(
        self,
        cycle_number: int,
    ) -> Tuple[bool, str]:
        """Check if the investigation should terminate after this cycle.

        If an entire Stage 1 -> Bridge cycle produces zero SURVIVED
        hypotheses (after processing all non-archived hypotheses),
        terminate the investigation rather than looping indefinitely.

        Args:
            cycle_number: The current cycle number.

        Returns:
            (should_terminate, reason)
        """
        # Count SURVIVED/SURVIVED_WARNING in the most recent cycle
        # (approximated by total counts since we don't track cycles per trial exactly)
        total_survived = self._state.get("total_survived", 0)
        total_survived_warning = self._state.get("total_survived_warning", 0)
        survived_this_cycle = total_survived + total_survived_warning

        # If after cycle 2+ we have zero survived, suggest termination
        if cycle_number >= 2 and survived_this_cycle == 0:
            reason = (
                f"INVESTIGATION TERMINATED: No hypotheses survived cycle {cycle_number}. "
                f"The idea space in this direction appears exhausted. "
                f"Total trials: {len(self._trials)}, "
                f"Broken: {self._state.get('total_broken', 0)}, "
                f"Inconclusive: {self._state.get('total_inconclusive', 0)}, "
                f"Untestable: {self._state.get('total_untestable', 0)}."
            )
            self._state.setdefault("termination_history", []).append({
                "cycle": cycle_number,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self._save()
            return True, reason

        # Track verdict counts per cycle
        cycle_key = str(cycle_number)
        verdict_counts = self._state.setdefault("verdict_counts_by_cycle", {})
        verdict_counts[cycle_key] = {
            "SURVIVED": total_survived,
            "SURVIVED_WARNING": total_survived_warning,
            "BROKEN": self._state.get("total_broken", 0),
            "INCONCLUSIVE": self._state.get("total_inconclusive", 0),
            "UNTESTABLE": self._state.get("total_untestable", 0),
        }
        self._save()

        return False, ""

    def get_hypothesis_submission_count(self, hypothesis_uuid: str) -> int:
        """Get the number of prior submissions for a hypothesis UUID.

        Used to enforce the refinement cap before testing.
        """
        return sum(
            1 for t in self._trials
            if t.hypothesis_uuid == hypothesis_uuid
        )

    def is_hypothesis_archived(self, hypothesis_uuid: str) -> bool:
        """Check if a hypothesis has been archived (refinement cap reached)."""
        return self.get_hypothesis_submission_count(hypothesis_uuid) >= MAX_REFINEMENTS_PER_HYPOTHESIS

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the investigation state for loop reporting."""
        context = self.get_investigation_context()
        return {
            "investigation_id": self.investigation_id,
            "total_hypotheses_tested": self._state.get("total_hypotheses_tested", 0),
            "total_tests_run": self._state.get("total_tests_run", 0),
            "total_broken_refine_cycles": self._state.get("total_broken_refine_cycles", 0),
            "total_survived": self._state.get("total_survived", 0),
            "total_survived_warning": self._state.get("total_survived_warning", 0),
            "total_broken": self._state.get("total_broken", 0),
            "total_inconclusive": self._state.get("total_inconclusive", 0),
            "total_untestable": self._state.get("total_untestable", 0),
            "total_archived": self._state.get("total_archived", 0),
            "bonferroni_threshold": context.bonferroni_threshold,
            "alpha": self.alpha,
            "family_wise_context": context.honest_report,
            "termination_history": self._state.get("termination_history", []),
        }

    def get_all_p_values(self) -> List[float]:
        """Get all p-values from non-archived trials."""
        return [
            t.p_value for t in self._trials
            if t.p_value is not None
            and "ARCHIVED" not in t.verdict.upper().replace(" (REFINEMENT CAP REACHED)", "")
        ]

    # ------------------------------------------------------------------
    # Honest report generator for verdict embedding
    # ------------------------------------------------------------------

    def generate_verdict_context_text(
        self,
        hypothesis_uuid: str,
        individual_p_value: Optional[float] = None,
    ) -> str:
        """Generate the investigation-wide context text for embedding in a verdict.

        This is the canonical text that appears in every verdict to prevent
        the most common form of false confidence: reporting individual-test
        p-values as if they were the only test run.
        """
        context = self.get_investigation_context(hypothesis_uuid)
        return context.honest_report


# ============================================================================
# Convenience factory
# ============================================================================


def create_trial_tracker(
    output_dir: str = "results",
    investigation_id: Optional[str] = None,
    alpha: float = DEFAULT_ALPHA,
) -> TrialTracker:
    """Create a TrialTracker with sensible defaults for the output directory.

    Args:
        output_dir: Root output directory for the investigation.
        investigation_id: Unique investigation ID.
        alpha: Family-wise significance level.

    Returns:
        Configured TrialTracker instance.
    """
    os.makedirs(output_dir, exist_ok=True)
    trial_path = os.path.join(output_dir, "trial_family.json")
    return TrialTracker(
        trial_family_path=trial_path,
        investigation_id=investigation_id,
        alpha=alpha,
    )
