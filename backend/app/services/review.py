"""复盘统计聚合服务:结算后的单关决策 + 串关方案统一聚合。

口径说明:
- KPI 总注数 = 单关决策数 + 串关方案数;命中率/盈亏只统计已结算记录;
- 盈亏曲线为统一事件流(已结算单关 + 已结算串关方案),按比赛时间排序累计;
- 维度分析(玩法/赔率区间/联赛)统计已结算的选注:单关决策 +
  串关明细逐腿,输出注数/命中数/命中率;
- 单关决策赔率与结算同口径(读时解析:HAD 优先 SP,否则当前在售赔率),
  串关明细用勾选时赔率快照。

注额均为模拟数据,仅用于复盘统计,不涉及真实资金。
"""

import datetime
import typing

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models import (
    BetScheme,
    DecisionStatus,
    MatchGame,
    MatchResult,
    MatchOdds,
    Recommendation,
    UserDecision,
)
from app.services.settlement import (
    PLAY_NAMES,
    _load_pools,
    _load_results,
    _result_label,
    resolve_option_hit,
    resolve_option_label,
    resolve_payout_odds,
    scheme_profit,
)

# 赔率区间分档:(下界, 上界, 展示名),上界 None 为开区间
ODDS_BANDS: tuple[tuple[float, float | None, str], ...] = (
    (0.0, 1.80, "低赔 <1.80"),
    (1.80, 2.50, "中赔 1.80-2.50"),
    (2.50, None, "高赔 ≥2.50"),
)


class ReviewKpi(typing.NamedTuple):
    """复盘核心指标。"""

    total_bets: int
    settled: int
    pending: int
    win_count: int
    hit_rate: float
    total_stake: float
    total_profit: float
    roi: float
    max_win_streak: int


class ProfitPoint(typing.NamedTuple):
    """盈亏曲线上的一个点(已结算事件累计)。"""

    label: str
    cumulative_profit: float


class DimensionStat(typing.NamedTuple):
    """维度分析条目(玩法/赔率区间/联赛)。"""

    name: str
    count: int
    hits: int
    hit_rate: float


class ReviewStats(typing.NamedTuple):
    """复盘统计聚合结果。"""

    kpi: ReviewKpi
    profit_curve: list[ProfitPoint]
    by_play: list[DimensionStat]
    by_odds_range: list[DimensionStat]
    by_league: list[DimensionStat]


class ReviewDecisionRow(typing.NamedTuple):
    """复盘单关决策富明细行(联表计算,不落库)。"""

    decision_id: int
    user_id: int
    match_id: str
    match_name: str
    league_name: str
    match_time: datetime.datetime
    pool_code: str
    play_name: str
    option_code: str
    option_label: str
    odds: float | None
    stake_amount: float
    result_label: str | None
    result_status: DecisionStatus
    profit_loss: float | None


class _DecisionContext(typing.NamedTuple):
    """单条决策的联表上下文(供统计与明细共用)。"""

    decision: UserDecision
    match_id: str
    match_name: str
    league_name: str
    match_time: datetime.datetime
    play_code: str
    option_code: str
    option_label: str
    odds: float | None
    result_label: str | None


class _Pick(typing.NamedTuple):
    """参与维度统计的一条选注。"""

    play_code: str
    league_name: str
    odds: float | None
    is_hit: bool


class _Event(typing.NamedTuple):
    """盈亏曲线事件(一笔已结算投注)。"""

    match_time: datetime.datetime
    label: str
    profit: float
    is_win: bool


class _ReviewData:
    """某用户的复盘数据集(单次加载,统计与明细共用)。"""

    def __init__(
        self,
        decisions: list[_DecisionContext],
        schemes: list[BetScheme],
        results: dict[str, MatchResult],
        game_league: dict[str, str],
        game_time: dict[str, datetime.datetime],
    ) -> None:
        self.decisions = decisions
        self.schemes = schemes
        self.results = results
        self.game_league = game_league
        self.game_time = game_time


