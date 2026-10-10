"""AI 策略推荐引擎:按售卖日汇总 AI 分析结果,生成单场推荐与串关候选。

数据流:每场最新 AI 分析的分玩法推荐(fp_match_llm_play_recs)
-> 解析选项编码与生成时点赔率 -> 计算去水隐含概率 / EV / 凯利
-> 落库批次 + 单场推荐(fp_strategy_ai_pick_batches / ai_picks)
-> 从高置信推荐中自动组 2-4 串候选(fp_strategy_ai_parlay_plans)。

一键转换:单场推荐 -> 桥接 Recommendation + UserDecision(仿用户自选流,
结算/复盘链路零改动);串关候选 -> parlay.save_bet_scheme 物化正式方案。

合规说明:所有注额均为模拟数据,分析结果仅供参考,不构成投注建议。
"""

import datetime
import logging
import math
import typing

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.exceptions import DataValidationError, ResourceNotFoundError
from app.models import (
    AiParlayPlan,
    AiPick,
    AiPickBatch,
    BetScheme,
    MatchGame,
    MatchStatus,
    Recommendation,
    UserDecision,
)
from app.services import llm_query, parlay, plan_analysis, poisson, settlement
from app.services.parlay import ParlayPick
from app.services.user_picks import POOL_TO_STRATEGY

logger = logging.getLogger(__name__)

# 默认置信度阈值:低于该值的 AI 推荐不进入清单
DEFAULT_MIN_CONFIDENCE = 0.55

# 桥接推荐记录的固定标注(与用户自选区分)
AI_PICK_TAG = "AI推荐"

# 串关候选的最大逆向腿数(校准规则:逆向腿 ≤ 2,来自竞彩复盘教训)
MAX_CONTRARIAN_LEGS = 2

# 凯利公式定义域为 (0,1) 开区间,置信度取到 0/1 边界值时钳制
_KELLY_PROB_MIN = 0.001
_KELLY_PROB_MAX = 0.999

# 组合置信度同样需钳制后再进凯利公式
_KELLY_CONF_MIN = 0.001
_KELLY_CONF_MAX = 0.999


class BatchSummary(typing.NamedTuple):
    """一次推荐生成的批次摘要。"""

    batch: AiPickBatch
    superseded_batch_ids: list[int]


class ParlayLegDraft(typing.NamedTuple):
    """串关候选中的一条腿草案(落库前)。"""

    pick: AiPick
    match_num_str: str
    match_name: str


def _clamp_kelly_prob(prob: float) -> float:
    """钳制概率到凯利公式定义域 (0,1)。"""
    return min(max(prob, _KELLY_PROB_MIN), _KELLY_PROB_MAX)


