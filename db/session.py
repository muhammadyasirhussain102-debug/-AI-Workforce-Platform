from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from core.config import settings

# 1. Async engine create kar rahe hain
engine = create_async_engine(
    settings.DATABASE_URL, 
    echo=False,          # Agar SQL queries terminal par print karni hon to True kar sakte hain
    future=True
)

# 2. Session generator jo har API request ko database session dega
AsyncSessionLocal = async_sessionmaker(
    bind=engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

# 3. Dependency function jo FastAPI routes mein inject hoga
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()