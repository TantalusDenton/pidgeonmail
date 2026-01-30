"""Database operations for style learning memory storage."""

import hashlib
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, AsyncGenerator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.memory.models import Base, StyleHistory, StyleSample, UserStyleProfile


class StyleMemoryStore:
    """Handles all database operations for style learning."""

    def __init__(self, database_url: Optional[str] = None):
        """Initialize the store with database connection."""
        settings = get_settings()
        url = database_url or settings.database_url

        # Convert postgresql:// to postgresql+asyncpg:// for async
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        self.engine = create_async_engine(url, echo=settings.debug)
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_db(self) -> None:
        """Initialize database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        """Close database connection."""
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session."""
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @staticmethod
    def hash_message(message: str) -> str:
        """Create a hash of a message for deduplication."""
        return hashlib.sha256(message.encode()).hexdigest()

    async def get_user_profile(self, user_id: str) -> Optional[UserStyleProfile]:
        """Get a user's style profile."""
        async with self.session() as session:
            result = await session.execute(
                select(UserStyleProfile).where(UserStyleProfile.user_id == user_id)
            )
            return result.scalar_one_or_none()

    async def get_user_style_data(self, user_id: str) -> Optional[dict[str, Any]]:
        """Get a user's style data as a dictionary."""
        profile = await self.get_user_profile(user_id)
        if profile:
            return {
                "style_data": profile.style_data,
                "style_summary": profile.style_summary,
                "samples_count": profile.samples_count,
                "updated_at": profile.updated_at,
            }
        return None

    async def save_user_profile(
        self,
        user_id: str,
        style_data: dict[str, Any],
        style_summary: str,
        samples_count: int,
    ) -> UserStyleProfile:
        """Create or update a user's style profile."""
        async with self.session() as session:
            result = await session.execute(
                select(UserStyleProfile).where(UserStyleProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()

            if profile:
                profile.style_data = style_data
                profile.style_summary = style_summary
                profile.samples_count = samples_count
            else:
                profile = UserStyleProfile(
                    user_id=user_id,
                    style_data=style_data,
                    style_summary=style_summary,
                    samples_count=samples_count,
                )
                session.add(profile)

            await session.flush()
            return profile

    async def save_sample(
        self,
        user_id: str,
        message_text: str,
        analysis_data: Optional[dict[str, Any]] = None,
    ) -> Optional[StyleSample]:
        """Save a message sample. Returns None if duplicate."""
        message_hash = self.hash_message(message_text)

        async with self.session() as session:
            # Check for duplicate
            result = await session.execute(
                select(StyleSample).where(
                    StyleSample.user_id == user_id,
                    StyleSample.message_hash == message_hash,
                )
            )
            if result.scalar_one_or_none():
                return None  # Duplicate

            sample = StyleSample(
                user_id=user_id,
                message_hash=message_hash,
                message_text=message_text,
                analysis_data=analysis_data,
            )
            session.add(sample)
            await session.flush()
            return sample

    async def get_user_samples(
        self, user_id: str, limit: int = 100
    ) -> list[StyleSample]:
        """Get a user's message samples."""
        async with self.session() as session:
            result = await session.execute(
                select(StyleSample)
                .where(StyleSample.user_id == user_id)
                .order_by(StyleSample.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_sample_count(self, user_id: str) -> int:
        """Get the count of samples for a user."""
        async with self.session() as session:
            result = await session.execute(
                select(StyleSample).where(StyleSample.user_id == user_id)
            )
            return len(result.scalars().all())

    async def save_history_snapshot(
        self, user_id: str, style_snapshot: dict[str, Any]
    ) -> StyleHistory:
        """Save a daily snapshot of the style profile."""
        today = date.today()

        async with self.session() as session:
            result = await session.execute(
                select(StyleHistory).where(
                    StyleHistory.user_id == user_id,
                    StyleHistory.snapshot_date == today,
                )
            )
            history = result.scalar_one_or_none()

            if history:
                history.style_snapshot = style_snapshot
            else:
                history = StyleHistory(
                    user_id=user_id,
                    style_snapshot=style_snapshot,
                    snapshot_date=today,
                )
                session.add(history)

            await session.flush()
            return history

    async def delete_old_samples(self, user_id: str, keep_count: int = 100) -> int:
        """Delete old samples keeping only the most recent ones."""
        async with self.session() as session:
            # Get all samples ordered by date
            result = await session.execute(
                select(StyleSample)
                .where(StyleSample.user_id == user_id)
                .order_by(StyleSample.created_at.desc())
            )
            samples = list(result.scalars().all())

            if len(samples) <= keep_count:
                return 0

            # Delete samples beyond the keep count
            to_delete = samples[keep_count:]
            for sample in to_delete:
                await session.delete(sample)

            return len(to_delete)


# Global store instance
_store: Optional[StyleMemoryStore] = None


def get_store() -> StyleMemoryStore:
    """Get the global store instance."""
    global _store
    if _store is None:
        _store = StyleMemoryStore()
    return _store


async def init_store() -> StyleMemoryStore:
    """Initialize and return the global store instance."""
    store = get_store()
    await store.init_db()
    return store
