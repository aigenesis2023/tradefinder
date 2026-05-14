"""
audit.py — Reproducibility, Seeding, and Audit Trail Generation
================================================================

Agent 7: Reproducibility & Audit Specialist

This module ensures that every test is fully reproducible. Every verdict can
be traced back to raw data and exact code. The output format allows anyone
to verify the result independently.

Key responsibilities:
- Deterministic random seeds for all stochastic operations
- Versioned data snapshots with content hashing
- Complete audit trail from raw data to final verdict
- LLM non-determinism handling
- Pipeline run metadata tracking
- Output format specification

DESIGN NOTE (Reproducibility Specialist):
A result that cannot be reproduced is not a result; it is an anecdote.
Every random operation must use a fixed, documented seed. Every data
transformation must be logged. Every verdict must be traceable.
"""

import hashlib
import json
import logging
import os
import platform
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================================
# Constants — Master Random Seeds
# ============================================================================

# These seeds are FIXED and NEVER change. They are documented in the spec.
GLOBAL_SEED = 42
BOOTSTRAP_SEED = 137
PERMUTATION_SEED = 841
TRAIN_TEST_SEED = 580
FACTOR_SEED = 733
REGIME_SEED = 251
POSITION_SEED = 364
BREAKER_SEED = 629
AUDIT_SEED = 915

# Map of seed names to values
ALL_SEEDS = {
    "global": GLOBAL_SEED,
    "bootstrap": BOOTSTRAP_SEED,
    "permutation": PERMUTATION_SEED,
    "train_test": TRAIN_TEST_SEED,
    "factor": FACTOR_SEED,
    "regime": REGIME_SEED,
    "position": POSITION_SEED,
    "breaker": BREAKER_SEED,
    "audit": AUDIT_SEED,
}


# ============================================================================
# Hypothesis-Specific Seed Derivation
# ============================================================================


def get_hypothesis_seed(hypothesis_uuid: str, base_seed: int) -> int:
    """
    Derive a deterministic seed from hypothesis UUID and base seed.

    This ensures different hypotheses get different but reproducible
    random sequences. Critical for honest multiple hypothesis testing.

    The 32-bit modulo prevents integer overflow while maintaining
    deterministic reproducibility.
    """
    uuid_hash = int(hashlib.sha256(hypothesis_uuid.encode()).hexdigest()[:8], 16)
    return (base_seed + uuid_hash) % (2 ** 31)


def get_all_hypothesis_seeds(hypothesis_uuid: str) -> Dict[str, int]:
    """
    Generate all seeds for a given hypothesis.

    Returns:
        Dict mapping seed name to derived seed value
    """
    return {
        name: get_hypothesis_seed(hypothesis_uuid, value)
        for name, value in ALL_SEEDS.items()
    }


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class AuditEntry:
    """A single entry in the audit trail."""

    timestamp: str                      # ISO 8601
    stage: str                          # 'universe' | 'temporal' | 'backtest' | 'statistics' | ...
    operation: str                      # 'universe_construction' | 'bootstrap_ci' | ...
    inputs: Dict[str, Any]              # Hash or summary of inputs
    outputs: Dict[str, Any]             # Hash or summary of outputs
    parameters: Dict[str, Any]          # Parameters used
    data_hashes: Dict[str, str]         # SHA-256 hashes of data files/sources
    random_state: Optional[Dict[str, Any]] = None  # Random state before/after if applicable
    warnings: List[str] = field(default_factory=list)
    duration_seconds: Optional[float] = None


@dataclass
class AuditTrail:
    """Complete audit trail for a pipeline run."""

    # Identity
    pipeline_version: str
    hypothesis_uuid: str
    hypothesis_name: str
    run_id: str                         # Unique run identifier
    run_timestamp: str                  # ISO 8601

    # Environment
    python_version: str
    platform_info: str
    package_versions: Dict[str, str]
    git_hash: Optional[str]

    # Seeds
    seeds: Dict[str, int]

    # Data sources
    data_sources: List[Dict[str, str]]  # source_name, access_timestamp, content_hash

    # Execution steps
    entries: List[AuditEntry] = field(default_factory=list)

    # Final outputs
    output_hashes: Dict[str, str] = field(default_factory=dict)

    # LLM model metadata (if applicable)
    llm_metadata: Optional[Dict[str, Any]] = None


