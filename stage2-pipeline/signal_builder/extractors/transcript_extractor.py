"""
transcript_extractor.py — Earnings Call Transcript Extraction from SEC EDGAR
============================================================================

Parses SEC full-submission .txt files to extract earnings call transcript
exhibits. Many companies file transcripts as 8-K EX-99.1 exhibits.

The SEC full submission format:
  <SEC-DOCUMENT>...
  <DOCUMENT>
  <TYPE>EX-99.1
  <SEQUENCE>N
  <FILENAME>earnings-transcript.htm
  <DESCRIPTION>EARNINGS CALL TRANSCRIPT
  <TEXT>
  <html>...transcript content...</html>
  </TEXT>
  </DOCUMENT>

Extracts the transcript text, cleans HTML, and segments prepared-remarks
vs. Q&A sections for downstream linguistic analysis.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Keywords that identify transcript exhibits in SEC filings
_TRANSCRIPT_DESCRIPTION_PATTERNS = [
    r"transcript",
    r"earnings\s*call",
    r"conference\s*call",
    r"investor\s*call",
    r"webcast",
    r"presentation\s*slides",  # sometimes bundled
]

_TRANSCRIPT_RE = re.compile(
    "|".join(f"({p})" for p in _TRANSCRIPT_DESCRIPTION_PATTERNS),
    re.IGNORECASE,
)

# Q&A section markers for segmenting transcripts
_QA_START_PATTERNS = [
    r"\n\s*Questions?\s*(?:and|&)\s*Answers?\s*\n",
    r"\n\s*Q\s*&?\s*A\s*Session\s*\n",
    r"\n\s*Operator\b",
    r"\n\s*Question-and-Answer",
    r"\n\s*Q&A\b",
]

_QA_START_RE = re.compile(
    "|".join(f"({p})" for p in _QA_START_PATTERNS),
    re.IGNORECASE,
)

# Speaker identification patterns
_SPEAKER_RE = re.compile(
    r"\n\s*(?:([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*[-–:]\s*)",
)

# Pronoun patterns for filtering (must have enough first-person plural)
_PRONOUN_RE = re.compile(
    r"\b(we|us|our|ours|ourselves)\b", re.IGNORECASE
)


class TranscriptExtractor:
    """Extract earnings call transcripts from SEC full-submission text."""

    def __init__(self, min_qa_length: int = 500, min_pronouns: int = 5):
        self._min_qa_length = min_qa_length
        self._min_pronouns = min_pronouns

    def extract_from_submission(
        self,
        raw_text: str,
        filing_type: str = "8-K",
    ) -> Optional[Dict[str, Any]]:
        """Extract transcript from a full SEC submission .txt file.

        Returns dict with:
          - full_transcript: str (entire transcript, prepared + Q&A)
          - qa_section: str (Q&A portion only)
          - prepared_remarks: str (prepared remarks only)
          - has_qa: bool
          - n_speakers: int
          - n_qa_words: int
        """
        if not raw_text or len(raw_text) < 5000:
            return None

        # Find transcript documents within the submission
        transcripts = self._find_transcript_docs(raw_text)
        if not transcripts:
            return None

        # Combine all transcript documents
        full_transcript = "\n\n".join(transcripts)
        if len(full_transcript) < 1000:
            return None

        # Clean HTML
        clean = self._strip_html(full_transcript)

        # Segment prepared remarks vs Q&A
        prepared, qa = self._segment_transcript(clean)

        # Check pronoun content (Q&A must have enough first-person plural)
        qa_pronouns = len(_PRONOUN_RE.findall(qa if qa else clean))
        if qa_pronouns < self._min_pronouns and not qa:
            # No Q&A section found and low pronouns overall — likely not a real transcript
            pass  # still return it, caller decides

        return {
            "full_transcript": clean,
            "qa_section": qa,
            "prepared_remarks": prepared,
            "has_qa": bool(qa) and len(qa) > self._min_qa_length,
            "n_speakers": self._count_speakers(clean),
            "n_qa_words": len(qa.split()) if qa else 0,
            "n_qa_pronouns": qa_pronouns,
        }

    # ------------------------------------------------------------------
    # Document extraction from SEC full submission
    # ------------------------------------------------------------------

    def _find_transcript_docs(self, raw_text: str) -> List[str]:
        """Find EX-99 documents that contain transcripts."""
        # Split into DOCUMENT blocks
        doc_blocks = re.split(
            r"\n\s*</?DOCUMENT>\s*\n", raw_text
        )

        transcripts = []
        for block in doc_blocks:
            if not self._is_transcript_doc(block):
                continue
            # Extract TEXT content
            text_content = self._extract_text_content(block)
            if text_content and len(text_content) > 500:
                transcripts.append(text_content)

        return transcripts

    def _is_transcript_doc(self, block: str) -> bool:
        """Check if a DOCUMENT block is a transcript exhibit."""
        # Must be an EX-99 type (exhibit 99)
        type_match = re.search(r"<TYPE>\s*(EX-99[.\d]*)\s*", block, re.IGNORECASE)
        if not type_match:
            return False

        # Check description for transcript keywords
        desc_match = re.search(
            r"<DESCRIPTION>\s*([^\n<]+)", block, re.IGNORECASE
        )
        desc = desc_match.group(1) if desc_match else ""
        filename_match = re.search(
            r"<FILENAME>\s*([^\n<]+)", block, re.IGNORECASE
        )
        filename = filename_match.group(1) if filename_match else ""

        combined = f"{desc} {filename}"
        return bool(_TRANSCRIPT_RE.search(combined))

    @staticmethod
    def _extract_text_content(block: str) -> Optional[str]:
        """Extract text between <TEXT> tags in a DOCUMENT block."""
        match = re.search(
            r"<TEXT>\s*(.*?)\s*</TEXT>", block, re.DOTALL | re.IGNORECASE
        )
        if not match:
            return None
        text = match.group(1)
        # Handle PDF/non-HTML content (base64 encoded or binary)
        if "<pdf>" in text.lower() or text.startswith("JVBER"):
            return None
        if "<xml>" in text.lower():
            return None
        return text.strip()

    # ------------------------------------------------------------------
    # HTML cleaning
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_html(text: str) -> str:
        """Strip HTML tags and return clean text."""
        try:
            from bs4 import BeautifulSoup
            try:
                import lxml  # noqa: F401
                parser = "lxml"
            except ImportError:
                parser = "html.parser"
            soup = BeautifulSoup(text, parser)
            for tag in soup(["script", "style", "meta", "link"]):
                tag.decompose()
            clean = soup.get_text(separator="\n")
        except ImportError:
            clean = re.sub(r"<[^>]+>", " ", text)
            clean = re.sub(r"&[a-z]+;", " ", clean)

        # Collapse whitespace
        clean = re.sub(r"\n\s*\n", "\n\n", clean)
        clean = re.sub(r"[ \t]+", " ", clean)
        clean = re.sub(r"\n{3,}", "\n\n", clean)
        return clean.strip()

    # ------------------------------------------------------------------
    # Transcript segmentation
    # ------------------------------------------------------------------

    @classmethod
    def _segment_transcript(cls, text: str) -> Tuple[str, str]:
        """Split transcript into prepared remarks and Q&A section.

        Returns (prepared_remarks, qa_section).
        """
        match = _QA_START_RE.search(text)
        if not match:
            return text, ""

        qa_start = match.start()
        prepared = text[:qa_start].strip()
        qa = text[qa_start:].strip()

        # If Q&A section is very short relative to prepared, the split
        # might be wrong — return everything as one block
        if len(qa) < len(prepared) * 0.1 and len(prepared) > 2000:
            return text, ""

        return prepared, qa

    @classmethod
    def _count_speakers(cls, text: str) -> int:
        """Count unique speaker names in the transcript."""
        speakers = set()
        for match in _SPEAKER_RE.finditer(text):
            name = match.group(1).strip()
            # Filter obvious non-names (common words at line start)
            if name.lower() not in {
                "the", "this", "that", "there", "these", "those",
                "they", "then", "thank", "thanks", "good", "great",
                "well", "yes", "yeah", "sure", "right", "ok", "okay",
                "and", "but", "for", "with", "from", "have", "been",
                "next", "last", "one", "two", "first", "second",
                "operator", "question", "answer", "morning", "afternoon",
                "ladies", "gentlemen", "hello", "hi", "hey",
            }:
                speakers.add(name)
        return len(speakers)

    # ------------------------------------------------------------------
    # Pronoun-specific extraction (for Pronoun Divergence hypothesis)
    # ------------------------------------------------------------------

    def extract_qa_pronouns(
        self,
        qa_text: str,
    ) -> Optional[Dict[str, float]]:
        """Extract pronoun metrics from Q&A section for PPR calculation.

        Returns:
            Dict with ppr, n_we_forms, n_total_pronouns, or None if insufficient.
        """
        if not qa_text or len(qa_text) < self._min_qa_length:
            return None

        we_forms = len(re.findall(r'\b(we|us|our|ours|ourselves)\b',
                                   qa_text, re.IGNORECASE))
        they_forms = len(re.findall(r'\b(they|them|their|theirs|themselves)\b',
                                    qa_text, re.IGNORECASE))
        i_forms = len(re.findall(r'\b(I|me|my|mine|myself)\b',
                                  qa_text, re.IGNORECASE))
        you_forms = len(re.findall(r'\b(you|your|yours|yourself|yourselves)\b',
                                    qa_text, re.IGNORECASE))
        he_she = len(re.findall(r'\b(he|she|him|her|his|hers|himself|herself)\b',
                                 qa_text, re.IGNORECASE))
        it_forms = len(re.findall(r'\b(it|its|itself)\b',
                                   qa_text, re.IGNORECASE))

        total_pronouns = we_forms + they_forms + i_forms + you_forms + he_she + it_forms
        if total_pronouns == 0:
            return None

        ppr = we_forms / total_pronouns
        return {
            "ppr": round(ppr, 4),
            "n_we_forms": we_forms,
            "n_total_pronouns": total_pronouns,
            "n_i_forms": i_forms,
            "n_they_forms": they_forms,
        }
