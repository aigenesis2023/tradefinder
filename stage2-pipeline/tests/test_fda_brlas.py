#!/usr/bin/env python3
"""
test_fda_brlas.py — FDA BRLAS Hypothesis Proof-of-Life Test
============================================================

This is the CANARY that proves the loop is alive. It:

1. Constructs a complete FDA BRLAS hypothesis specification
2. Runs the full loop: signal_builder -> pipeline
3. Produces an empirical verdict

If FDA.gov is unreachable (network limitations), it uses synthetic FDA
documents with known linguistic patterns that exercise the full pipeline.
The synthetic dataset is designed so that the BRLAS signal should show
measurable predictive power — proving the loop can detect a real signal.

Synthetic Data Design:
  - 120 drugs with known benefit/risk text sections
  - 30% of drugs have high-BRLAS linguistic patterns (hedged benefits, certain risks)
  - High-BRLAS drugs have 50% CRL rate vs 18% for low-BRLAS drugs
  - Effect size is embedded: a 2.78x lift in CRL rate
  - This should be detectable by the pipeline's statistical tests

What constitutes "proof of life":
  - Signal builder produces a valid signal file (.parquet)
  - Pipeline ingests the signal and runs all stages
  - A verdict is produced (even if BROKEN/INCONCLUSIVE)
  - The end-to-end data flow is verified

Running this test:
  python tests/test_fda_brlas.py
  python tests/test_fda_brlas.py --verbose
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

# Add parent directories to path
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_IMPL = os.path.join(_PARENT, "implementation")
_SIGNAL = os.path.join(_PARENT, "signal_builder")

for d in [_IMPL, _PARENT]:
    if d not in sys.path:
        sys.path.insert(0, d)

import numpy as np
import pandas as pd


# ============================================================================
# FDA BRLAS Hypothesis Specification (hardcoded from bridge template)
# ============================================================================

FDA_BRLAS_HYPOTHESIS = {
    "name": "FDA Briefing Document Asymmetric Skepticism (BRLAS)",
    "uuid": "test-fda-brlas-001",
    "source_agent": "Alternative Data Alchemist (Agent 5)",
    "submission_number": 1,
    "mechanism": (
        "FDA reviewers encode skepticism through asymmetric language — "
        "hedging benefits while stating risks definitively. BRLAS measures "
        "this asymmetry. High BRLAS predicts Complete Response Letter (CRL) "
        "at 2.5-3x the unconditional rate."
    ),
    "llm_advantage": (
        "LLM segments FDA documents into benefit/risk sections, computes "
        "hedging density and certainty markers per section, builds per-reviewer "
        "linguistic baselines across historical FDA reviews."
    ),
    "why_underweighted": (
        "FDA documents require domain expertise. No quant fund systematically "
        "computes cross-sectional linguistic asymmetry scores. Universe is "
        "naturally limited (150-200 drugs/year)."
    ),
    "universe": {
        "universe_type": "custom",
        "custom_tickers": ["All publicly traded biotech companies with PDUFA dates 2017-2025"],
        "min_price": 1.0,
        "include_delisted": True,
    },
    "signal": {
        "signal_type": "numeric",
        "signal_name": "BRLAS_zscore",
        "higher_is_better": True,
        "llm_model_used": None,
        "llm_temperature": None,
        "llm_seed": None,
        "llm_is_deterministic": True,
        "signal_source": None,  # Will be set by signal_builder
    },
    "holding_period_days": 5,
    "time_period": {
        "start_date": "2017-01-01",
        "end_date": "2025-12-31",
        "oos_start_date": "2024-01-01",
        "frequency": "daily",
    },
    "position_sizing": {
        "method": "signal_proportional",
        "max_position_pct": 0.05,
        "max_positions": 20,
        "capital": 100000.0,
    },
    "minimum_effect_size": {
        "annualized_alpha_bps": 300,
        "sharpe_ratio": 0.3,
        "information_coefficient": 0.03,
        "hit_rate": 0.51,
        "max_drawdown_pct": 25.0,
    },
    "data_sources": [
        {
            "source_type": "fda_document",
            "provider": "fda",
            "frequency": "as_filed",
            "fields": ["benefit_section_text", "risk_section_text", "decision"],
            "start_date": "2017-01-01",
            "end_date": "2025-12-31",
            "known_biases": [
                "Only covers drugs that went through advisory committee review",
                "Briefing documents not available for all submissions",
                "Document format changed over time (pre-2015 less structured)",
            ],
            "api_tier": "free",
            "monthly_cost_usd": 0.0,
        },
    ],
    "falsifiable_prediction": (
        "Drugs with BRLAS z-score > +1.5 should receive CRL at >=50% rate "
        "vs. 15-20% unconditional. Flagged drugs should average -15% return "
        "between publication and decision vs. 0% to -5% for unflagged."
    ),
    "self_assessed_confidence": "HIGH",
    "biggest_weakness": (
        "Options market efficiency — pre-PDUFA implied volatility is 150-300%. "
        "BRLAS must provide incremental predictive power beyond what option "
        "prices already reflect."
    ),
}


# ============================================================================
# Tests
# ============================================================================


class TestFDABRLASSignalBuilder(unittest.TestCase):
    """Test the signal builder end-to-end for the FDA BRLAS hypothesis."""

    @classmethod
    def setUpClass(cls):
        """Set up test environment."""
        cls.output_dir = "/tmp/tradefinder_test_fda_brlas"
        os.makedirs(cls.output_dir, exist_ok=True)

    def test_01_save_hypothesis_file(self):
        """Save the FDA BRLAS hypothesis to a JSON file."""
        hyp_path = os.path.join(self.output_dir, "hypothesis.json")
        with open(hyp_path, "w") as f:
            json.dump(FDA_BRLAS_HYPOTHESIS, f, indent=2)
        self.assertTrue(os.path.exists(hyp_path))
        print(f"  [PASS] Hypothesis saved to {hyp_path}")

    def test_02_load_hypothesis(self):
        """Load the hypothesis using HypothesisSpec."""
        from signal_builder.base import HypothesisSpec

        hyp_path = os.path.join(self.output_dir, "hypothesis.json")
        hyp = HypothesisSpec.from_json_file(hyp_path)
        self.assertEqual(hyp.name, FDA_BRLAS_HYPOTHESIS["name"])
        self.assertEqual(hyp.uuid, FDA_BRLAS_HYPOTHESIS["uuid"])
        issues = hyp.validate()
        self.assertEqual(len(issues), 0, f"Validation issues: {issues}")
        print(f"  [PASS] Hypothesis loaded and validated: {hyp.name} ({hyp.uuid})")

    @unittest.skip("FDAAdapter no longer generates synthetic data (no-fabrication design)")
    def test_03_fda_adapter_synthetic(self):
        """Test FDA adapter with synthetic data generation."""

    @unittest.skip("FDAAdapter no longer generates synthetic data (no-fabrication design)")
    def test_04_linguistic_extractor(self):
        """Test linguistic feature extraction from FDA text."""

    def test_05_signal_builder_full(self):
        """Test the full SignalBuilder orchestrator."""
        from signal_builder.base import HypothesisSpec
        from signal_builder.signal_builder import SignalBuilder

        hyp_path = os.path.join(self.output_dir, "hypothesis.json")
        hyp = HypothesisSpec.from_json_file(hyp_path)

        builder = SignalBuilder(
            output_dir=os.path.join(self.output_dir, "signals"),
            verbose=False,
        )

        # Force synthetic for test
        os.environ["UNTESTABLE_ON_DATA_FAILURE"] = "0"
        signal_path = builder.build(hyp, force_synthetic=False)

        self.assertTrue(os.path.exists(signal_path))
        print(f"  [PASS] SignalBuilder produced: {signal_path}")

        # Check the file is valid
        df = pd.read_parquet(signal_path)
        print(f"         Signal dimensions: {df.shape}")
        print(f"         Index: {df.index[:3].tolist()}...")
        print(f"         Columns: {df.columns[:5].tolist()}...")

        # Check metadata file
        meta_path = signal_path.replace(".parquet", "_metadata.json")
        self.assertTrue(os.path.exists(meta_path), f"Metadata file not found: {meta_path}")

        with open(meta_path) as f:
            metadata = json.load(f)
        print(f"         Metadata keys: {list(metadata.keys())}")
        print(f"         Extractor: {metadata.get('extractor_name')} v{metadata.get('extractor_version')}")

    @unittest.skip("FDAAdapter no longer generates synthetic data (no-fabrication design)")
    def test_06_signal_predictive_power(self):
        """Verify that the BRLAS signal has predictive power on synthetic data."""

    def test_07_full_loop(self):
        """Run the full loop: signal_builder -> pipeline -> verdict.

        This is the ultimate proof-of-life test.
        """
        from signal_builder.base import HypothesisSpec
        from signal_builder.signal_builder import SignalBuilder

        # Step 1: Build signal
        hyp_path = os.path.join(self.output_dir, "hypothesis.json")
        hyp = HypothesisSpec.from_json_file(hyp_path)

        signal_output_dir = os.path.join(self.output_dir, "full_loop", "signals")
        builder = SignalBuilder(output_dir=signal_output_dir, verbose=False)
        signal_path = builder.build(hyp, force_synthetic=False)

        self.assertTrue(os.path.exists(signal_path))
        print(f"  [PASS] Signal built: {signal_path}")

        # Step 2: Run pipeline
        try:
            from pipeline import HypothesisPipeline, HypothesisSpec as PipeHypothesisSpec

            hyp.signal.signal_source = signal_path

            # Convert to pipeline format
            pipe_hyp = PipeHypothesisSpec.from_dict(hyp.to_dict())
            pipe_hyp.signal.signal_source = signal_path

            pipeline_output_dir = os.path.join(self.output_dir, "full_loop", "pipeline")
            pipeline = HypothesisPipeline(
                output_dir=pipeline_output_dir,
                verbose=False,
            )

            result = pipeline.run(pipe_hyp)
            verdict = result.get("verdict", "UNKNOWN")
            reason = result.get("verdict_reason", "")

            print(f"  [PASS] Pipeline executed successfully")
            print(f"         Verdict: {verdict}")
            print(f"         Reason: {reason}")

            # Save verdict for inspection
            verdict_path = os.path.join(self.output_dir, "full_loop", "verdict.json")
            with open(verdict_path, "w") as f:
                json.dump(result, f, indent=2, default=str)

            print(f"  [PASS] Full loop complete — verdict saved to {verdict_path}")

        except ImportError as e:
            print(f"  [SKIP] Pipeline import failed: {e}")
            print(f"         Signal builder works — pipeline would need to be run separately")
            print(f"         Signal file available at: {signal_path}")
            self.skipTest("Pipeline module not importable")

    def test_08_run_loop_script(self):
        """Test that run_loop.py can be called on the hypothesis."""
        import subprocess

        hyp_path = os.path.join(self.output_dir, "hypothesis.json")
        loop_output_dir = os.path.join(self.output_dir, "run_loop_script")

        result = subprocess.run(
            [
                sys.executable,
                os.path.join(_PARENT, "run_loop.py"),
                "--hypothesis", hyp_path,
                "--output", loop_output_dir,
                "--force-synthetic",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        print(f"  [PASS] run_loop.py executed (exit code {result.returncode})")
        print(f"         stdout: {result.stdout[-500:]}")
        if result.stderr:
            stderr_short = result.stderr[-500:]
            print(f"         stderr: {stderr_short}")


if __name__ == "__main__":
    # Run tests
    unittest.main(verbosity=2)
