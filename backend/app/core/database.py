"""FortunePitch 数据库连接与会话管理(异步优先)。"""

from collections.abc import AsyncGenerator

from sqlalchemy import BigInteger, Integer
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

# MySQL 使用 BIGINT;SQLite(单测回退)下 BIGINT 主键不支持自增,
# 统一通过 with_variant 保证两种数据库行为一致
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


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


async def init_db() -> None:
    """根据 ORM 元数据初始化数据库表(开发/联调环境便捷入口)。

    自动导入 app.models 以确保所有模型完成注册后统一建表。
    """
    import app.models  # noqa: F401 触发全部模型注册

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
