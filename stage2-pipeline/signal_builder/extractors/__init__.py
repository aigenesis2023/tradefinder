"""
extractors/__init__.py — Signal Extractor Registry
==================================================

All concrete signal extractors are registered here.
"""

import os as _os, sys as _sys
_PARENT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PARENT not in _sys.path:
    _sys.path.insert(0, _PARENT)

from .linguistic import LinguisticExtractor

EXTRACTOR_REGISTRY: dict = {
    "linguistic": LinguisticExtractor,
}


def get_extractor(name: str):
    """Look up an extractor by name."""
    cls = EXTRACTOR_REGISTRY.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown extractor '{name}'. "
            f"Available: {list(EXTRACTOR_REGISTRY.keys())}"
        )
    return cls()


__all__ = [
    "LinguisticExtractor",
    "EXTRACTOR_REGISTRY",
    "get_extractor",
]
