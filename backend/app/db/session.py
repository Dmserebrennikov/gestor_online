from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


## Not used for now, but kept for future reference in case we need to 
## develop endpoints that require a database session (e.g. admin endpoints).
# @asynccontextmanager
# async def get_session() -> AsyncIterator[AsyncSession]:
#     async with session_factory() as session:
#         yield session


async def close_db() -> None:
    """Return pooled connections to Postgres. Call once when the API process stops."""
    await engine.dispose()
