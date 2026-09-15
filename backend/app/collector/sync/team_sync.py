"""球队同步:按联赛名称拉取球队清单并写入 fp_base_teams。

流程:定位联赛(自动 upsert 联赛档案)-> 取球队清单(优先积分榜,
从新到旧取第一个有积分榜的赛季,并集最新赛季赛程参赛队以补齐
资格赛球队;纯淘汰赛制杯赛无积分榜,退化为从各赛季赛程参赛队
提取)-> 逐队拉取详情补全名称 -> 按 (league_id, team_name) 幂等 upsert。

竞彩网不提供主场/主教练/阵型数据,相应字段保持为空。
球队详情同时写入竞彩网档案映射(fp_base_team_profiles),
供球队看板同步按 uniform_team_id 定位球队。
"""

import typing

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.parsers import league as league_parser
from app.collector.parsers import team as team_parser
from app.collector.sources import sporttery
from app.collector.sync import league_sync
from app.collector.sync import team_dashboard_sync
from app.core.exceptions import DataValidationError, ExternalSourceError
from app.models import League, Team


class TeamSyncResult(typing.NamedTuple):
    """一次球队同步的结果。"""

    league: League
    teams: list[Team]
    created_count: int
    updated_count: int
    uniform_league_id: int
    # 竞彩网统一球队 ID -> 入库 Team 实体(供球员同步复用)
    uniform_team_map: dict[int, Team]


async def _resolve_team_rows(
    item: dict[str, typing.Any],
) -> tuple[str, list[dict[str, typing.Any]]]:
    """解析球队清单:积分榜为基准,赛程参赛队兜底与补齐。

    竞彩网 seasonList 首项是最新赛季,但赛季尚未开赛时积分榜为空
    (如欧冠新赛季 8 月底仍未开打),此时回溯上一赛季积分榜;
    资格赛参赛队不在积分榜中,以最新赛季赛程补齐。
    纯淘汰赛制杯赛(如英联赛杯)各赛季均无积分榜,从新到旧扫描
    赛程参赛队,合并历史赛季以覆盖全部常参赛球队。

    Returns:
        (seasonName, 球队行列表,均含 abbCnName + uniformTeamId;
        档案赛季跟随积分榜赛季,无积分榜时为最新赛季)。

    Raises:
        ExternalSourceError: 各赛季均无积分榜与赛程数据。
        DataValidationError: 赛季列表缺失。
    """
    season_list = item.get("seasonList")
    if not isinstance(season_list, list) or not season_list:
        raise DataValidationError("联赛赛季列表为空")

    for season in season_list:
        standings_rows = await sporttery.fetch_league_standings(
            int(season["seasonId"])
        )
        if standings_rows:
            match_rows = await _match_team_rows(item, season_list[:1])
            return (
                str(season.get("seasonName", "")),
                _merge_rows(standings_rows, match_rows),
            )

    rows = await _match_team_rows(item, season_list)
    if not rows:
        raise ExternalSourceError(
            "联赛积分榜为空",
            detail="各赛季均无积分榜与赛程数据,该联赛可能尚未开赛或已下线",
        )
    return str(season_list[0].get("seasonName", "")), rows


async def _match_team_rows(
    item: dict[str, typing.Any],
    seasons: list[dict[str, typing.Any]],
) -> list[dict[str, typing.Any]]:
    """从指定赛季的赛程参赛队提取球队行,按 uniformTeamId 去重。

    Returns:
        球队行列表(格式与积分榜行兼容:abbCnName + uniformTeamId),
        无赛程数据时为空列表。
    """
    rows: list[dict[str, typing.Any]] = []
    seen: set[int] = set()
    for season in seasons:
        matches = await sporttery.fetch_season_matches(
            int(season["seasonId"]), int(item["uniformLeagueId"])
        )
        for match in matches:
            for side in ("Home", "Away"):
                team_id = match.get(f"uniform{side}TeamId")
                name = str(match.get(f"{side.lower()}AbbCnName") or "").strip()
                if not team_id or not name or team_id in seen:
                    continue
                seen.add(team_id)
                rows.append({"abbCnName": name, "uniformTeamId": team_id})
    return rows


def _merge_rows(
    base: list[dict[str, typing.Any]],
    extra: list[dict[str, typing.Any]],
) -> list[dict[str, typing.Any]]:
    """按 uniformTeamId 去重合并两组球队行,base 优先保留。"""
    seen = {
        row["uniformTeamId"]
        for row in base
        if row.get("uniformTeamId") is not None
    }
    merged = list(base)
    for row in extra:
        team_id = row.get("uniformTeamId")
        if team_id is not None:
            if team_id in seen:
                continue
            seen.add(team_id)
        merged.append(row)
    return merged


async def sync_league_teams(
    session: AsyncSession, league_name: str
) -> TeamSyncResult:
    """按联赛名称同步球队清单(先确保联赛档案存在)。

    Args:
        session: 异步数据库会话。
        league_name: 联赛名称,如“西甲”。

    Returns:
        同步结果,包含入库后的球队列表与计数。
    """
    item, detail = await league_sync.resolve_league(league_name)
    league_result = await league_sync.upsert_league(session, item, detail)
    return await sync_teams_for_league(session, item, league_result)


async def sync_teams_for_league(
    session: AsyncSession,
    item: dict[str, typing.Any],
    league_result: league_sync.LeagueSyncResult,
) -> TeamSyncResult:
    """将联赛球队清单写入 fp_base_teams(供球员同步复用)。

    Args:
        session: 异步数据库会话。
        item: 联赛列表条目(含 seasonList)。
        league_result: 已完成的联赛同步结果(联赛已入库)。

    Returns:
        同步结果,含 uniform_team_map(竞彩网球队 ID -> Team)。
        球队来源:有积分榜取积分榜(从新到旧第一个非空赛季)并集
        最新赛季赛程参赛队(补齐资格赛球队),纯淘汰赛制杯赛
        退化为各赛季赛程参赛队。
    """
    league = league_result.league
    season_name, rows = await _resolve_team_rows(item)
    # 球队清单可能来自上一赛季(新赛季未开赛),联赛档案赛季随之校正
    league.season = league_parser.normalize_season(season_name)
    team_ids = team_parser.uniform_team_ids(rows)
    infos = await sporttery.fetch_team_infos(team_ids)

    teams: list[Team] = []
    uniform_team_map: dict[int, Team] = {}
    created_count = 0
    updated_count = 0
    for row, info in zip(rows, infos):
        fields = team_parser.build_team_fields(row, info)
        team = await session.scalar(
            select(Team).where(
                Team.league_id == league.league_id,
                Team.team_name == fields["team_name"],
            )
        )
        if team is None:
            team = Team(league_id=league.league_id, **fields)
            session.add(team)
            await session.flush()
            created_count += 1
        else:
            updated_count += 1
        # 球队详情写入竞彩网档案映射,供球队看板同步定位
        if info:
            await team_dashboard_sync.upsert_team_profile(session, team, info)
        teams.append(team)
        uniform_team_map[int(row["uniformTeamId"])] = team

    return TeamSyncResult(
        league=league,
        teams=teams,
        created_count=created_count,
        updated_count=updated_count,
        uniform_league_id=league_result.uniform_league_id,
        uniform_team_map=uniform_team_map,
    )
