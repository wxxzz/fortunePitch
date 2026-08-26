"""联赛同步:按名称从竞彩网拉取联赛信息并写入 fp_base_leagues。

同步策略为手动触发(由前端传入联赛名称),
按 ``league_name`` 幂等 upsert:已存在则更新国家/级别/赛季,否则新建。

本模块同时向球队/球员同步提供联赛定位复用入口
(``resolve_league`` / ``upsert_league``),避免重复调用外部接口。
"""

import typing

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.parsers import league as league_parser
from app.collector.sources import sporttery
from app.models import League


class LeagueSyncResult(typing.NamedTuple):
    """一次联赛同步的结果。"""

    league: League
    # created=新建档案,updated=更新已有档案
    action: typing.Literal["created", "updated"]
    # 竞彩网统一联赛 ID,便于后续扩展球队/赛程同步
    uniform_league_id: int
    # 联赛列表条目(含 seasonList,供球队/球员同步复用)
    item: dict[str, typing.Any]


async def resolve_league(
    league_name: str,
) -> tuple[dict[str, typing.Any], dict[str, typing.Any]]:
    """定位联赛:拉取列表并按名称匹配,再拉取详情。

    Raises:
        DataValidationError: 名称无法唯一定位联赛。
        ExternalSourceError: 竞彩网接口访问失败。
    """
    items = await sporttery.fetch_league_list()
    item = league_parser.find_league_item(items, league_name)
    detail = await sporttery.fetch_league_detail(int(item["uniformLeagueId"]))
    return item, detail


async def upsert_league(
    session: AsyncSession,
    item: dict[str, typing.Any],
    detail: dict[str, typing.Any],
) -> LeagueSyncResult:
    """将联赛信息幂等写入 fp_base_leagues。

    Args:
        session: 异步数据库会话(事务提交由会话依赖负责)。
        item: 联赛列表条目(含 group/tier/seasonList)。
        detail: 联赛详情。

    Returns:
        同步结果,包含入库后的 League 实体与动作类型。
    """
    fields = league_parser.build_league_fields(item, detail)
    uniform_league_id = int(item["uniformLeagueId"])

    existing = await session.scalar(
        select(League).where(League.league_name == fields["league_name"])
    )
    if existing is None:
        league = League(**fields)
        session.add(league)
        await session.flush()
        action = "created"
    else:
        existing.country = fields["country"]
        existing.tier = fields["tier"]
        existing.season = fields["season"]
        league = existing
        action = "updated"
    await session.refresh(league)
    return LeagueSyncResult(
        league=league, action=action, uniform_league_id=uniform_league_id, item=item
    )


async def sync_league_by_name(
    session: AsyncSession, league_name: str
) -> LeagueSyncResult:
    """按联赛名称执行同步(列表定位 -> 详情补充 -> upsert 入库)。

    Args:
        session: 异步数据库会话(由路由层注入,事务提交由会话依赖负责)。
        league_name: 联赛名称,支持简称(如“西甲”)或竞彩网简称的子串。

    Returns:
        同步结果,包含入库后的 League 实体与动作类型。
    """
    item, detail = await resolve_league(league_name)
    return await upsert_league(session, item, detail)
