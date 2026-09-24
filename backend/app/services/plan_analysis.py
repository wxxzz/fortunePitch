"""投注方案分析服务:基于赔率隐含概率计算方案的中奖概率与期望值。

概率口径(隐含概率,去水):
- 对某玩法在售的全部选项,``p_i = (1/odds_i) / Σ(1/odds_j)``,
  归一化消除返还率折扣(overround);赔率优先取 fp_match_odds 当前值,
  库中无该玩法/选项时回退用勾选时点赔率、并入分母参与归一。

单关口径:
- 每注独立结算,期望回报 = 注额 x Σ(p_i x odds_i);
- 中奖概率 = 至少一注命中 = 1 - Π(1 - q_g),g 按(场次,玩法)分组、
  q_g 为组内概率和;同组选项互斥,跨组按独立近似
  (同场不同玩法实际相关,此为近似口径)。

串关 N串1 口径(与 parlay.py 同规则:每场一玩法、复式多选项):
- 注数/总投入/单注最高赔率直接复用 calculate_parlay;
- 每场定义 q_m = Σ p_i(该场被覆盖概率)、S_m = Σ(odds_i x p_i);
- 期望回报 = 注额 x Σ_{C(M,N) 组合} Π S_m(精确:每注期望贡献为
  各场 odds x p 之积,复式对选项求和可分解到每场);
- 中奖概率 = 至少 N 场被覆盖 = Poisson-binomial 尾概率(各场覆盖
  相互独立,恰好 k 场覆盖的概率用 DP 累积,再对 k >= N 求和)。
  复式枚举全部选项组合,任取 N 个已覆盖场次的实际赢家组合必为
  其中一注,故该口径精确无近似。

注额均为模拟数据,分析结果不构成投注建议。
"""

import itertools
import math
import typing

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DataValidationError
from app.models import MatchOdds
from app.services.parlay import ParlayPick, calculate_parlay
from app.services.poisson import kelly_fraction

# 概率与比例统一保留 4 位小数,金额保留 2 位
_PROB_DIGITS = 4
_MONEY_DIGITS = 2

# 单关模式标记(其余模式按串关口径分析,与保存路径一致)
SINGLE_MODE = "single"


class SelectionAnalysis(typing.NamedTuple):
    """单条选注的分析结果(隐含概率 + 单位期望 + 凯利)。"""

    match_id: str
    match_name: str
    pool_code: str
    play_name: str
    option_code: str
    option_label: str
    odds: float
    implied_prob: float
    fair_odds: float
    ev_per_unit: float
    kelly_fraction: float


class PlanAnalysis(typing.NamedTuple):
    """投注方案整体分析结果(中奖概率与期望值)。"""

    mode: str
    selections: list[SelectionAnalysis]
    bet_count: int
    total_stake: float
    max_odds: float
    win_prob: float
    expected_return: float
    expected_value: float
    ev_pct: float


def implied_probabilities(options: list[tuple[str, float]]) -> dict[str, float]:
    """按去水口径计算一组选项的隐含概率。

    Args:
        options: (选项编码, 十进制赔率) 列表,取自同一玩法的全部在售选项。

    Returns:
        选项编码到隐含概率的映射(和为 1);无有效赔率时返回空映射。
    """
    inversions = {code: 1.0 / odds for code, odds in options if odds > 0}
    total = sum(inversions.values())
    if total <= 0:
        return {}
    return {code: inv / total for code, inv in inversions.items()}


def _poisson_binomial_at_least(qs: list[float], threshold: int) -> float:
    """独立伯努利试验中,成功次数 >= threshold 的概率(Poisson-binomial 尾)。

    Args:
        qs: 每次试验的成功概率列表。
        threshold: 成功次数下限(含)。

    Returns:
        成功次数不少于 threshold 的概率。
    """
    # dp[k] = 到当前为止恰好 k 次成功的概率
    dp = [1.0] + [0.0] * len(qs)
    for q in qs:
        for k in range(len(qs) - 1, -1, -1):
            if dp[k] > 0:
                dp[k + 1] += dp[k] * q
                dp[k] *= 1.0 - q
    return sum(dp[threshold:])


