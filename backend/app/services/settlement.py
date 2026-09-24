"""复盘结算引擎:按赛果判定用户模拟决策与串关方案的输赢并计算盈亏。

结算口径(用户确认):
- 单关决策(fp_strategy_user_decisions)未存下注时赔率,结算时解析:
  HAD 优先用赛果 SP 每赔(sp_h/sp_d/sp_a),其余玩法用当前在售赔率
  (fp_match_odds.pools);赔率不可解析时跳过,保持 PUSH 待下次结算;
- 串关方案明细已存赔率快照,总回报 = 每注注额 x Σ_{中奖注} Π odds,
  status 落库 WIN/LOSS,盈亏读时实时计算(不改表);
- 未同步赛果或该玩法未开奖的记录跳过(保持 PUSH/PENDING)。

注额均为模拟数据,仅用于复盘统计,不涉及真实资金。
"""

import datetime
import itertools
import re
import typing

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    BetScheme,
    BetSchemeItem,
    DecisionStatus,
    MatchOdds,
    MatchResult,
    Recommendation,
    UserDecision,
)
from app.services.llm_query import RESULT_FIELD_BY_PLAY, _normalize_play_label

# 玩法编码 -> 展示名(与 parsers/odds.py 一致)
PLAY_NAMES: dict[str, str] = {
    "HAD": "胜平负",
    "HHAD": "让球胜平负",
    "CRS": "比分",
    "TTG": "总进球",
    "HAFU": "半全场",
}

# 胜平负/让球胜平负选项编码 -> 展示名(注意:HHAD 选项文案不带"让球"前缀)
_WDL_CODES = {"h": "主胜", "d": "平", "a": "客胜"}

# 半全场 9 个选项:前半场 + 全场结果
_HAFU_CODES = {
    "hh": "胜胜",
    "hd": "胜平",
    "ha": "胜负",
    "dh": "平胜",
    "dd": "平平",
    "da": "平负",
    "ah": "负胜",
    "ad": "负平",
    "aa": "负负",
}

# 比分特殊选项(胜/平/负其他)
_CRS_SPECIAL = {"s1sh": "胜其他", "s1sd": "平其他", "s1sa": "负其他"}

# 比分选项编码正则:如 s01s02 -> 1:2
_CRS_RE = re.compile(r"^s(\d{2})s(\d{2})$")

# HAD 赛果 SP 字段按选项编码映射
_HAD_SP_FIELD = {"h": "sp_h", "d": "sp_d", "a": "sp_a"}


class SettlementResult(typing.NamedTuple):
    """一次结算的汇总计数。"""

    decision_wins: int
    decision_losses: int
    scheme_wins: int
    scheme_losses: int


def resolve_option_label(play_code: str, option_code: str) -> str | None:
    """玩法选项编码 -> 展示名(静态映射,不依赖库中赔率)。

    Args:
        play_code: 玩法编码(HAD/HHAD/CRS/TTG/HAFU)。
        option_code: 选项编码,如 h / s01s02 / s7 / hh。

    Returns:
        展示名;无法解析时为 None。
    """
    if play_code in ("HAD", "HHAD"):
        return _WDL_CODES.get(option_code)
    if play_code == "HAFU":
        return _HAFU_CODES.get(option_code)
    if play_code == "TTG":
        if not option_code.startswith("s") or not option_code[1:].isdigit():
            return None
        num = int(option_code[1:])
        return "7+" if num >= 7 else str(num)
    if play_code == "CRS":
        if option_code in _CRS_SPECIAL:
            return _CRS_SPECIAL[option_code]
        matched = _CRS_RE.match(option_code)
        if matched is None:
            return None
        return f"{int(matched.group(1))}:{int(matched.group(2))}"
    return None


def resolve_option_hit(
    play_code: str,
    option_label: str,
    result: str | None,
) -> bool | None:
    """比对选项展示名与该玩法开奖结果,判定是否命中。

    复用 llm_query 的归一化(剥"让球"前缀/"球"后缀)。
    TTG 边界:选项"7+"命中所有总进球 >=7 的赛果(如"7"/"8")。

    Args:
        play_code: 玩法编码。
        option_label: 选项展示名(如"主胜"/"7+"/"1:2"/"胜胜")。
        result: 开奖结果标签;未开奖为 None。

    Returns:
        命中为 True,未中为 False,未开奖为 None。
    """
    if not result:
        return None
    if play_code == "TTG" and option_label == "7+":
        try:
            return int(result) >= 7
        except ValueError:
            return False
    return _normalize_play_label(play_code, option_label) == _normalize_play_label(
        play_code, result
    )


