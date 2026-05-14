"""
signal_builder.py — Main Signal Construction Orchestrator
=========================================================

Takes a HypothesisSpec, determines which DataAdapter(s) and SignalExtractor(s)
are needed, runs the full signal construction pipeline, and saves the result
to a parquet file ready for pipeline.py ingestion.

Architecture:
    1. Parse hypothesis spec
    2. Identify required data sources -> DataAdapters
    3. Acquire raw data from each adapter
    4. Validate raw data
    5. Route to appropriate SignalExtractor
    6. Extract signal
    7. Run THREE CRITICAL SAFEGUARDS (post-extraction, pre-save):
       a. ContaminationDetector — temporal contamination / training-data leakage
       b. SurvivorshipGuard — survivorship bias in universe construction
       c. TrialTracker — cumulative FDR across investigation
    8. Validate signal
    9. Save to parquet + metadata
   10. Return path to signal file

The goal is: hypothesis JSON in, signal file out.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure the signal_builder directory is importable
_SIGNAL_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_SIGNAL_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    from signal_builder.base import (
        DataAcquisitionError,
        DataAdapter,
        DataSourceSpec,
        HypothesisSpec,
        RawData,
        SignalData,
        SignalExtractor,
        SignalMetadata,
        SignalSpec,
        UntestableHypothesisError,
        Verdict,
    )
    from signal_builder.adapters import ADAPTER_REGISTRY, get_adapter
    from signal_builder.extractors import EXTRACTOR_REGISTRY, get_extractor
except ImportError:
    # Fall back to relative imports when used as a package
    from .base import (
        DataAcquisitionError,
        DataAdapter,
        DataSourceSpec,
        HypothesisSpec,
        RawData,
        SignalData,
        SignalExtractor,
        SignalMetadata,
        SignalSpec,
        UntestableHypothesisError,
        Verdict,
    )
    from .adapters import ADAPTER_REGISTRY, get_adapter
    from .extractors import EXTRACTOR_REGISTRY, get_extractor

# Import safeguards
try:
    from signal_builder.contamination import (
        ContaminationDetector,
        ContaminationReport,
        DEFAULT_KNOWLEDGE_CUTOFF,
    )
    from signal_builder.survivorship import (
        SurvivorshipGuard,
        SurvivorshipBiasReport,
    )
    from signal_builder.trial_tracker import TrialTracker, create_trial_tracker
except ImportError:
    from .contamination import (
        ContaminationDetector,
        ContaminationReport,
        DEFAULT_KNOWLEDGE_CUTOFF,
    )
    from .survivorship import (
        SurvivorshipGuard,
        SurvivorshipBiasReport,
    )
    from .trial_tracker import TrialTracker, create_trial_tracker

logger = logging.getLogger(__name__)


class SignalBuilder:
    """Orchestrates signal construction from hypothesis specification.

    Determines which adapters and extractors are needed, runs them,
    and produces a standardized signal file for the pipeline.

    Usage:
        builder = SignalBuilder()
        signal_path = builder.build(hypothesis_spec)
        # signal_path feeds into pipeline.py as signal_source
    """

    def __init__(
        self,
        output_dir: str = "signals",
        cache_dir: Optional[str] = None,
        verbose: bool = False,
        trial_tracker: Optional["TrialTracker"] = None,
        enable_contamination_detection: bool = True,
        enable_survivorship_guard: bool = True,
        knowledge_cutoff_date: str = DEFAULT_KNOWLEDGE_CUTOFF,
    ):
        self.output_dir = output_dir
        self.cache_dir = cache_dir
        self.verbose = verbose
        self.trial_tracker = trial_tracker
        self.enable_contamination_detection = enable_contamination_detection
        self.enable_survivorship_guard = enable_survivorship_guard
        self.knowledge_cutoff_date = knowledge_cutoff_date
        os.makedirs(output_dir, exist_ok=True)

    def build(
        self,
        hypothesis: HypothesisSpec,
        force_synthetic: bool = False,
    ) -> str:
        """Build a signal file from a hypothesis specification.

        Args:
            hypothesis: Complete hypothesis specification.
            force_synthetic: If True, use synthetic data even when live
                             adapters are available.

        Returns:
            Absolute path to the generated signal file (.parquet).

        Raises:
            UntestableHypothesisError: If the hypothesis cannot be tested
                due to unrecoverable data constraints.
        """
        logger.info(f"SignalBuilder: Building signal for '{hypothesis.name}'")
        logger.info(f"  UUID: {hypothesis.uuid}, Agent: {hypothesis.source_agent}")
        logger.info(f"  Data sources: {[ds.provider for ds in hypothesis.data_sources]}")

        warnings: List[str] = []

        # Step 1: Parse data sources
        data_sources = hypothesis.data_sources
        if not data_sources:
            raise UntestableHypothesisError(
                hypothesis_uuid=hypothesis.uuid,
                reason="No data sources specified in hypothesis",
                data_gap="Hypothesis must specify at least one DataSourceSpec",
            )

        # Step 2: Group data sources by provider, identify needed adapters
        provider_map: Dict[str, List[DataSourceSpec]] = {}
        for ds in data_sources:
            provider_map.setdefault(ds.provider, []).append(ds)

        # Inject universe tickers into data source metadata so adapters
        # know which tickers to fetch (tickers live in universe, not in
        # the data source spec, but adapters need them).
        universe_tickers = hypothesis.universe.custom_tickers or []
        if universe_tickers:
            for specs in provider_map.values():
                for spec in specs:
                    if not spec.metadata.get("tickers"):
                        spec.metadata["tickers"] = universe_tickers

        # Step 3: Acquire raw data from each adapter
        all_raw_data: Dict[str, RawData] = {}
        for provider, specs in provider_map.items():
            try:
                adapter = get_adapter(provider)
            except ValueError as e:
                logger.warning(f"No adapter for '{provider}': {e}")
                warnings.append(f"No adapter for provider '{provider}': {e}")
                continue

            for spec in specs:
                logger.info(f"  Acquiring {spec.source_type} from {provider}...")
                try:
                    raw_data = adapter.acquire(spec)
                    valid, issues = adapter.validate(raw_data)
                    if not valid:
                        logger.warning(
                            f"  Validation issues for {provider}/{spec.source_type}: "
                            f"{'; '.join(issues)}"
                        )
                        warnings.extend(
                            f"[{provider}/{spec.source_type}] {issue}"
                            for issue in issues
                        )

                    all_raw_data[f"{provider}_{spec.source_type}"] = raw_data
                    logger.info(
                        f"    Acquired {len(raw_data.records)} records "
                        f"(synthetic={raw_data.metadata.get('synthetic', False)})"
                    )
                except DataAcquisitionError as e:
                    logger.error(f"  Data acquisition failed: {e}")
                    raise UntestableHypothesisError(
                        hypothesis_uuid=hypothesis.uuid,
                        reason=str(e),
                        data_gap=e.missing_data or str(e.reason),
                    ) from e
                except Exception as e:
                    logger.error(f"  Unexpected error from {provider}: {e}")
                    warnings.append(f"Adapter error [{provider}]: {e}")

        if not all_raw_data:
            raise UntestableHypothesisError(
                hypothesis_uuid=hypothesis.uuid,
                reason="No data could be acquired from any source",
                data_gap=f"Providers: {list(provider_map.keys())}",
            )

        # Step 4: Determine which extractor to use
        extractor_name = self._determine_extractor(hypothesis)
        extractor = get_extractor(extractor_name)
        logger.info(f"  Using extractor: {extractor_name} v{extractor.version}")

        # Step 5: Extract signal
        signal_data = self._extract_signal(
            extractor=extractor,
            raw_data_map=all_raw_data,
            hypothesis=hypothesis,
            force_synthetic=force_synthetic,
        )

        # Step 6: Validate signal
        valid, issues = extractor.validate_signal(signal_data)
        if not valid:
            logger.error(f"Signal validation failed: {issues}")
            raise UntestableHypothesisError(
                hypothesis_uuid=hypothesis.uuid,
                reason=f"Signal validation failed: {'; '.join(issues)}",
                data_gap="Signal extraction produced invalid data",
            )

        # ==================================================================
        # SAFEGUARD 1: Temporal Contamination Detection
        # ==================================================================
        contamination_report = None
        if self.enable_contamination_detection:
            logger.info("  SAFEGUARD 1: Running contamination detection...")
            try:
                # Determine if LLM was used for extraction
                llm_used = (
                    hypothesis.signal.llm_model_used is not None
                    and len(hypothesis.signal.llm_model_used or "") > 0
                )
                extraction_method = signal_data.metadata.extractor_method

                detector = ContaminationDetector(
                    knowledge_cutoff_date=self.knowledge_cutoff_date,
                    extraction_method=extraction_method,
                    llm_used=llm_used,
                )

                # Get the primary raw data
                primary_key = self._select_primary_data_key(all_raw_data, hypothesis)
                raw_data = all_raw_data[primary_key]

                contamination_report = detector.detect(
                    raw_data=raw_data,
                    signal_df=signal_data.df,
                    run_placebo=False,  # Computationally expensive; can enable for critical hypotheses
                )

                logger.info(
                    f"    Contamination risk: {contamination_report.contamination_risk} "
                    f"({contamination_report.pre_cutoff_events} pre-cutoff, "
                    f"{contamination_report.post_cutoff_events} post-cutoff)"
                )

                # Save contamination report alongside signal
                contam_path = os.path.join(
                    self.output_dir, hypothesis.uuid,
                    f"{hypothesis.uuid}_contamination.json",
                )
                os.makedirs(os.path.dirname(contam_path), exist_ok=True)
                detector.save_report(contamination_report, contam_path)

                # Embed in signal metadata
                signal_data.metadata.warnings.extend(
                    [f"[CONTAMINATION] {w}" for w in contamination_report.warnings]
                )

                if contamination_report.contamination_risk == "HIGH":
                    logger.warning(
                        "    CONTAMINATION RISK HIGH: Verdict should be capped to INCONCLUSIVE "
                        "if no post-cutoff data exists."
                    )

            except Exception as e:
                logger.warning(f"    Contamination detection failed (non-fatal): {e}")
                signal_data.metadata.warnings.append(
                    f"[CONTAMINATION] Detection failed: {e}"
                )

        # ==================================================================
        # SAFEGUARD 2: Survivorship Bias Guard
        # ==================================================================
        survivorship_report = None
        if self.enable_survivorship_guard:
            logger.info("  SAFEGUARD 2: Running survivorship bias guard...")
            try:
                guard = SurvivorshipGuard()

                # Build a minimal universe DataFrame from the data we have
                universe_df = self._build_universe_check_df(all_raw_data, hypothesis)

                survivorship_report = guard.validate_universe(
                    universe_df=universe_df,
                    start_date=hypothesis.time_period.start_date,
                    end_date=hypothesis.time_period.end_date,
                    universe_type=hypothesis.universe.universe_type,
                    signal_df=signal_data.df,
                )

                logger.info(
                    f"    Survivorship bias: {survivorship_report.bias_assessment} "
                    f"(cap: {survivorship_report.verdict_confidence_cap}, "
                    f"reliable: {survivorship_report.can_test_reliably})"
                )

                # Save survivorship report alongside signal
                surv_path = os.path.join(
                    self.output_dir, hypothesis.uuid,
                    f"{hypothesis.uuid}_survivorship.json",
                )
                os.makedirs(os.path.dirname(surv_path), exist_ok=True)
                guard.save_report(survivorship_report, surv_path)

                # Embed in signal metadata
                signal_data.metadata.warnings.extend(
                    [f"[SURVIVORSHIP] {w}" for w in survivorship_report.warnings]
                )

                if not survivorship_report.can_test_reliably:
                    logger.warning(
                        "    SURVIVORSHIP BIAS: Universe may not be reliable. "
                        f"Confidence cap: {survivorship_report.verdict_confidence_cap}"
                    )

            except Exception as e:
                logger.warning(f"    Survivorship guard failed (non-fatal): {e}")
                signal_data.metadata.warnings.append(
                    f"[SURVIVORSHIP] Guard failed: {e}"
                )

        # ==================================================================
        # TRIAL TRACKER: Record trial
        # ==================================================================
        if self.trial_tracker is not None:
            logger.info("  TRIAL TRACKER: Recording hypothesis test...")
            try:
                # The trial was already started by the loop runner;
                # ensure the record exists.
                trial_count = self.trial_tracker.get_hypothesis_submission_count(
                    hypothesis.uuid
                )
                logger.info(
                    f"    Hypothesis {hypothesis.uuid}: submission "
                    f"{hypothesis.submission_number} (prior submissions: {trial_count - 1})"
                )

                if self.trial_tracker.is_hypothesis_archived(hypothesis.uuid):
                    logger.warning(
                        f"    HYPOTHESIS ARCHIVED: Refinement cap "
                        f"({trial_count} submissions) reached."
                    )
            except Exception as e:
                logger.debug(f"    Trial tracker note failed (non-fatal): {e}")

        # Step 7: Save signal file
        signal_path = self._save_signal(hypothesis, signal_data)

        # Save safeguards metadata alongside signal
        safeguards_meta = {
            "contamination_risk": contamination_report.contamination_risk if contamination_report else "NOT_CHECKED",
            "contamination_rationale": contamination_report.contamination_rationale if contamination_report else "Contamination detection disabled or failed",
            "knowledge_cutoff_date": self.knowledge_cutoff_date,
            "survivorship_bias_assessment": survivorship_report.bias_assessment if survivorship_report else "NOT_CHECKED",
            "survivorship_verdict_cap": survivorship_report.verdict_confidence_cap if survivorship_report else "NONE",
            "safeguards_version": "1.0.0",
        }
        safeguards_path = os.path.join(
            self.output_dir, hypothesis.uuid,
            f"{hypothesis.uuid}_safeguards.json",
        )
        os.makedirs(os.path.dirname(safeguards_path), exist_ok=True)
        with open(safeguards_path, "w") as f:
            json.dump(safeguards_meta, f, indent=2, default=str)

        logger.info(f"  Signal saved to: {signal_path}")

        return signal_path

    def _determine_extractor(self, hypothesis: HypothesisSpec) -> str:
        """Determine which extractor to use based on the hypothesis's data sources.

        Currently always returns 'linguistic' since it's the primary extractor.
        Future: could route to 'filing_diff' or 'classification' based on
        source_type or signal_name.
        """
        for ds in hypothesis.data_sources:
            source_type = ds.source_type.lower()
            if "fda" in source_type or "document" in source_type:
                return "linguistic"
            if "sec_filing" in source_type or "filing" in source_type:
                return "linguistic"
            if "transcript" in source_type:
                return "linguistic"

        # Default for text-based signals
        signal_type = hypothesis.signal.signal_type
        if signal_type in ("numeric", "composite"):
            return "linguistic"

        return "linguistic"

    def _extract_signal(
        self,
        extractor: SignalExtractor,
        raw_data_map: Dict[str, RawData],
        hypothesis: HypothesisSpec,
        force_synthetic: bool = False,
    ) -> SignalData:
        """Extract the signal from raw data using the chosen extractor.

        Routes data to the extractor with appropriate parameters derived
        from the hypothesis specification.
        """
        # Determine which raw data to use as primary
        primary_key = self._select_primary_data_key(raw_data_map, hypothesis)
        raw_data = raw_data_map[primary_key]

        # Build extraction parameters from hypothesis
        params: Dict[str, Any] = {
            "hypothesis_uuid": hypothesis.uuid,
            "hypothesis_name": hypothesis.name,
            "signal_name": hypothesis.signal.signal_name,
            "higher_is_better": hypothesis.signal.higher_is_better,
        }

        # Map signal name to composite formula
        if "brlas" in hypothesis.name.lower() or "brlas" in (hypothesis.signal.signal_name or "").lower():
            params["composite"] = "brlas"
            params["text_columns"] = {
                "benefit_section_text": "benefit",
                "risk_section_text": "risk",
            }
        elif "departure" in hypothesis.name.lower():
            params["composite"] = "departure_language"
        elif "pronoun" in hypothesis.name.lower():
            params["composite"] = "pronoun_divergence"
        else:
            # Default: use the first text column found
            for col in raw_data.records.columns:
                if "text" in col.lower():
                    params["text_columns"] = {col: "full"}
                    break
            if "text_columns" not in params:
                params["text_columns"] = {}

        # Add LLM config if using LLM extraction
        if hypothesis.signal.llm_model_used:
            params["use_llm"] = True
            params["llm_model"] = hypothesis.signal.llm_model_used
            params["llm_temperature"] = hypothesis.signal.llm_temperature or 0.0
            params["llm_seed"] = hypothesis.signal.llm_seed or 42

        # Select signal column based on what's available
        if "decision" in raw_data.records.columns:
            params["date_column"] = self._find_date_column(raw_data.records)
            params["id_column"] = self._find_id_column(raw_data.records)

        if params.get("composite") == "brlas":
            params["signal_column"] = "composite_score"

        logger.info(f"  Extraction params: {json.dumps(params, default=str)[:200]}")

        signal_data = extractor.extract(raw_data, params)

        # Add additional metadata
        signal_data.metadata.builder_version = "1.0.0"
        signal_data.metadata.hypothesis_uuid = hypothesis.uuid
        signal_data.metadata.hypothesis_name = hypothesis.name
        signal_data.metadata.parameters = params

        return signal_data

    def _select_primary_data_key(
        self,
        raw_data_map: Dict[str, RawData],
        hypothesis: HypothesisSpec,
    ) -> str:
        """Select the primary data source for signal extraction."""
        # Prefer non-price data (text/documents) for signal extraction
        for key in raw_data_map:
            if "fda" in key.lower() or "sec" in key.lower() or "filing" in key.lower():
                return key

        # Fall back to first available
        return list(raw_data_map.keys())[0]

    def _find_date_column(self, df: "pd.DataFrame") -> str:
        """Find a date column in the DataFrame."""
        for col in ["pdufa_date", "advisory_committee_date", "filing_date",
                     "date", "submission_date", "known_date"]:
            if col in df.columns:
                return col
        return ""

    def _find_id_column(self, df: "pd.DataFrame") -> str:
        """Find an identifier column in the DataFrame."""
        for col in ["drug_name", "application_number", "ticker", "cik", "sponsor"]:
            if col in df.columns:
                return col
        return ""

    def _build_universe_check_df(
        self,
        raw_data_map: Dict[str, RawData],
        hypothesis: HypothesisSpec,
    ) -> "pd.DataFrame":
        """Build a minimal universe DataFrame for survivorship bias checking.

        This extracts identifier columns from raw data to create a
        universe-like structure the SurvivorshipGuard can validate.
        """
        import pandas as pd

        records = []
        for key, raw_data in raw_data_map.items():
            if raw_data.records is not None and not raw_data.records.empty:
                df = raw_data.records
                for idx, row in df.iterrows():
                    rec = {
                        "date": row.get("pdufa_date", row.get("submission_date", "")),
                        "ticker": row.get("drug_name", row.get("ticker", row.get("sponsor", "UNKNOWN"))),
                        "entity_id": row.get("application_number", row.get("cik", "")),
                        "company_name": row.get("sponsor", row.get("drug_name", "")),
                        "is_delisted": False,
                        "delisting_date": None,
                        "delisting_return": None,
                    }
                    records.append(rec)

        if not records:
            return pd.DataFrame(columns=["date", "ticker", "entity_id", "is_delisted"])

        return pd.DataFrame(records)

    def _save_signal(
        self,
        hypothesis: HypothesisSpec,
        signal_data: SignalData,
    ) -> str:
        """Save signal data to a parquet file and return the path."""
        output_dir = os.path.join(
            self.output_dir,
            hypothesis.uuid,
        )
        os.makedirs(output_dir, exist_ok=True)

        filename = f"{hypothesis.uuid}_signal.parquet"
        path = os.path.join(output_dir, filename)
        signal_data.save(path)

        # Also save a copy of the hypothesis and metadata for reproducibility
        hypothesis_path = os.path.join(output_dir, f"{hypothesis.uuid}_hypothesis.json")
        with open(hypothesis_path, "w") as f:
            json.dump(hypothesis.to_dict(), f, indent=2, default=str)

        return os.path.abspath(path)


# ============================================================================
# CLI Entry Point
# ============================================================================


def build_signal_from_hypothesis(
    hypothesis_path: str,
    output_dir: str = "signals",
    verbose: bool = False,
) -> str:
    """Build a signal file from a hypothesis JSON file.

    Convenience function for running the signal builder from CLI.

    Args:
        hypothesis_path: Path to hypothesis JSON file.
        output_dir: Directory for signal output.
        verbose: Enable verbose logging.

    Returns:
        Path to the generated signal file.
    """
    if verbose:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    hypothesis = HypothesisSpec.from_json_file(hypothesis_path)

    issues = hypothesis.validate()
    if issues:
        raise ValueError(f"Hypothesis validation failed: {'; '.join(issues)}")

    builder = SignalBuilder(output_dir=output_dir, verbose=verbose)
    signal_path = builder.build(hypothesis)
    return signal_path


def main():
    """CLI entry point for signal builder."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Signal Construction Framework — Build signals from hypotheses",
    )
    parser.add_argument("--hypothesis", required=True, help="Path to hypothesis JSON file")
    parser.add_argument("--output", default="signals", help="Output directory for signal files")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--force-synthetic", action="store_true",
                        help="Force synthetic data even when live adapters available")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    hypothesis = HypothesisSpec.from_json_file(args.hypothesis)

    issues = hypothesis.validate()
    if issues:
        print(f"ERROR: Hypothesis validation failed: {'; '.join(issues)}", file=sys.stderr)
        sys.exit(1)

    builder = SignalBuilder(output_dir=args.output, verbose=args.verbose)

    try:
        signal_path = builder.build(hypothesis, force_synthetic=args.force_synthetic)
        print(f"\nSIGNAL BUILT SUCCESSFULLY")
        print(f"  Path: {signal_path}")
        print(f"  Hypothesis: {hypothesis.name}")
        print(f"  UUID: {hypothesis.uuid}")
    except UntestableHypothesisError as e:
        print(f"\nUNTESTABLE: {e}", file=sys.stderr)
        print(f"  Data gap: {e.data_gap}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