async def _load_pool_options(
    session: AsyncSession, match_ids: set[str]
) -> dict[tuple[str, str], dict[str, float]]:
    """批量加载比赛的当前在售赔率,建 (match_id, pool_code) -> {option_code: odds}。

    Args:
        session: 异步数据库会话。
        match_ids: 比赛编号集合。

    Returns:
        各场比赛各玩法的选项赔率映射;未同步赔率的场次不在其中。
    """
    if not match_ids:
        return {}
    result = await session.execute(
        select(MatchOdds).where(MatchOdds.match_id.in_(match_ids))
    )
    pool_options: dict[tuple[str, str], dict[str, float]] = {}
    for row in result.scalars().all():
        for pool in row.pools:
            pool_code = pool.get("poolCode")
            options = {
                str(option.get("code")): float(option.get("odds"))
                for option in pool.get("options", [])
                if option.get("code") and option.get("odds")
            }
            if pool_code and options:
                pool_options[(row.match_id, str(pool_code))] = options
    return pool_options


class _ResolvedSelection(typing.NamedTuple):
    """选注的赔率解析结果(原始精度,供汇总计算)。"""

    pick: ParlayPick
    odds: float
    implied_prob: float


def _analyze_selections(
    picks: list[ParlayPick],
    pool_options: dict[tuple[str, str], dict[str, float]],
) -> list[_ResolvedSelection]:
    """逐条选注解析当前赔率并计算隐含概率(原始精度)。

    Args:
        picks: 选注列表(每场一玩法,可多选项复式)。
        pool_options: 各场各玩法的当前在售选项赔率。

    Returns:
        与 picks 同序的 (选注, 赔率, 隐含概率) 列表。

    Raises:
        DataValidationError: 选注赔率不大于 1(凯利公式要求)。
    """
    # 同一 (场次, 玩法) 的选项集合 = 库中当前在售 ∪ 勾选时点(兜底合并)
    merged: dict[tuple[str, str], dict[str, float]] = {}
    for pick in picks:
        key = (pick.match_id, pick.pool_code)
        options = dict(pool_options.get(key, {}))
        options.setdefault(pick.option_code, pick.odds)
        merged[key] = options

    resolved: list[_ResolvedSelection] = []
    for pick in picks:
        key = (pick.match_id, pick.pool_code)
        # 赔率优先取库中当前值,勾选时点赔率兜底
        odds = pool_options.get(key, {}).get(pick.option_code, pick.odds)
        if odds <= 1.0:
            raise DataValidationError(
                f"选注赔率必须大于 1:{pick.match_name} {pick.option_label} @{odds}"
            )
        if key in pool_options:
            # 库中在售:全选项(含兜底并入的勾选项)去水归一
            prob_map = implied_probabilities(list(merged[key].items()))
            prob = prob_map[pick.option_code]
        else:
            # 库中无该玩法:仅勾选时点赔率,直接取隐含概率不归一
            prob = 1.0 / odds
        resolved.append(
            _ResolvedSelection(pick=pick, odds=odds, implied_prob=prob)
        )
    return resolved


