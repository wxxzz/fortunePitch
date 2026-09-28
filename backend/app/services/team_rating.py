"""Elo 评分回放管线:按时间序回放已完赛看板比赛,全量重建球队评分。

数据源为 fp_base_team_matches(两队看板视角各存一行,复合主键
(team_id, uniform_match_id))。同一场比赛按 uniform_match_id 分组,
由看板行的 is_home 确定主客;对手的本地球队 ID 经
fp_base_team_profiles.uniform_team_id 映射解析。纯计算复用
services/elo.py 的 update_ratings(K=20,HFA=100)。

评分不保留历史:任何时点的历史都可由原始赛果全量回放重建,
故写回采用 delete + 批量 insert 的幂等全量重建。
"""

import collections
import datetime
import logging
import typing

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TeamMatch, TeamProfile, TeamRating
from app.services import elo

logger = logging.getLogger(__name__)

# 场次元组:(uniform_match_id, 主队本地ID, 客队本地ID, 主队进球, 客队进球, 比赛时间)
Fixture = tuple[int, int, int, int, int, datetime.datetime]


class RatingRecomputeResult(typing.NamedTuple):
    """重算结果摘要。"""

    matches_replayed: int  # 实际参与回放的比赛数
    teams_rated: int  # 写入评分表的球队数
    matches_skipped: int  # 因对手无法解析到本地球队而跳过的比赛数


async def recompute_team_ratings(session: AsyncSession) -> RatingRecomputeResult:
    """按时间序回放全部已完赛看板比赛,全量重建球队 Elo 评分。

    Args:
        session: 异步数据库会话(提交由调用方/请求级依赖完成)。

    Returns:
        重算结果摘要(回放场次/评分球队数/跳过场次)。
    """
    rows = list(
        await session.scalars(
            select(TeamMatch).where(
                TeamMatch.full_home_score.is_not(None),
                TeamMatch.full_away_score.is_not(None),
            )
        )
    )
    profiles = list(await session.scalars(select(TeamProfile)))
    uniform_to_local = {
        profile.uniform_team_id: profile.team_id for profile in profiles
    }

    # 同一场比赛按 uniform_match_id 分组,解析出 (主队本地ID, 客队本地ID, 比分, 时间)
    grouped: dict[int, list[TeamMatch]] = collections.defaultdict(list)
    for row in rows:
        grouped[row.uniform_match_id].append(row)

    fixtures: list[Fixture] = []
    skipped = 0
    for uniform_match_id, group in grouped.items():
        fixture = _resolve_fixture(uniform_match_id, group, uniform_to_local)
        if fixture is None:
            skipped += 1
        else:
            fixtures.append(fixture)

    fixtures.sort(key=lambda item: (item[5], item[0]))

    # 按时间序回放,更新内存中的评分
    ratings: dict[int, float] = collections.defaultdict(lambda: elo.DEFAULT_ELO)
    played: dict[int, int] = collections.defaultdict(int)
    last_time: dict[int, datetime.datetime] = {}
    for _uniform_match_id, home_id, away_id, home_goals, away_goals, match_time in fixtures:
        update = elo.update_ratings(
            ratings[home_id], ratings[away_id], home_goals, away_goals
        )
        ratings[home_id] = update.home_rating_new
        ratings[away_id] = update.away_rating_new
        played[home_id] += 1
        played[away_id] += 1
        last_time[home_id] = match_time
        last_time[away_id] = match_time

    # 幂等全量重建写回
    await session.execute(delete(TeamRating))
    for team_id, rating in ratings.items():
        session.add(
            TeamRating(
                team_id=team_id,
                rating=round(rating, 2),
                matches_played=played[team_id],
                last_match_time=last_time[team_id],
            )
        )
    return RatingRecomputeResult(
        matches_replayed=len(fixtures),
        teams_rated=len(ratings),
        matches_skipped=skipped,
    )


def _resolve_fixture(
    uniform_match_id: int,
    group: list[TeamMatch],
    uniform_to_local: dict[int, int],
) -> Fixture | None:
    """把同一场比赛的看板行组解析为回放用的场次元组。

    Returns:
        (uniform_match_id, 主队本地ID, 客队本地ID, 主队进球, 客队进球, 比赛时间);
        主客任何一侧无法解析到本地球队、主客同队、或组内多行比分不一致
        (脏数据,无法判定真值)时返回 None。
    """
    # 同一场比赛两队看板各存一行,比分必须一致;不一致说明数据脏,跳过该场
    scores = {
        (row.full_home_score, row.full_away_score) for row in group
    }
    if len(scores) > 1:
        logger.warning(
            "uniform_match_id=%s 看板行比分不一致 %s,跳过该场",
            uniform_match_id,
            scores,
        )
        return None
    home_goals, away_goals = next(iter(scores))

    home_local: int | None = None
    away_local: int | None = None
    for row in group:
        if row.is_home:
            home_local = row.team_id
            opponent_uniform = row.uniform_away_team_id
        else:
            away_local = row.team_id
            opponent_uniform = row.uniform_home_team_id
        if opponent_uniform is not None:
            opponent_local = uniform_to_local.get(opponent_uniform)
            if row.is_home and away_local is None:
                away_local = opponent_local
            elif not row.is_home and home_local is None:
                home_local = opponent_local

    if home_local is None or away_local is None or home_local == away_local:
        return None
    return (
        uniform_match_id,
        home_local,
        away_local,
        home_goals,
        away_goals,
        group[0].match_time,
    )