async def _load_review_data(
    session: AsyncSession, user_id: int | None
) -> _ReviewData:
    """加载某用户的全部决策/方案及其联表上下文。"""
    decision_stmt = select(UserDecision)
    if user_id is not None:
        decision_stmt = decision_stmt.where(UserDecision.user_id == user_id)
    decisions = list((await session.execute(decision_stmt)).scalars().all())

    scheme_stmt = (
        select(BetScheme).options(selectinload(BetScheme.items))
    )
    if user_id is not None:
        scheme_stmt = scheme_stmt.where(BetScheme.user_id == user_id)
    schemes = list((await session.execute(scheme_stmt)).scalars().all())

    match_ids: set[str] = set()
    if decisions:
        rec_result = await session.execute(
            select(Recommendation).where(
                Recommendation.recommend_id.in_(
                    {d.recommend_id for d in decisions}
                )
            )
        )
        rec_by_id = {r.recommend_id: r for r in rec_result.scalars().all()}
        match_ids.update(r.match_id for r in rec_by_id.values())
    else:
        rec_by_id = {}
    match_ids.update(i.match_id for s in schemes for i in s.items)

    games_result = await session.execute(
        select(MatchGame)
        .options(
            joinedload(MatchGame.league),
            joinedload(MatchGame.home_team),
            joinedload(MatchGame.away_team),
        )
        .where(MatchGame.match_id.in_(match_ids))
    )
    game_by_id = {g.match_id: g for g in games_result.scalars().unique().all()}

    results = await _load_results(session, match_ids)
    pools = await _load_pools(session, match_ids)

    contexts: list[_DecisionContext] = []
    for decision in decisions:
        recommendation = rec_by_id.get(decision.recommend_id)
        if recommendation is None:
            continue
        game = game_by_id.get(recommendation.match_id)
        if game is None:
            continue
        play_code, _, option_code = decision.user_bet_type.partition(":")
        option_label = resolve_option_label(play_code, option_code)
        if option_label is None:
            continue
        result_label = _result_label(results.get(game.match_id), play_code)
        odds = None
        if result_label is not None:
            odds = resolve_payout_odds(
                play_code,
                option_code,
                results.get(game.match_id),
                pools.get(game.match_id),
            )
        league = game.league
        contexts.append(
            _DecisionContext(
                decision=decision,
                match_id=game.match_id,
                match_name=f"{game.home_team.team_name} vs {game.away_team.team_name}",
                league_name=league.league_name if league is not None else "未知联赛",
                match_time=game.match_time,
                play_code=play_code,
                option_code=option_code,
                option_label=option_label,
                odds=odds,
                result_label=result_label,
            )
        )

    game_league = {
        match_id: (
            g.league.league_name if g.league is not None else "未知联赛"
        )
        for match_id, g in game_by_id.items()
    }
    game_time = {match_id: g.match_time for match_id, g in game_by_id.items()}
    return _ReviewData(contexts, schemes, results, game_league, game_time)


def _odds_band(odds: float) -> str | None:
    """赔率归档到区间名,无法归档返回 None。"""
    for low, high, name in ODDS_BANDS:
        if odds >= low and (high is None or odds < high):
            return name
    return None


def _aggregate_dimension(
    picks: list[_Pick],
    key_fn: typing.Callable[[_Pick], str | None],
) -> list[DimensionStat]:
    """按 key_fn 分组聚合选注,返回 注数/命中数/命中率(按注数降序)。"""
    stats: dict[str, list[int]] = {}
    for pick in picks:
        key = key_fn(pick)
        if key is None:
            continue
        entry = stats.setdefault(key, [0, 0])
        entry[0] += 1
        if pick.is_hit:
            entry[1] += 1
    return [
        DimensionStat(
            name=name,
            count=values[0],
            hits=values[1],
            hit_rate=round(values[1] / values[0], 4) if values[0] else 0.0,
        )
        for name, values in sorted(
            stats.items(), key=lambda kv: (-kv[1][0], kv[0])
        )
    ]