@dataclass
class PipelineRunMetadata:
    """Metadata for a single pipeline execution."""

    run_id: str
    hypothesis_uuid: str
    hypothesis_name: str
    start_time: str
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    status: str = "RUNNING"             # RUNNING | COMPLETED | FAILED
    error_message: Optional[str] = None
    verdict: Optional[str] = None       # SURVIVED | BROKEN | INCONCLUSIVE | UNTESTABLE


# ============================================================================
# Audit Trail Generator
# ============================================================================


class AuditTrailGenerator:
    """
    Generates complete, verifiable audit trails for every pipeline run.

    Every data transformation, every statistical test, every random operation
    is logged with its inputs, outputs, parameters, and data hashes.

    The resulting audit trail can be independently verified by replaying
    the operations in order.
    """

    def __init__(
        self,
        pipeline_version: str = "1.0.0",
        data_directory: Optional[str] = None,
        output_directory: Optional[str] = None,
    ):
        self.pipeline_version = pipeline_version
        self.data_directory = data_directory
        self.output_directory = output_directory

        self.entries: List[AuditEntry] = []
        self._stage_timers: Dict[str, datetime] = {}

    def initialize_trail(
        self,
        hypothesis_uuid: str,
        hypothesis_name: str,
        package_versions: Optional[Dict[str, str]] = None,
        git_hash: Optional[str] = None,
    ) -> AuditTrail:
        """
        Initialize a new audit trail for a hypothesis test run.
        """
        run_id = self._generate_run_id(hypothesis_uuid)

        # Capture environment
        if package_versions is None:
            package_versions = self._capture_package_versions()

        seeds = get_all_hypothesis_seeds(hypothesis_uuid)

        self.trail = AuditTrail(
            pipeline_version=self.pipeline_version,
            hypothesis_uuid=hypothesis_uuid,
            hypothesis_name=hypothesis_name,
            run_id=run_id,
            run_timestamp=datetime.now(timezone.utc).isoformat(),
            python_version=sys.version,
            platform_info=platform.platform(),
            package_versions=package_versions,
            git_hash=git_hash,
            seeds=seeds,
            data_sources=[],
            entries=[],
        )

        return self.trail

    def _generate_run_id(self, hypothesis_uuid: str) -> str:
        """Generate a unique run identifier."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        uuid_short = hypothesis_uuid[:8] if len(hypothesis_uuid) >= 8 else hypothesis_uuid
        return f"run_{timestamp}_{uuid_short}"

    def _capture_package_versions(self) -> Dict[str, str]:
        """Capture installed package versions."""
        versions = {}
        key_packages = [
            "numpy", "pandas", "scipy", "statsmodels", "scikit-learn",
            "matplotlib", "seaborn", "pyarrow",
        ]

        for pkg in key_packages:
            try:
                module = __import__(pkg)
                versions[pkg] = getattr(module, "__version__", "unknown")
            except ImportError:
                versions[pkg] = "not_installed"

        return versions

    def start_stage(self, stage: str) -> None:
        """Record the start of a processing stage."""
        self._stage_timers[stage] = datetime.now()

    def log_operation(
        self,
        stage: str,
        operation: str,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        parameters: Dict[str, Any],
        data_hashes: Optional[Dict[str, str]] = None,
        warnings: Optional[List[str]] = None,
        random_state: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """
        Log a single operation to the audit trail.

        Args:
            stage: Processing stage ('universe', 'temporal', 'backtest', etc.)
            operation: Specific operation name
            inputs: Summary/hashes of inputs
            outputs: Summary/hashes of outputs
            parameters: Parameters used
            data_hashes: SHA-256 hashes of data files
            warnings: Any warnings generated
            random_state: Random state before/after (for reproducibility)

        Returns:
            The AuditEntry that was created and appended
        """
        start_time = self._stage_timers.get(stage, datetime.now())
        duration = (datetime.now() - start_time).total_seconds()

        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            stage=stage,
            operation=operation,
            inputs=inputs,
            outputs=outputs,
            parameters=parameters,
            data_hashes=data_hashes or {},
            random_state=random_state,
            warnings=warnings or [],
            duration_seconds=duration,
        )

        self.entries.append(entry)
        self.trail.entries.append(entry)

        logger.debug(
            f"[{stage}] {operation} completed in {duration:.2f}s"
        )

        return entry

    def log_data_source(
        self,
        source_name: str,
        access_timestamp: str,
        content_hash: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> None:
        """Log a data source access."""
        self.trail.data_sources.append({
            "source_name": source_name,
            "access_timestamp": access_timestamp,
            "content_hash": content_hash,
            "metadata": metadata or {},
        })

    def log_llm_usage(
        self,
        model_name: str,
        model_version: str,
        temperature: float,
        seed: int,
        is_deterministic: bool,
        extraction_step: str,
        input_hash: str,
        output_hash: str,
        quant_config: Optional[str] = None,
    ) -> None:
        """
        Log LLM usage for a specific extraction step.

        This is critical for reproducibility. Non-deterministic LLM outputs
        make the entire pipeline non-reproducible if not properly documented.
        """
        if self.trail.llm_metadata is None:
            self.trail.llm_metadata = []

        self.trail.llm_metadata.append({
            "model_name": model_name,
            "model_version": model_version,
            "temperature": temperature,
            "seed": seed,
            "is_deterministic": is_deterministic,
            "extraction_step": extraction_step,
            "input_data_hash": input_hash,
            "output_data_hash": output_hash,
            "quant_config": quant_config,
        })

    def finalize_trail(
        self,
        output_files: Dict[str, str],  # filename -> filepath
        verdict: str,
    ) -> AuditTrail:
        """Finalize the audit trail with output file hashes."""
        # Compute output file hashes
        for filename, filepath in output_files.items():
            if os.path.exists(filepath):
                self.trail.output_hashes[filename] = self.compute_file_hash(filepath)
            else:
                self.trail.output_hashes[filename] = "FILE_NOT_FOUND"

        # Add final summary entry
        summary_entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            stage="complete",
            operation="pipeline_complete",
            inputs={"hypothesis_uuid": self.trail.hypothesis_uuid},
            outputs={"verdict": verdict, "output_hashes": self.trail.output_hashes},
            parameters={"pipeline_version": self.pipeline_version},
            data_hashes={},
        )
        self.trail.entries.append(summary_entry)

        return self.trail

    @staticmethod
    def compute_data_hash(data: Any) -> str:
        """
        Compute a SHA-256 hash of data for integrity verification.

        Handles DataFrames, Series, arrays, dicts, lists, and strings.
        """
        if isinstance(data, (pd.DataFrame, pd.Series)):
            # Hash the underlying values
            content = data.to_json().encode("utf-8")
        elif isinstance(data, np.ndarray):
            content = data.tobytes()
        elif isinstance(data, (dict, list)):
            content = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        elif isinstance(data, bytes):
            content = data
        else:
            content = str(data).encode("utf-8")

        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def compute_file_hash(filepath: str) -> str:
        """Compute SHA-256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def export_trail(self, output_path: str) -> str:
        """
        Export the complete audit trail to a JSON file.

        Returns:
            Path to the exported file
        """
        output = {
            "pipeline_version": self.trail.pipeline_version,
            "hypothesis_uuid": self.trail.hypothesis_uuid,
            "hypothesis_name": self.trail.hypothesis_name,
            "run_id": self.trail.run_id,
            "run_timestamp": self.trail.run_timestamp,
            "python_version": self.trail.python_version,
            "platform_info": self.trail.platform_info,
            "package_versions": self.trail.package_versions,
            "git_hash": self.trail.git_hash,
            "seeds": self.trail.seeds,
            "data_sources": self.trail.data_sources,
            "llm_metadata": self.trail.llm_metadata,
            "entries": [
                {
                    "timestamp": e.timestamp,
                    "stage": e.stage,
                    "operation": e.operation,
                    "inputs": {k: str(v)[:200] for k, v in e.inputs.items()},
                    "outputs": {k: str(v)[:200] for k, v in e.outputs.items()},
                    "parameters": e.parameters,
                    "data_hashes": e.data_hashes,
                    "warnings": e.warnings,
                    "duration_seconds": e.duration_seconds,
                    "random_state": e.random_state,
                }
                for e in self.trail.entries
            ],
            "output_hashes": self.trail.output_hashes,
            "audit_trail_hash": self.compute_file_hash(output_path) if os.path.exists(output_path) else "N/A",
        }

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, default=str)

        logger.info(f"Audit trail exported to {output_path}")
        return output_path


