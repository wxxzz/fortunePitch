"""FortunePitch 数据库连接与会话管理(异步优先)。"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""


def create_engine() -> AsyncEngine:
    """创建异步数据库引擎。"""
    return create_async_engine(
        get_settings().DATABASE_URL,
        echo=get_settings().DEBUG,
        pool_pre_ping=True,
    )


engine: AsyncEngine = create_engine()

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖:提供请求级异步数据库会话,并在结束时自动关闭。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_models(metadata_obj: type[Base]) -> None:
    """根据 ORM 元数据初始化数据库表(开发环境便捷入口)。

    Args:
        metadata_obj: `Base` 的元数据对象,通常传入 `Base.metadata` 所在类。
    """
    async with engine.begin() as conn:
        await conn.run_sync(metadata_obj.metadata.create_all)