def _max_win_streak(events: list[_Event]) -> int:
    """按时间排序后统计最长连续 WIN。"""
    current = 0
    best = 0
    for event in sorted(events, key=lambda e: e.match_time):
        if event.is_win:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _build_stats(data: _ReviewData) -> ReviewStats:
    """从数据集聚合 KPI、盈亏曲线与维度分析。"""
    settled_decisions = [
        ctx
        for ctx in data.decisions
        if ctx.decision.result_status != DecisionStatus.PUSH
    ]
    settled_schemes = [
        s for s in data.schemes if s.status != "PENDING"
    ]

    events: list[_Event] = [
        _Event(
            match_time=ctx.match_time,
            label=ctx.match_time.strftime("%m-%d"),
            profit=float(ctx.decision.profit_loss or 0),
            is_win=ctx.decision.result_status == DecisionStatus.WIN,
        )
        for ctx in settled_decisions
    ]
    for scheme in settled_schemes:
        profit = scheme_profit(scheme, data.results)
        if profit is None:
            continue
        item_times = [
            data.game_time[i.match_id]
            for i in scheme.items
            if i.match_id in data.game_time
        ]
        if not item_times:
            continue
        match_time = max(item_times)
        events.append(
            _Event(
                match_time=match_time,
                label=match_time.strftime("%m-%d"),
                profit=profit,
                is_win=scheme.status == "WIN",
            )
        )

    win_count = sum(1 for e in events if e.is_win)
    settled = len(events)
    total_stake = sum(float(d.decision.stake_amount) for d in data.decisions) + sum(
        float(s.total_stake) for s in data.schemes
    )
    total_profit = round(sum(e.profit for e in events), 2)

    curve: list[ProfitPoint] = []
    cumulative = 0.0
    for event in sorted(events, key=lambda e: e.match_time):
        cumulative = round(cumulative + event.profit, 2)
        curve.append(ProfitPoint(label=event.label, cumulative_profit=cumulative))

    # 维度统计:已结算单关(命中=WIN)+ 已结算串关逐腿
    picks: list[_Pick] = [
        _Pick(
            play_code=ctx.play_code,
            league_name=ctx.league_name,
            odds=ctx.odds,
            is_hit=ctx.decision.result_status == DecisionStatus.WIN,
        )
        for ctx in settled_decisions
    ]
    for scheme in settled_schemes:
        for item in scheme.items:
            result_label = _result_label(data.results.get(item.match_id), item.pool_code)
            picks.append(
                _Pick(
                    play_code=item.pool_code,
                    league_name=data.game_league.get(item.match_id, "未知联赛"),
                    odds=float(item.odds),
                    is_hit=bool(
                        resolve_option_hit(item.pool_code, item.option_label, result_label)
                    ),
                )
            )

    return ReviewStats(
        kpi=ReviewKpi(
            total_bets=len(data.decisions) + len(data.schemes),
            settled=settled,
            pending=(len(data.decisions) + len(data.schemes)) - settled,
            win_count=win_count,
            hit_rate=round(win_count / settled, 4) if settled else 0.0,
            total_stake=round(total_stake, 2),
            total_profit=total_profit,
            roi=round(total_profit / total_stake, 4) if total_stake else 0.0,
            max_win_streak=_max_win_streak(events),
        ),
        profit_curve=curve,
        by_play=_aggregate_dimension(
            picks, lambda p: PLAY_NAMES.get(p.play_code, p.play_code)
        ),
        by_odds_range=_aggregate_dimension(
            picks, lambda p: _odds_band(p.odds) if p.odds is not None else None
        ),
        by_league=_aggregate_dimension(picks, lambda p: p.league_name),
    )


async def review_stats(session: AsyncSession, user_id: int | None) -> ReviewStats:
    """聚合某用户的复盘统计(KPI/盈亏曲线/维度分析)。"""
    data = await _load_review_data(session, user_id)
    return _build_stats(data)


async def list_review_decisions(
    session: AsyncSession,
    user_id: int | None,
    result_status: DecisionStatus | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[ReviewDecisionRow]:
    """查询某用户的单关决策富明细(联表计算,按比赛时间倒序)。

    Args:
        session: 异步数据库会话。
        user_id: 按用户过滤,None 为全部用户。
        result_status: 按结算状态过滤(None 为全部)。
        offset: 分页偏移。
        limit: 每页条数。

    Returns:
        富明细行列表。
    """
    data = await _load_review_data(session, user_id)
    rows = [
        ReviewDecisionRow(
            decision_id=ctx.decision.decision_id,
            user_id=ctx.decision.user_id,
            match_id=ctx.match_id,
            match_name=ctx.match_name,
            league_name=ctx.league_name,
            match_time=ctx.match_time,
            pool_code=ctx.play_code,
            play_name=PLAY_NAMES.get(ctx.play_code, ctx.play_code),
            option_code=ctx.option_code,
            option_label=ctx.option_label,
            odds=ctx.odds,
            stake_amount=float(ctx.decision.stake_amount),
            result_label=ctx.result_label,
            result_status=ctx.decision.result_status,
            profit_loss=(
                None
                if ctx.decision.profit_loss is None
                else float(ctx.decision.profit_loss)
            ),
        )
        for ctx in data.decisions
        if result_status is None or ctx.decision.result_status == result_status
    ]
    rows.sort(key=lambda r: (r.match_time, r.decision_id), reverse=True)
    return rows[offset : offset + limit]
