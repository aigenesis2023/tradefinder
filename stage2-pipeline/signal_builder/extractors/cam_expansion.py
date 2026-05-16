"""
cam_expansion.py — CAM Expansion Velocity Extractor
=====================================================

Detects when auditors add new Critical Audit Matters (CAMs) or expand
existing CAM topics — signaling escalating accounting complexity before
visible financial deterioration.

Approach: extracts CAM paragraphs from the audit report section of 10-K
filings, counts CAMs per filing, and computes expansion metrics vs the
prior year's filing for the same company.

Signal = cam_expansion_velocity (higher = more CAM expansion = bearish).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .linguistic import SignalExtractor
from ..base import RawData, SignalData, SignalMetadata

logger = logging.getLogger(__name__)

# CAM section start: "Critical Audit Matter(s)" at line start — the main header
_CAM_SECTION_START = re.compile(
    r'(?:^|\n)\s*(?:Critical\s+Audit\s+Matters?)\s*\n',
    re.IGNORECASE | re.MULTILINE,
)

# Individual CAM markers — two formats observed in real filings:
#   Format A: "Critical Accounting Matter Description" or "Critical Audit Matter Description"
#   Format B: "Description of the Matter"
# Each marker starts a new CAM's description block.
_CAM_DESC_HEADING = re.compile(
    r'(?:^|\n)\s*'
    r'(?:Critical\s+(?:Accounting|Audit)\s+Matter\s+Description'
    r'|Description\s+of\s+the\s+Matter)'
    r'\s*\n',
    re.IGNORECASE | re.MULTILINE,
)

# End-of-CAM-section markers: auditor signature, financial statements, next Item
_CAM_END_RE = re.compile(
    r'\n\s*/s/\s*\n'
    r'|\n(?:REPORT\s+OF\s+INDEPENDENT|Report\s+of\s+Independent)'
    r'|\n\s*(?:CONSOLIDATED\s+)?BALANCE\s+SHEETS?\s*\n'
    r'|\n\s*(?:ITEM|Item)\s*(?:9B|10|11|12|13|14|15)[\.\s]',
    re.IGNORECASE | re.MULTILINE,
)

# Simple topic classification keywords for CAM paragraphs
CAM_TOPIC_KEYWORDS = {
    # Order matters: more specific / serious patterns first.
    "goodwill_impairment": [
        r"goodwill", r"impairment", r"indefinite.?lived\s+intangible",
        r"fair\s+value\s+of\s+reporting\s+unit",
        r"proved\s+reserves?", r"full\s+cost\s+method",
        r"oil\s+and\s+gas\s+propert",
    ],
    "loan_loss_reserve": [
        r"allowance\s+for\s+(?:loan|credit)\s+loss",
        r"credit\s+loss", r"expected\s+loss", r"cecl",
        r"loan\s+portfolio", r"reserve\s+for\s+credit",
    ],
    "litigation_contingency": [
        r"litigation", r"legal\s+proceed", r"contingen",
        r"loss\s+contingen", r"settlement", r"regulatory\s+matter",
    ],
    "tax": [
        r"tax\s+provision", r"uncertain\s+tax\s+position",
        r"deferred\s+tax\s+asset", r"valuation\s+allowance",
        r"transfer\s+pric", r"unrecognized\s+tax\s+benefit",
    ],
    "acquisition_accounting": [
        r"business\s+combin", r"acquis", r"purchase\s+price\s+alloc",
        r"intangible\s+asset", r"contingent\s+consideration",
    ],
    "revenue_recognition": [
        r"revenue\s+recogni", r"performance\s+obligation",
        r"variable\s+consideration", r"percentage\s+of\s+completion",
        r"contract\s+(?:cost|revenue|drilling)",
    ],
    "inventory": [
        r"inventor", r"obsolescence", r"lower\s+of\s+cost",
        r"net\s+realizable\s+value", r"excess\s+and\s+obsolete",
    ],
    "financial_instruments": [
        r"financial\s+instrument", r"derivative", r"hedg",
        r"fair\s+value\s+measurement", r"level\s+[123]",
    ],
    "pension": [
        r"pension", r"post.?retirement\s+benefit", r"defined\s+benefit",
        r"actuarial\s+assumption", r"discount\s+rate",
    ],
    "other_estimates": [
        r"estimate", r"assumption", r"judgment", r"subjectivity",
        r"management\s+bias", r"complex\s+accounting",
    ],
}

# Aggregate topic categories
_TOPIC_AGGREGATES = {
    "revenue_recognition": "revenue",
    "goodwill_impairment": "asset_valuation",
    "inventory": "asset_valuation",
    "tax": "tax_liability",
    "litigation_contingency": "tax_liability",
    "acquisition_accounting": "acquisition",
    "financial_instruments": "financial_instruments",
    "loan_loss_reserve": "credit_risk",
    "pension": "benefit_obligations",
    "other_estimates": "estimates",
}


def _isolate_cam_section(text: str) -> str:
    """Extract the CAM sub-section from audit report or full filing text.

    Finds "Critical Audit Matter(s)" header, then cuts at the auditor
    signature, financial statements, or next Item heading.
    """
    if not text or not isinstance(text, str):
        return ""

    m = _CAM_SECTION_START.search(text)
    if not m:
        return ""

    cam_start = m.start()
    remaining = text[cam_start:]

    # Find the end: auditor signature, financial statements, or next Item
    end_m = _CAM_END_RE.search(remaining[100:])
    if end_m:
        remaining = remaining[:end_m.start() + 100]

    # Hard cap at 15K chars — CAM sections are typically 2-10K
    return remaining[:15000]


def _extract_cam_paragraphs(text: str) -> List[str]:
    """Extract individual CAM paragraphs from filing text.

    Handles two real-world formats:
      Format A: "Critical Accounting Matter Description" sub-headings
      Format B: "Description of the Matter" sub-headings

    Each CAM = one description-marker block. Topic classification runs
    on the full CAM paragraph (topic heading + description + procedures).
    """
    if not text or not isinstance(text, str):
        return []

    cam_section = _isolate_cam_section(text)
    if not cam_section:
        return []

    # Find all CAM description markers
    desc_matches = list(_CAM_DESC_HEADING.finditer(cam_section))
    if not desc_matches:
        # No structured sub-headings; treat the whole section as one CAM
        body = cam_section.strip()
        if len(body) >= 300:
            return [body]
        return []

    # Build one paragraph per description marker. Include the preceding
    # topic heading (text between the previous marker/intro and this marker)
    # for classification context.
    paras = []
    for i, dm in enumerate(desc_matches):
        # Start of this CAM: find the topic heading text before the marker
        if i == 0:
            preamble = cam_section[:dm.start()]
            # Strip the boilerplate intro paragraph ("The critical audit
            # matter(s) communicated below are...")
            intro_cut = re.search(
                r'(?:communicated\s+below|do\s+not\s+alter|providing\s+separate|'
                r'does\s+not\s+alter|in\s+any\s+way\s+our\s+opinion)',
                preamble, re.I,
            )
            if intro_cut:
                # Take text after the intro sentence (find next sentence break)
                post_intro = preamble[intro_cut.end():]
                # Skip to next paragraph break
                para_break = re.search(r'\n\s*\n', post_intro)
                topic_heading = post_intro[para_break.end():].strip() if para_break else ''
            else:
                topic_heading = preamble.strip()
        else:
            prev_end = desc_matches[i - 1].end()
            topic_heading = cam_section[prev_end:dm.start()].strip()

        # End of this CAM: next description marker or end of section
        cam_end = desc_matches[i + 1].start() if i + 1 < len(desc_matches) else len(cam_section)
        para = cam_section[dm.start():cam_end].strip()

        # Prepend topic heading for classification context
        if topic_heading:
            # Clean page numbers and table-of-contents artifacts
            topic_heading = re.sub(r'\n\s*\d{1,3}\s*\n', '\n', topic_heading)
            topic_heading = re.sub(r'\nTable\s+of\s+Contents\s*\n', '\n', topic_heading, flags=re.I)
            if len(topic_heading) < 800:
                para = topic_heading + '\n' + para

        if len(para) >= 100:
            paras.append(para)

    return paras


def _classify_cam_topic(cam_text: str) -> Optional[str]:
    """Classify a CAM paragraph into a topic category using keyword matching.

    Prioritises the Description sub-section (between "Critical ... Matter Description"
    and "How ... Addressed") since that describes what the CAM is about. The
    How-Addressed section often references boilerplate procedures that can
    mention unrelated topics.
    """
    text_lower = cam_text.lower()

    # Extract the description portion only (highest-signal text)
    desc_match = re.search(
        r'critical\s+(?:accounting|audit)\s+matter\s+description\s*\n(.*?)(?:how\s+(?:the\s+)?critical\s+audit\s+matter\s+was\s+addressed|\Z)',
        text_lower, re.DOTALL | re.IGNORECASE,
    )
    desc_text = desc_match.group(1) if desc_match else text_lower

    # Search description first, then fall back to full text
    for search_text in (desc_text, text_lower):
        for topic, patterns in CAM_TOPIC_KEYWORDS.items():
            for pattern in patterns:
                if re.search(pattern, search_text):
                    return _TOPIC_AGGREGATES.get(topic, topic)

    return "other"


def _compute_cam_metrics(
    cam_text: str, prev_cam_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute CAM metrics for a single filing.

    Uses _extract_cam_paragraphs to find individual CAMs, then classifies
    each one into topic categories. When prev_cam_text is provided, computes
    expansion metrics (new topics, count change).
    """
    cam_paras = _extract_cam_paragraphs(cam_text)
    n_cams = len(cam_paras)

    topics = set()
    for cp in cam_paras:
        topic = _classify_cam_topic(cp)
        if topic:
            topics.add(topic)

    metrics: Dict[str, Any] = {
        "n_cams": n_cams,
        "n_topics": len(topics),
        "topics": sorted(topics),
    }

    if prev_cam_text:
        prev_paras = _extract_cam_paragraphs(prev_cam_text)
        prev_n = len(prev_paras)
        prev_topics = set()
        for cp in prev_paras:
            topic = _classify_cam_topic(cp)
            if topic:
                prev_topics.add(topic)
        n_new_topics = len(topics - prev_topics)
        n_removed_topics = len(prev_topics - topics)
        metrics["n_new_topics"] = n_new_topics
        metrics["n_removed_topics"] = n_removed_topics
        metrics["cam_count_change"] = n_cams - prev_n
        metrics["prev_n_cams"] = prev_n
        metrics["prev_n_topics"] = len(prev_topics)

    return metrics


