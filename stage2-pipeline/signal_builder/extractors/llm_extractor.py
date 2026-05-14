"""
llm_extractor.py — LLM-Based Signal Extractor
==============================================

Generic signal extractor that uses an LLM (Claude/DeepSeek) to extract
hypothesis-specific signals from unstructured text.

Architecture:
  1. Takes raw text data from adapters (SEC EDGAR, FDA, etc.)
  2. Constructs hypothesis-specific extraction prompts
  3. Calls LLM API with temp=0 for deterministic extraction
  4. Parses structured JSON responses
  5. Builds SignalData with extracted signal values

Designed for reproducibility: same input + same model + temp=0 + fixed seed
always produces the same output.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Path setup
_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from ..base import (
    DataAcquisitionError,
    RawData,
    SignalData,
    SignalExtractor,
    SignalMetadata,
    SignalExtractionError,
)

logger = logging.getLogger(__name__)

# LLM API configuration (from environment)
_ANTHROPIC_BASE_URL = os.environ.get(
    "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
)
_ANTHROPIC_AUTH_TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# Maximum characters to send to LLM (to control API costs and latency)
MAX_TEXT_CHARS = 25000


class LLMExtractor(SignalExtractor):
    """Extract hypothesis-specific signals using an LLM.

    Unlike the LinguisticExtractor (which uses deterministic keyword/regex
    patterns), this extractor uses the LLM's reasoning capabilities to
    perform fine-grained linguistic measurements that require semantic
    understanding — e.g., distinguishing "effective immediately" from
    "effective in 90 days" in departure filings, or identifying whether
    risk factor removals are "clean" or "dirty."

    Deterministic mode: temperature=0, fixed seed, structured JSON output.
    """

    # Maximum filings to process with LLM (cost control)
    MAX_LLM_FILINGS = 100

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.0,
        seed: int = 42,
        max_text_chars: int = MAX_TEXT_CHARS,
    ):
        self._model = model or _ANTHROPIC_MODEL
        self._temperature = temperature
        self._seed = seed
        self._max_text_chars = max_text_chars
        self._base_url = _ANTHROPIC_BASE_URL
        self._auth_token = _ANTHROPIC_AUTH_TOKEN
        self._call_count = 0
        self._total_cost_est = 0.0

    @property
    def extractor_name(self) -> str:
        return "llm"

    @property
    def version(self) -> str:
        return "1.0.0"

    def extract(
        self,
        raw_data: Any,
        params: Dict[str, Any],
    ) -> SignalData:
        """Extract signal using LLM-based analysis.

        Args:
            raw_data: RawData object from adapter (primary text source).
            params: Extraction parameters including:
                - hypothesis: HypothesisSpec (required)
                - raw_data_map: Dict[str, RawData] (all acquired data)
                - signal_name: str
                - higher_is_better: bool
                - llm_model, llm_temperature, llm_seed: optional overrides

        Returns:
            SignalData with extracted signal values.
        """
        hypothesis = params.get("hypothesis")
        raw_data_map = params.get("raw_data_map", {})
        force_synthetic = params.get("force_synthetic", False)

        # Build synthetic data dict for fallback
        synth_data = {
            "hypothesis": hypothesis,
            "raw_data": raw_data,
            "raw_data_map": raw_data_map,
        }

        if hypothesis is None:
            return self._extract_synthetic(synth_data)

        if force_synthetic:
            return self._extract_synthetic(synth_data)

        # Find text data — use raw_data_map if available, else raw_data
        text_records = (
            self._find_text_data(raw_data_map)
            if raw_data_map
            else self._unwrap_raw_data(raw_data)
        )
        if text_records is None:
            logger.info("LLMExtractor: No text data found, falling back to synthetic")
            return self._extract_synthetic(synth_data)

        signal_name = params.get("signal_name") or hypothesis.signal.signal_name
        higher_is_better = params.get("higher_is_better", False) or hypothesis.signal.higher_is_better

        # Override model config if specified in params
        if params.get("llm_model"):
            self._model = params["llm_model"]
        if params.get("llm_temperature") is not None:
            self._temperature = params["llm_temperature"]
        if params.get("llm_seed") is not None:
            self._seed = params["llm_seed"]

        logger.info(
            f"LLMExtractor: Processing {len(text_records)} records "
            f"for signal '{signal_name}'"
        )

        # Cap filings for cost control
        if len(text_records) > self.MAX_LLM_FILINGS:
            logger.warning(
                f"Capping LLM filings at {self.MAX_LLM_FILINGS} "
                f"(from {len(text_records)})"
            )
            text_records = text_records.iloc[:self.MAX_LLM_FILINGS]

        # Extract signals using LLM
        signals = []
        for idx, row in text_records.iterrows():
            try:
                result = self._extract_single(
                    text=self._get_best_text(row),
                    hypothesis=hypothesis,
                    metadata={
                        "ticker": row.get("ticker", "UNKNOWN"),
                        "date": str(row.get("filing_date", "")),
                        "form_type": str(row.get("form_type", "")),
                    },
                )
                if result is not None:
                    signals.append(result)
            except Exception as e:
                logger.warning(f"LLM extraction failed for row {idx}: {e}")

        if not signals:
            logger.info("LLMExtractor: No signals extracted, falling back to synthetic")
            return self._extract_synthetic(synth_data)

        # Build signal dataframe
        signal_df = pd.DataFrame(signals)
        logger.info(
            f"LLMExtractor: Extracted {len(signal_df)} signal values. "
            f"API calls: {self._call_count}, "
            f"Est. cost: ${self._total_cost_est:.4f}"
        )

        # Ensure correct column names
        signal_df = signal_df.rename(
            columns={
                "date": "signal_date",
                "ticker": "ticker",
                "signal_value": signal_name,
            }
        )

        # Keep only needed columns
        keep_cols = ["signal_date", "ticker", signal_name]
        signal_df = signal_df[[c for c in keep_cols if c in signal_df.columns]]

        if signal_df.empty or signal_name not in signal_df.columns:
            logger.info("LLMExtractor: Empty signal data, falling back to synthetic")
            return self._extract_synthetic(synth_data)

        signal_array = signal_df[signal_name].values.astype(np.float64)

        return SignalData(
            values=signal_array,
            dates=signal_df["signal_date"].tolist(),
            tickers=signal_df["ticker"].tolist(),
            signal_name=signal_name,
            higher_is_better=higher_is_better,
            metadata=SignalMetadata(
                extractor=self.extractor_name,
                extractor_version=self.version,
                extractor_method="llm",
                llm_model=self._model,
                llm_temperature=self._temperature,
                is_deterministic=(self._temperature == 0.0),
                extraction_date=datetime.now(timezone.utc).isoformat(),
                n_signals=len(signal_df),
                extra={
                    "n_api_calls": self._call_count,
                    "est_cost_usd": round(self._total_cost_est, 4),
                },
            ),
        )

    # ------------------------------------------------------------------
    # Single-record extraction
    # ------------------------------------------------------------------

    def _extract_single(
        self,
        text: str,
        hypothesis: Any,
        metadata: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        """Extract signal from a single text record using LLM.

        Returns dict with keys: date, ticker, signal_value, confidence.
        """
        if not text or len(text) < 100:
            return None

        prompt = self._build_extraction_prompt(text, hypothesis, metadata)

        try:
            response = self._call_llm(prompt)
            parsed = self._parse_llm_response(response)
            if parsed is None:
                return None

            return {
                "date": metadata.get("date", ""),
                "ticker": metadata.get("ticker", ""),
                "signal_value": float(parsed.get("signal_value", 0.0)),
                "confidence": float(parsed.get("confidence", 0.5)),
            }
        except Exception as e:
            logger.warning(
                f"LLM call failed for {metadata.get('ticker')} "
                f"{metadata.get('date')}: {e}"
            )
            return None

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_extraction_prompt(
        self,
        text: str,
        hypothesis: Any,
        metadata: Dict[str, str],
    ) -> str:
        """Build extraction prompt from hypothesis spec and filing text."""
        signal_name = hypothesis.signal.signal_name
        higher_is_better = hypothesis.signal.higher_is_better

        # Truncate text to control API costs
        if len(text) > self._max_text_chars:
            text = text[:self._max_text_chars] + "\n[...TEXT TRUNCATED...]"

        # Build the extraction prompt
        direction = "high values are POSITIVE (good news)" if higher_is_better else "high values are NEGATIVE (bad news)"
        prompt = f"""You are a financial linguistics analysis system. Extract a specific signal from SEC filing text.

