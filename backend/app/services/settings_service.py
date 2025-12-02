"""Service helpers for working with settings."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting


class SettingsService:
    """Utility helpers for CRUD operations on Setting rows."""

    @staticmethod
    async def get_all(db: AsyncSession) -> list[Setting]:
        """Return all settings sorted by key."""
        result = await db.execute(select(Setting).order_by(Setting.key))
        return list(result.scalars().all())

    @staticmethod
    async def get(db: AsyncSession, key: str) -> Optional[Setting]:
        """Fetch a single setting by key."""
        result = await db.execute(select(Setting).where(Setting.key == key))
        return result.scalar_one_or_none()

    @staticmethod
    async def set(
        db: AsyncSession,
        key: str,
        value: Optional[str],
        *,
        category: Optional[str] = None,
        description: Optional[str] = None,
        encrypted: Optional[bool] = None,
    ) -> Setting:
        """
        Create or update a Setting.

        The operation is not committed automatically; callers control the transaction.
        """
        setting = await SettingsService.get(db, key)

        if setting is None:
            setting = Setting(
                key=key,
                value=value,
                category=category or "general",
                description=description,
                encrypted=encrypted if encrypted is not None else False,
            )
            db.add(setting)
        else:
            setting.value = value
            if category is not None:
                setting.category = category
            if description is not None:
                setting.description = description
            if encrypted is not None:
                setting.encrypted = encrypted

        await db.flush()
        return setting

    @staticmethod
    async def delete(db: AsyncSession, key: str) -> None:
        """Delete a setting by key."""
        await db.execute(delete(Setting).where(Setting.key == key))
        await db.flush()
