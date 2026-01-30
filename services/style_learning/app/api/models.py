"""Pydantic models for API requests and responses."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# Request Models
class MessageContent(BaseModel):
    """Email message content for learning."""

    body: str = Field(..., min_length=1, description="The email body text")
    subject: str = Field(default="", description="Email subject line")
    recipients: list[str] = Field(default_factory=list, description="List of recipient emails")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="When the message was sent")


class MessageContext(BaseModel):
    """Context about the message being learned from."""

    is_reply: bool = Field(default=False, description="Whether this is a reply to another email")
    original_subject: Optional[str] = Field(default=None, description="Subject of the original email if replying")


class LearnRequest(BaseModel):
    """Request to learn from a user-written message."""

    user_id: str = Field(..., min_length=1, description="Unique identifier for the user")
    message: MessageContent = Field(..., description="The message content to learn from")
    context: MessageContext = Field(default_factory=MessageContext, description="Additional context about the message")


# Response Models
class ToneProfile(BaseModel):
    """Tone characteristics of user's writing style."""

    formality: str = Field(default="neutral", description="Level of formality: casual, semi-formal, formal")
    warmth: int = Field(default=5, ge=1, le=10, description="Warmth level from 1-10")
    assertiveness: int = Field(default=5, ge=1, le=10, description="Assertiveness level from 1-10")
    directness: int = Field(default=5, ge=1, le=10, description="Directness level from 1-10")


class PatternProfile(BaseModel):
    """Common patterns in user's writing."""

    common_greetings: list[str] = Field(default_factory=list, description="Frequently used greetings")
    common_closings: list[str] = Field(default_factory=list, description="Frequently used sign-offs")
    punctuation_style: str = Field(default="standard", description="Punctuation preferences")


class VocabularyProfile(BaseModel):
    """Vocabulary characteristics of user's writing."""

    complexity: str = Field(default="moderate", description="Vocabulary complexity: simple, moderate, advanced")
    common_phrases: list[str] = Field(default_factory=list, description="Frequently used phrases")
    average_sentence_length: int = Field(default=15, description="Average words per sentence")
    average_paragraph_length: int = Field(default=3, description="Average sentences per paragraph")


class StyleProfile(BaseModel):
    """Complete style profile for a user."""

    tone: ToneProfile = Field(default_factory=ToneProfile)
    patterns: PatternProfile = Field(default_factory=PatternProfile)
    vocabulary: VocabularyProfile = Field(default_factory=VocabularyProfile)


class StyleResponse(BaseModel):
    """Response containing a user's learned style profile."""

    user_id: str = Field(..., description="User identifier")
    style_summary: str = Field(default="", description="Human-readable style summary")
    style_profile: StyleProfile = Field(default_factory=StyleProfile, description="Detailed style profile")
    samples_count: int = Field(default=0, description="Number of samples used to build this profile")
    last_updated: Optional[datetime] = Field(default=None, description="When the profile was last updated")


class LearnResponse(BaseModel):
    """Response after learning from a message."""

    success: bool = Field(..., description="Whether learning was successful")
    message: str = Field(default="", description="Status message")
    samples_count: int = Field(default=0, description="Total samples for this user")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="healthy")
    version: str = Field(default="1.0.0")


class ErrorResponse(BaseModel):
    """Error response."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(default=None, description="Detailed error information")
