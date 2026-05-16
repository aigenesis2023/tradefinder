"""
bootstrap_signal.py — Build signal directly from filing cache (no network).

Bypasses the full pipeline's download phase. Reads cached .clean.txt
files directly, runs the signal extractor, and writes signal parquet.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List

import pandas as pd

_PARENT = os.path.dirname(os.path.abspath(__file__))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
)
logger = logging.getLogger("bootstrap")

_cache_dir = os.path.join(
    _PARENT, "signal_builder", "_cache", "sec_edgar",
)

# CIK-to-ticker mapping from company_tickers.json
_ct_path = os.path.join(os.path.dirname(_cache_dir), "company_tickers_full.json")


def _load_cik_to_ticker() -> Dict[str, str]:
    """Load CIK -> ticker mapping."""
    if not os.path.exists(_ct_path):
        logger.warning(f"No company_tickers.json at {_ct_path}")
        return {}
    with open(_ct_path) as f:
        data = json.load(f)
    mapping = {}
    for entry in data.values():
        cik = str(entry.get("cik_str", entry.get("cik", ""))).zfill(10)
        ticker = entry.get("ticker", "").strip().upper()
        if cik and ticker:
            mapping[cik] = ticker
    logger.info(f"Loaded {len(mapping)} CIK->ticker mappings")
    return mapping


def load_cached_10k_filings(
    cache_dir: str = _cache_dir,
    min_filing_len: int = 5000,
    max_tickers: int = 200,
    required_pattern: Optional[str] = None,
    max_text_chars: int = 0,
    form_type: str = "10-K",
) -> pd.DataFrame:
    """Load cached 10-K clean text files into a DataFrame.

    Args:
        cache_dir: Path to the cache directory.
        min_filing_len: Minimum text length to keep a filing.
        max_tickers: Stop after this many unique tickers.
        required_pattern: If set, only keep filings whose text matches
            this regex (applied case-insensitive). Non-matching files
            are skipped BEFORE storing in the DataFrame, saving memory.
        max_text_chars: If > 0, truncate stored full_text to this many
            chars. Saves massive memory (3.7MB → 100KB per filing).
    """
    from datetime import datetime

    cik_to_ticker = _load_cik_to_ticker()
    required_re = re.compile(required_pattern, re.I) if required_pattern else None

    records = []
    cik_counts = defaultdict(int)

    for fname in sorted(os.listdir(cache_dir)):
        if not fname.endswith(".clean.txt"):
            continue
        # Format: CIK_accession.clean.txt
        parts = fname.replace(".clean.txt", "").split("_")
        if len(parts) < 2:
            continue
        cik = parts[0].zfill(10)
        acc = parts[1]

        # Skip if we have enough for this CIK
        if cik_counts[cik] >= 6:
            continue

        ticker = cik_to_ticker.get(cik)
        if not ticker:
            continue

        filepath = os.path.join(cache_dir, fname)
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            continue

        if len(text) < min_filing_len:
            continue

        # Extract form type from header
        fm_form = re.search(
            r"(?:FORM\s+TYPE|CONFORMED\s+SUBMISSION\s+TYPE)[:\s]+([0-9A-Z\-]+)",
            text[:2000], re.IGNORECASE,
        )
        filing_form_type = fm_form.group(1) if fm_form else "Unknown"
        if form_type and filing_form_type != form_type:
            continue

        # Memory-saving pre-filter: skip filing if it doesn't match
        if required_re and not required_re.search(text[:100000]):
            continue

        # Extract filing date from the clean text header.
        # Format: FILED AS OF DATE: 20231218
        # Also try CONFORMED PERIOD OF REPORT (fiscal period end date),
        # and accession number year as last resort.
        fm1 = re.search(
            r"(?:FILED\s+AS\s+OF\s+DATE|FILING\s+DATE|DATE\s+OF\s+FILING)[:\s]+(\d{8})",
            text[:2000], re.IGNORECASE,
        )
        fm2 = re.search(
            r"CONFORMED\s+PERIOD\s+OF\s+REPORT[:\s]+(\d{8})",
            text[:2000], re.IGNORECASE,
        )

        filing_date = None
        if fm1:
            try:
                d = fm1.group(1)
                filing_date = datetime(int(d[:4]), int(d[4:6]), int(d[6:8]))
            except (ValueError, IndexError):
                pass
        if filing_date is None and fm2:
            try:
                d = fm2.group(1)
                filing_date = datetime(int(d[:4]), int(d[4:6]), int(d[6:8]))
            except (ValueError, IndexError):
                pass

        if filing_date is None:
            # Extract year from accession number (CIK-yy-seq format)
            try:
                # Accession like "0000010048-23-000022" -> year 2023
                if "-" in acc:
                    yy = int(acc.split("-")[1])
                    year = 2000 + yy if yy < 50 else 1900 + yy
                else:
                    # Undashed format: CIK(10)YY(2)seq(6) -> chars 10-12
                    year = 2000 + int(acc[10:12])
                filing_date = datetime(year, 12, 31)
            except (ValueError, IndexError):
                continue

        records.append({
            "cik": cik,
            "ticker": ticker,
            "filing_date": filing_date,
            "form_type": filing_form_type,
            "full_text": text[:max_text_chars] if max_text_chars > 0 else text,
            "risk_factors_text": "",  # Will be extracted by extractor
            "cam_text": "",
            "audit_report_text": "",
        })
        cik_counts[cik] += 1

    df = pd.DataFrame(records)
    logger.info(
        f"Loaded {len(df)} cached 10-K filings from "
        f"{df['ticker'].nunique()} tickers"
    )
    return df


def build_risk_factor_removal(cache_dir: str = _cache_dir) -> str:
    """Build risk factor removal signal from cache. Returns signal parquet path."""
    from signal_builder.extractors.risk_factor_removal import (
        RiskFactorRemovalExtractor,
        _split_risk_factors,
    )
    from signal_builder.base import RawData, SignalData

    # Pre-filter for risk factors mentions to save memory
    # "Item 1A" matches ~55% of filings; use small max_tickers to keep
    # memory manageable (~50-60 files * 3.7MB avg).
    df = load_cached_10k_filings(
        cache_dir, max_tickers=40, min_filing_len=10000,
        required_pattern=r"(?:Risk\s+Factors|Item\s+1A)",
        max_text_chars=200000,
    )

    # Extract risk factors sections from full_text
    from signal_builder.adapters.sec_edgar import SECEdgarAdapter

    for idx, row in df.iterrows():
        sections = SECEdgarAdapter._extract_filing_sections_from_clean(
            str(row["full_text"]), "10-K",
        )
        df.at[idx, "risk_factors_text"] = sections.get("risk_factors", "")

    # Filter to rows with substantive risk factors
    df = df[df["risk_factors_text"].str.len() >= 500].copy()
    # Drop full_text to free memory (no longer needed)
    df = df.drop(columns=["full_text", "audit_report_text", "cam_text"], errors="ignore")
    logger.info(f"After risk_factors_text filter: {len(df)} filings")

    raw_data = RawData(
        records=df, source_type="sec_filing", provider="sec_edgar_cache",
    )
    extractor = RiskFactorRemovalExtractor()
    signal = extractor.extract(raw_data, {
        "signal_name": "risk_factor_removal_score",
        "higher_is_better": False,
    })

    if signal.df.empty:
        logger.warning("Risk Factor Removal extractor returned empty signal")
        return ""

    out_path = "/tmp/rf_removal_signal_cache.parquet"
    signal.df.to_parquet(out_path)
    signal.long_format.to_parquet("/tmp/rf_removal_signal_long_cache.parquet")
    logger.info(
        f"Signal saved to {out_path}: {len(signal.long_format)} events, "
        f"{len(signal.df.columns)} tickers"
    )
    return out_path


def build_cam_expansion(cache_dir: str = _cache_dir) -> str:
    """Build CAM expansion signal from cache."""
    from signal_builder.extractors.cam_expansion import CAMExpansionExtractor
    from signal_builder.base import RawData

    df = load_cached_10k_filings(
        cache_dir, max_tickers=5000, min_filing_len=10000,
        required_pattern=r"Critical\s+Audit\s+Matters?",
        max_text_chars=400000,
    )
    logger.info(f"After CAM mention filter: {len(df)} filings")

    if df.empty:
        logger.warning("No filings with CAM mentions found")
        return ""

    raw_data = RawData(
        records=df, source_type="sec_filing", provider="sec_edgar_cache",
    )
    extractor = CAMExpansionExtractor()
    signal = extractor.extract(raw_data, {
        "signal_name": "cam_expansion_velocity",
        "higher_is_better": False,
    })

    if signal.df.empty:
        logger.warning("CAM Expansion extractor returned empty signal")
        return ""

    out_path = "/tmp/cam_expansion_signal_cache.parquet"
    signal.df.to_parquet(out_path)
    signal.long_format.to_parquet("/tmp/cam_expansion_signal_long_cache.parquet")
    logger.info(
        f"CAM signal saved to {out_path}: {len(signal.long_format)} events, "
        f"{len(signal.df.columns)} tickers"
    )
    return out_path


def build_llm_signal(
    hypothesis_path: str,
    cache_dir: str = _cache_dir,
    required_pattern: Optional[str] = None,
    max_tickers: int = 5000,
    min_filing_len: int = 1000,
    max_text_chars: int = 25000,
) -> str:
    """Build signal using LLM extraction for any hypothesis.

    Loads cached filings, extracts relevant sections, runs LLMExtractor,
    and writes a signal parquet. No network calls — uses cache only.

    Args:
        hypothesis_path: Path to hypothesis JSON file.
        cache_dir: Path to the SEC EDGAR cache directory.
        required_pattern: Optional regex to pre-filter filing text.
        max_tickers: Max unique tickers to load.
        min_filing_len: Minimum text length to keep a filing.
        max_text_chars: Truncate text to this many chars for LLM.

    Returns:
        Path to the signal parquet file, or "" if extraction failed.
    """
    from signal_builder.extractors.llm_extractor import LLMExtractor
    from signal_builder.base import RawData

    # Load hypothesis
    with open(hypothesis_path) as f:
        hyp_dict = json.load(f)

    signal_name = hyp_dict["signal"]["signal_name"]
    hyp_name = hyp_dict.get("name", os.path.basename(hypothesis_path))

    # Determine form type from data_sources
    form_type = "8-K"
    for ds in hyp_dict.get("data_sources", []):
        if ds.get("source_type") == "sec_filing":
            fields = ds.get("fields", [])
            if fields:
                form_type = fields[0]
            break

    # Derive section key and text column name from form type
    section_key = {
        "8-K": "departure",
        "10-K": "risk_factors",
        "10-Q": "risk_factors",
    }.get(form_type, "full_text")

    text_column = f"{section_key}_text" if section_key != "full_text" else "full_text"

    logger.info(f"Building LLM signal for: {hyp_name}")
    logger.info(f"  Form type: {form_type}, Section: {section_key}, Column: {text_column}")

    # Load cached filings
    df = load_cached_10k_filings(
        cache_dir, form_type=form_type, max_tickers=max_tickers,
        min_filing_len=min_filing_len, required_pattern=required_pattern,
        max_text_chars=max_text_chars,
    )

    if df.empty:
        logger.warning(f"No cached {form_type} filings found")
        return ""

    logger.info(f"Loaded {len(df)} {form_type} filings from {df['ticker'].nunique()} tickers")

    # Extract sections from full_text
    from signal_builder.adapters.sec_edgar import SECEdgarAdapter

    for idx, row in df.iterrows():
        sections = SECEdgarAdapter._extract_filing_sections_from_clean(
            str(row["full_text"]), form_type,
        )
        col_val = sections.get(section_key, "")
        df.at[idx, text_column] = col_val

    # Filter to rows with substantive section text
    df = df[df[text_column].str.len() >= 100].copy()
    if df.empty:
        logger.warning(f"No filings with substantive {text_column} content")
        return ""

    logger.info(f"After {text_column} filter: {len(df)} filings from {df['ticker'].nunique()} tickers")

    # Build RawData and run LLMExtractor
    raw_data = RawData(
        records=df, source_type="sec_filing", provider="sec_edgar_cache",
    )

    # Convert to HypothesisSpec for LLMExtractor
    import sys as _sys
    _impl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "implementation")
    if _impl_dir not in _sys.path:
        _sys.path.insert(0, _impl_dir)
    from pipeline import HypothesisSpec
    hypothesis = HypothesisSpec.from_dict(hyp_dict)

    extractor = LLMExtractor(
        model=os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-pro"),
        temperature=0.0,
        seed=42,
        max_text_chars=max_text_chars,
    )

    signal = extractor.extract(raw_data, {
        "hypothesis": hypothesis,
        "signal_name": signal_name,
        "higher_is_better": hyp_dict.get("signal", {}).get("higher_is_better", True),
        "raw_data_map": {"sec_edgar": raw_data},
    })

    if signal.df.empty:
        logger.warning("LLM extractor returned empty signal")
        return ""

    n_events = len(signal.long_format) if signal.long_format is not None else 0
    n_tickers = len(signal.df.columns)
    logger.info(f"LLM signal: {n_events} events across {n_tickers} tickers")

    # Validate minimum signal count
    if n_events < 10:
        logger.warning(
            f"INSUFFICIENT SIGNALS: Only {n_events} LLM-extracted events. "
            "Cache may not have enough {form_type} filings with {section_key} content. "
            "Refusing to proceed — need at least 10."
        )
        return ""

    # Save
    safe_name = signal_name.replace("_score", "").replace("_signal", "")
    out_path = f"/tmp/{safe_name}_signal_cache.parquet"
    signal.df.to_parquet(out_path)
    signal.long_format.to_parquet(f"/tmp/{safe_name}_signal_long_cache.parquet")
    logger.info(
        f"Signal saved to {out_path}: {n_events} events, {n_tickers} tickers. "
        f"API calls: {extractor._call_count}, Est. cost: ${extractor._total_cost_est:.4f}"
    )
    return out_path


def build_departure_severity(cache_dir: str = _cache_dir) -> str:
    """Build departure language severity signal from cached 8-K filings."""
    hyp_path = os.path.join(_PARENT, "hypothesis_departure_severity.json")
    return build_llm_signal(
        hyp_path, cache_dir,
        required_pattern=r"ITEM\s+INFORMATION.*(?:Departure|5\.02)",
        min_filing_len=1000,
        max_text_chars=25000,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build signals from cache (no network)")
    parser.add_argument("--signal", choices=[
        "risk_factor_removal", "cam_expansion",
        "departure_severity", "llm",
    ], default="risk_factor_removal")
    parser.add_argument("--cache-dir", default=_cache_dir)
    parser.add_argument("--hypothesis", default=None,
                       help="Path to hypothesis JSON (required for --signal llm)")
    args = parser.parse_args()

    if args.signal == "risk_factor_removal":
        build_risk_factor_removal(args.cache_dir)
    elif args.signal == "cam_expansion":
        build_cam_expansion(args.cache_dir)
    elif args.signal == "departure_severity":
        build_departure_severity(args.cache_dir)
    elif args.signal == "llm":
        if not args.hypothesis:
            parser.error("--hypothesis is required for --signal llm")
        build_llm_signal(args.hypothesis, args.cache_dir)
