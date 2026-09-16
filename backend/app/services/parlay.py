"""串关虚拟投注方案服务:选注组合计算 + 方案留存。

竞彩串关口径(本系统规则):
- ``N串1`` 要求从已勾选的不同场次中任取 N 场做过关组合;
- 每场比赛仅允许勾选一种玩法(同一玩法可多选项,即复式);
- 注数 = 各 N 场组合的选项数乘积之和;
- 单注最高赔率 = 所有组合中"各场最高赔率乘积"的最大值;
- 虚拟注额与盈亏均为模拟数据,仅用于复盘,不涉及真实资金。
"""

import itertools
import typing

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import DataValidationError, ResourceNotFoundError
from app.models import BetScheme, BetSchemeItem, MatchGame

# 串关场次范围:2串1 ~ 8串1
MIN_PARLAY_SIZE = 2
MAX_PARLAY_SIZE = 8

# 总注数上限(防复式组合爆炸,超出提示用户减少选项)
MAX_BET_COUNT = 10000

# 竞彩串关支持的玩法编码(与 user_picks.POOL_TO_STRATEGY 一致)
PARLAY_POOL_CODES = frozenset({"HAD", "HHAD", "CRS", "TTG", "HAFU"})

# 单次方案的选注条数上限(与接口 Schema 的 max_length 一致)
MAX_ITEMS = 30


class ParlayPick(typing.NamedTuple):
    """一条串关选注(玩法选项 + 勾选时点赔率快照)。"""

    match_id: str
    match_name: str
    pool_code: str
    play_name: str
    option_code: str
    option_label: str
    odds: float


class ParlayCalc(typing.NamedTuple):
    """串关组合计算结果(服务端计算,不信任前端上传值)。"""

    bet_count: int
    total_stake: float
    max_odds: float


def _group_by_match(picks: list[ParlayPick]) -> dict[str, list[ParlayPick]]:
    """按比赛分组选注,并校验每场仅一种玩法。

    Raises:
        DataValidationError: 玩法编码非法,或同一场勾选了多种玩法。
    """
    groups: dict[str, list[ParlayPick]] = {}
    for pick in picks:
        if pick.pool_code not in PARLAY_POOL_CODES:
            raise DataValidationError(
                f"串关玩法编码必须是 {sorted(PARLAY_POOL_CODES)} 之一: {pick.pool_code}"
            )
        groups.setdefault(pick.match_id, []).append(pick)
    for match_id, match_picks in groups.items():
        pool_codes = {p.pool_code for p in match_picks}
        if len(pool_codes) > 1:
            raise DataValidationError(
                f"同一场比赛仅允许勾选一种玩法(串关口径): {match_id} "
                f"勾选了 {sorted(pool_codes)}"
            )
    return groups


def calculate_parlay(
    picks: list[ParlayPick], parlay_size: int, stake_per_bet: float
) -> ParlayCalc:
    """按竞彩串关口径计算注数、总投入与单注最高赔率。

    Args:
        picks: 选注列表(至少两场,每场一种玩法,可多选项复式)。
        parlay_size: N串1 的 N。
        stake_per_bet: 每注模拟注额。

    Returns:
        ParlayCalc: 注数、总投入、单注最高赔率。

    Raises:
        DataValidationError: 串关参数或选注组合不满足串关规则。
    """
    if not MIN_PARLAY_SIZE <= parlay_size <= MAX_PARLAY_SIZE:
        raise DataValidationError(
            f"串关场次必须是 {MIN_PARLAY_SIZE}~{MAX_PARLAY_SIZE} 之间: {parlay_size}"
        )

    groups = _group_by_match(picks)
    match_count = len(groups)
    if parlay_size > match_count:
        raise DataValidationError(
            f"{parlay_size}串1 需要 {parlay_size} 个不同场次,当前仅勾选了 {match_count} 场"
        )

    bet_count = 0
    max_odds = 0.0
    for combo in itertools.combinations(groups.values(), parlay_size):
        bet_count += 1
        for match_picks in combo:
            bet_count *= len(match_picks)
        combo_odds = 1.0
        for match_picks in combo:
            combo_odds *= max(p.odds for p in match_picks)
        max_odds = max(max_odds, combo_odds)
    if bet_count > MAX_BET_COUNT:
        raise DataValidationError(
            f"串关总注数超过上限 {MAX_BET_COUNT}(当前 {bet_count}),请减少复式选项"
        )
    return ParlayCalc(
        bet_count=bet_count,
        total_stake=round(bet_count * stake_per_bet, 2),
        max_odds=round(max_odds, 2),
    )


async def save_bet_scheme(
    session: AsyncSession,
    user_id: int,
    parlay_size: int,
    stake_per_bet: float,
    picks: list[ParlayPick],
) -> BetScheme:
    """校验选注并保存一个串关虚拟投注方案。

    Args:
        session: 异步数据库会话。
        user_id: 用户编号(模拟,文档未定义用户表)。
        parlay_size: N串1 的 N。
        stake_per_bet: 每注模拟注额。
        picks: 选注列表(勾选时点快照)。

    Returns:
        保存后的方案(含明细)。

    Raises:
        DataValidationError: 选注不满足串关规则或组合数超限。
        ResourceNotFoundError: 比赛不存在。
    """
    calc = calculate_parlay(picks, parlay_size, stake_per_bet)

    match_ids = {p.match_id for p in picks}
    result = await session.execute(
        select(MatchGame).where(MatchGame.match_id.in_(match_ids))
    )
    found_ids = {row.match_id for row in result.scalars().all()}
    missing_ids = match_ids - found_ids
    if missing_ids:
        raise ResourceNotFoundError("比赛", ", ".join(sorted(missing_ids)))

    scheme = BetScheme(
        user_id=user_id,
        parlay_size=parlay_size,
        stake_per_bet=stake_per_bet,
        bet_count=calc.bet_count,
        total_stake=calc.total_stake,
        max_odds=calc.max_odds,
        status="PENDING",
        items=[
            BetSchemeItem(
                match_id=p.match_id,
                match_name=p.match_name,
                pool_code=p.pool_code,
                play_name=p.play_name,
                option_code=p.option_code,
                option_label=p.option_label,
                odds=p.odds,
            )
            for p in picks
        ],
    )
    session.add(scheme)
    # flush 触发 INSERT(Python 端默认值已就位);不 refresh,
    # 保留内存中的 items 明细,响应序列化无需二次查询。
    await session.flush()
    return scheme


async def list_bet_schemes(
    session: AsyncSession,
    user_id: int | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[BetScheme]:
    """分页查询串关方案,可按用户过滤,按创建时间倒序(含明细)。"""
    stmt = (
        select(BetScheme)
        .options(selectinload(BetScheme.items))
        .offset(offset)
        .limit(limit)
        .order_by(BetScheme.created_at.desc(), BetScheme.scheme_id.desc())
    )
    if user_id is not None:
        stmt = stmt.where(BetScheme.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())
