"""联赛多维度分析服务:对联赛内已完赛场次做结果分布统计。

数据来源:
- 竞彩比赛档案(fp_match_games,完赛比分);
- 赛果开奖快照(fp_match_results,半全场/让球玩法标签与胜平负 SP)。

维度:胜平负分布、进球(场均/3 球及以上/双方进球)、总进球分布、
半全场分布、让球胜平负分布、热门命中(SP 最低项的开奖命中率)。

合规说明:仅提供数据分析参考,不构成投注建议。
"""

import typing

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundError
from app.models import League, MatchGame, MatchResult, MatchStatus

# 让球胜平负开奖标签的固定展示顺序
_HHAD_ORDER = ("让球主胜", "让球平", "让球客胜")

# 胜平负开奖标签(与竞彩赛果口径一致)
_HAD_LABELS = ("主胜", "平", "客胜")


class LabelCount(typing.NamedTuple):
    """有限标签分布的一行:标签 + 出现次数。"""

    label: str
    count: int


class FavoriteStats(typing.NamedTuple):
    """热门命中统计:每场取 SP 最低项为热门,统计其开奖命中。"""

    # 参与 SP 统计的场次数(三项 SP 齐全且有胜平负开奖)
    count: int
    # 热门选项最终开奖命中的场次数
    hit_count: int
    # 命中率(0~1,无场次时为 None)
    hit_rate: float | None
    # 热门项平均 SP(无场次时为 None)
    avg_sp: float | None


class LeagueInsightsData(typing.NamedTuple):
    """联赛多维度分析聚合结果(供路由层组装响应模型)。"""

    league: League
    season: str
    # 已完赛且有比分的场次数(全部统计口径的分母)
    finished_count: int
    # 胜平负分布(计数)
    home_win: int
    draw: int
    away_win: int
    # 胜平负分布(占比 0~1,无场次时为 None)
    home_win_rate: float | None
    draw_rate: float | None
    away_win_rate: float | None
    # 进球维度
    avg_total_goals: float | None
    avg_home_goals: float | None
    avg_away_goals: float | None
    # 总进球 >= 3(竞彩大小球 3 球线)的场次数与占比
    over2_5_count: int
    over2_5_rate: float | None
    # 主客队均取得进球的场次数与占比
    btts_count: int
    btts_rate: float | None
    # 总进球分布(0/1/2/3/4/5+,固定顺序)
    total_goals: list[LabelCount]
    # 半全场分布(按出现次数降序)
    half_full: list[LabelCount]
    # 让球胜平负分布(固定顺序,仅非零项)
    handicap: list[LabelCount]
    # 热门命中统计(无 SP 数据时为 None)
    favorite: FavoriteStats | None


def _rate(part: int, total: int) -> float | None:
    """占比(0~1,保留三位);分母为零时返回 None。"""
    if total <= 0:
        return None
    return round(part / total, 3)


async def get_league_insights(
    session: AsyncSession,
    league_id: int,
) -> LeagueInsightsData:
    """统计联赛已完赛场次的多维度分布。

    Args:
        session: 异步数据库会话。
        league_id: 联赛编号。

    Returns:
        联赛多维度分析数据。

    Raises:
        ResourceNotFoundError: 联赛不存在。
    """
    league = await session.get(League, league_id)
    if league is None:
        raise ResourceNotFoundError("联赛", str(league_id))

    rows = (
        (
            await session.execute(
                select(MatchGame, MatchResult)
                .outerjoin(
                    MatchResult, MatchResult.match_id == MatchGame.match_id
                )
                .where(
                    MatchGame.league_id == league_id,
                    MatchGame.match_status == MatchStatus.FINISHED,
                    MatchGame.home_score.is_not(None),
                    MatchGame.away_score.is_not(None),
                )
                .order_by(MatchGame.match_time.asc(), MatchGame.match_id.asc())
            )
        )
        .all()
    )

    finished_count = 0
    home_win = draw = away_win = 0
    total_goals_counter: dict[str, int] = {}
    over2_5_count = btts_count = 0
    goals_sum = home_goals_sum = away_goals_sum = 0
    hafu_counter: dict[str, int] = {}
    hhad_counter: dict[str, int] = {}
    favorite_count = favorite_hits = 0
    favorite_sp_sum = 0.0

    for game, result in rows:
        home, away = game.home_score, game.away_score
        if home is None or away is None:
            continue  # 查询条件已过滤,防御性跳过
        finished_count += 1
        goals_sum += home + away
        home_goals_sum += home
        away_goals_sum += away
        if home > away:
            home_win += 1
        elif home < away:
            away_win += 1
        else:
            draw += 1
        if home + away >= 3:
            over2_5_count += 1
        if home > 0 and away > 0:
            btts_count += 1
        bucket = str(home + away) if home + away < 5 else "5+"
        total_goals_counter[bucket] = total_goals_counter.get(bucket, 0) + 1

        if result is None:
            continue
        if result.hafu:
            hafu_counter[result.hafu] = hafu_counter.get(result.hafu, 0) + 1
        if result.hhad:
            hhad_counter[result.hhad] = hhad_counter.get(result.hhad, 0) + 1
        # 热门命中:三项 SP 齐全时取最低项,与胜平负开奖比对
        if (
            result.had
            and result.sp_h is not None
            and result.sp_d is not None
            and result.sp_a is not None
        ):
            sps = {"主胜": result.sp_h, "平": result.sp_d, "客胜": result.sp_a}
            favorite_label = min(sps, key=sps.get)
            favorite_count += 1
            favorite_sp_sum += sps[favorite_label]
            if result.had == favorite_label:
                favorite_hits += 1

    favorite = (
        FavoriteStats(
            count=favorite_count,
            hit_count=favorite_hits,
            hit_rate=_rate(favorite_hits, favorite_count),
            avg_sp=(
                round(favorite_sp_sum / favorite_count, 2)
                if favorite_count > 0
                else None
            ),
        )
        if favorite_count > 0
        else None
    )

    return LeagueInsightsData(
        league=league,
        season=league.season,
        finished_count=finished_count,
        home_win=home_win,
        draw=draw,
        away_win=away_win,
        home_win_rate=_rate(home_win, finished_count),
        draw_rate=_rate(draw, finished_count),
        away_win_rate=_rate(away_win, finished_count),
        avg_total_goals=(
            round(goals_sum / finished_count, 2) if finished_count else None
        ),
        avg_home_goals=(
            round(home_goals_sum / finished_count, 2) if finished_count else None
        ),
        avg_away_goals=(
            round(away_goals_sum / finished_count, 2) if finished_count else None
        ),
        over2_5_count=over2_5_count,
        over2_5_rate=_rate(over2_5_count, finished_count),
        btts_count=btts_count,
        btts_rate=_rate(btts_count, finished_count),
        total_goals=[
            LabelCount(label=bucket, count=total_goals_counter.get(bucket, 0))
            for bucket in ("0", "1", "2", "3", "4", "5+")
        ],
        half_full=[
            LabelCount(label=label, count=count)
            for label, count in sorted(
                hafu_counter.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
        handicap=[
            LabelCount(label=label, count=hhad_counter.get(label, 0))
            for label in _HHAD_ORDER
            if hhad_counter.get(label, 0) > 0
        ],
        favorite=favorite,
    )
