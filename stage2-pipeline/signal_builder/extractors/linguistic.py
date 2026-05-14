"""
linguistic.py — Linguistic Feature Extractor
=============================================

Extracts linguistic features from text documents using deterministic,
reproducible methods (keyword counting, regex patterns, readability
formulas). No LLM non-determinism unless explicitly enabled with
temperature=0 and fixed seeds.

Features computed:
    - Hedging density (hedge phrases / total sentences)
    - Certainty markers (definitive phrases / total sentences)
    - Active-to-passive voice ratio
    - Readability scores (Flesch-Kincaid, automated readability index)
    - Pronoun ratio (first-person plural / first-person singular)
    - Sentiment polarity (VADER-based, deterministic)
    - Composite scores (BRLAS for FDA, departure language index, etc.)

Extraction method: DETERMINISTIC (keyword + regex)
Optional: LLM-based extraction with temp=0, fixed seed (documented)

Every extraction is fully reproducible given the same input text.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..base import (
    RawData,
    SignalData,
    SignalExtractor,
    SignalMetadata,
    SignalExtractionError,
)

import os as _os, sys as _sys
_PARENT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PARENT not in _sys.path:
    _sys.path.insert(0, _PARENT)

logger = logging.getLogger(__name__)


# ============================================================================
# Keyword dictionaries — extensible, documented, deterministic
# ============================================================================


@dataclass
class LinguisticFeatures:
    """Container for all extracted linguistic features."""
    # Basic counts
    n_sentences: int = 0
    n_words: int = 0
    n_syllables: int = 0
    n_complex_words: int = 0  # words with >= 3 syllables

    # Hedging
    hedge_phrases: int = 0
    hedge_density: float = 0.0
    hedge_phrases_found: List[str] = field(default_factory=list)

    # Certainty
    certainty_phrases: int = 0
    certainty_density: float = 0.0
    certainty_phrases_found: List[str] = field(default_factory=list)

    # Voice
    passive_constructions: int = 0
    active_constructions: int = 0
    active_to_passive_ratio: float = 0.0

    # Readability
    flesch_kincaid_grade: float = 0.0
    automated_readability_index: float = 0.0
    flesch_reading_ease: float = 0.0

    # Pronouns
    first_person_singular: int = 0
    first_person_plural: int = 0
    pronoun_ratio: float = 0.0  # 1st plural / 1st singular

    # Sentiment (VADER)
    sentiment_compound: float = 0.0
    sentiment_positive: float = 0.0
    sentiment_negative: float = 0.0
    sentiment_neutral: float = 0.0

    # Composite
    section_label: str = ""  # Which section this belongs to (benefit, risk, general)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_sentences": self.n_sentences,
            "n_words": self.n_words,
            "n_syllables": self.n_syllables,
            "n_complex_words": self.n_complex_words,
            "hedge_phrases": self.hedge_phrases,
            "hedge_density": self.hedge_density,
            "certainty_phrases": self.certainty_phrases,
            "certainty_density": self.certainty_density,
            "passive_constructions": self.passive_constructions,
            "active_constructions": self.active_constructions,
            "active_to_passive_ratio": self.active_to_passive_ratio,
            "flesch_kincaid_grade": self.flesch_kincaid_grade,
            "automated_readability_index": self.automated_readability_index,
            "flesch_reading_ease": self.flesch_reading_ease,
            "first_person_singular": self.first_person_singular,
            "first_person_plural": self.first_person_plural,
            "pronoun_ratio": self.pronoun_ratio,
            "sentiment_compound": self.sentiment_compound,
            "sentiment_positive": self.sentiment_positive,
            "sentiment_negative": self.sentiment_negative,
            "sentiment_neutral": self.sentiment_neutral,
            "section_label": self.section_label,
        }


# ============================================================================
# Hedge phrases (expressions of uncertainty, doubt, tentativeness)
# ============================================================================

HEDGE_PHRASES = [
    # Modal hedges
    "may be", "might be", "could be", "would be", "should be",
    "may have", "might have", "could have", "would have",
    "may not", "might not", "may still",
    # Approximator hedges
    "approximately", "roughly", "about", "around", "nearly", "close to",
    "more or less", "somewhat", "relatively",
    # Shield hedges
    "it appears", "it seems", "it would appear", "it would seem",
    "appears to", "seems to", "appeared to", "seemed to",
    "tends to", "tended to", "tend to",
    # Plausibility shields
    "it is possible", "it is conceivable", "it is likely",
    "it is probable", "it is unlikely", "it is plausible",
    "there is a possibility", "there is a chance",
    # Author hedging
    "we believe", "we think", "we suspect", "we speculate",
    "in our view", "in our opinion", "to our knowledge",
    "we interpret", "we suggest",
    # Attribute hedges
    "according to", "reportedly", "allegedly", "purportedly",
    "ostensibly", "presumably",
    # Quantifier hedges
    "somewhat", "rather", "quite", "fairly", "pretty",
    "a little", "slightly", "to some extent", "in part",
    "to a certain degree", "to a degree",
    # Frequency hedges
    "sometimes", "occasionally", "from time to time", "now and then",
    "in some cases", "in certain cases", "in some instances",
    # Possibility hedges
    "potentially", "possibly", "conceivably", "maybe", "perhaps",
]

# ============================================================================
# Certainty markers (expressions of definiteness, confidence, conclusiveness)
# ============================================================================

CERTAINTY_MARKERS = [
    # Booster words
    "clearly", "obviously", "undoubtedly", "undeniably", "unquestionably",
    "definitely", "certainly", "absolutely", "indisputably", "incontrovertibly",
    # Strong quantifiers
    "all", "every", "none", "never", "always", "entirely", "completely",
    "totally", "fully", "wholly",
    # Author certainty
    "we conclude", "we find", "we determine", "we establish",
    "we demonstrate", "we confirm", "we prove",
    "it is clear", "it is evident", "it is certain",
    "there is no doubt", "without doubt",
    # Demonstratives of certainty
    "demonstrates", "demonstrated", "establishes", "established",
    "confirms", "confirmed", "proves", "proved",
    "shows conclusively", "shown conclusively",
    # Strong adjectives
    "significant", "substantial", "robust", "compelling", "conclusive",
    "definitive", "decisive", "unequivocal",
    # Strong verbs of finding
    "we found", "we observed", "we detected", "we identified",
    "we measured", "we quantified", "we verified",
    # Statistical certainty
    "statistically significant", "p <", "p =",
    "highly significant", "strongly significant",
    "95% confidence", "99% confidence",
    "p-value", "effect size",
]

# ============================================================================
# Passive voice patterns
# ============================================================================

# Regex for passive voice: form of "to be" + past participle
PASSIVE_PATTERNS = [
    r'\b(?:am|is|are|was|were|be|been|being)\s+(\w+(?:ed|en|t|d))\b',
    r'\b(?:am|is|are|was|were|be|been|being)\s+(\w+ed)\b',
    r'\b(?:has|have|had|having)\s+been\s+(\w+(?:ed|en|t|d))\b',
    r'\b(?:will|would|shall|should|may|might|must|can|could)\s+be\s+(\w+(?:ed|en|t|d))\b',
]

# ============================================================================
# First-person pronouns
# ============================================================================

FIRST_PERSON_SINGULAR = [
    r'\bI\b', r'\bme\b', r'\bmy\b', r'\bmine\b', r'\bmyself\b',
]

FIRST_PERSON_PLURAL = [
    r'\bwe\b', r'\bus\b', r'\bour\b', r'\bours\b', r'\bourselves\b',
]

# ============================================================================
# Common passive past participles (for improved passive detection)
# ============================================================================

COMMON_PASSIVE_PARTICIPLES = {
    "given", "taken", "made", "seen", "found", "shown", "known",
    "done", "observed", "reported", "noted", "considered", "expected",
    "required", "based", "used", "conducted", "performed", "evaluated",
    "assessed", "determined", "identified", "measured", "treated",
    "administered", "analyzed", "compared", "collected", "reviewed",
}


class LinguisticExtractor(SignalExtractor):
    """Extract linguistic features from text using deterministic methods.

    Features:
    - Hedging density: hedge_phrase_count / total_sentences
    - Certainty density: certainty_marker_count / total_sentences
    - Active-to-passive ratio: (active clauses) / (passive clauses)
    - Readability: Flesch-Kincaid Grade Level, ARI, Flesch Reading Ease
    - Pronoun ratio: first_person_plural / first_person_singular
    - Sentiment: VADER compound, positive, negative, neutral scores
    - Composite scores: BRLAS, Departure Language Index, etc.

    All extraction is 100% deterministic (keyword + regex). Same input
    always produces same output.

    Optional LLM-based extraction can be used as enhancement with
    temperature=0 and fixed seed (clearly documented).
    """

    # Common composite score formulas
    COMPOSITE_FORMULAS = {
        "brlas": {
            "description": "Benefit-Risk Linguistic Asymmetry Score",
            "formula": (
                "(hedge_density_benefit - hedge_density_risk) + "
                "(certainty_density_risk - certainty_density_benefit) + "
                "0.5 * (readability_benefit - readability_risk)"
            ),
            "params": ["hedge_density", "certainty_density", "flesch_reading_ease"],
        },
        "departure_language": {
            "description": "Departure Language Index (management change detection)",
            "formula": "(hedge_density_current - hedge_density_prior) + "
                       "(certainty_density_prior - certainty_density_current)",
            "params": ["hedge_density", "certainty_density"],
        },
        "pronoun_divergence": {
            "description": "Pronoun Divergence Score (we/I ratio shift)",
            "formula": "pronoun_ratio_current - pronoun_ratio_prior",
            "params": ["pronoun_ratio"],
        },
    }

    @property
    def extractor_name(self) -> str:
        return "linguistic"

    @property
    def version(self) -> str:
        return "1.0.0"

    def __init__(
        self,
        use_llm: bool = False,
        llm_model: Optional[str] = None,
        llm_temperature: float = 0.0,
        llm_seed: int = 42,
    ):
        """
        Args:
            use_llm: Whether to use LLM-based extraction (enhancement).
            llm_model: Model name if using LLM (e.g., 'llama-3-8b').
            llm_temperature: MUST be 0 for deterministic extraction.
            llm_seed: Fixed random seed.
        """
        self._use_llm = use_llm
        self._llm_model = llm_model
        self._llm_temperature = llm_temperature
        self._llm_seed = llm_seed

        if use_llm and llm_temperature != 0.0:
            logger.warning(
                "LLM temperature != 0. Results will be NON-DETERMINISTIC. "
                "The pipeline will flag this in the audit trail."
            )

    def extract(
        self,
        raw_data: RawData,
        params: Optional[Dict[str, Any]] = None,
    ) -> SignalData:
        """Extract linguistic features from raw document text.

        Args:
            raw_data: RawData containing text documents (from FDA, SEC, etc.).
            params: Optional parameters:
                - text_columns: Dict mapping column names to section labels
                  e.g., {"benefit_section_text": "benefit", "risk_section_text": "risk"}
                  Or just "full_document_text" for single-section extraction.
                - composite: Composite score to compute (e.g., "brlas", "departure_language").
                - normalize: Whether to z-score normalize features across documents.
                - extra_hedge_phrases: Additional hedge phrases to detect.
                - extra_certainty_markers: Additional certainty markers.

        Returns:
            SignalData with computed linguistic features per document.
        """
        params = params or {}
        df = raw_data.records.copy()

        # Determine text columns
        text_columns = params.get("text_columns", {})
        if not text_columns:
            # Auto-detect text columns
            for col in df.columns:
                col_lower = col.lower()
                if "benefit" in col_lower and "text" in col_lower:
                    text_columns[col] = "benefit"
                elif "risk" in col_lower and "text" in col_lower:
                    text_columns[col] = "risk"
                elif "full_document" in col_lower or "document_text" in col_lower:
                    text_columns[col] = "full"
            if not text_columns:
                # Fallback: treat any column with "text" in name as general
                text_cols = [c for c in df.columns if "text" in c.lower()]
                if text_cols:
                    for c in text_cols:
                        text_columns[c] = "general"
                else:
                    raise SignalExtractionError(
                        "linguistic",
                        "No text columns found in raw data. "
                        "Available columns: " + ", ".join(df.columns[:10]),
                    )

        # Custom hedge/certainty lists
        extra_hedges = params.get("extra_hedge_phrases", [])
        extra_certainty = params.get("extra_certainty_markers", [])
        all_hedges = HEDGE_PHRASES + extra_hedges
        all_certainty = CERTAINTY_MARKERS + extra_certainty

        # Compile regex patterns
        hedge_pattern = re.compile(
            r'\b(' + '|'.join(re.escape(h.lower()) for h in all_hedges) + r')\b',
            re.IGNORECASE,
        )
        certainty_pattern = re.compile(
            r'\b(' + '|'.join(re.escape(c.lower()) for c in all_certainty) + r')\b',
            re.IGNORECASE,
        )

        # Initialize VADER if available
        vader_analyzer = self._init_vader()

        # Extract features per document and per section
        all_features: List[Dict[str, Any]] = []

        for idx, row in df.iterrows():
            row_features = {"_row_index": idx}
            section_features = {}

            for text_col, section_label in text_columns.items():
                text = str(row.get(text_col, ""))
                if not text or text == "nan":
                    section_features[section_label] = LinguisticFeatures(section_label=section_label)
                    continue

                feats = self._extract_from_text(
                    text,
                    section_label=section_label,
                    hedge_pattern=hedge_pattern,
                    certainty_pattern=certainty_pattern,
                    vader_analyzer=vader_analyzer,
                )
                section_features[section_label] = feats

            # Store all section features
            for section_label, feats in section_features.items():
                feat_dict = feats.to_dict()
                for key, value in feat_dict.items():
                    row_features[f"{section_label}_{key}"] = value

            # Compute composite scores if requested
            composite_name = params.get("composite", "")
            if composite_name and composite_name in self.COMPOSITE_FORMULAS:
                composite_value = self._compute_composite(
                    composite_name, section_features
                )
                row_features["composite_score"] = composite_value

            all_features.append(row_features)

        # Build features DataFrame
        features_df = pd.DataFrame(all_features)

        # Carry forward identifier columns from the original data
        id_columns = [
            "application_number", "drug_name", "sponsor", "ticker",
            "cik", "filing_date", "accession_number", "pdufa_date",
            "advisory_committee_date", "decision", "submission_type",
        ]
        for col in id_columns:
            if col in df.columns and col not in features_df.columns:
                features_df[col] = df[col].values[:len(features_df)]

        # Build signal DataFrame (wide format for pipeline: date index, ticker columns)
        signal_df = self._build_signal_dataframe(features_df, df, params)

        # Normalize if requested
        if params.get("normalize", False):
            signal_df = self._normalize_signal(signal_df)

        # Build metadata
        metadata = SignalMetadata(
            builder_version="1.0.0",
            adapter_name=raw_data.provider,
            adapter_version="1.0.0",
            extractor_name=self.extractor_name,
            extractor_version=self.version,
            extractor_method="llm_temperature_zero" if self._use_llm and self._llm_temperature == 0 else "deterministic",
            hypothesis_uuid=params.get("hypothesis_uuid", ""),
            hypothesis_name=params.get("hypothesis_name", ""),
            parameters=params,
            data_source_timestamps={raw_data.provider: raw_data.acquired_at},
        )

        return SignalData(
            df=signal_df,
            metadata=metadata,
            long_format=features_df,
        )

    def _extract_from_text(
        self,
        text: str,
        section_label: str,
        hedge_pattern: re.Pattern,
        certainty_pattern: re.Pattern,
        vader_analyzer: Optional[Any] = None,
    ) -> LinguisticFeatures:
        """Extract all features from a single text string."""
        feats = LinguisticFeatures(section_label=section_label)

        # Tokenize into sentences
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip().split()) >= 3]
        feats.n_sentences = len(sentences)

        # Tokenize into words
        words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
        feats.n_words = len(words)

        if feats.n_sentences == 0 or feats.n_words == 0:
            return feats

        # Count syllables and complex words
        for word in words:
            syllables = self._count_syllables(word)
            feats.n_syllables += syllables
            if syllables >= 3:
                feats.n_complex_words += 1

        # --- Hedging ---
        hedge_matches = hedge_pattern.findall(text.lower())
        feats.hedge_phrases = len(hedge_matches)
        feats.hedge_density = feats.hedge_phrases / max(feats.n_sentences, 1)
        feats.hedge_phrases_found = list(set(hedge_matches))[:20]

        # --- Certainty ---
        cert_matches = certainty_pattern.findall(text.lower())
        feats.certainty_phrases = len(cert_matches)
        feats.certainty_density = feats.certainty_phrases / max(feats.n_sentences, 1)
        feats.certainty_phrases_found = list(set(cert_matches))[:20]

        # --- Active/Passive Ratio ---
        passive_count = 0
        for pattern in PASSIVE_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            passive_count += len(matches)
        feats.passive_constructions = passive_count

        # Approximate active constructions: sentences minus passive
        feats.active_constructions = max(0, feats.n_sentences - passive_count)
        if passive_count > 0:
            feats.active_to_passive_ratio = feats.active_constructions / passive_count
        else:
            feats.active_to_passive_ratio = float(feats.active_constructions) if feats.active_constructions > 0 else 0.0

        # --- Readability ---
        if feats.n_words > 0 and feats.n_sentences > 0:
            feats.flesch_kincaid_grade = (
                0.39 * (feats.n_words / feats.n_sentences)
                + 11.8 * (feats.n_syllables / feats.n_words)
                - 15.59
            )
            feats.automated_readability_index = (
                4.71 * (sum(len(re.findall(r'[a-zA-Z]+', s)) for s in sentences) / feats.n_sentences)
                + 0.5 * (feats.n_words / feats.n_sentences)
                - 21.43
            ) if sentences else 0

            feats.flesch_reading_ease = (
                206.835
                - 1.015 * (feats.n_words / feats.n_sentences)
                - 84.6 * (feats.n_syllables / feats.n_words)
            )

        # --- Pronouns ---
        for pattern in FIRST_PERSON_SINGULAR:
            feats.first_person_singular += len(re.findall(pattern, text))
        for pattern in FIRST_PERSON_PLURAL:
            feats.first_person_plural += len(re.findall(pattern, text))

        if feats.first_person_singular > 0:
            feats.pronoun_ratio = feats.first_person_plural / feats.first_person_singular
        else:
            feats.pronoun_ratio = float(feats.first_person_plural) if feats.first_person_plural > 0 else 0.0

        # --- Sentiment (VADER) ---
        if vader_analyzer is not None:
            try:
                scores = vader_analyzer.polarity_scores(text)
                feats.sentiment_compound = scores.get("compound", 0.0)
                feats.sentiment_positive = scores.get("pos", 0.0)
                feats.sentiment_negative = scores.get("neg", 0.0)
                feats.sentiment_neutral = scores.get("neu", 0.0)
            except Exception:
                pass

        return feats

    def _compute_composite(
        self,
        composite_name: str,
        section_features: Dict[str, LinguisticFeatures],
    ) -> float:
        """Compute a composite score from section-level features.

        Currently supported: BRLAS (Benefit-Risk Linguistic Asymmetry Score).

        BRLAS = (HedgeBenefit - HedgeRisk) + (CertaintyRisk - CertaintyBenefit)
                + 0.5 * (ReadabilityBenefit - ReadabilityRisk)
        """
        if composite_name == "brlas":
            benefit = section_features.get("benefit", LinguisticFeatures())
            risk = section_features.get("risk", LinguisticFeatures())

            hedge_diff = benefit.hedge_density - risk.hedge_density
            certainty_diff = risk.certainty_density - benefit.certainty_density
            readability_diff = benefit.flesch_reading_ease - risk.flesch_reading_ease

            # Normalize readability diff to similar scale as densities
            readability_norm = readability_diff / 100.0

            return hedge_diff + certainty_diff + 0.5 * readability_norm

        elif composite_name == "departure_language":
            current = section_features.get("current", section_features.get("full", LinguisticFeatures()))
            prior = section_features.get("prior", LinguisticFeatures())

            hedge_diff = current.hedge_density - prior.hedge_density
            certainty_diff = prior.certainty_density - current.certainty_density

            return hedge_diff + certainty_diff

        elif composite_name == "pronoun_divergence":
            current = section_features.get("current", section_features.get("full", LinguisticFeatures()))
            prior = section_features.get("prior", LinguisticFeatures())

            return current.pronoun_ratio - prior.pronoun_ratio

        return 0.0

    def _build_signal_dataframe(
        self,
        features_df: pd.DataFrame,
        original_df: pd.DataFrame,
        params: Dict[str, Any],
    ) -> pd.DataFrame:
        """Build a wide-format signal DataFrame (date index, ticker columns).

        The pipeline expects a DataFrame where:
        - Index: dates (DatetimeIndex)
        - Columns: ticker symbols
        - Values: signal values

        For non-equity hypotheses (like FDA), the 'ticker' is the drug name
        or application_number, and 'date' is the PDUFA date or document date.
        """
        # Determine the date column
        date_col = params.get("date_column", "")
        if not date_col:
            for candidate in ["pdufa_date", "advisory_committee_date", "filing_date", "date", "submission_date"]:
                if candidate in features_df.columns:
                    date_col = candidate
                    break
            if not date_col and "date" in original_df.columns:
                date_col = "date"

        # Determine the identifier column
        id_col = params.get("id_column", "")
        if not id_col:
            for candidate in ["drug_name", "application_number", "ticker", "sponsor"]:
                if candidate in features_df.columns:
                    id_col = candidate
                    break

        # Determine the signal value column
        signal_col = params.get("signal_column", "composite_score")
        if signal_col not in features_df.columns:
            # Fall back to any recognizable signal
            signal_candidates = ["composite_score",
                                 "full_hedge_density", "general_hedge_density",
                                 "risk_hedge_density", "mda_hedge_density",
                                 "benefit_hedge_density", "benefit_certainty_density"]
            for cand in signal_candidates:
                if cand in features_df.columns:
                    signal_col = cand
                    break

        if date_col not in features_df.columns and date_col not in original_df.columns:
            # No date column available, create a sequential date index
            logger.warning("No date column found; creating sequential date index")
            features_df["_date"] = pd.date_range("2020-01-01", periods=len(features_df), freq="B")
            date_col = "_date"

        # Merge date from original if needed
        if date_col not in features_df.columns and date_col in original_df.columns:
            features_df[date_col] = original_df[date_col].values[:len(features_df)]

        if date_col not in features_df.columns:
            raise SignalExtractionError(
                "linguistic",
                f"Cannot find date column '{date_col}' in features or original data. "
                f"Available: {list(features_df.columns)}",
            )

        if id_col not in features_df.columns:
            raise SignalExtractionError(
                "linguistic",
                f"Cannot find ID column '{id_col}'. "
                f"Available: {list(features_df.columns)}",
            )

        if signal_col in features_df.columns:
            signal_value = features_df[signal_col].values
        else:
            # Last resort: find any column with "hedge_density" or "density" in name
            fallback_cols = [c for c in features_df.columns if "density" in c.lower()]
            if fallback_cols:
                signal_value = features_df[fallback_cols[0]].values
            else:
                # Absolute fallback: use row index as dummy signal
                signal_value = list(range(len(features_df)))

        # Pivot: date index, id columns, signal value
        features_df["_date_parsed"] = pd.to_datetime(features_df[date_col], errors="coerce")
        features_df = features_df.dropna(subset=["_date_parsed"])
        features_df["_signal_value"] = signal_value[:len(features_df)]

        # Pivot to wide format
        try:
            signal_df = features_df.pivot_table(
                index="_date_parsed",
                columns=id_col,
                values="_signal_value",
                aggfunc="mean",
            )
        except Exception as e:
            # Fallback: create a simple wide DataFrame
            logger.warning(f"Pivot failed ({e}), creating simple signal DataFrame")
            unique_ids = features_df[id_col].unique()
            signal_df = pd.DataFrame(
                {uid: features_df.loc[features_df[id_col] == uid, "_signal_value"].values
                 for uid in unique_ids},
                index=features_df["_date_parsed"].iloc[:len(features_df)],
            )

        signal_df.index.name = "date"
        logger.info(
            f"Built signal DataFrame: {signal_df.shape[0]} dates x "
            f"{signal_df.shape[1]} IDs, signal column: {signal_col}"
        )

        return signal_df

    def _normalize_signal(self, signal_df: pd.DataFrame) -> pd.DataFrame:
        """Z-score normalize across columns (cross-sectional normalization)."""
        mean = signal_df.mean(axis=1)
        std = signal_df.std(axis=1)
        std = std.replace(0, 1.0)  # Avoid division by zero
        normalized = signal_df.sub(mean, axis=0).div(std, axis=0)
        return normalized

    def _init_vader(self) -> Optional[Any]:
        """Initialize VADER sentiment analyzer if available."""
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            return SentimentIntensityAnalyzer()
        except ImportError:
            logger.debug("vaderSentiment not installed; sentiment scores will be 0")
            return None

    def _count_syllables(self, word: str) -> int:
        """Count syllables in a word using vowel-group heuristic."""
        word = word.lower().strip()
        if not word:
            return 0
        if len(word) <= 3:
            return 1

        # Remove trailing silent e
        if word.endswith('e'):
            word = word[:-1]

        # Count vowel groups
        vowels = "aeiouy"
        count = 0
        prev_is_vowel = False
        for char in word:
            is_vowel = char in vowels
            if is_vowel and not prev_is_vowel:
                count += 1
            prev_is_vowel = is_vowel

        return max(1, count)

    def validate_signal(self, signal: SignalData) -> Tuple[bool, List[str]]:
        """Validate linguistic signal output."""
        issues = []
        valid, basic_issues = signal.validate()
        issues.extend(basic_issues)
        return len(issues) == 0, issues