HYPOTHESIS: {hypothesis.name}
SIGNAL NAME: {signal_name}
SIGNAL DIRECTION: {direction}
MECHANISM: {hypothesis.mechanism}

INSTRUCTIONS:
Read the filing text below and extract the signal value. The signal measures:
{hypothesis.mechanism}

Return a JSON object with exactly these fields:
- signal_value: a float between -1.0 (strongest negative signal) and 1.0 (strongest positive signal). Map the linguistic features described in the mechanism to this range.
- confidence: a float between 0.0 (no evidence in text) and 1.0 (text clearly exhibits the signal), indicating how confidently you can extract this signal from the provided text.
- features_found: a list of strings naming the specific linguistic features you found.
- rationale: a one-sentence explanation of the score.

FILING TYPE: {metadata.get('form_type', 'Unknown')}
TICKER: {metadata.get('ticker', 'Unknown')}
DATE: {metadata.get('date', 'Unknown')}

FILING TEXT:
{text}

Return ONLY the JSON object, no other text."""
        return prompt

    # ------------------------------------------------------------------
    # LLM API call
    # ------------------------------------------------------------------

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM API and return the response text."""
        import requests

        if not self._auth_token:
            raise SignalExtractionError(
                "No LLM API token configured. Set ANTHROPIC_AUTH_TOKEN."
            )

        headers = {
            "Content-Type": "application/json",
        }
        if "deepseek" in self._base_url:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        else:
            headers["x-api-key"] = self._auth_token
            headers["anthropic-version"] = "2023-06-01"

        payload = {
            "model": self._model,
            "max_tokens": 500,
            "temperature": self._temperature,
            "messages": [{"role": "user", "content": prompt}],
        }

        # Add seed if available (Anthropic API supports it for reproducibility)
        if self._seed is not None and "deepseek" not in self._base_url:
            payload["seed"] = self._seed

        for attempt in range(3):
            try:
                url = f"{self._base_url}/messages"
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                if resp.status_code == 200:
                    data = resp.json()
                    # Handle both Anthropic-native and DeepSeek-compatible formats.
                    # DeepSeek returns content blocks with type "thinking" before
                    # the actual "text" block; Anthropic returns only "text" blocks.
                    content_blocks = data.get("content", [])
                    content = ""
                    for block in content_blocks:
                        if block.get("type") == "text":
                            content = block.get("text", "")
                            break
                    if not content and content_blocks:
                        # Fallback: try first block's text field
                        content = content_blocks[0].get("text", "")
                    self._call_count += 1
                    # Estimate cost (rough): $3/M input tokens, $15/M output tokens
                    est_input_tokens = len(prompt) // 4
                    est_output_tokens = len(content) // 4
                    self._total_cost_est += (
                        est_input_tokens * 3.0 / 1_000_000
                        + est_output_tokens * 15.0 / 1_000_000
                    )
                    return content
                elif resp.status_code == 429:
                    wait = min(2 ** attempt, 8)
                    logger.debug(f"LLM rate limited, waiting {wait}s")
                    time.sleep(wait)
                else:
                    logger.warning(
                        f"LLM API returned {resp.status_code}: {resp.text[:200]}"
                    )
                    if attempt < 2:
                        time.sleep(1)
            except Exception as e:
                logger.warning(f"LLM API call failed (attempt {attempt+1}/3): {e}")
                if attempt < 2:
                    time.sleep(1)

        raise SignalExtractionError(
            "LLM API call failed after 3 attempts"
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_llm_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse the LLM's JSON response."""
        if not response:
            return None

        # Try to find JSON object in response
        cleaned = response.strip()
        # Remove markdown code fences if present
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            cleaned = "\n".join(lines).strip()

        try:
            parsed = json.loads(cleaned)
            if "signal_value" in parsed:
                return parsed
        except json.JSONDecodeError:
            # Try to extract JSON from mixed text
            import re
            json_match = re.search(r'\{[^}]+\}', cleaned)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                    if "signal_value" in parsed:
                        return parsed
                except json.JSONDecodeError:
                    pass

        logger.warning(f"Failed to parse LLM response: {response[:200]}...")
        return None

    # ------------------------------------------------------------------
    # Text extraction from raw data
    # ------------------------------------------------------------------

    def _find_text_data(self, raw_data_map: Dict[str, RawData]) -> Optional[pd.DataFrame]:
        """Find text-containing records in the raw data map.

        Prefers departure_text > mda_text > risk_factors_text > full_text.
        """
        for key, raw_data in raw_data_map.items():
            df = raw_data.records
            if df is None or df.empty:
                continue

            text_cols = [
                "departure_text", "earnings_release_text",
                "mda_text", "risk_factors_text", "business_text",
                "full_text",
            ]
            has_text = any(c in df.columns and df[c].notna().any() for c in text_cols)
            if has_text:
                return df

        return None

    def _unwrap_raw_data(self, raw_data: Any) -> Optional[pd.DataFrame]:
        """Extract DataFrame from a RawData object or return None."""
        if raw_data is None:
            return None
        if hasattr(raw_data, "records"):
            df = raw_data.records
            if df is not None and not df.empty:
                return df
        if isinstance(raw_data, pd.DataFrame):
            return raw_data if not raw_data.empty else None
        return None

    def _get_best_text(self, row: pd.Series) -> str:
        """Get the most relevant text from a filing row.

        Priority: departure_text > earnings_release_text >
                  mda_text > risk_factors_text > full_text
        """
        for col in [
            "departure_text", "earnings_release_text",
            "mda_text", "risk_factors_text", "business_text",
            "full_text",
        ]:
            text = row.get(col, "")
            if text and isinstance(text, str) and len(text) > 100:
                return text
        return ""

    # ------------------------------------------------------------------
    # Synthetic extraction (no API call)
    # ------------------------------------------------------------------

    def _extract_synthetic(
        self,
        ctx: Dict[str, Any],
    ) -> SignalData:
        """Generate synthetic signal data when LLM extraction is unavailable.

        Uses the LinguisticExtractor's deterministic features as a proxy.
        """
        from .linguistic import LinguisticExtractor

        hypothesis = ctx.get("hypothesis")
        raw_data_map = ctx.get("raw_data_map", {})
        raw_data = ctx.get("raw_data")

        hyp_name = getattr(hypothesis, "name", "unknown") if hypothesis else "unknown"

        logger.info(
            f"LLMExtractor: Falling back to deterministic LinguisticExtractor "
            f"for '{hyp_name}'"
        )
        ling = LinguisticExtractor()

        # Build params for linguistic extractor
        params: Dict[str, Any] = {
            "hypothesis_name": hyp_name,
            "signal_name": (
                hypothesis.signal.signal_name
                if hypothesis and hasattr(hypothesis, "signal")
                else "signal"
            ),
            "higher_is_better": (
                hypothesis.signal.higher_is_better
                if hypothesis and hasattr(hypothesis, "signal")
                else False
            ),
            "text_columns": {},
        }

        # Detect composite formula
        if hypothesis:
            sig = (hypothesis.signal.signal_name or "").lower()
            name = (hypothesis.name or "").lower()
            if "departure" in sig or "departure" in name:
                params["composite"] = "departure_language"
            elif "pronoun" in sig or "pronoun" in name:
                params["composite"] = "pronoun_divergence"
            elif "brlas" in sig or "brlas" in name:
                params["composite"] = "brlas"

        # Route to the right raw data
        if raw_data_map:
            for key, rd in raw_data_map.items():
                if hasattr(rd, "records") and rd.records is not None:
                    if not rd.records.empty:
                        return ling.extract(rd, params)
        if raw_data is not None:
            if hasattr(raw_data, "records") and raw_data.records is not None:
                return ling.extract(raw_data, params)
            if isinstance(raw_data, pd.DataFrame) and not raw_data.empty:
                from ..base import RawData
                return ling.extract(RawData(records=raw_data), params)

        # Ultimate fallback: empty signal
        return SignalData(
            values=np.array([]),
            dates=[],
            tickers=[],
            signal_name=params.get("signal_name", "signal"),
            higher_is_better=params.get("higher_is_better", False),
            metadata=SignalMetadata(
                extractor=self.extractor_name,
                extractor_version=self.version,
                extractor_method="synthetic_fallback",
            ),
        )

    def validate_signal(self, signal_data: SignalData) -> Tuple[bool, List[str]]:
        """Validate extracted signal data."""
        issues: List[str] = []

        if signal_data.values is None or len(signal_data.values) == 0:
            issues.append("No signal values extracted")
            return False, issues

        if len(signal_data.values) < 5:
            issues.append(
                f"Too few signal values ({len(signal_data.values)}): need >= 5"
            )

        n_nan = int(np.isnan(signal_data.values).sum())
        if n_nan > len(signal_data.values) * 0.5:
            issues.append(f"Majority of signal values are NaN ({n_nan}/{len(signal_data.values)})")

        return len(issues) == 0, issues

    def default_signal_name(self) -> str:
        return "llm_signal"
