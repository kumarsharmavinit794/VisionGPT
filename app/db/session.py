from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings


try:
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=settings.DEBUG,
    )
except ModuleNotFoundError:
    engine = None

async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False) if engine else None


async def get_db() -> AsyncSession:
    """Dependency to get database session."""
    if async_session_maker is None:
        raise RuntimeError("Database driver is not installed. Install asyncpg or use Python 3.11/3.12.")
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


get_db_session = get_db
