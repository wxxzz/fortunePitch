"""球队看板查询服务:聚合档案、未来赛事、赛程赛果与战绩统计。

数据由球队看板同步(竞彩网球队专栏)写入,统计按已完赛看板
比赛实时计算,支持按参赛联赛与主客场筛选。
"""

import typing

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundError
from app.models import Team, TeamMatch, TeamProfile


class DashboardStatistics(typing.NamedTuple):
    """球队看板战绩统计。"""

    played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    goal_diff: int
    win_rate: float


class TeamDashboardData(typing.NamedTuple):
    """球队看板聚合数据。"""

    team: Team
    profile: TeamProfile | None
    future_matches: list[TeamMatch]
    match_results: list[TeamMatch]
    leagues: list[tuple[int | None, str | None]]
    statistics: DashboardStatistics


def _row_result(row: TeamMatch) -> str | None:
    """看板球队视角结果:优先取存储值,比分在而结果缺失时按比分推导。

    同步流程总会同时写入比分与结果,此处兜底部分写入的异常行,
    保证统计口径一致(played == 胜 + 平 + 负)。
    """
    if row.team_result in ("W", "D", "L"):
        return row.team_result
    if row.full_home_score is None or row.full_away_score is None:
        return None
    own = row.full_home_score if row.is_home else row.full_away_score
    opp = row.full_away_score if row.is_home else row.full_home_score
    if own > opp:
        return "W"
    if own < opp:
        return "L"
    return "D"


def _compute_statistics(rows: list[TeamMatch]) -> DashboardStatistics:
    """按看板球队视角统计已完赛比赛:胜负平、进失球与胜率。"""
    wins = draws = losses = goals_for = goals_against = 0
    for row in rows:
        result = _row_result(row)
        if result == "W":
            wins += 1
        elif result == "D":
            draws += 1
        elif result == "L":
            losses += 1
        own = row.full_home_score if row.is_home else row.full_away_score
        opp = row.full_away_score if row.is_home else row.full_home_score
        goals_for += own or 0
        goals_against += opp or 0
    played = wins + draws + losses
    win_rate = round(wins / played * 100, 1) if played else 0.0
    return DashboardStatistics(
        played=played,
        wins=wins,
        draws=draws,
        losses=losses,
        goals_for=goals_for,
        goals_against=goals_against,
        goal_diff=goals_for - goals_against,
        win_rate=win_rate,
    )


async def get_team_dashboard(
    session: AsyncSession,
    team_id: int,
    uniform_league_id: int | None = None,
    home_away: str | None = None,
    future_limit: int = 10,
    result_limit: int = 10,
) -> TeamDashboardData:
    """聚合球队看板数据。

    Args:
        session: 异步数据库会话。
        team_id: 本地球队 ID。
        uniform_league_id: 按参赛联赛过滤(竞彩网统一联赛 ID)。
        home_away: 主客过滤,"home"/"away"/None(全部)。
        future_limit: 未来赛事返回条数上限。
        result_limit: 赛程赛果返回条数上限。

    Returns:
        看板聚合数据(未来赛事升序 / 赛程赛果降序,
        统计覆盖筛选后的全部已完赛行,不受条数上限约束)。

    Raises:
        ResourceNotFoundError: 球队不存在。
    """
    team = await session.get(Team, team_id)
    if team is None:
        raise ResourceNotFoundError("球队", str(team_id))

    profile = await session.get(TeamProfile, team_id)

    conditions = [TeamMatch.team_id == team_id]
    if uniform_league_id is not None:
        conditions.append(TeamMatch.uniform_league_id == uniform_league_id)
    if home_away == "home":
        conditions.append(TeamMatch.is_home.is_(True))
    elif home_away == "away":
        conditions.append(TeamMatch.is_home.is_(False))
    rows = list(
        await session.scalars(select(TeamMatch).where(*conditions))
    )

    finished = [row for row in rows if row.full_home_score is not None]
    upcoming = [row for row in rows if row.full_home_score is None]
    finished.sort(key=lambda row: row.match_time, reverse=True)
    upcoming.sort(key=lambda row: row.match_time)

    league_map: dict[int | None, str | None] = {}
    for row in rows:
        league_map.setdefault(row.uniform_league_id, row.league_name)

    return TeamDashboardData(
        team=team,
        profile=profile,
        future_matches=upcoming[:future_limit],
        match_results=finished[:result_limit],
        leagues=list(league_map.items()),
        statistics=_compute_statistics(finished),
    )