async def generate_batch(
    session: AsyncSession,
    *,
    business_date: datetime.date,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> BatchSummary:
    """按售卖日生成一批 AI 策略推荐(可反复重算)。

    取每场最新 AI 分析的全部玩法推荐,过滤已开赛场次与无法解析
    选项编码/赔率的条目(计入 skipped_count),计算隐含概率/EV/凯利
    后落库;随后从每场 EV 最高代表腿自动组 2-4 串候选方案。
    同售卖日旧 ACTIVE 批次置为 SUPERSEDED(历史保留)。

    Args:
        session: 异步数据库会话。
        business_date: 竞彩售卖日。
        min_confidence: 置信度阈值(含)。

    Returns:
        批次摘要(含被取代的旧批次 ID 列表)。
    """
    recs = await llm_query.query_play_recommendations(
        session, business_date=business_date, min_confidence=min_confidence
    )

    batch = AiPickBatch(
        business_date=business_date,
        min_confidence=min_confidence,
        pick_count=0,
        skipped_count=0,
        plan_count=0,
    )
    session.add(batch)
    await session.flush()

    # 旧 ACTIVE 批次置 SUPERSEDED(在插入新批次之后执行并排除自身:
    # 并发生成时"最后提交者"清理同日其他 ACTIVE 批次,收窄竞态窗口)
    superseded_ids = list(
        (
            await session.execute(
                select(AiPickBatch.batch_id).where(
                    AiPickBatch.business_date == business_date,
                    AiPickBatch.status == "ACTIVE",
                    AiPickBatch.batch_id != batch.batch_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if superseded_ids:
        await session.execute(
            update(AiPickBatch)
            .where(AiPickBatch.batch_id.in_(superseded_ids))
            .values(status="SUPERSEDED")
        )

    picks: list[AiPick] = []
    skipped_count = 0
    # match_id -> (场次编号, 对阵快照),供串关腿组装
    match_info: dict[str, tuple[str, str]] = {}
    for rec in recs:
        game = rec.analysis.game
        if game.match_status != MatchStatus.PENDING:
            skipped_count += 1
            continue
        pools = game.odds.pools if game.odds is not None else None
        matched = llm_query.resolve_recommendation_option(
            pools, rec.play_code, rec.recommendation
        )
        if matched is None:
            skipped_count += 1
            continue
        option_code = str(matched.get("code") or "").strip()
        try:
            odds = float(matched.get("odds"))
        except (TypeError, ValueError):
            odds = 0.0
        # 编码缺失 / 赔率非正(≤1 无套利意义且 EV 口径失真)/ 结算引擎
        # 无法静态映射的编码,一律跳过,不产生不可结算的脏数据
        if not option_code or odds <= 1.0:
            skipped_count += 1
            continue
        if settlement.resolve_option_label(rec.play_code, option_code) is None:
            logger.warning(
                "AI 推荐选项编码 %s(%s)无法被结算引擎映射,跳过",
                option_code, rec.play_code,
            )
            skipped_count += 1
            continue

        # 去水隐含概率:按该玩法池全部在售选项归一
        pool = next(
            (p for p in pools or [] if p.get("poolCode") == rec.play_code), None
        )
        pool_options = [
            (str(o["code"]), float(o["odds"]))
            for o in (pool or {}).get("options") or []
            if isinstance(o, dict) and str(o.get("code") or "").strip()
        ]
        try:
            implied = plan_analysis.implied_probabilities(pool_options)[option_code]
        except (KeyError, ZeroDivisionError):
            skipped_count += 1
            continue

        confidence = float(rec.confidence)
        pick = AiPick(
            batch_id=batch.batch_id,
            match_id=game.match_id,
            analysis_id=rec.analysis_id,
            play_code=rec.play_code,
            play_name=rec.play_name,
            recommendation=rec.recommendation,
            option_code=option_code,
            option_label=str(matched.get("label") or rec.recommendation),
            odds=odds,
            confidence=confidence,
            implied_prob=implied,
            ev=confidence * odds - 1.0,
            kelly=poisson.kelly_fraction(
                _clamp_kelly_prob(confidence), odds
            ),
            is_contrarian=confidence < implied,
            reasoning=str(rec.reasoning or ""),
        )
        picks.append(pick)
        if game.match_id not in match_info:
            match_info[game.match_id] = (
                game.match_num_str,
                f"{game.home_team.team_name} vs {game.away_team.team_name}",
            )

    session.add_all(picks)
    plans = _build_parlay_plans(batch.batch_id, picks, match_info)
    session.add_all(plans)
    await session.flush()

    batch.pick_count = len(picks)
    batch.skipped_count = skipped_count
    batch.plan_count = len(plans)
    await session.flush()
    return BatchSummary(batch=batch, superseded_batch_ids=superseded_ids)


def _build_parlay_plans(
    batch_id: int,
    picks: list[AiPick],
    match_info: dict[str, tuple[str, str]],
) -> list[AiParlayPlan]:
    """从单场推荐中自动组 2-4 串候选方案。

    腿池:每场仅取 EV 最高代表腿(并列取置信度高),天然满足
    "每场一玩法"串关规则;分层为顺向腿(chalk)与逆向腿(value)。
    固定产出至多 4 个候选(腿不足的档位不硬凑):
    稳胆 2串1 / 稳胆 3串1 / 稳胆 4串1(3 顺向 + 1 逆向)/
    价值混合 2串1(1 顺向 + 1 逆向)。
    硬约束:逆向腿数 ≤ MAX_CONTRARIAN_LEGS(校准规则)。
    组合置信度按腿间独立近似(浅盘日让平存在相关性,见校准教训)。
    """
    # 每场 EV 最高代表腿(EV 并列取置信度高)
    best_by_match: dict[str, AiPick] = {}
    for pick in picks:
        current = best_by_match.get(pick.match_id)
        if current is None or (pick.ev, pick.confidence) > (
            current.ev, current.confidence
        ):
            best_by_match[pick.match_id] = pick
    reps = list(best_by_match.values())
    chalk = sorted(
        (p for p in reps if not p.is_contrarian),
        key=lambda p: (p.confidence, p.ev),
        reverse=True,
    )
    value = sorted(
        (p for p in reps if p.is_contrarian),
        key=lambda p: (p.ev, p.confidence),
        reverse=True,
    )

    drafts: list[tuple[str, str, list[AiPick]]] = []
    if len(chalk) >= 2:
        drafts.append(("稳胆 2串1", "置信度最高的 2 条顺向腿", chalk[:2]))
    if len(chalk) >= 3:
        drafts.append(("稳胆 3串1", "置信度最高的 3 条顺向腿", chalk[:3]))
    if len(chalk) >= 3:
        # 3 顺向 + EV 最高的 1 条逆向;逆向不足时取第 4 条顺向
        legs = chalk[:3] + (value[:1] if value else chalk[3:4])
        if len(legs) >= 4:
            desc = (
                "3 条顺向 + 1 条逆向(价值混合)"
                if value
                else "置信度最高的 4 条顺向腿"
            )
            drafts.append(("稳胆 4串1", desc, legs))
    if chalk and value:
        drafts.append(
            ("价值混合 2串1", "最高 1 条顺向 + EV 最高 1 条逆向", chalk[:1] + value[:1])
        )

    plans: list[AiParlayPlan] = []
    for plan_name, plan_desc, legs in drafts:
        contrarian_count = sum(1 for leg in legs if leg.is_contrarian)
        # 校准规则硬约束:逆向腿 ≤ 2(构建逻辑保证,此处防御性校验)
        if contrarian_count > MAX_CONTRARIAN_LEGS or len(legs) < 2:
            logger.warning(
                "串关候选 %s 构建异常(逆向 %s 条/共 %s 腿),跳过",
                plan_name, contrarian_count, len(legs),
            )
            continue
        combined_odds = math.prod(float(leg.odds) for leg in legs)
        combined_confidence = math.prod(float(leg.confidence) for leg in legs)
        plans.append(
            AiParlayPlan(
                batch_id=batch_id,
                parlay_size=len(legs),
                plan_name=plan_name,
                plan_desc=(
                    f"{plan_desc};腿间独立性为近似口径"
                    "(浅盘日让平存在相关性)"
                ),
                legs=[
                    {
                        "match_id": leg.match_id,
                        "match_num_str": match_info[leg.match_id][0],
                        "match_name": match_info[leg.match_id][1],
                        "play_code": leg.play_code,
                        "play_name": leg.play_name,
                        "option_code": leg.option_code,
                        "option_label": leg.option_label,
                        "odds": float(leg.odds),
                        "confidence": float(leg.confidence),
                        "is_contrarian": bool(leg.is_contrarian),
                    }
                    for leg in legs
                ],
                combined_odds=combined_odds,
                combined_confidence=combined_confidence,
                ev=combined_confidence * combined_odds - 1.0,
                kelly=poisson.kelly_fraction(
                    min(
                        max(combined_confidence, _KELLY_CONF_MIN),
                        _KELLY_CONF_MAX,
                    ),
                    combined_odds,
                ),
                contrarian_count=contrarian_count,
            )
        )
    return plans


async def _latest_active_batch(
    session: AsyncSession, business_date: datetime.date | None
) -> AiPickBatch | None:
    """取指定售卖日(缺省为最近一天)的 ACTIVE 批次。"""
    stmt = select(AiPickBatch).where(AiPickBatch.status == "ACTIVE")
    if business_date is None:
        latest_date = await session.scalar(
            select(func.max(AiPickBatch.business_date)).where(
                AiPickBatch.status == "ACTIVE"
            )
        )
        if latest_date is None:
            return None
        stmt = stmt.where(AiPickBatch.business_date == latest_date)
    else:
        stmt = stmt.where(AiPickBatch.business_date == business_date)
    return await session.scalar(
        stmt.order_by(AiPickBatch.batch_id.desc()).limit(1)
    )


async def list_active_picks(
    session: AsyncSession,
    *,
    business_date: datetime.date | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[AiPick]:
    """查询 ACTIVE 批次的单场推荐清单(含比赛/联赛/主客队信息)。

    Args:
        session: 异步数据库会话。
        business_date: 售卖日,缺省取最近一个 ACTIVE 批次。
        offset: 分页偏移。
        limit: 分页条数上限。

    Returns:
        推荐明细列表,按 EV 倒序、置信度倒序。
    """
    batch = await _latest_active_batch(session, business_date)
    if batch is None:
        return []
    stmt = (
        select(AiPick)
        .where(AiPick.batch_id == batch.batch_id)
        .options(
            joinedload(AiPick.game).joinedload(MatchGame.home_team),
            joinedload(AiPick.game).joinedload(MatchGame.away_team),
            joinedload(AiPick.game).joinedload(MatchGame.league),
        )
        .order_by(AiPick.ev.desc(), AiPick.confidence.desc())
        .offset(offset)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_active_plans(
    session: AsyncSession,
    *,
    business_date: datetime.date | None = None,
) -> list[AiParlayPlan]:
    """查询 ACTIVE 批次的串关候选方案,按场次规模降序。"""
    batch = await _latest_active_batch(session, business_date)
    if batch is None:
        return []
    stmt = (
        select(AiParlayPlan)
        .where(AiParlayPlan.batch_id == batch.batch_id)
        .order_by(
            AiParlayPlan.parlay_size.desc(), AiParlayPlan.plan_id
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def convert_pick_to_decision(
    session: AsyncSession,
    *,
    pick_id: int,
    user_id: int,
    stake_amount: float,
) -> tuple[UserDecision, bool]:
    """将单场推荐转为用户模拟决策(接入结算/复盘闭环)。

    幂等:已转换过的推荐直接返回既有决策(created=False)。
    先建桥接 Recommendation(UserDecision.recommend_id 非空 FK 要求),
    strategy_type 与 user_bet_type 均按结算引擎契约落库。

    Raises:
        ResourceNotFoundError: 推荐不存在。
        DataValidationError: 批次已失效、比赛已开赛或玩法编码非法。
    """
    # 行锁串行化并发的重复转换:后到事务阻塞等待,提交后读到
    # 已回填的 decision_id,直接返回既有决策(SQLite 忽略 FOR UPDATE)
    pick = (
        await session.execute(
            select(AiPick).where(AiPick.pick_id == pick_id).with_for_update()
        )
    ).scalar_one_or_none()
    if pick is None:
        raise ResourceNotFoundError("AI 推荐", str(pick_id))
    if pick.decision_id is not None:
        decision = await session.get(UserDecision, pick.decision_id)
        if decision is not None:
            return decision, False
    batch = await session.get(AiPickBatch, pick.batch_id)
    if batch is None or batch.status != "ACTIVE":
        raise DataValidationError("该推荐所属批次已被重算取代,请刷新后重新选择")
    game = await session.get(MatchGame, pick.match_id)
    if game is None or game.match_status != MatchStatus.PENDING:
        raise DataValidationError("比赛已开赛或完赛,无法转换")

    strategy_type = POOL_TO_STRATEGY.get(pick.play_code)
    if strategy_type is None:
        raise DataValidationError(f"玩法编码非法: {pick.play_code}")

    # 桥接推荐:与用户自选流同构,复盘侧通过 logic_tags 区分来源
    recommendation = Recommendation(
        match_id=pick.match_id,
        strategy_type=strategy_type,
        predicted_outcome=pick.option_label,
        confidence_score=round(float(pick.confidence), 2),
        logic_tags=[AI_PICK_TAG, pick.play_name],
    )
    session.add(recommendation)
    await session.flush()

    decision = UserDecision(
        user_id=user_id,
        recommend_id=recommendation.recommend_id,
        user_bet_type=f"{pick.play_code}:{pick.option_code}",
        stake_amount=stake_amount,
    )
    session.add(decision)
    await session.flush()

    pick.decision_id = decision.decision_id
    await session.flush()
    return decision, True


async def convert_plan_to_scheme(
    session: AsyncSession,
    *,
    plan_id: int,
    user_id: int,
    stake_per_bet: float,
) -> tuple[BetScheme, bool]:
    """将串关候选方案保存为正式模拟串关方案(幂等)。

    候选腿经 parlay.save_bet_scheme 物化(每场一玩法/注数校验全复用),
    BetSchemeItem 持有勾选时点的赔率快照。

    Raises:
        ResourceNotFoundError: 方案不存在。
        DataValidationError: 批次已失效或任一腿比赛已开赛。
    """
    # 行锁串行化并发的重复保存(与单场转换同口径,SQLite 忽略 FOR UPDATE)
    plan = (
        await session.execute(
            select(AiParlayPlan)
            .where(AiParlayPlan.plan_id == plan_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if plan is None:
        raise ResourceNotFoundError("串关候选方案", str(plan_id))
    if plan.scheme_id is not None:
        # 幂等路径:既有方案需带明细一起加载,响应序列化不做懒加载 IO
        scheme = await session.scalar(
            select(BetScheme)
            .options(selectinload(BetScheme.items))
            .where(BetScheme.scheme_id == plan.scheme_id)
        )
        if scheme is not None:
            return scheme, False
    batch = await session.get(AiPickBatch, plan.batch_id)
    if batch is None or batch.status != "ACTIVE":
        raise DataValidationError("该方案所属批次已被重算取代,请刷新后重新选择")

    legs = [leg for leg in plan.legs or [] if isinstance(leg, dict)]
    if len(legs) != plan.parlay_size:
        raise DataValidationError("候选方案腿数据异常,请重新生成推荐")
    match_ids = [str(leg["match_id"]) for leg in legs]
    pending_ids = set(
        (
            await session.execute(
                select(MatchGame.match_id).where(
                    MatchGame.match_id.in_(match_ids),
                    MatchGame.match_status == MatchStatus.PENDING,
                )
            )
        )
        .scalars()
        .all()
    )
    not_pending = [mid for mid in match_ids if mid not in pending_ids]
    if not_pending:
        raise DataValidationError(
            f"存在已开赛/完赛的腿,无法保存: {', '.join(not_pending)}"
        )

    picks = [
        ParlayPick(
            match_id=str(leg["match_id"]),
            match_name=str(leg["match_name"]),
            pool_code=str(leg["play_code"]),
            play_name=str(leg["play_name"]),
            option_code=str(leg["option_code"]),
            option_label=str(leg["option_label"]),
            odds=float(leg["odds"]),
        )
        for leg in legs
    ]
    scheme = await parlay.save_bet_scheme(
        session, user_id, plan.parlay_size, stake_per_bet, picks
    )
    plan.scheme_id = scheme.scheme_id
    await session.flush()
    return scheme, True
