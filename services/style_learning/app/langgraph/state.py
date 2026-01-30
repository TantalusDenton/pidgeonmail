"""State schema for the style learning LangGraph workflow."""

from typing import Any, Optional, TypedDict


class ToneAnalysis(TypedDict, total=False):
    """Tone analysis results."""

    formality: str  # casual, semi-formal, formal
    warmth: int  # 1-10
    assertiveness: int  # 1-10
    directness: int  # 1-10


class VocabularyAnalysis(TypedDict, total=False):
    """Vocabulary analysis results."""

    complexity: str  # simple, moderate, advanced
    common_phrases: list[str]
    average_sentence_length: int
    average_paragraph_length: int


class PatternAnalysis(TypedDict, total=False):
    """Pattern analysis results."""

    common_greetings: list[str]
    common_closings: list[str]
    punctuation_style: str


class StyleProfile(TypedDict, total=False):
    """Complete style profile."""

    tone: ToneAnalysis
    vocabulary: VocabularyAnalysis
    patterns: PatternAnalysis


class StyleLearningState(TypedDict, total=False):
    """State for the style learning workflow."""

    # Input
    user_id: str
    message_body: str
    message_subject: str
    is_reply: bool

    # Existing profile (loaded from memory)
    existing_profile: Optional[StyleProfile]
    samples_count: int

    # Analysis results from each node
    tone_analysis: ToneAnalysis
    vocabulary_analysis: VocabularyAnalysis
    pattern_analysis: PatternAnalysis

    # Merged/updated profile
    updated_profile: StyleProfile
    style_summary: str

    # Status
    is_duplicate: bool
    error: Optional[str]
