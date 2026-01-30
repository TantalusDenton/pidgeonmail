"""API routes for the style learning service."""

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.models import (
    ErrorResponse,
    HealthResponse,
    LearnRequest,
    LearnResponse,
    PatternProfile,
    StyleProfile,
    StyleResponse,
    ToneProfile,
    VocabularyProfile,
)
from app.config import Settings, get_settings
from app.langgraph.graph import run_style_learning
from app.memory.store import get_store

router = APIRouter(prefix="/api/v1", tags=["style-learning"])


def verify_api_key(
    x_api_key: str = Header(None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> bool:
    """Verify the API key if one is configured."""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return True


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="healthy", version="1.0.0")


@router.post(
    "/learn",
    response_model=LearnResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def learn_from_message(
    request: LearnRequest,
    _: bool = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
) -> LearnResponse:
    """Submit a user-written message for style learning.

    This endpoint analyzes the provided message and updates the user's
    style profile based on the writing patterns detected.
    """
    # Validate message length
    if len(request.message.body) < settings.min_message_length:
        return LearnResponse(
            success=False,
            message=f"Message too short (minimum {settings.min_message_length} characters)",
            samples_count=0,
        )

    try:
        # Run the style learning workflow
        result = await run_style_learning(
            user_id=request.user_id,
            message_body=request.message.body,
            message_subject=request.message.subject,
            is_reply=request.context.is_reply,
        )

        if result.get("is_duplicate"):
            return LearnResponse(
                success=True,
                message="Message already processed (duplicate)",
                samples_count=result.get("samples_count", 0),
            )

        if result.get("error"):
            return LearnResponse(
                success=False,
                message=f"Analysis error: {result['error']}",
                samples_count=result.get("samples_count", 0),
            )

        return LearnResponse(
            success=True,
            message="Style profile updated successfully",
            samples_count=result.get("samples_count", 0),
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process message: {str(e)}",
        )


@router.get(
    "/style/{user_id}",
    response_model=StyleResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_user_style(
    user_id: str,
    _: bool = Depends(verify_api_key),
) -> StyleResponse:
    """Retrieve the learned style profile for a user.

    Returns the user's writing style characteristics including tone,
    vocabulary patterns, and common phrases.
    """
    store = get_store()
    profile_data = await store.get_user_style_data(user_id)

    if not profile_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No style profile found for user: {user_id}",
        )

    style_data = profile_data.get("style_data", {})

    # Convert to response model
    tone_data = style_data.get("tone", {})
    patterns_data = style_data.get("patterns", {})
    vocab_data = style_data.get("vocabulary", {})

    return StyleResponse(
        user_id=user_id,
        style_summary=profile_data.get("style_summary", ""),
        style_profile=StyleProfile(
            tone=ToneProfile(
                formality=tone_data.get("formality", "neutral"),
                warmth=tone_data.get("warmth", 5),
                assertiveness=tone_data.get("assertiveness", 5),
                directness=tone_data.get("directness", 5),
            ),
            patterns=PatternProfile(
                common_greetings=patterns_data.get("common_greetings", []),
                common_closings=patterns_data.get("common_closings", []),
                punctuation_style=patterns_data.get("punctuation_style", "standard"),
            ),
            vocabulary=VocabularyProfile(
                complexity=vocab_data.get("complexity", "moderate"),
                common_phrases=vocab_data.get("common_phrases", []),
                average_sentence_length=vocab_data.get("average_sentence_length", 15),
                average_paragraph_length=vocab_data.get("average_paragraph_length", 3),
            ),
        ),
        samples_count=profile_data.get("samples_count", 0),
        last_updated=profile_data.get("updated_at"),
    )


@router.delete(
    "/style/{user_id}",
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def delete_user_style(
    user_id: str,
    _: bool = Depends(verify_api_key),
) -> dict:
    """Delete a user's style profile and all associated samples.

    This is a destructive operation that removes all learned data for the user.
    """
    store = get_store()

    # Check if profile exists
    profile = await store.get_user_profile(user_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No style profile found for user: {user_id}",
        )

    # Delete samples and profile
    async with store.session() as session:
        from sqlalchemy import delete

        from app.memory.models import StyleHistory, StyleSample, UserStyleProfile

        await session.execute(
            delete(StyleSample).where(StyleSample.user_id == user_id)
        )
        await session.execute(
            delete(StyleHistory).where(StyleHistory.user_id == user_id)
        )
        await session.execute(
            delete(UserStyleProfile).where(UserStyleProfile.user_id == user_id)
        )

    return {"message": f"Style profile deleted for user: {user_id}"}