async def analyze_plan(
    session: AsyncSession,
    picks: list[ParlayPick],
    mode: str,
    parlay_size: int | None,
    stake_per_bet: float,
) -> PlanAnalysis:
    """分析一张投注方案:各选项隐含概率 + 方案中奖概率与期望值。

    Args:
        session: 异步数据库会话。
        picks: 选注列表(每场一玩法,同玩法可多选项复式)。
        mode: 投注模式(single/parlay/mixed);非 single 按串关口径分析。
        parlay_size: N串1 的 N,串关/混合模式必填。
        stake_per_bet: 每注模拟注额。

    Returns:
        方案分析结果(金额 2 位小数、概率与比例 4 位小数)。

    Raises:
        DataValidationError: 参数非法或选注不满足串关规则
            (玩法编码 / 同场多玩法 / 场次不足 / 注数超限)。
    """
    if not picks:
        raise DataValidationError("方案至少需要一条选注")
    if stake_per_bet <= 0:
        raise DataValidationError(f"每注注额必须大于 0:{stake_per_bet}")
    if mode != SINGLE_MODE and parlay_size is None:
        raise DataValidationError("串关/混合模式必须提供过关方式 parlay_size")

    pool_options = await _load_pool_options(session, {p.match_id for p in picks})
    resolved = _analyze_selections(picks, pool_options)
    # 展示用逐条分析(四舍五入);汇总计算用上方原始精度
    analyses = [
        SelectionAnalysis(
            match_id=r.pick.match_id,
            match_name=r.pick.match_name,
            pool_code=r.pick.pool_code,
            play_name=r.pick.play_name,
            option_code=r.pick.option_code,
            option_label=r.pick.option_label,
            odds=round(r.odds, _MONEY_DIGITS),
            implied_prob=round(r.implied_prob, _PROB_DIGITS),
            fair_odds=round(1.0 / r.implied_prob, _MONEY_DIGITS),
            ev_per_unit=round(r.implied_prob * r.odds - 1.0, _PROB_DIGITS),
            kelly_fraction=round(
                kelly_fraction(r.implied_prob, r.odds), _PROB_DIGITS
            ),
        )
        for r in resolved
    ]

    if mode == SINGLE_MODE:
        bet_count = len(resolved)
        total_stake = round(bet_count * stake_per_bet, _MONEY_DIGITS)
        max_odds = max(r.odds for r in resolved)
        expected_return = stake_per_bet * sum(
            r.implied_prob * r.odds for r in resolved
        )
        # 按 (场次, 玩法) 分组求覆盖概率,同组互斥、跨组按独立近似;
        # 不归一兜底口径下组内概率和可能超过 1,截断到 1
        group_probs: dict[tuple[str, str], float] = {}
        for r in resolved:
            key = (r.pick.match_id, r.pick.pool_code)
            group_probs[key] = min(
                group_probs.get(key, 0.0) + r.implied_prob, 1.0
            )
        win_prob = 1.0
        for q in group_probs.values():
            win_prob *= 1.0 - q
        win_prob = 1.0 - win_prob
    else:
        # 串关口径:注数/总投入/单注最高赔率复用 calculate_parlay(含规则校验)
        calc = calculate_parlay(picks, parlay_size, stake_per_bet)
        bet_count = calc.bet_count
        total_stake = calc.total_stake
        max_odds = calc.max_odds
        # 每场的覆盖概率 q 与期望回报乘数 S(复式对选项求和)
        match_q: dict[str, float] = {}
        match_s: dict[str, float] = {}
        for r in resolved:
            match_id = r.pick.match_id
            match_q[match_id] = min(
                match_q.get(match_id, 0.0) + r.implied_prob, 1.0
            )
            match_s[match_id] = match_s.get(match_id, 0.0) + (
                r.implied_prob * r.odds
            )
        # 期望回报 = 注额 x Σ_{C(M,N) 组合} Π S_m(与注数同一组合口径)
        expected_return = stake_per_bet * sum(
            math.prod(match_s[match_id] for match_id in combo)
            for combo in itertools.combinations(match_q, parlay_size)
        )
        # 中奖概率 = 至少 N 场被覆盖(Poisson-binomial 尾概率,精确)
        win_prob = _poisson_binomial_at_least(
            list(match_q.values()), parlay_size
        )

    expected_return = round(expected_return, _MONEY_DIGITS)
    expected_value = round(expected_return - total_stake, _MONEY_DIGITS)
    ev_pct = round(expected_value / total_stake, _PROB_DIGITS) if total_stake else 0.0
    return PlanAnalysis(
        mode=mode,
        selections=analyses,
        bet_count=bet_count,
        total_stake=total_stake,
        max_odds=max_odds,
        win_prob=round(win_prob, _PROB_DIGITS),
        expected_return=expected_return,
        expected_value=expected_value,
        ev_pct=ev_pct,
    )
