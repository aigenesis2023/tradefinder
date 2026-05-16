"""
run_backtest_from_cache.py — Run backtest directly from pre-built signal parquet.

Bypasses signal building. Downloads price data from Yahoo (with cache),
then runs the pipeline backtest. Designed for cache-only runs.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_IMPL_DIR = os.path.join(_SCRIPT_DIR, "implementation")
sys.path.insert(0, _IMPL_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run_backtest")

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")


def run_backtest(
    signal_parquet: str,
    hypothesis_template: str,
    output_dir: str,
    signal_name: str = "signal",
) -> dict:
    """Load pre-built signal, download prices, run backtest."""
    import pandas as pd
    from pipeline import HypothesisSpec, HypothesisPipeline

    # Load hypothesis template
    with open(hypothesis_template) as f:
        hyp_dict = json.load(f)

    # Override with pre-built signal
    hyp_dict["signal"]["signal_source"] = signal_parquet
    hyp_dict["signal"]["signal_name"] = signal_name

    hyp = HypothesisSpec.from_dict(hyp_dict)

    # Run pipeline
    pipe = HypothesisPipeline(output_dir=output_dir, verbose=True)
    result = pipe.run(hyp)

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run backtest from pre-built signal parquet")
    parser.add_argument("--signal", required=True, help="Path to signal parquet file")
    parser.add_argument("--hypothesis", required=True, help="Path to hypothesis JSON template")
    parser.add_argument("--output", default="/tmp/backtest_results", help="Output directory")
    parser.add_argument("--signal-name", default=None, help="Signal name override")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    # Infer signal name from signal path if not provided
    if args.signal_name is None:
        basename = os.path.basename(args.signal).replace("_signal_cache.parquet", "")
        signal_name = basename
    else:
        signal_name = args.signal_name

    logger.info(f"Running backtest for {signal_name}")
    logger.info(f"  Signal: {args.signal}")
    logger.info(f"  Hypothesis: {args.hypothesis}")
    logger.info(f"  Output: {args.output}")

    try:
        result = run_backtest(
            signal_parquet=args.signal,
            hypothesis_template=args.hypothesis,
            output_dir=os.path.join(args.output, signal_name),
            signal_name=signal_name,
        )
        logger.info(f"Verdict: {result.get('verdict', 'UNKNOWN')}")
        logger.info(f"Reason: {result.get('verdict_reason', 'N/A')}")

        # Save result
        result_path = os.path.join(args.output, f"{signal_name}_result.json")
        with open(result_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        logger.info(f"Result saved to {result_path}")
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        traceback.print_exc()
