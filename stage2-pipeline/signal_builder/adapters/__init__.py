"""
adapters/__init__.py — Data Adapter Registry
============================================

All concrete data adapters are registered here for discovery.
"""

import os as _os, sys as _sys
_PARENT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PARENT not in _sys.path:
    _sys.path.insert(0, _PARENT)

from .fda import FDAAdapter
from .sec_edgar import SECEdgarAdapter
from .yahoo_finance import YahooFinanceAdapter
from .fmp import FMPAdapter
from .fred import FREDAdapter

# Adapter registry: provider name -> adapter class
ADAPTER_REGISTRY: dict = {
    "fda": FDAAdapter,
    "sec_edgar": SECEdgarAdapter,
    "yahoo": YahooFinanceAdapter,
    "fmp": FMPAdapter,
    "fred": FREDAdapter,
}


def get_adapter(provider: str):
    """Look up an adapter by provider name."""
    cls = ADAPTER_REGISTRY.get(provider)
    if cls is None:
        raise ValueError(
            f"Unknown data provider '{provider}'. "
            f"Available: {list(ADAPTER_REGISTRY.keys())}"
        )
    return cls()


__all__ = [
    "FDAAdapter",
    "SECEdgarAdapter",
    "YahooFinanceAdapter",
    "FMPAdapter",
    "FREDAdapter",
    "ADAPTER_REGISTRY",
    "get_adapter",
]
