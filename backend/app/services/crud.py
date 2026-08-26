"""通用异步 CRUD 服务。

为 4 个业务模块(基础档案/比赛与赛果/高阶数据分析/策略与赔率)
提供统一的实体增删查实现,路由层通过传入 ORM 模型类复用本模块,
避免 10 张表重复编写相同的数据库访问代码。
"""

from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.core.exceptions import ResourceNotFoundError

# 任意 ORM 模型类型(均为 Base 子类)
ModelT = TypeVar("ModelT", bound=Base)

# 列表接口分页上限,防止无界查询
MAX_PAGE_SIZE: int = 100
DEFAULT_PAGE_SIZE: int = 20


async def create_entity(session: AsyncSession, model: type[ModelT], data: dict[str, Any]) -> ModelT:
    """创建实体并返回持久化后的实例。

    Args:
        session: 异步数据库会话。
        model: ORM 模型类。
        data: 字段名到字段值的映射(已通过 Pydantic 校验)。

    Returns:
        已写入数据库(含主键)的实体实例。
    """
    instance = model(**data)
    session.add(instance)
    await session.flush()
    await session.refresh(instance)
    return instance


async def get_entity(
    session: AsyncSession, model: type[ModelT], pk_value: Any
) -> ModelT:
    """按主键查询单个实体。

    Raises:
        ResourceNotFoundError: 实体不存在。
    """
    instance = await session.get(model, pk_value)
    if instance is None:
        raise ResourceNotFoundError(model.__tablename__, str(pk_value))
    return instance


async def list_entities(
    session: AsyncSession,
    model: type[ModelT],
    offset: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
    filters: dict[str, Any] | None = None,
) -> Sequence[ModelT]:
    """分页查询实体列表(限制单页上限,防止无界查询)。

    Args:
        session: 异步数据库会话。
        model: ORM 模型类。
        offset: 偏移量。
        limit: 单页条数(自动收敛到 [1, MAX_PAGE_SIZE])。
        filters: 可选的等值过滤条件(字段名 -> 值),如 ``{"league_id": 1}``。

    Returns:
        实体列表。
    """
    safe_limit = min(max(limit, 1), MAX_PAGE_SIZE)
    safe_offset = max(offset, 0)
    statement = select(model)
    if filters:
        statement = statement.filter_by(**filters)
    result = await session.execute(
        statement.offset(safe_offset).limit(safe_limit)
    )
    return result.scalars().all()


async def delete_entity(
    session: AsyncSession, model: type[ModelT], pk_value: Any
) -> None:
    """按主键删除实体。

    Raises:
        ResourceNotFoundError: 实体不存在。
    """
    instance = await get_entity(session, model, pk_value)
    await session.delete(instance)
    await session.flush()


async def delete_all_entities(session: AsyncSession, model: type[ModelT]) -> int:
    """清空指定表的全部数据(测试辅助,生产慎用)。

    Returns:
        删除的行数。
    """
    result = await session.execute(delete(model))
    await session.flush()
    return int(result.rowcount or 0)
