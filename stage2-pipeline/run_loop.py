#!/usr/bin/env python3
"""
run_loop.py — Full Loop Runner: Hypothesis -> Signal -> Pipeline -> Verdict
=============================================================================

The loop IS the product. This script makes the loop executable:

    1. signal_builder: HypothesisSpec -> signal parquet file
    2. pipeline.py:     signal parquet file -> empirical verdict

With THREE CRITICAL SAFEGUARDS active by default:
    - TrialTracker: tracks cumulative FDR across all investigation trials
    - ContaminationDetector: flags training-data leakage in LLM-based extraction
    - SurvivorshipGuard: detects and quantifies survivorship bias

Usage:
    python run_loop.py --hypothesis hypothesis.json --output results/
    python run_loop.py --hypothesis hypothesis.json --output results/ --verbose --skip-signal

Output:
    results/{uuid}/
      verdict.json           # Final empirical verdict
      audit_trail.json       # Complete audit trail
      signals/               # Generated signal files
      data/                  # Processed data snapshots
      logs/                  # Pipeline execution logs
      trial_family.json      # Cumulative false discovery rate tracker

The loop is complete when this script produces a verdict based on real
(or realistically synthetic) data — not a manual assessment.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Add implementation directory to path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_IMPL_DIR = os.path.join(_SCRIPT_DIR, "implementation")
_SIGNAL_DIR = os.path.join(_SCRIPT_DIR, "signal_builder")

# The parent of signal_builder (stage2-pipeline/) must be on sys.path
# so that `signal_builder` is importable as a package
for d in [_IMPL_DIR, _SCRIPT_DIR]:
    if d not in sys.path:
        sys.path.insert(0, d)

logger = logging.getLogger("run_loop")


def setup_logging(verbose: bool = False, log_file: Optional[str] = None):
    """Configure loop-wide logging."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers = [logging.StreamHandler(sys.stderr)]
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)


