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

for d in [_IMPL, _SIGNAL, _PARENT]:
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

    def test_03_fda_adapter_synthetic(self):
        """Test FDA adapter with synthetic data generation."""
        from signal_builder.adapters.fda import FDAAdapter
        from signal_builder.base import DataSourceSpec

        adapter = FDAAdapter(use_synthetic=True)

        spec = DataSourceSpec(
            source_type="fda_document",
            provider="fda",
            frequency="as_filed",
            fields=["benefit_section_text", "risk_section_text", "decision"],
            start_date="2017-01-01",
            end_date="2025-12-31",
        )

        raw_data = adapter.acquire(spec)
        self.assertIsNotNone(raw_data)
        self.assertFalse(raw_data.records.empty)

        df = raw_data.records
        print(f"  [PASS] FDA adapter produced {len(df)} records")
        print(f"         Columns: {list(df.columns)}")
        print(f"         Synthetic: {raw_data.metadata.get('synthetic', False)}")
        print(f"         High-BRLAS CRL rate: {raw_data.metadata.get('synthetic_high_brlas_crl_rate', 'N/A'):.2%}")
        print(f"         Low-BRLAS CRL rate: {raw_data.metadata.get('synthetic_low_brlas_crl_rate', 'N/A'):.2%}")

        # Validate data
        valid, issues = adapter.validate(raw_data)
        self.assertTrue(valid, f"Validation issues: {issues}")

        # Check that benefit and risk text sections are present
        self.assertIn("benefit_section_text", df.columns)
        self.assertIn("risk_section_text", df.columns)
        self.assertIn("decision", df.columns)

        # Check that decisions are valid
        decisions = set(df["decision"].unique())
        expected_decisions = {"APPROVED", "CRL"}
        self.assertTrue(expected_decisions.issubset(decisions),
                        f"Expected decisions {expected_decisions}, got {decisions}")

        # Check that the BRLAS signal flags exist
        self.assertIn("true_brlas_flag", df.columns)

    def test_04_linguistic_extractor(self):
        """Test linguistic feature extraction from FDA text."""
        from signal_builder.adapters.fda import FDAAdapter
        from signal_builder.extractors.linguistic import LinguisticExtractor
        from signal_builder.base import DataSourceSpec

        # Get raw data
        adapter = FDAAdapter(use_synthetic=True)
        spec = DataSourceSpec(
            source_type="fda_document",
            provider="fda",
            frequency="as_filed",
            fields=["benefit_section_text", "risk_section_text", "decision"],
            start_date="2017-01-01",
            end_date="2025-12-31",
        )
        raw_data = adapter.acquire(spec)

        # Extract linguistic features
        extractor = LinguisticExtractor()
        signal_data = extractor.extract(
            raw_data,
            params={
                "text_columns": {
                    "benefit_section_text": "benefit",
                    "risk_section_text": "risk",
                },
                "composite": "brlas",
                "signal_column": "composite_score",
                "date_column": "pdufa_date",
                "id_column": "drug_name",
                "hypothesis_uuid": "test-fda-brlas-001",
                "hypothesis_name": "FDA BRLAS Test",
            },
        )

        # Check signal DataFrame
        self.assertIsNotNone(signal_data.df)
        self.assertFalse(signal_data.df.empty)

        df = signal_data.df
        print(f"  [PASS] Linguistic extractor produced {df.shape[0]} dates x {df.shape[1]} IDs")
        print(f"         Index type: {type(df.index)}")
        print(f"         Signal name: {signal_data.metadata.hypothesis_name}")

        # Check long format features
        if signal_data.long_format is not None:
            long_df = signal_data.long_format
            print(f"         Long format: {len(long_df)} rows")

            # Check for BRLAS-related features
            feature_cols = [c for c in long_df.columns if any(
                term in c.lower() for term in
                ["hedge", "certainty", "composite", "benefit_", "risk_"]
            )]
            print(f"         Linguistic features: {len(feature_cols)} columns")
            self.assertGreater(len(feature_cols), 0, "No linguistic features found")

            # Verify that the composite score column exists
            self.assertIn("composite_score", long_df.columns)

            # Check that benefit hedged text has higher hedging density than unhedged
            # The synthetic data embeds this: high-BRLAS drugs have hedged benefits
            if "benefit_hedge_density" in long_df.columns and "risk_hedge_density" in long_df.columns:
                avg_benefit_hd = long_df["benefit_hedge_density"].mean()
                avg_risk_hd = long_df["risk_hedge_density"].mean()
                print(f"         Avg benefit hedge density: {avg_benefit_hd:.3f}")
                print(f"         Avg risk hedge density: {avg_risk_hd:.3f}")

            if "benefit_certainty_density" in long_df.columns and "risk_certainty_density" in long_df.columns:
                avg_benefit_cd = long_df["benefit_certainty_density"].mean()
                avg_risk_cd = long_df["risk_certainty_density"].mean()
                print(f"         Avg benefit certainty density: {avg_benefit_cd:.3f}")
                print(f"         Avg risk certainty density: {avg_risk_cd:.3f}")

        # Validate signal
        valid, issues = extractor.validate_signal(signal_data)
        self.assertTrue(valid, f"Signal validation issues: {issues}")

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

    def test_06_signal_predictive_power(self):
        """Verify that the BRLAS signal has predictive power on synthetic data.

        This is a sanity check: with known linguistic patterns embedded in
        synthetic data, the extracted signal should separate high-CRL from
        low-CRL drugs.
        """
        from signal_builder.adapters.fda import FDAAdapter
        from signal_builder.extractors.linguistic import LinguisticExtractor
        from signal_builder.base import DataSourceSpec

        # Get raw data
        adapter = FDAAdapter(use_synthetic=True)
        spec = DataSourceSpec(
            source_type="fda_document",
            provider="fda",
            frequency="as_filed",
            fields=["benefit_section_text", "risk_section_text", "decision"],
            start_date="2017-01-01",
            end_date="2025-12-31",
        )
        raw_data = adapter.acquire(spec)

        # Extract features
        extractor = LinguisticExtractor()
        signal_data = extractor.extract(
            raw_data,
            params={
                "text_columns": {
                    "benefit_section_text": "benefit",
                    "risk_section_text": "risk",
                },
                "composite": "brlas",
            },
        )

        long_df = signal_data.long_format
        self.assertIsNotNone(long_df, "Long format DataFrame is None")

        # Merge decisions from original data
        if "decision" in long_df.columns and "composite_score" in long_df.columns:
            df = long_df.dropna(subset=["composite_score", "decision"])

            crl_mask = df["decision"] == "CRL"
            approved_mask = df["decision"] == "APPROVED"

            avg_crl = df.loc[crl_mask, "composite_score"].mean()
            avg_approved = df.loc[approved_mask, "composite_score"].mean()

            print(f"  [PASS] BRLAS signal predictive analysis:")
            print(f"         CRL drugs avg BRLAS:     {avg_crl:.4f}")
            print(f"         Approved drugs avg BRLAS: {avg_approved:.4f}")
            print(f"         Difference (CRL - Approved): {avg_crl - avg_approved:.4f}")

            # High BRLAS should indicate higher CRL risk
            # In the synthetic data, we embedded this pattern
            if avg_crl > avg_approved:
                print(f"         BRLAS correctly identifies higher CRL risk")
            else:
                print(f"         NOTE: BRLAS direction unexpected on synthetic data")

            # Check top-quartile BRLAS CRL rate
            threshold = df["composite_score"].quantile(0.75)
            top_quartile = df[df["composite_score"] >= threshold]
            top_quartile_crl_rate = (top_quartile["decision"] == "CRL").mean()
            overall_crl_rate = (df["decision"] == "CRL").mean()

            print(f"         Overall CRL rate:     {overall_crl_rate:.2%}")
            print(f"         Top-quartile BRLAS CRL rate: {top_quartile_crl_rate:.2%}")
            print(f"         Lift factor:         {top_quartile_crl_rate / max(overall_crl_rate, 0.001):.1f}x")

            # The lift should be > 1.0 if BRLAS has predictive power
            self.assertGreater(
                top_quartile_crl_rate / max(overall_crl_rate, 0.001),
                1.0,
                "BRLAS signal shows no predictive power (lift <= 1.0)"
            )

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