# ============================================================================
# Reproducibility Manager
# ============================================================================


class ReproducibilityManager:
    """
    Ensures complete reproducibility of every pipeline run.

    Responsibilities:
    - Set and verify deterministic random seeds
    - Verify data integrity before processing
    - Log all version information
    - Detect non-reproducible data sources
    - Enforce LLM determinism requirements
    """

    def __init__(self, hypothesis_uuid: str):
        self.hypothesis_uuid = hypothesis_uuid
        self.seeds = get_all_hypothesis_seeds(hypothesis_uuid)
        self.non_reproducible_sources: List[str] = []

    def set_all_seeds(self) -> Dict[str, int]:
        """
        Set all random seeds for reproducibility.

        Returns:
            Dict of seed name -> value for audit trail
        """
        # Set NumPy seed
        np.random.seed(self.seeds["global"])

        # Set Python random seed
        import random
        random.seed(self.seeds["global"])

        # Record the state for verification
        return self.seeds

    def verify_seed_integrity(self) -> bool:
        """
        Verify that seeds are correctly set and haven't been tampered with.

        Generates a known sequence and checks it against expected values.
        """
        rng = np.random.RandomState(self.seeds["global"])
        test_sequence = rng.rand(5)

        # Expected test sequence for global seed=42
        expected = np.random.RandomState(42).rand(5)

        match = np.allclose(test_sequence, expected)
        if not match:
            logger.error("SEED INTEGRITY CHECK FAILED. Seeds may have been tampered with.")

        return match

    def check_data_reproducibility(self, source_name: str, source_type: str) -> bool:
        """
        Check whether a data source can produce reproducible results.

        Dynamic APIs (live prices, news feeds) may return different data
        on different calls. These are flagged as non-reproducible.

        Returns:
            True if the data source is reproducible
        """
        non_reproducible_types = [
            "live_api", "realtime_feed", "streaming",
        ]

        if source_type in non_reproducible_types:
            self.non_reproducible_sources.append(source_name)
            logger.warning(
                f"Data source '{source_name}' ({source_type}) is non-reproducible. "
                f"Results may not be exactly reproducible without data snapshot."
            )
            return False

        return True

    def generate_reproducibility_report(self) -> Dict[str, Any]:
        """
        Generate a reproducibility assessment for the pipeline run.
        """
        all_reproducible = len(self.non_reproducible_sources) == 0

        return {
            "hypothesis_uuid": self.hypothesis_uuid,
            "seeds_used": self.seeds,
            "seeds_verified": self.verify_seed_integrity(),
            "all_sources_reproducible": all_reproducible,
            "non_reproducible_sources": self.non_reproducible_sources,
            "python_version": sys.version,
            "platform": platform.platform(),
            "recommendation": (
                "Full reproducibility confirmed."
                if all_reproducible
                else "Some data sources are non-reproducible. Results should be "
                     "validated with data snapshots."
            ),
        }


