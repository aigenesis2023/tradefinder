"""
Signal Builder Framework — Stage 2 Signal Construction Layer
=============================================================

Bridges the gap between hypothesis specification and pipeline execution.
Takes a HypothesisSpec, acquires raw data, builds the signal, and
produces a signal file ready for pipeline ingestion.

Architecture:
    HypothesisSpec
    -> DataAdapter.acquire()      # Get raw data from source
    -> DataAdapter.validate()     # Verify data quality
    -> SignalExtractor.extract()  # Build signal from raw data
    -> SignalBuilder.build()      # Orchestrate + save to parquet
    -> pipeline.py                # Test the signal
"""

import os as _os, sys as _sys
_PARENT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PARENT not in _sys.path:
    _sys.path.insert(0, _PARENT)

from .base import (
    DataAdapter,
    DataSourceSpec,
    HypothesisSpec,
    RawData,
    SignalData,
    SignalExtractor,
    SignalMetadata,
    UNTESTABLE,
    Verdict,
)

# SignalBuilder is imported separately to avoid circular imports
# It is in signal_builder.py, not base.py
from .signal_builder import SignalBuilder

__all__ = [
    "DataAdapter",
    "DataSourceSpec",
    "HypothesisSpec",
    "RawData",
    "SignalBuilder",
    "SignalData",
    "SignalExtractor",
    "SignalMetadata",
    "UNTESTABLE",
    "Verdict",
]
