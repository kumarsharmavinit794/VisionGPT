from app.db.base import Base
from app.db.session import engine


async def init_db():
    """Initialize database tables using SQLAlchemy create_all()."""
    if engine is None:
        return
    # Import models here so their tables are registered on Base.metadata.
    from app.models.user import User  # noqa: F401
    from app.models.file import UploadedFile  # noqa: F401
    from app.models.analysis import ImageAnalysis  # noqa: F401
    from app.models.conversation import Conversation, Message  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