class CAMExpansionExtractor(SignalExtractor):
    """Extract CAM expansion signal from sequential 10-K audit reports.

    Groups 10-K filings by ticker, pairs sequential filings, extracts CAM
    paragraphs, classifies topics, and computes expansion velocity.
    """

    MIN_PAIR_OBSERVATIONS = 3

    @property
    def extractor_name(self) -> str:
        return "cam_expansion"

    @property
    def version(self) -> str:
        return "1.0.0"

    def extract(
        self,
        raw_data: RawData,
        params: Optional[Dict[str, Any]] = None,
    ) -> SignalData:
        params = params or {}
        signal_name = params.get("signal_name", "cam_expansion_velocity")
        higher_is_better = params.get("higher_is_better", False)

        df = raw_data.records.copy()

        # Prefer full text (cleanest CAM isolation), then audit_report, then cam_text.
        # cam_text from section extraction often starts at sub-headings and
        # misses the main CAM section header.
        cam_col = None
        if "full_text" in df.columns:
            cam_col = "full_text"
        elif "audit_report_text" in df.columns:
            cam_col = "audit_report_text"
        elif "cam_text" in df.columns:
            cam_col = "cam_text"
        else:
            return self._empty_signal(signal_name)

        # Filter to 10-K only
        if "form_type" in df.columns:
            df = df[df["form_type"].str.upper().str.strip().isin(["10-K", "10-K/A"])].copy()
            if df.empty:
                logger.info("CAMExpansion: no 10-K filings in data")
                return self._empty_signal(signal_name)

        # Must have filing_date
        if "filing_date" not in df.columns:
            logger.warning("CAMExpansion: no filing_date column")
            return self._empty_signal(signal_name)

        df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
        df = df.dropna(subset=["filing_date", cam_col])
        df = df[df[cam_col].str.len() >= 500].copy()

        n_tickers = df["ticker"].nunique() if "ticker" in df.columns else 0
        logger.info(
            f"CAMExpansion: {len(df)} 10-K filings across {n_tickers} tickers"
        )

        if df.empty or n_tickers < self.MIN_PAIR_OBSERVATIONS:
            return self._empty_signal(signal_name)

        signal_rows = []
        for ticker, grp in df.groupby("ticker"):
            grp = grp.sort_values("filing_date")
            if len(grp) < 2:
                continue

            cam_cache: Dict[int, Dict[str, Any]] = {}
            for idx, row in grp.iterrows():
                cam_text = str(row[cam_col])
                metrics = _compute_cam_metrics(cam_text)
                if metrics["n_cams"] >= 1:
                    cam_cache[idx] = metrics

            if len(cam_cache) < 2:
                continue

            indices = list(cam_cache.keys())
            for i in range(len(indices) - 1):
                old_idx = indices[i]
                new_idx = indices[i + 1]

                old_metrics = cam_cache[old_idx]
                new_metrics = cam_cache[new_idx]

                # Recompute with previous for expansion metrics
                new_row = grp.loc[new_idx]
                full_metrics = _compute_cam_metrics(
                    str(new_row[cam_col]),
                    str(grp.loc[old_idx, cam_col]),
                )

                n_new_topics = full_metrics.get("n_new_topics", 0)
                cam_count_change = full_metrics.get("cam_count_change", 0)

                # CAM expansion velocity: new topics weighted by count increase
                velocity = n_new_topics + 0.5 * max(cam_count_change, 0)

                signal_rows.append({
                    "signal_date": pd.Timestamp(new_row["filing_date"]),
                    "ticker": ticker,
                    signal_name: round(float(velocity), 6),
                    "n_cams": new_metrics["n_cams"],
                    "n_topics": new_metrics["n_topics"],
                    "n_new_topics": n_new_topics,
                    "cam_count_change": cam_count_change,
                    "prev_n_cams": old_metrics["n_cams"],
                })

        if not signal_rows:
            logger.info("CAMExpansion: no 10-K pairs with extractable CAMs")
            return self._empty_signal(signal_name)

        signal_df = pd.DataFrame(signal_rows)
        signal_df["signal_date"] = pd.to_datetime(signal_df["signal_date"])

        n_tickers_out = signal_df["ticker"].nunique()
        n_signals = len(signal_df)
        mean_vel = signal_df[signal_name].mean()

        logger.info(
            f"CAMExpansion: {n_signals} signal events across "
            f"{n_tickers_out} tickers. "
            f"Mean velocity: {mean_vel:.4f}. "
            f"Mean CAMs: {signal_df['n_cams'].mean():.1f}, "
            f"Mean new topics: {signal_df['n_new_topics'].mean():.1f}"
        )

        wide_df = signal_df.pivot_table(
            index="signal_date", columns="ticker",
            values=signal_name, aggfunc="first",
        )
        wide_df.index = pd.DatetimeIndex(wide_df.index)

        return SignalData(
            df=wide_df,
            long_format=signal_df.copy(),
            metadata=SignalMetadata(
                extractor_name=self.extractor_name,
                extractor_version=self.version,
                extractor_method="deterministic",
                parameters={
                    "signal_name": signal_name,
                    "method": "sequential_10k_cam_diff",
                    "n_tickers": n_tickers_out,
                    "n_signals": n_signals,
                    "mean_n_cams": float(signal_df["n_cams"].mean()),
                    "mean_n_new_topics": float(signal_df["n_new_topics"].mean()),
                    "mean_velocity": float(mean_vel),
                },
            ),
        )

    def validate_signal(
        self, signal: SignalData,
    ) -> Tuple[bool, List[str]]:
        issues = []
        df = signal.df if hasattr(signal, 'df') else signal

        if df is None or (hasattr(df, 'empty') and df.empty):
            issues.append("CAM Signal DataFrame is empty")
            return False, issues

        if not isinstance(df, pd.DataFrame):
            issues.append(f"CAM Signal is not a DataFrame: {type(df)}")
            return False, issues

        n_non_nan = int((~df.isna()).sum().sum())
        if n_non_nan < 3:
            issues.append(f"Too few non-NaN CAM signal values ({n_non_nan})")
            return False, issues

        return True, issues

    def _empty_signal(self, signal_name: str) -> SignalData:
        return SignalData(
            df=pd.DataFrame(),
            metadata=SignalMetadata(
                extractor_name=self.extractor_name,
                extractor_version=self.version,
                extractor_method="deterministic",
                parameters={"signal_name": signal_name, "empty": True},
            ),
        )