def run_loop(
    hypothesis_path: str,
    output_dir: str = "results",
    verbose: bool = False,
    skip_signal: bool = False,
    force_synthetic: bool = False,
    fmp_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the full loop: hypothesis -> signal -> pipeline -> verdict.

    Args:
        hypothesis_path: Path to hypothesis JSON file.
        output_dir: Root output directory.
        verbose: Enable verbose logging.
        skip_signal: If True, use the signal_source in the hypothesis directly
                     (assume signal is pre-built).
        force_synthetic: Force synthetic data in signal builder.
        fmp_api_key: FMP API key for pipeline.

    Returns:
        Complete results dictionary including verdict.
    """
    os.makedirs(output_dir, exist_ok=True)
    log_file = os.path.join(output_dir, "logs", "loop_run.log")
    setup_logging(verbose=verbose, log_file=log_file)

    start_time = time.time()

    # ================================================================
    # Initialize TrialTracker (SAFEGUARD 3: Cumulative FDR)
    # ================================================================
    try:
        from signal_builder.trial_tracker import create_trial_tracker
        trial_tracker = create_trial_tracker(output_dir=output_dir)
        logger.info("TrialTracker initialized for investigation-wide FDR control.")
    except ImportError:
        logger.warning("TrialTracker not available. Family-wise FDR will not be tracked.")
        trial_tracker = None

    results: Dict[str, Any] = {
        "loop_version": "1.0.0",
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "hypothesis_path": hypothesis_path,
        "output_dir": output_dir,
    }

    logger.info("=" * 70)
    logger.info("LOOP RUNNER v1.0.0 — Full Hypothesis Testing Loop")
    logger.info(f"Hypothesis: {hypothesis_path}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Signal building: {'SKIPPED (pre-built)' if skip_signal else 'ENABLED'}")
    logger.info("=" * 70)

    # -------------------------------------------------------------------
    # Load hypothesis
    # -------------------------------------------------------------------
    try:
        from pipeline import HypothesisSpec as PipelineHypothesisSpec
        hyp = PipelineHypothesisSpec.from_json_file(hypothesis_path)
    except ImportError:
        from signal_builder.base import HypothesisSpec
        hyp = HypothesisSpec.from_json_file(hypothesis_path)

    issues = hyp.validate()
    if issues:
        logger.error(f"Hypothesis validation failed: {'; '.join(issues)}")
        results["error"] = f"Invalid hypothesis: {'; '.join(issues)}"
        return results

    logger.info(f"Hypothesis loaded: {hyp.name} ({hyp.uuid})")
    logger.info(f"  Agent: {hyp.source_agent}, Submission: {hyp.submission_number}")
    logger.info(f"  Universe: {hyp.universe.universe_type}, Holding: {hyp.holding_period_days}d")
    logger.info(f"  Period: {hyp.time_period.start_date} -> {hyp.time_period.end_date}")

    # ================================================================
    # TrialTracker: Record trial start
    # ================================================================
    if trial_tracker is not None:
        try:
            # Check refinement cap
            if trial_tracker.is_hypothesis_archived(hyp.uuid):
                logger.warning(
                    f"HYPOTHESIS ARCHIVED: Refinement cap reached for {hyp.uuid}. "
                    f"Results will be returned as ARCHIVED."
                )
                results["verdict"] = "ARCHIVED (REFINEMENT CAP REACHED)"
                results["verdict_reason"] = (
                    f"Hypothesis {hyp.uuid} has reached the maximum of 3 submission attempts."
                )
                results["elapsed_seconds"] = round(time.time() - start_time, 1)

                # Save loop results
                loop_results_path = os.path.join(output_dir, "loop_results.json")
                with open(loop_results_path, "w") as f:
                    json.dump(results, f, indent=2, default=str)
                return results

            trial_id = trial_tracker.record_trial_start(
                hypothesis_uuid=hyp.uuid,
                submission_number=hyp.submission_number,
                hypothesis_name=hyp.name,
                source_agent=hyp.source_agent,
            )
            if trial_id is None:
                logger.warning("TrialTracker blocked this hypothesis (refinement cap).")
        except Exception as e:
            logger.debug(f"TrialTracker start recording failed (non-fatal): {e}")

    # -------------------------------------------------------------------
    # Stage 1: Build signal (if not skipping)
    # -------------------------------------------------------------------
    signal_path = hyp.signal.signal_source

    if not skip_signal or not signal_path:
        logger.info("-" * 70)
        logger.info("STAGE 1: Building signal from hypothesis...")

        # Ensure imports are available before try block
        from signal_builder.signal_builder import SignalBuilder
        from signal_builder.base import UntestableHypothesisError

        try:
            from signal_builder.signal_builder import SignalBuilder as _SB
            from signal_builder.base import UntestableHypothesisError as _UHE

            signal_output_dir = os.path.join(output_dir, "signals")
            builder = SignalBuilder(
                output_dir=signal_output_dir,
                verbose=verbose,
                trial_tracker=trial_tracker,
            )

            # Convert to signal_builder's HypothesisSpec if needed
            sb_hyp = _convert_to_sb_hypothesis(hyp)

            signal_path = builder.build(sb_hyp, force_synthetic=force_synthetic)

            # Update the hypothesis with the built signal path
            hyp.signal.signal_source = signal_path
            logger.info(f"Signal built: {signal_path}")

        except UntestableHypothesisError as e:
            logger.error(f"UNTESTABLE: {e}")
            results["verdict"] = "UNTESTABLE"
            results["verdict_reason"] = str(e)
            results["data_gap"] = e.data_gap
            return results
        except Exception as e:
            logger.error(f"Signal building failed: {e}")
            results["error"] = f"Signal building failed: {e}"
            return results
    else:
        logger.info(f"STAGE 1: SKIPPED (using pre-built signal: {signal_path})")
        if not os.path.exists(signal_path):
            logger.error(f"Pre-built signal not found: {signal_path}")
            results["error"] = f"Signal file not found: {signal_path}"
            return results

    # -------------------------------------------------------------------
    # Stage 2: Run pipeline
    # -------------------------------------------------------------------
    logger.info("-" * 70)
    logger.info("STAGE 2: Running pipeline...")

    try:
        from pipeline import HypothesisPipeline

        pipeline_output_dir = os.path.join(output_dir, hyp.uuid)
        pipe = HypothesisPipeline(
            output_dir=pipeline_output_dir,
            verbose=verbose,
            fmp_api_key=fmp_api_key,
            trial_tracker=trial_tracker,
        )

        # Ensure the pipeline uses our signal path
        hyp.signal.signal_source = signal_path

        logger.info(f"Pipeline output: {pipeline_output_dir}")
        logger.info(f"Signal source: {hyp.signal.signal_source}")

        verdict_result = pipe.run(hyp)

        results["verdict"] = verdict_result.get("verdict", "UNKNOWN")
        results["verdict_reason"] = verdict_result.get("verdict_reason", "")
        results["pipeline_output"] = verdict_result

    except ImportError:
        logger.warning("pipeline.py import failed; running signal builder only")
        results["warning"] = "Pipeline not available; signal built but not tested"
        results["verdict"] = "SIGNAL_ONLY"
        results["signal_path"] = signal_path
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        results["error"] = f"Pipeline execution failed: {e}"

    # -------------------------------------------------------------------
    # Finalize
    # -------------------------------------------------------------------
    elapsed = time.time() - start_time
    results["elapsed_seconds"] = round(elapsed, 1)
    results["signal_path"] = signal_path

    # ================================================================
    # TrialTracker: Record trial end
    # ================================================================
    if trial_tracker is not None:
        try:
            pipeline_output = results.get("pipeline_output", {})
            verdict_val = results.get("verdict", "UNKNOWN")
            p_value = None
            sharpe = None
            alpha_bps = None

            # Extract p-value and metrics from pipeline output if available
            if isinstance(pipeline_output, dict):
                checks = pipeline_output.get("checks", {})
                metrics_data = pipeline_output.get("metrics", {})

                # Get the permutation p-value as the primary test p-value
                adv_checks = checks.get("adversarial_breakage", {})
                p_value = adv_checks.get("permutation_test_p")

                # Get Sharpe and alpha from metrics
                sharpe = metrics_data.get("sharpe_ratio")
                alpha_bps = metrics_data.get("annualized_return_pct", 0) * 100

            trial_tracker.record_trial_end(
                hypothesis_uuid=hyp.uuid,
                submission_number=hyp.submission_number,
                verdict=verdict_val,
                p_value=p_value,
                sharpe_ratio=sharpe,
                annualized_alpha_bps=alpha_bps,
            )

            # Get investigation-wide context
            investigation_ctx = trial_tracker.get_investigation_context(hyp.uuid)
            if investigation_ctx:
                results["investigation_context"] = investigation_ctx.to_dict()
                logger.info(f"Investigation context: {investigation_ctx.honest_report}")

            # Include investigation summary
            results["trial_family_summary"] = trial_tracker.get_summary()

        except Exception as e:
            logger.debug(f"TrialTracker end recording failed (non-fatal): {e}")

    logger.info("=" * 70)
    verdict = results.get("verdict", "ERROR")
    logger.info(f"FINAL VERDICT: {verdict}")
    if results.get("verdict_reason"):
        logger.info(f"Reason: {results['verdict_reason']}")
    logger.info(f"Elapsed: {elapsed:.1f}s")
    logger.info("=" * 70)

    # Save loop results
    loop_results_path = os.path.join(output_dir, "loop_results.json")
    with open(loop_results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    return results


def _convert_to_sb_hypothesis(pipeline_hyp):
    """Convert a pipeline HypothesisSpec to signal_builder HypothesisSpec."""
    from signal_builder.base import (
        DataSourceSpec,
        HypothesisSpec,
        MinimumEffectSpec,
        PositionSizingSpec,
        SignalSpec,
        TimePeriodSpec,
        UniverseSpec,
    )

    return HypothesisSpec(
        name=pipeline_hyp.name,
        uuid=pipeline_hyp.uuid,
        source_agent=pipeline_hyp.source_agent,
        submission_number=pipeline_hyp.submission_number,
        mechanism=pipeline_hyp.mechanism,
        llm_advantage=pipeline_hyp.llm_advantage,
        why_underweighted=pipeline_hyp.why_underweighted,
        universe=UniverseSpec(
            universe_type=pipeline_hyp.universe.universe_type,
            custom_tickers=pipeline_hyp.universe.custom_tickers,
            min_price=pipeline_hyp.universe.min_price,
            min_daily_volume=pipeline_hyp.universe.min_daily_volume,
            include_delisted=pipeline_hyp.universe.include_delisted,
        ),
        signal=SignalSpec(
            signal_type=pipeline_hyp.signal.signal_type,
            signal_name=pipeline_hyp.signal.signal_name,
            higher_is_better=pipeline_hyp.signal.higher_is_better,
            llm_model_used=pipeline_hyp.signal.llm_model_used,
            llm_temperature=pipeline_hyp.signal.llm_temperature,
            llm_seed=pipeline_hyp.signal.llm_seed,
            llm_is_deterministic=pipeline_hyp.signal.llm_is_deterministic,
            signal_source=pipeline_hyp.signal.signal_source,
        ),
        holding_period_days=pipeline_hyp.holding_period_days,
        time_period=TimePeriodSpec(
            start_date=pipeline_hyp.time_period.start_date,
            end_date=pipeline_hyp.time_period.end_date,
            oos_start_date=pipeline_hyp.time_period.oos_start_date,
            min_training_days=pipeline_hyp.time_period.min_training_days,
            frequency=pipeline_hyp.time_period.frequency,
        ),
        position_sizing=PositionSizingSpec(
            method=pipeline_hyp.position_sizing.method,
            max_position_pct=pipeline_hyp.position_sizing.max_position_pct,
            max_positions=pipeline_hyp.position_sizing.max_positions,
            max_sector_pct=pipeline_hyp.position_sizing.max_sector_pct,
            capital=pipeline_hyp.position_sizing.capital,
            rebalance_frequency=pipeline_hyp.position_sizing.rebalance_frequency,
        ),
        minimum_effect_size=MinimumEffectSpec(
            annualized_alpha_bps=pipeline_hyp.minimum_effect_size.annualized_alpha_bps,
            sharpe_ratio=pipeline_hyp.minimum_effect_size.sharpe_ratio,
            information_coefficient=pipeline_hyp.minimum_effect_size.information_coefficient,
            hit_rate=pipeline_hyp.minimum_effect_size.hit_rate,
            max_drawdown_pct=pipeline_hyp.minimum_effect_size.max_drawdown_pct,
        ),
        data_sources=[
            DataSourceSpec(
                source_type=ds.source_type,
                provider=ds.provider,
                frequency=ds.frequency,
                fields=ds.fields,
                start_date=ds.start_date,
                end_date=ds.end_date,
                known_biases=ds.known_biases,
                api_tier=ds.api_tier,
                monthly_cost_usd=ds.monthly_cost_usd,
            )
            for ds in pipeline_hyp.data_sources
        ],
        falsifiable_prediction=pipeline_hyp.falsifiable_prediction,
        self_assessed_confidence=pipeline_hyp.self_assessed_confidence,
        biggest_weakness=pipeline_hyp.biggest_weakness,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run the full hypothesis testing loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_loop.py --hypothesis hypo.json --output results/
  python run_loop.py --hypothesis hypo.json --output results/ --verbose
  python run_loop.py --hypothesis hypo.json --output results/ --skip-signal
        """,
    )
    parser.add_argument("--hypothesis", required=True,
                        help="Path to hypothesis JSON file")
    parser.add_argument("--output", default="results",
                        help="Output directory (default: results/)")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable verbose logging")
    parser.add_argument("--skip-signal", action="store_true",
                        help="Skip signal building (use pre-built signal_source)")
    parser.add_argument("--force-synthetic", action="store_true",
                        help="Force synthetic data in signal builder")
    parser.add_argument("--fmp-key", default=None,
                        help="FMP API key for pipeline")

    args = parser.parse_args()

    if not os.path.exists(args.hypothesis):
        print(f"ERROR: Hypothesis file not found: {args.hypothesis}", file=sys.stderr)
        sys.exit(1)

    results = run_loop(
        hypothesis_path=args.hypothesis,
        output_dir=args.output,
        verbose=args.verbose,
        skip_signal=args.skip_signal,
        force_synthetic=args.force_synthetic,
        fmp_api_key=args.fmp_key,
    )

    verdict = results.get("verdict", "ERROR")
    if verdict == "UNTESTABLE":
        print(f"\nVERDICT: UNTESTABLE — {results.get('verdict_reason', '')}")
        sys.exit(2)
    elif "error" in results:
        print(f"\nERROR: {results['error']}")
        sys.exit(3)
    else:
        print(f"\nVERDICT: {verdict}")
        print(f"Reason: {results.get('verdict_reason', 'N/A')}")
        sys.exit(0)


if __name__ == "__main__":
    main()
