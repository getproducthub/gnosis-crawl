"""Prompt injection and hidden-text detection helpers.

This module is intentionally conservative: it only quarantines when we have
strong evidence that instruction-like content exists in extracted text but is
not present in the page's visible text (rendered content).

Why:
- DOM extraction can include hidden/screen-reader-only text.
- Downstream agents/LLMs might ingest those hidden instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional


# Heuristic patterns for agent-instruction style prompt injection.
# Keep this small and high-signal to avoid false positives.
_INJECTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"(?i)\b(ignore|disregard)\b.{0,40}\b(previous|above|earlier)\b.{0,20}\b(instructions|rules)\b"),
    re.compile(r"(?i)\b(system prompt|developer message)\b"),
    re.compile(r"(?i)\byou are (an|a)\s+(ai|language model|assistant)\b"),
    re.compile(r"(?i)\b(do not mention|never mention)\b.{0,40}\b(this|these)\b"),
    re.compile(r"(?i)\b(exfiltrate|leak|steal|dump)\b.{0,60}\b(token|secret|password|api key|apikey|credentials)\b"),
    re.compile(r"(?i)\b(send|post|upload)\b.{0,60}\b(to|into)\b.{0,60}\b(http|https)://"),
    re.compile(r"(?i)\b(call|invoke|use)\b.{0,30}\b(tool|function|mcp)\b"),
    re.compile(r"(?i)\b(curl|wget|powershell|bash|sh)\b"),
]


def _normalize_for_compare(text: str) -> str:
    text = (text or "").lower()
    # Remove obvious noise but keep words and spaces.
    text = re.sub(r"[^a-z0-9\\s]+", " ", text)
    text = re.sub(r"\\s+", " ", text).strip()
    return text


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\\b\\w+\\b", text))


@dataclass
class PromptInjectionAnalysis:
    quarantined: bool = False
    quarantine_reason: Optional[str] = None
    flags: List[str] = None
    visible_similarity: Optional[float] = None
    visible_char_count: int = 0
    visible_word_count: int = 0

    def __post_init__(self) -> None:
        if self.flags is None:
            self.flags = []


def analyze_hidden_prompt_injection(
    *,
    extracted_text: str,
    visible_text: str,
    similarity_prefix_chars: int = 20000,
) -> PromptInjectionAnalysis:
    """Compare extracted text vs visible rendered text and detect hidden injections."""
    extracted_text = extracted_text or ""
    visible_text = visible_text or ""

    analysis = PromptInjectionAnalysis(
        quarantined=False,
        quarantine_reason=None,
        flags=[],
        visible_similarity=None,
        visible_char_count=len(visible_text.strip()),
        visible_word_count=_word_count(visible_text),
    )

    if not extracted_text.strip():
        return analysis

    extracted_has_injection = any(p.search(extracted_text) for p in _INJECTION_PATTERNS)
    visible_has_injection = any(p.search(visible_text) for p in _INJECTION_PATTERNS)
    if extracted_has_injection:
        analysis.flags.append("prompt_injection_keywords")

    # Similarity is best-effort; avoid expensive comparisons on huge pages.
    norm_extracted = _normalize_for_compare(extracted_text)[:similarity_prefix_chars]
    norm_visible = _normalize_for_compare(visible_text)[:similarity_prefix_chars]
    if norm_extracted and norm_visible:
        analysis.visible_similarity = SequenceMatcher(None, norm_extracted, norm_visible).ratio()

    # High confidence quarantine: instruction-like text present in extracted content
    # but not present in visible rendered text.
    if extracted_has_injection and visible_text.strip() and not visible_has_injection:
        analysis.quarantined = True
        analysis.quarantine_reason = "hidden_prompt_injection_suspected"
        analysis.flags.extend(["hidden_text_suspected", "quarantined"])
        return analysis

    # Lower confidence: large mismatch between extracted and visible text.
    # This alone should not quarantine (too many legitimate edge cases), but we do
    # flag it for auditability and downstream gating.
    if (
        analysis.visible_similarity is not None
        and analysis.visible_similarity < 0.12
        and analysis.visible_word_count >= 80
        and _word_count(extracted_text) >= 120
    ):
        analysis.flags.append("visible_text_mismatch")
        if extracted_has_injection:
            analysis.quarantined = True
            analysis.quarantine_reason = "prompt_injection_with_visible_mismatch"
            analysis.flags.append("quarantined")

    return analysis

