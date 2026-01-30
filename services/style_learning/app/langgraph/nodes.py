"""LangGraph nodes for style analysis workflow."""

import json
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.langgraph.state import (
    PatternAnalysis,
    StyleLearningState,
    StyleProfile,
    ToneAnalysis,
    VocabularyAnalysis,
)
from app.memory.store import get_store


def get_openai_client() -> AsyncOpenAI:
    """Get OpenAI client."""
    settings = get_settings()
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def load_memory(state: StyleLearningState) -> dict[str, Any]:
    """Load existing user style profile from database."""
    store = get_store()
    user_id = state["user_id"]

    profile_data = await store.get_user_style_data(user_id)

    if profile_data and profile_data.get("style_data"):
        return {
            "existing_profile": profile_data["style_data"],
            "samples_count": profile_data.get("samples_count", 0),
        }

    return {
        "existing_profile": None,
        "samples_count": 0,
    }


async def analyze_tone(state: StyleLearningState) -> dict[str, Any]:
    """Analyze tone characteristics using OpenAI."""
    settings = get_settings()
    client = get_openai_client()

    prompt = f"""Analyze the tone of this email message and return a JSON object with the following fields:
- formality: one of "casual", "semi-formal", or "formal"
- warmth: integer from 1-10 (1=cold/distant, 10=very warm/friendly)
- assertiveness: integer from 1-10 (1=passive, 10=very assertive)
- directness: integer from 1-10 (1=indirect/hedging, 10=very direct)

Email:
{state["message_body"]}

Return ONLY valid JSON, no markdown or explanation."""

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        content = response.choices[0].message.content or "{}"
        # Clean up markdown code blocks if present
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)

        analysis = json.loads(content)

        return {
            "tone_analysis": ToneAnalysis(
                formality=analysis.get("formality", "semi-formal"),
                warmth=max(1, min(10, analysis.get("warmth", 5))),
                assertiveness=max(1, min(10, analysis.get("assertiveness", 5))),
                directness=max(1, min(10, analysis.get("directness", 5))),
            )
        }
    except Exception as e:
        return {
            "tone_analysis": ToneAnalysis(
                formality="semi-formal",
                warmth=5,
                assertiveness=5,
                directness=5,
            ),
            "error": f"Tone analysis error: {str(e)}",
        }


async def analyze_vocabulary(state: StyleLearningState) -> dict[str, Any]:
    """Analyze vocabulary and structure using OpenAI."""
    settings = get_settings()
    client = get_openai_client()

    prompt = f"""Analyze the vocabulary and structure of this email and return a JSON object with:
- complexity: one of "simple", "moderate", or "advanced" (based on word choice)
- common_phrases: array of 2-5 notable phrases or expressions used
- average_sentence_length: estimated average words per sentence (integer)
- average_paragraph_length: estimated average sentences per paragraph (integer)

Email:
{state["message_body"]}

Return ONLY valid JSON, no markdown or explanation."""

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        content = response.choices[0].message.content or "{}"
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)

        analysis = json.loads(content)

        return {
            "vocabulary_analysis": VocabularyAnalysis(
                complexity=analysis.get("complexity", "moderate"),
                common_phrases=analysis.get("common_phrases", [])[:5],
                average_sentence_length=max(5, min(50, analysis.get("average_sentence_length", 15))),
                average_paragraph_length=max(1, min(10, analysis.get("average_paragraph_length", 3))),
            )
        }
    except Exception as e:
        return {
            "vocabulary_analysis": VocabularyAnalysis(
                complexity="moderate",
                common_phrases=[],
                average_sentence_length=15,
                average_paragraph_length=3,
            ),
            "error": f"Vocabulary analysis error: {str(e)}",
        }


async def analyze_patterns(state: StyleLearningState) -> dict[str, Any]:
    """Analyze greeting, closing, and punctuation patterns using OpenAI."""
    settings = get_settings()
    client = get_openai_client()

    prompt = f"""Analyze the patterns in this email and return a JSON object with:
- common_greetings: array of greetings used (e.g., "Hi", "Hello", "Hey there")
- common_closings: array of sign-offs used (e.g., "Best regards", "Thanks", "Cheers")
- punctuation_style: one of "minimal", "standard", or "expressive" (uses lots of ! or ...)

Email:
{state["message_body"]}

Return ONLY valid JSON, no markdown or explanation."""

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        content = response.choices[0].message.content or "{}"
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)

        analysis = json.loads(content)

        return {
            "pattern_analysis": PatternAnalysis(
                common_greetings=analysis.get("common_greetings", [])[:5],
                common_closings=analysis.get("common_closings", [])[:5],
                punctuation_style=analysis.get("punctuation_style", "standard"),
            )
        }
    except Exception as e:
        return {
            "pattern_analysis": PatternAnalysis(
                common_greetings=[],
                common_closings=[],
                punctuation_style="standard",
            ),
            "error": f"Pattern analysis error: {str(e)}",
        }


def _merge_lists(existing: list[str], new: list[str], max_items: int = 5) -> list[str]:
    """Merge two lists, prioritizing items that appear in both."""
    # Count occurrences
    counts: dict[str, int] = {}
    for item in existing:
        counts[item] = counts.get(item, 0) + 1
    for item in new:
        counts[item] = counts.get(item, 0) + 2  # Weight new items more

    # Sort by count and return top items
    sorted_items = sorted(counts.keys(), key=lambda x: counts[x], reverse=True)
    return sorted_items[:max_items]


