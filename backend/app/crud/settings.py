from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import AppSettings


async def get_app_settings(db: AsyncSession) -> AppSettings:
    """
    Return the singleton AppSettings row (id=1), creating it with defaults if it
    does not yet exist.
    """
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings_row = result.scalar_one_or_none()
    if settings_row is None:
        settings_row = AppSettings(id=1, auto_assign_enabled=True)
        db.add(settings_row)
        await db.flush()
        await db.refresh(settings_row)
    return settings_row
