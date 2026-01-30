"""SQLAlchemy database models for style learning."""

from datetime import datetime, date
from typing import Any

from sqlalchemy import Column, Date, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class UserStyleProfile(Base):
    """Stores the learned style profile for each user."""

    __tablename__ = "user_style_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), unique=True, nullable=False, index=True)
    style_data = Column(JSONB, nullable=False, default=dict)
    style_summary = Column(Text, nullable=True)
    samples_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "style_data": self.style_data,
            "style_summary": self.style_summary,
            "samples_count": self.samples_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class StyleSample(Base):
    """Stores individual message samples used for learning."""

    __tablename__ = "style_samples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, index=True)
    message_hash = Column(String(64), nullable=False)
    message_text = Column(Text, nullable=False)
    analysis_data = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_user_message_hash", "user_id", "message_hash", unique=True),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "message_hash": self.message_hash,
            "message_text": self.message_text,
            "analysis_data": self.analysis_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class StyleHistory(Base):
    """Stores historical snapshots of style profiles."""

    __tablename__ = "style_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, index=True)
    style_snapshot = Column(JSONB, nullable=False)
    snapshot_date = Column(Date, nullable=False)

    __table_args__ = (
        Index("idx_user_snapshot_date", "user_id", "snapshot_date", unique=True),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "style_snapshot": self.style_snapshot,
            "snapshot_date": self.snapshot_date.isoformat() if self.snapshot_date else None,
        }