def _weighted_average(existing: int, new: int, weight: float) -> int:
    """Calculate weighted average of two values."""
    return round(existing * (1 - weight) + new * weight)


async def merge_analysis(state: StyleLearningState) -> dict[str, Any]:
    """Merge new analysis with existing profile."""
    settings = get_settings()
    weight = settings.profile_update_weight

    existing = state.get("existing_profile")
    tone = state.get("tone_analysis", {})
    vocabulary = state.get("vocabulary_analysis", {})
    patterns = state.get("pattern_analysis", {})

    if existing:
        # Merge with existing profile
        existing_tone = existing.get("tone", {})
        existing_vocab = existing.get("vocabulary", {})
        existing_patterns = existing.get("patterns", {})

        merged_profile = StyleProfile(
            tone=ToneAnalysis(
                formality=tone.get("formality", existing_tone.get("formality", "semi-formal")),
                warmth=_weighted_average(
                    existing_tone.get("warmth", 5), tone.get("warmth", 5), weight
                ),
                assertiveness=_weighted_average(
                    existing_tone.get("assertiveness", 5), tone.get("assertiveness", 5), weight
                ),
                directness=_weighted_average(
                    existing_tone.get("directness", 5), tone.get("directness", 5), weight
                ),
            ),
            vocabulary=VocabularyAnalysis(
                complexity=vocabulary.get("complexity", existing_vocab.get("complexity", "moderate")),
                common_phrases=_merge_lists(
                    existing_vocab.get("common_phrases", []),
                    vocabulary.get("common_phrases", []),
                ),
                average_sentence_length=_weighted_average(
                    existing_vocab.get("average_sentence_length", 15),
                    vocabulary.get("average_sentence_length", 15),
                    weight,
                ),
                average_paragraph_length=_weighted_average(
                    existing_vocab.get("average_paragraph_length", 3),
                    vocabulary.get("average_paragraph_length", 3),
                    weight,
                ),
            ),
            patterns=PatternAnalysis(
                common_greetings=_merge_lists(
                    existing_patterns.get("common_greetings", []),
                    patterns.get("common_greetings", []),
                ),
                common_closings=_merge_lists(
                    existing_patterns.get("common_closings", []),
                    patterns.get("common_closings", []),
                ),
                punctuation_style=patterns.get(
                    "punctuation_style", existing_patterns.get("punctuation_style", "standard")
                ),
            ),
        )
    else:
        # Create new profile from analysis
        merged_profile = StyleProfile(
            tone=tone or ToneAnalysis(formality="semi-formal", warmth=5, assertiveness=5, directness=5),
            vocabulary=vocabulary or VocabularyAnalysis(
                complexity="moderate", common_phrases=[], average_sentence_length=15, average_paragraph_length=3
            ),
            patterns=patterns or PatternAnalysis(
                common_greetings=[], common_closings=[], punctuation_style="standard"
            ),
        )

    return {"updated_profile": merged_profile}


async def generate_summary(state: StyleLearningState) -> dict[str, Any]:
    """Generate a human-readable style summary."""
    profile = state.get("updated_profile", {})
    tone = profile.get("tone", {})
    vocab = profile.get("vocabulary", {})
    patterns = profile.get("patterns", {})

    formality = tone.get("formality", "semi-formal")
    warmth = tone.get("warmth", 5)
    directness = tone.get("directness", 5)

    warmth_desc = "warm and friendly" if warmth >= 7 else "neutral" if warmth >= 4 else "reserved"
    directness_desc = "direct" if directness >= 7 else "balanced" if directness >= 4 else "indirect"

    greetings = patterns.get("common_greetings", [])
    closings = patterns.get("common_closings", [])

    summary_parts = [f"You write in a {formality}, {warmth_desc} tone."]
    summary_parts.append(f"Your communication style is {directness_desc}.")

    if greetings:
        summary_parts.append(f"Common greetings: {', '.join(greetings[:3])}.")
    if closings:
        summary_parts.append(f"Common sign-offs: {', '.join(closings[:3])}.")

    complexity = vocab.get("complexity", "moderate")
    summary_parts.append(f"Vocabulary complexity: {complexity}.")

    avg_sent = vocab.get("average_sentence_length", 15)
    summary_parts.append(f"Average sentence length: ~{avg_sent} words.")

    return {"style_summary": " ".join(summary_parts)}


async def store_memory(state: StyleLearningState) -> dict[str, Any]:
    """Store the updated profile and sample in the database."""
    store = get_store()
    user_id = state["user_id"]
    message_body = state["message_body"]
    profile = state.get("updated_profile", {})
    summary = state.get("style_summary", "")
    samples_count = state.get("samples_count", 0)

    # Save the sample
    sample = await store.save_sample(
        user_id=user_id,
        message_text=message_body,
        analysis_data={
            "tone": state.get("tone_analysis"),
            "vocabulary": state.get("vocabulary_analysis"),
            "patterns": state.get("pattern_analysis"),
        },
    )

    if sample is None:
        return {"is_duplicate": True}

    new_count = samples_count + 1

    # Save the updated profile
    await store.save_user_profile(
        user_id=user_id,
        style_data=dict(profile),
        style_summary=summary,
        samples_count=new_count,
    )

    # Save history snapshot
    await store.save_history_snapshot(user_id=user_id, style_snapshot=dict(profile))

    # Clean up old samples
    settings = get_settings()
    await store.delete_old_samples(user_id, keep_count=settings.max_samples_per_user)

    return {"samples_count": new_count, "is_duplicate": False}
