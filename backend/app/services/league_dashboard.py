"""联赛看板服务:聚合联赛档案、积分榜与近期赛程赛果。

数据来源:
- 联赛/球队档案(fp_base_leagues / fp_base_teams);
- 球队基本面积分榜(fp_base_team_fundamentals,数据采集页"同步基本面"写入);
- 竞彩比赛档案(fp_match_games,赛程与完赛比分)。

合规说明:仅提供数据分析参考,不构成投注建议。
"""

import datetime
import typing

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.exceptions import ResourceNotFoundError
from app.models import (
    League,
    MatchGame,
    MatchStatus,
    Team,
    TeamFundamentals,
)


class StandingRow(typing.NamedTuple):
    """积分榜一行:球队 + 该队基本面(未同步过时为 None)。"""

    team_id: int
    team_name: str
    fundamentals: TeamFundamentals | None


class MatchRow(typing.NamedTuple):
    """联赛赛程/赛果一行(含主客队名与完赛比分)。"""

    match_id: str
    match_num_str: str
    match_time: datetime.datetime
    match_status: str
    home_team_name: str
    away_team_name: str
    home_score: int | None
    away_score: int | None


class LeagueDashboardData(typing.NamedTuple):
    """联赛看板聚合结果(供路由层组装响应模型)。"""

    league: League
    team_count: int
    standings: list[StandingRow]
    recent_results: list[MatchRow]
    upcoming_fixtures: list[MatchRow]


async def get_league_dashboard(
    session: AsyncSession,
    league_id: int,
    *,
    result_limit: int = 10,
    fixture_limit: int = 10,
) -> LeagueDashboardData:
    """查询联赛看板:基本信息、球队数、积分榜(总榜)与近期赛程赛果。

    积分榜左联球队基本面,按排名升序;未同步基本面的球队排在末尾
    (保持稳定顺序)。近期赛果取已完赛按开赛时间倒序,近期赛程取
    未完赛(未开赛/进行中)按开赛时间正序。

    Args:
        session: 异步数据库会话。
        league_id: 联赛编号。
        result_limit: 近期赛果条数。
        fixture_limit: 近期赛程条数。

    Returns:
        联赛看板聚合数据。

    Raises:
        ResourceNotFoundError: 联赛不存在。
    """
    league = await session.get(League, league_id)
    if league is None:
        raise ResourceNotFoundError("联赛", str(league_id))

    team_count = (
        await session.scalar(
            select(func.count())
            .select_from(Team)
            .where(Team.league_id == league_id)
        )
        or 0
    )

    # 积分榜:排名为空(未同步基本面)的球队排末尾;
    # "ranking IS NULL" 在 MySQL/SQLite 中按 0/1 排序实现 NULLS LAST
    standings_rows = (
        (
            await session.execute(
                select(Team, TeamFundamentals)
                .outerjoin(
                    TeamFundamentals,
                    TeamFundamentals.team_id == Team.team_id,
                )
                .where(Team.league_id == league_id)
                .order_by(
                    TeamFundamentals.ranking.is_(None),
                    TeamFundamentals.ranking,
                    Team.team_id,
                )
            )
        )
        .all()
    )
    standings = [
        StandingRow(
            team_id=team.team_id,
            team_name=team.team_name,
            fundamentals=fundamentals,
        )
        for team, fundamentals in standings_rows
    ]

    home_team = aliased(Team)
    away_team = aliased(Team)

    async def _query_games(*, finished: bool, limit: int) -> list[MatchRow]:
        stmt = (
            select(MatchGame, home_team.team_name, away_team.team_name)
            .join(home_team, MatchGame.home_team_id == home_team.team_id)
            .join(away_team, MatchGame.away_team_id == away_team.team_id)
            .where(MatchGame.league_id == league_id)
        )
        if finished:
            stmt = stmt.where(MatchGame.match_status == MatchStatus.FINISHED)
            stmt = stmt.order_by(
                MatchGame.match_time.desc(), MatchGame.match_id.desc()
            )
        else:
            stmt = stmt.where(MatchGame.match_status != MatchStatus.FINISHED)
            stmt = stmt.order_by(
                MatchGame.match_time.asc(), MatchGame.match_id.asc()
            )
        rows = (await session.execute(stmt.limit(limit))).all()
        return [
            MatchRow(
                match_id=game.match_id,
                match_num_str=game.match_num_str,
                match_time=game.match_time,
                match_status=game.match_status.value,
                home_team_name=home_name,
                away_team_name=away_name,
                home_score=game.home_score,
                away_score=game.away_score,
            )
            for game, home_name, away_name in rows
        ]

    recent_results = await _query_games(finished=True, limit=result_limit)
    upcoming_fixtures = await _query_games(finished=False, limit=fixture_limit)
    return LeagueDashboardData(
        league=league,
        team_count=team_count,
        standings=standings,
        recent_results=recent_results,
        upcoming_fixtures=upcoming_fixtures,
    )