def resolve_payout_odds(
    play_code: str,
    option_code: str,
    result: MatchResult | None,
    pools: list[dict[str, typing.Any]] | None,
) -> float | None:
    """解析结算赔率:HAD 优先赛果 SP,否则当前在售赔率池。

    Args:
        play_code: 玩法编码。
        option_code: 选项编码。
        result: 该场赛果记录(可为 None)。
        pools: fp_match_odds.pools 当前在售玩法列表(可为 None)。

    Returns:
        结算赔率;无法解析时为 None(调用方应跳过本次结算)。
    """
    if play_code == "HAD" and result is not None:
        field = _HAD_SP_FIELD.get(option_code)
        sp_value = getattr(result, field) if field else None
        if sp_value is not None and float(sp_value) > 0:
            return float(sp_value)
    if not pools:
        return None
    pool = next((p for p in pools if p.get("poolCode") == play_code), None)
    if pool is None:
        return None
    option = next(
        (
            o
            for o in pool.get("options") or []
            if isinstance(o, dict) and str(o.get("code") or "") == option_code
        ),
        None,
    )
    if option is None:
        return None
    try:
        value = float(option.get("odds"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


async def _load_results(
    session: AsyncSession, match_ids: set[str]
) -> dict[str, MatchResult]:
    """批量加载赛果,返回 match_id -> MatchResult。"""
    if not match_ids:
        return {}
    result = await session.execute(
        select(MatchResult).where(MatchResult.match_id.in_(match_ids))
    )
    return {row.match_id: row for row in result.scalars().all()}


async def _load_pools(
    session: AsyncSession, match_ids: set[str]
) -> dict[str, list[dict[str, typing.Any]]]:
    """批量加载当前在售赔率,返回 match_id -> pools 列表。"""
    if not match_ids:
        return {}
    result = await session.execute(
        select(MatchOdds).where(MatchOdds.match_id.in_(match_ids))
    )
    return {row.match_id: list(row.pools or []) for row in result.scalars().all()}


def _result_label(result: MatchResult | None, play_code: str) -> str | None:
    """取赛果记录中该玩法的开奖结果标签。"""
    if result is None:
        return None
    field = RESULT_FIELD_BY_PLAY.get(play_code)
    if field is None:
        return None
    return getattr(result, field)


def compute_scheme_payout(
    items: list[BetSchemeItem],
    results: dict[str, MatchResult],
    parlay_size: int,
    stake_per_bet: float,
) -> float | None:
    """按串关口径计算方案总回报(中奖注赔率乘积之和 x 每注注额)。

    任一腿赛果未开奖时返回 None(无法结算)。
    每注回报分解:Σ_{中奖注} Π odds = Π_{各场}(Σ_{命中选项} odds),
    与 plan_analysis 的期望分解同构,避免枚举单注。

    Args:
        items: 方案选注明细(含赔率快照与选项展示名)。
        results: match_id -> MatchResult。
        parlay_size: N串1 的 N。
        stake_per_bet: 每注模拟注额。

    Returns:
        总回报(2dp);赛果不齐时为 None。
    """
    groups: dict[str, list[BetSchemeItem]] = {}
    for item in items:
        groups.setdefault(item.match_id, []).append(item)
    # 每场命中选项的赔率和(未开奖 -> None 标记)
    match_hit_sums: dict[str, float | None] = {}
    for match_id, match_items in groups.items():
        result = _result_label(results.get(match_id), match_items[0].pool_code)
        hit_sum: float | None = None
        if result is not None:
            hit_sum = 0.0
            for item in match_items:
                if resolve_option_hit(item.pool_code, item.option_label, result):
                    hit_sum += float(item.odds)
        match_hit_sums[match_id] = hit_sum
    if any(value is None for value in match_hit_sums.values()):
        return None

    total_payout = 0.0
    match_ids = list(groups)
    for combo in itertools.combinations(match_ids, parlay_size):
        combo_payout = 1.0
        for match_id in combo:
            assert match_hit_sums[match_id] is not None
            combo_payout *= match_hit_sums[match_id]
        total_payout += combo_payout
    return round(total_payout * stake_per_bet, 2)


def scheme_profit(
    scheme: BetScheme,
    results: dict[str, MatchResult],
) -> float | None:
    """方案盈亏 = 总回报 - 总投入(读时实时计算,不改表)。

    Returns:
        盈亏金额(2dp);任一腿未开奖时为 None。
    """
    payout = compute_scheme_payout(
        list(scheme.items), results, scheme.parlay_size, float(scheme.stake_per_bet)
    )
    if payout is None:
        return None
    return round(payout - float(scheme.total_stake), 2)


async def settle_user_decisions(
    session: AsyncSession, user_id: int | None = None
) -> tuple[int, int]:
    """结算待结算(PUSH)的用户模拟决策。

    判定输赢并回写 result_status / profit_loss;未开奖或赔率
    不可解析的保持 PUSH,留待下次结算。幂等:已结算的不重复处理。

    Args:
        session: 异步数据库会话(事务由调用方管理)。
        user_id: 按用户过滤,None 为全部用户。

    Returns:
        (结算 WIN 数, 结算 LOSS 数)。
    """
    stmt = select(UserDecision).where(
        UserDecision.result_status == DecisionStatus.PUSH
    )
    if user_id is not None:
        stmt = stmt.where(UserDecision.user_id == user_id)
    decisions = list((await session.execute(stmt)).scalars().all())
    if not decisions:
        return (0, 0)

    rec_result = await session.execute(
        select(Recommendation).where(
            Recommendation.recommend_id.in_({d.recommend_id for d in decisions})
        )
    )
    rec_by_id = {r.recommend_id: r for r in rec_result.scalars().all()}

    match_ids = {
        r.match_id for r in rec_by_id.values() if r is not None
    }
    results = await _load_results(session, match_ids)
    pools = await _load_pools(session, match_ids)

    wins = 0
    losses = 0
    for decision in decisions:
        recommendation = rec_by_id.get(decision.recommend_id)
        if recommendation is None:
            continue
        play_code, _, option_code = decision.user_bet_type.partition(":")
        result_label = _result_label(results.get(recommendation.match_id), play_code)
        if result_label is None:
            continue
        option_label = resolve_option_label(play_code, option_code)
        if option_label is None:
            continue
        hit = resolve_option_hit(play_code, option_label, result_label)
        if hit is None:
            continue
        stake = float(decision.stake_amount)
        if hit:
            odds = resolve_payout_odds(
                play_code,
                option_code,
                results.get(recommendation.match_id),
                pools.get(recommendation.match_id),
            )
            if odds is None or odds <= 0:
                # 赔率暂不可解析,保持 PUSH 等下次结算
                continue
            decision.profit_loss = round(stake * (odds - 1), 2)
            decision.result_status = DecisionStatus.WIN
            wins += 1
        else:
            decision.profit_loss = round(-stake, 2)
            decision.result_status = DecisionStatus.LOSS
            losses += 1
    return (wins, losses)


async def settle_bet_schemes(
    session: AsyncSession, user_id: int | None = None
) -> tuple[int, int]:
    """结算待结算(PENDING)的串关虚拟投注方案。

    全部腿赛果齐备才结算:存在中奖注为 WIN,否则 LOSS;
    盈亏不落库,读时实时计算(scheme_profit)。
    幂等:已结算的不重复处理。

    Args:
        session: 异步数据库会话(事务由调用方管理)。
        user_id: 按用户过滤,None 为全部用户。

    Returns:
        (结算 WIN 数, 结算 LOSS 数)。
    """
    stmt = (
        select(BetScheme)
        .options(selectinload(BetScheme.items))
        .where(BetScheme.status == "PENDING")
    )
    if user_id is not None:
        stmt = stmt.where(BetScheme.user_id == user_id)
    schemes = list((await session.execute(stmt)).scalars().all())
    if not schemes:
        return (0, 0)

    match_ids = {i.match_id for s in schemes for i in s.items}
    results = await _load_results(session, match_ids)

    wins = 0
    losses = 0
    for scheme in schemes:
        payout = compute_scheme_payout(
            list(scheme.items), results, scheme.parlay_size, float(scheme.stake_per_bet)
        )
        if payout is None:
            continue
        if payout > 0:
            scheme.status = "WIN"
            wins += 1
        else:
            scheme.status = "LOSS"
            losses += 1
    return (wins, losses)


async def run_settlement(
    session: AsyncSession, user_id: int | None = None
) -> SettlementResult:
    """执行完整结算(单关决策 + 串关方案),供接口调用。"""
    decision_wins, decision_losses = await settle_user_decisions(session, user_id)
    scheme_wins, scheme_losses = await settle_bet_schemes(session, user_id)
    return SettlementResult(
        decision_wins=decision_wins,
        decision_losses=decision_losses,
        scheme_wins=scheme_wins,
        scheme_losses=scheme_losses,
    )


async def load_scheme_annotations(
    session: AsyncSession, schemes: list[BetScheme]
) -> dict[int, dict[str, typing.Any]]:
    """为方案列表加载读时结算注记(逐腿赛果/命中 + 方案盈亏)。

    Args:
        session: 异步数据库会话。
        schemes: 已加载明细的方案列表。

    Returns:
        scheme_id -> {"profit_loss": float | None, "items": {item_id: (result_label, is_hit)}}。
    """
    match_ids = {i.match_id for s in schemes for i in s.items}
    results = await _load_results(session, match_ids)
    annotations: dict[int, dict[str, typing.Any]] = {}
    for scheme in schemes:
        item_hits: dict[int, tuple[str | None, bool | None]] = {}
        for item in scheme.items:
            result_label = _result_label(results.get(item.match_id), item.pool_code)
            item_hits[item.item_id] = (
                result_label,
                resolve_option_hit(item.pool_code, item.option_label, result_label),
            )
        annotations[scheme.scheme_id] = {
            "profit_loss": scheme_profit(scheme, results),
            "items": item_hits,
        }
    return annotations
