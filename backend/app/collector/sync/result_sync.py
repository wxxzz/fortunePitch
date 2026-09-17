"""赛果同步:拉取竞彩赛果开奖数据并写入 fp_match_results。

赛果接口按比赛日(matchBeginDate/matchEndDate)返回数据;调用方可按
比赛日(date_type="match")或售卖日(date_type="sale")发起同步——
同一售卖日的场次包含当日晚场与次日凌晨场,售卖日口径会同时拉取
该售卖日与次日的比赛日赛果。

流程:拉取赛果 -> 逐条解析 -> 场次须已在 fp_match_games 中
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


async def sync_results_by_date(
    session: AsyncSession,
    date: str,
    *,
    date_type: typing.Literal["match", "sale"] = "match",
) -> ResultSyncResult:
    """同步竞彩赛果开奖数据,并回写比赛比分与状态。

    Args:
        session: 异步数据库会话。
        date: 日期,格式 ``YYYY-MM-DD``。
        date_type: ``match``=比赛日(仅拉取该日赛果);``sale``=售卖日
            (拉取该日与次日的赛果,覆盖归属该售卖日的次日凌晨场)。

    Returns:
        同步结果,含新建/更新计数、比分回写场次数与被跳过的场次说明。
    """
    # 售卖日口径:该售卖日当晚与次日凌晨的场次一并拉取(按 matchId 去重)
    fetch_dates = [date]
    if date_type == "sale":
        sale_date = datetime.date.fromisoformat(date)
        fetch_dates.append((sale_date + datetime.timedelta(days=1)).isoformat())
    result_items: list[dict[str, typing.Any]] = []
    seen_match_ids: set[str] = set()
    for fetch_date in fetch_dates:
        for item in await sporttery.fetch_match_results(fetch_date):
            match_id = str(item.get("matchId") or "")
            if match_id in seen_match_ids:
                continue
            seen_match_ids.add(match_id)
            result_items.append(item)

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


async def list_results_by_business_date(
    session: AsyncSession, date: datetime.date
) -> list[tuple[MatchResult, MatchGame]]:
    """查询指定售卖日的赛果列表(赛果 + 关联比赛),按场次编号排序。

    与赛事中心口径一致:按 fp_match_games.business_date 过滤,
    次日凌晨开赛的比赛归属前一售卖日。

    Args:
        session: 异步数据库会话。
        date: 售卖日。

    Returns:
        (赛果, 比赛) 元组列表。
    """
    stmt = (
        select(MatchResult, MatchGame)
        .join(MatchGame, MatchResult.match_id == MatchGame.match_id)
        .where(MatchGame.business_date == date)
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
