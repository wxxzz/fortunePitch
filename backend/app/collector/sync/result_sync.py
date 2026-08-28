"""赛果同步:按比赛日拉取竞彩赛果开奖数据并写入 fp_match_results。

流程:拉取当日赛果 -> 逐条解析 -> 场次须已在 fp_match_games 中
(未入库的场次跳过并在结果中说明,需先在数据采集页同步赛事)->
按 match_id 幂等 upsert 赛果 -> 比分有效的场次同步刷新
fp_match_games 的比分与状态(FINISHED),取消/无效场次不改写比分。
"""

import datetime
import typing

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.collector.parsers import result as result_parser
from app.collector.sources import sporttery
from app.models import MatchGame, MatchResult, MatchStatus


class ResultSyncResult(typing.NamedTuple):
    """一次赛果同步的结果。"""

    date: str
    # 赛果接口返回的当日场次总数
    day_result_count: int
    created_count: int
    updated_count: int
    # 本次刷新比分与完赛状态的场次数
    game_updated_count: int
    # 场次未入库等原因被跳过的场次说明
    skipped_matches: list[str]


async def sync_results_by_date(session: AsyncSession, date: str) -> ResultSyncResult:
    """按比赛日同步竞彩赛果开奖数据,并回写比赛比分与状态。

    Args:
        session: 异步数据库会话。
        date: 比赛日,格式 ``YYYY-MM-DD``。

    Returns:
        同步结果,含新建/更新计数、比分回写场次数与被跳过的场次说明。
    """
    result_items = await sporttery.fetch_match_results(date)

    skipped_matches: list[str] = []
    created_count = 0
    updated_count = 0
    game_updated_count = 0
    for item in result_items:
        fields = result_parser.build_result_fields(item)
        game = await session.get(MatchGame, fields["match_id"])
        if game is None:
            skipped_matches.append(
                f"{fields['match_num_str']} "
                f"{fields['home_team_name']} vs {fields['away_team_name']}"
                "(场次未入库,请先同步赛事)"
            )
            continue

        # 联赛/球队名称仅用于跳过提示,不写入赛果表
        db_fields = {
            key: value
            for key, value in fields.items()
            if key not in ("league_name", "home_team_name", "away_team_name")
        }
        record = await session.get(MatchResult, fields["match_id"])
        if record is None:
            record = MatchResult(**db_fields)
            session.add(record)
            created_count += 1
        else:
            for key, value in db_fields.items():
                setattr(record, key, value)
            record.update_time = datetime.datetime.now()
            updated_count += 1

        if fields["full_home_score"] is not None:
            game.home_score = fields["full_home_score"]
            game.away_score = fields["full_away_score"]
            game.match_status = MatchStatus.FINISHED
            game_updated_count += 1

    await session.flush()
    return ResultSyncResult(
        date=date,
        day_result_count=len(result_items),
        created_count=created_count,
        updated_count=updated_count,
        game_updated_count=game_updated_count,
        skipped_matches=skipped_matches,
    )


async def list_results_by_date(
    session: AsyncSession, date: datetime.date
) -> list[tuple[MatchResult, MatchGame]]:
    """查询指定比赛日的赛果列表(赛果 + 关联比赛),按场次编号排序。

    Args:
        session: 异步数据库会话。
        date: 比赛日。

    Returns:
        (赛果, 比赛) 元组列表;比赛的开赛时间落在该日(本地口径)。
    """
    day_start = datetime.datetime(date.year, date.month, date.day)
    day_end = day_start + datetime.timedelta(days=1)
    stmt = (
        select(MatchResult, MatchGame)
        .join(MatchGame, MatchResult.match_id == MatchGame.match_id)
        .where(
            MatchGame.match_time >= day_start,
            MatchGame.match_time < day_end,
        )
        .options(
            # 显式加载名称关系,避免响应序列化时异步懒加载
            selectinload(MatchGame.league),
            selectinload(MatchGame.home_team),
            selectinload(MatchGame.away_team),
        )
        .order_by(MatchResult.match_num_str)
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows]
