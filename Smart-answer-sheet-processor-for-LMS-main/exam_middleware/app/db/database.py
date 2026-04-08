"""
SQLAlchemy Database Configuration and Session Management
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from typing import AsyncGenerator
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

database_url = settings.database_url_computed
is_sqlite = database_url.startswith("sqlite")

engine_kwargs = {
    "echo": settings.debug,
    "future": True,
}

if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["poolclass"] = NullPool

# Create async engine
engine = create_async_engine(
    database_url,
    **engine_kwargs,
)

# Async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides database session
    
    Yields:
        AsyncSession: Database session
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database - create all tables
    """
    async with engine.begin() as conn:
        # Import all models to ensure they're registered
        from app.db import models  # noqa
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully")


async def close_db() -> None:
    """
    Close database connections
    """
    await engine.dispose()
    logger.info("Database connections closed")
