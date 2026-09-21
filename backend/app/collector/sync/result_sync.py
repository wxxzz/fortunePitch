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
    session: AsyncSession,
    start_date: datetime.date,
    end_date: datetime.date,
) -> list[tuple[MatchResult, MatchGame]]:
    """查询指定售卖日范围的赛果列表(赛果 + 关联比赛)。

    与赛事中心口径一致:按 fp_match_games.business_date 过滤,
    次日凌晨开赛的比赛归属前一售卖日;跨多日时按售卖日 + 场次编号排序。

    Args:
        session: 异步数据库会话。
        start_date: 售卖日起(含)。
        end_date: 售卖日止(含)。

    Returns:
        (赛果, 比赛) 元组列表。
    """
    stmt = (
        select(MatchResult, MatchGame)
        .join(MatchGame, MatchResult.match_id == MatchGame.match_id)
        .where(
            MatchGame.business_date >= start_date,
            MatchGame.business_date <= end_date,
        )
        .options(
            # 显式加载名称关系,避免响应序列化时异步懒加载
            selectinload(MatchGame.league),
            selectinload(MatchGame.home_team),
            selectinload(MatchGame.away_team),
        )
        .order_by(MatchGame.business_date, MatchResult.match_num_str)
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows]


# 胜平负 / 让球开奖结果的固定展示顺序
_WDL_ORDER = ("主胜", "平", "客胜")
_HHAD_ORDER = ("让球主胜", "让球平", "让球客胜")

# 总进球分布的 7+ 合并阈值
_TTG_MERGE_THRESHOLD = 7


def _count_labels(values: list[str | None]) -> dict[str, int]:
    """统计非空标签的出现次数。"""
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def _fixed_distribution(
    values: list[str | None], order: tuple[str, ...]
) -> list[dict[str, typing.Any]]:
    """按固定顺序输出分布(主胜/平/客胜这类有限标签)。"""
    counts = _count_labels(values)
    if not counts:
        return []
    total = sum(counts.values())
    labels = [label for label in order if label in counts]
    labels += sorted(label for label in counts if label not in order)
    return [
        {
            "label": label,
            "count": counts[label],
            "pct": counts[label] / total,
        }
        for label in labels
    ]


def _ranked_distribution(values: list[str | None]) -> list[dict[str, typing.Any]]:
    """按出现次数倒序输出分布(比分/半全场这类开放标签)。"""
    counts = _count_labels(values)
    if not counts:
        return []
    total = sum(counts.values())
    return [
        {
            "label": label,
            "count": counts[label],
            "pct": counts[label] / total,
        }
        for label in sorted(counts, key=lambda label: (-counts[label], label))
    ]


def _ttg_distribution(values: list[str | None]) -> list[dict[str, typing.Any]]:
    """总进球分布:按进球数升序,7 球及以上合并为"7+"。"""
    buckets: dict[str, int] = {}
    for value in values:
        if not value:
            continue
        try:
            goals = int(value)
        except ValueError:
            bucket = value
        else:
            bucket = "7+" if goals >= _TTG_MERGE_THRESHOLD else str(goals)
        buckets[bucket] = buckets.get(bucket, 0) + 1
    if not buckets:
        return []
    total = sum(buckets.values())

    def bucket_key(label: str) -> tuple[int, str]:
        if label == "7+":
            return (_TTG_MERGE_THRESHOLD, "")
        try:
            return (int(label), "")
        except ValueError:
            return (_TTG_MERGE_THRESHOLD + 1, label)

    return [
        {
            "label": label,
            "count": buckets[label],
            "pct": buckets[label] / total,
        }
        for label in sorted(buckets, key=bucket_key)
    ]


def _league_stats(
    pairs: list[tuple[MatchResult, MatchGame]],
) -> list[dict[str, typing.Any]]:
    """按联赛统计已开赛场次的胜负分布与场均总进球,按场次倒序。"""
    groups: dict[str, list[MatchResult]] = {}
    for result, game in pairs:
        if result.full_home_score is None:
            continue
        league_name = game.league.league_name if game.league else "未知联赛"
        groups.setdefault(league_name, []).append(result)
    rows: list[dict[str, typing.Any]] = []
    for league_name, results in groups.items():
        goals = [
            (item.full_home_score or 0) + (item.full_away_score or 0)
            for item in results
        ]
        rows.append(
            {
                "league_name": league_name,
                "total": len(results),
                "home_win": sum(1 for item in results if item.had == "主胜"),
                "draw": sum(1 for item in results if item.had == "平"),
                "away_win": sum(1 for item in results if item.had == "客胜"),
                "avg_total_goals": round(sum(goals) / len(results), 2),
            }
        )
    rows.sort(key=lambda row: (-row["total"], row["league_name"]))
    return rows


async def build_result_stats(
    session: AsyncSession,
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict[str, typing.Any]:
    """统计指定售卖日范围内赛果的多维度分布,供开奖页分析区展示。

    维度:胜平负/让球胜平负/总进球(7+ 合并)/比分/半全场的开奖分布,
    以及按联赛的胜负分布与场均进球。取消/无效场次不参与统计。

    Args:
        session: 异步数据库会话。
        start_date: 售卖日起(含)。
        end_date: 售卖日止(含)。

    Returns:
        统计字典:total/settled/cancelled 计数 + 各维度条目列表
        (label/count/pct)与按联赛统计行。
    """
    pairs = await list_results_by_business_date(session, start_date, end_date)
    settled_pairs = [
        (result, game)
        for result, game in pairs
        if result.full_home_score is not None
    ]
    return {
        "total": len(pairs),
        "settled": len(settled_pairs),
        "cancelled": len(pairs) - len(settled_pairs),
        "had": _fixed_distribution(
            [result.had for result, _ in settled_pairs], _WDL_ORDER
        ),
        "hhad": _fixed_distribution(
            [result.hhad for result, _ in settled_pairs], _HHAD_ORDER
        ),
        "ttg": _ttg_distribution([result.ttg for result, _ in settled_pairs]),
        "crs": _ranked_distribution([result.crs for result, _ in settled_pairs]),
        "hafu": _ranked_distribution([result.hafu for result, _ in settled_pairs]),
        "leagues": _league_stats(pairs),
    }
