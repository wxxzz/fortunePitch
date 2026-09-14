"""球队基本面同步:按联赛名称拉取积分榜三榜并写入 fp_base_team_fundamentals。

流程:定位联赛(自动 upsert 联赛档案)-> 同步球队清单(获得
uniformTeamId -> Team 映射,球队档案名与积分榜简称不一致,不能按名匹配)
-> 从新到旧取第一个有积分榜数据的赛季 -> 总/主/客三榜按
uniformTeamId 关联成单队记录 -> 按 team_id 幂等 upsert。

积分榜尚未覆盖的球队(如赛季初尚未开赛的升班马)在结果中如实上报。
"""

import typing

from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.parsers import fundamental as fundamental_parser
from app.collector.parsers import league as league_parser
from app.collector.sources import sporttery
from app.collector.sync import league_sync, team_sync
from app.core.exceptions import ExternalSourceError
from app.models import League, TeamFundamentals


class FundamentalSyncResult(typing.NamedTuple):
    """一次球队基本面同步的结果。"""

    league: League
    # 基本面所属赛季(归一化后,如 "2026-2027")
    season: str
    # 积分榜覆盖的球队数(写入或刷新基本面)
    team_count: int
    created_count: int
    updated_count: int
    # 积分榜未覆盖的球队名(如赛季初尚未开赛)
    skipped_team_names: list[str]
    uniform_league_id: int


async def sync_league_fundamentals(
    session: AsyncSession, league_name: str
) -> FundamentalSyncResult:
    """按联赛名称同步球队基本面(自动先同步联赛与球队清单)。

    Args:
        session: 异步数据库会话。
        league_name: 联赛名称,如“西甲”。

    Returns:
        同步结果,含赛季标识、计数与积分榜未覆盖的球队名单。

    Raises:
        ExternalSourceError: 各赛季均无积分榜数据(联赛可能尚未开赛)。
    """
    item, detail = await league_sync.resolve_league(league_name)
    league_result = await league_sync.upsert_league(session, item, detail)
    # 球队同步提供 uniformTeamId -> Team 映射;球队档案名为全称
    # (如“巴塞罗那”)而积分榜行为简称(如“巴萨”),必须按 ID 关联
    team_result = await team_sync.sync_teams_for_league(session, item, league_result)

    season_name, tables = await _resolve_fundamental_tables(item)
    total_rows = _index_by_team_id(tables["total"])
    home_rows = _index_by_team_id(tables["home"])
    away_rows = _index_by_team_id(tables["away"])

    created_count = 0
    updated_count = 0
    skipped_team_names: list[str] = []
    for uniform_team_id, team in team_result.uniform_team_map.items():
        total_row = total_rows.get(uniform_team_id)
        if total_row is None:
            # 积分榜未覆盖:赛季初未开赛或资格赛球队
            skipped_team_names.append(team.team_name)
            continue
        fields = fundamental_parser.build_fundamental_fields(
            season_name,
            total_row,
            home_rows.get(uniform_team_id),
            away_rows.get(uniform_team_id),
        )
        record = await session.get(TeamFundamentals, team.team_id)
        if record is None:
            session.add(TeamFundamentals(team_id=team.team_id, **fields))
            created_count += 1
        else:
            for key, value in fields.items():
                setattr(record, key, value)
            updated_count += 1

    await session.flush()
    return FundamentalSyncResult(
        league=league_result.league,
        season=league_parser.normalize_season(season_name),
        team_count=created_count + updated_count,
        created_count=created_count,
        updated_count=updated_count,
        skipped_team_names=skipped_team_names,
        uniform_league_id=league_result.uniform_league_id,
    )


async def _resolve_fundamental_tables(
    item: dict[str, typing.Any],
) -> tuple[str, dict[str, list[dict[str, typing.Any]]]]:
    """从新到旧定位第一个有积分榜数据的赛季,拉取总/主/客三榜。

    Returns:
        (赛季名, 三榜行字典 {"total": [...], "home": [...], "away": [...]})。

    Raises:
        ExternalSourceError: 各赛季均无积分榜数据。
    """
    for season in item.get("seasonList") or []:
        tables = await sporttery.fetch_league_fundamentals(int(season["seasonId"]))
        if tables is not None:
            return str(season.get("seasonName", "")), tables
    raise ExternalSourceError(
        "积分榜为空",
        detail="各赛季均无积分榜数据,该联赛可能尚未开赛或已下线",
    )


def _index_by_team_id(
    rows: list[dict[str, typing.Any]],
) -> dict[int, dict[str, typing.Any]]:
    """积分榜行按 uniformTeamId 建索引(无 ID 的行丢弃)。"""
    return {
        int(row["uniformTeamId"]): row
        for row in rows
        if row.get("uniformTeamId") is not None
    }