# ============================================================================
# Data Snapshot Manager
# ============================================================================


class DataSnapshotManager:
    """
    Manages versioned data snapshots for reproducibility.

    All input data is cached with content hashing. If data sources are dynamic,
    snapshots ensure that the same input data can be replayed.
    """

    def __init__(self, snapshot_directory: str):
        self.snapshot_directory = snapshot_directory
        os.makedirs(snapshot_directory, exist_ok=True)

    def save_snapshot(
        self,
        data: Union[pd.DataFrame, pd.Series, Dict],
        name: str,
        run_id: str,
    ) -> str:
        """
        Save a data snapshot with versioning. Falls back to CSV if parquet engine unavailable.

        Args:
            data: Data to snapshot
            name: Logical name of the dataset
            run_id: Unique run identifier

        Returns:
            SHA-256 hash of the saved data
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        # Try parquet first, fall back to CSV
        try:
            import pyarrow  # noqa: F401
            _use_parquet = True
        except ImportError:
            try:
                import fastparquet  # noqa: F401
                _use_parquet = True
            except ImportError:
                _use_parquet = False

        ext = "parquet" if _use_parquet else "csv"
        filename = f"{name}_{run_id}_{timestamp}.{ext}"
        filepath = os.path.join(self.snapshot_directory, filename)

        if isinstance(data, pd.DataFrame):
            if _use_parquet:
                data.to_parquet(filepath, index=True)
            else:
                data.to_csv(filepath, index=True)
        elif isinstance(data, pd.Series):
            df = data.to_frame(name if name else "value")
            if _use_parquet:
                df.to_parquet(filepath, index=True)
            else:
                df.to_csv(filepath, index=True)
        elif isinstance(data, dict):
            df = pd.DataFrame([data])
            if _use_parquet:
                df.to_parquet(filepath)
            else:
                df.to_csv(filepath, index=True)
        else:
            raise ValueError(f"Unsupported snapshot type: {type(data)}")

        file_hash = AuditTrailGenerator.compute_file_hash(filepath)

        # Save metadata
        meta_path = filepath + ".meta.json"
        with open(meta_path, "w") as f:
            json.dump({
                "name": name,
                "run_id": run_id,
                "timestamp": timestamp,
                "file_hash": file_hash,
                "row_count": len(data) if hasattr(data, "__len__") else 1,
                "format": ext,
            }, f, indent=2)

        logger.info(f"Snapshot saved: {filename} (hash: {file_hash[:16]}...)")
        return file_hash

    def load_snapshot(self, filepath: str, verify_hash: Optional[str] = None) -> pd.DataFrame:
        """
        Load a previously saved snapshot and optionally verify integrity.
        """
        if verify_hash:
            actual_hash = AuditTrailGenerator.compute_file_hash(filepath)
            if actual_hash != verify_hash:
                raise ValueError(
                    f"Snapshot integrity check FAILED for {filepath}. "
                    f"Expected {verify_hash[:16]}..., got {actual_hash[:16]}..."
                )

        return pd.read_parquet(filepath)

    def list_snapshots(self, name: Optional[str] = None) -> List[Dict[str, str]]:
        """List available snapshots, optionally filtered by name."""
        snapshots = []

        for filename in os.listdir(self.snapshot_directory):
            if filename.endswith(".parquet"):
                filepath = os.path.join(self.snapshot_directory, filename)

                # Look for metadata
                meta_path = filepath + ".meta.json"
                if os.path.exists(meta_path):
                    with open(meta_path, "r") as f:
                        meta = json.load(f)
                else:
                    meta = {"name": filename, "file_hash": "unknown"}

                if name is None or meta.get("name") == name:
                    snapshots.append({
                        "filename": filename,
                        "filepath": filepath,
                        "hash": meta.get("file_hash", "unknown"),
                        "name": meta.get("name", "unknown"),
                        "run_id": meta.get("run_id", "unknown"),
                    })

        return snapshots


# ============================================================================
# Verdict Output Generator
# ============================================================================


class VerdictOutputGenerator:
    """
    Generates the final verdict output in the standardized JSON format.

    This is the primary output that the Bridge (Stage 3) consumes.
    """

    def __init__(self, output_directory: str):
        self.output_directory = output_directory
        os.makedirs(output_directory, exist_ok=True)

    def generate_verdict(
        self,
        audit_trail: AuditTrail,
        hypothesis_config: Dict[str, Any],
        test_results: Dict[str, Any],
        verdict: str,
        verdict_reason: str,
        failure_stage: Optional[str],
        checks: Dict[str, Any],
        metrics: Dict[str, Any],
        warnings: List[str],
    ) -> Dict[str, Any]:
        """
        Generate the complete verdict output.

        Follows the format specified in PIPELINE_SPEC.md Section 12.2.
        """
        verdict_output = {
            "hypothesis_uuid": audit_trail.hypothesis_uuid,
            "hypothesis_name": audit_trail.hypothesis_name,
            "pipeline_version": audit_trail.pipeline_version,
            "run_id": audit_trail.run_id,
            "run_timestamp": audit_trail.run_timestamp,
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "failure_stage": failure_stage,
            "checks": checks,
            "metrics": metrics,
            "warnings": warnings,
            "audit_trail_hash": audit_trail.output_hashes.get("audit_trail", "N/A"),
            "data_source_hashes": {
                src["source_name"]: src["content_hash"]
                for src in audit_trail.data_sources
            },
            "seeds_used": audit_trail.seeds,
            "data_sources_accessed": audit_trail.data_sources,
            "llm_metadata": audit_trail.llm_metadata,
        }

        # Write verdict to file
        output_path = os.path.join(
            self.output_directory,
            f"verdict_{audit_trail.hypothesis_uuid}.json",
        )

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(verdict_output, f, indent=2, default=str)

        logger.info(f"Verdict written to {output_path}")
        return verdict_output

    def generate_summary(
        self,
        results_summary: Dict[str, Any],
        audit_trail: AuditTrail,
    ) -> str:
        """
        Generate a human-readable summary of results.
        """
        summary_path = os.path.join(
            self.output_directory,
            f"results_summary_{audit_trail.hypothesis_uuid}.json",
        )

        with open(summary_path, "w") as f:
            json.dump(results_summary, f, indent=2, default=str)

        return summary_path
