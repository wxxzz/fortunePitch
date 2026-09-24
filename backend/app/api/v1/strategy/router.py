"""策略与赔率模块路由:三张表 CRUD + 凯利指数计算。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.strategy.schemas import (
    BetSchemeCreate,
    BetSchemeRead,
    DimensionStatRead,
    OddsHistoryCreate,
    OddsHistoryRead,
    PlanAnalysisRead,
    PlanAnalysisRequest,
    ProfitPointRead,
    RecommendationCreate,
    RecommendationRead,
    ReviewDecisionRead,
    ReviewKpiRead,
    ReviewStatsRead,
    SelectionAnalysisRead,
    SettlementRequest,
    SettlementResultRead,
    UserDecisionCreate,
    UserDecisionRead,
    UserDecisionsBatchCreate,
    UserDecisionsBatchResult,
    STRATEGY_TYPES,
    KellyRequest,
    KellyResponse,
)
from app.core.database import get_db_session
from app.core.exceptions import DataValidationError
from app.core.security import verify_api_key
from app.models import (
    BetScheme,
    DecisionStatus,
    MatchGame,
    OddsHistory,
    Recommendation,
    UserDecision,
)
from app.services import crud, plan_analysis, review, settlement
from app.services.parlay import ParlayPick, list_bet_schemes, save_bet_scheme
from app.services.poisson import kelly_fraction
from app.services.user_picks import UserPick, create_user_picks

router = APIRouter(
    prefix="/strategy", tags=["strategy"], dependencies=[Depends(verify_api_key)]
)


# ---------- 赔率历史 /odds-history ----------

@router.post(
    "/odds-history", response_model=OddsHistoryRead, status_code=status.HTTP_201_CREATED
)
async def create_odds_record(
    payload: OddsHistoryCreate, session: AsyncSession = Depends(get_db_session)
) -> OddsHistory:
    """录入一条赔率快照。"""
    await crud.get_entity(session, MatchGame, payload.match_id)
    return await crud.create_entity(session, OddsHistory, payload.model_dump())


@router.get("/odds-history", response_model=list[OddsHistoryRead])
async def list_odds_records(
    match_id: str | None = Query(default=None, description="按比赛过滤"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[OddsHistory]:
    """分页查询赔率快照,可按比赛过滤,按更新时间升序。"""
    stmt = select(OddsHistory).offset(offset).limit(limit)
    if match_id is not None:
        stmt = stmt.where(OddsHistory.match_id == match_id)
    stmt = stmt.order_by(OddsHistory.update_time)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.delete(
    "/odds-history/{odds_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_odds_record(
    odds_id: int, session: AsyncSession = Depends(get_db_session)
) -> None:
    """删除赔率快照。"""
    await crud.delete_entity(session, OddsHistory, odds_id)


# ---------- 策略推荐 /recommendations ----------

@router.post(
    "/recommendations",
    response_model=RecommendationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_recommendation(
    payload: RecommendationCreate, session: AsyncSession = Depends(get_db_session)
) -> Recommendation:
    """录入一条 AI 策略推荐(含归因标签)。"""
    if payload.strategy_type not in STRATEGY_TYPES:
        raise DataValidationError(
            f"策略类型必须是 {STRATEGY_TYPES} 之一: {payload.strategy_type}"
        )
    await crud.get_entity(session, MatchGame, payload.match_id)
    return await crud.create_entity(session, Recommendation, payload.model_dump())


@router.get("/recommendations", response_model=list[RecommendationRead])
async def list_recommendations(
    match_id: str | None = Query(default=None, description="按比赛过滤"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[Recommendation]:
    """分页查询策略推荐,可按比赛过滤,按生成时间倒序。"""
    stmt = select(Recommendation).offset(offset).limit(limit)
    if match_id is not None:
        stmt = stmt.where(Recommendation.match_id == match_id)
    stmt = stmt.order_by(Recommendation.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.delete(
    "/recommendations/{recommend_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_recommendation(
    recommend_id: int, session: AsyncSession = Depends(get_db_session)
) -> None:
    """删除策略推荐。"""
    await crud.delete_entity(session, Recommendation, recommend_id)


# ---------- 用户决策(模拟)/user-decisions ----------

@router.post(
    "/user-decisions",
    response_model=UserDecisionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_user_decision(
    payload: UserDecisionCreate, session: AsyncSession = Depends(get_db_session)
) -> UserDecision:
    """录入用户模拟决策(用于复盘与战绩统计,不涉及真实资金)。"""
    await crud.get_entity(session, Recommendation, payload.recommend_id)
    return await crud.create_entity(session, UserDecision, payload.model_dump())


@router.post(
    "/user-decisions/batch",
    response_model=UserDecisionsBatchResult,
    status_code=status.HTTP_201_CREATED,
    summary="批量创建用户自选模拟决策",
)
async def create_user_decisions_batch(
    payload: UserDecisionsBatchCreate, session: AsyncSession = Depends(get_db_session)
) -> UserDecisionsBatchResult:
    """赛事中心自选玩法确认入口:逐条创建模拟决策。

    每条自选会先生成一条 confidence_score=0 的"用户自选"推荐记录
    (决策表外键依赖),再创建对应的模拟决策。
    """
    decisions = await create_user_picks(
        session,
        user_id=payload.user_id,
        stake_amount=payload.stake_amount,
        picks=[
            UserPick(
                match_id=s.match_id,
                pool_code=s.pool_code,
                option_code=s.option_code,
                option_label=s.option_label,
            )
            for s in payload.selections
        ],
    )
    return UserDecisionsBatchResult(
        decision_count=len(decisions),
        decisions=[
            UserDecisionRead.model_validate(decision) for decision in decisions
        ],
    )


@router.get("/user-decisions", response_model=list[UserDecisionRead])
async def list_user_decisions(
    user_id: int | None = Query(default=None, description="按用户过滤"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[UserDecision]:
    """分页查询用户决策,可按用户过滤。"""
    stmt = select(UserDecision).offset(offset).limit(limit)
    if user_id is not None:
        stmt = stmt.where(UserDecision.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.delete(
    "/user-decisions/{decision_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_user_decision(
    decision_id: int, session: AsyncSession = Depends(get_db_session)
) -> None:
    """删除用户决策。"""
    await crud.delete_entity(session, UserDecision, decision_id)


# ---------- 串关虚拟投注方案 /bet-schemes ----------

@router.post(
    "/bet-schemes",
    response_model=BetSchemeRead,
    status_code=status.HTTP_201_CREATED,
    summary="保存串关虚拟投注方案",
)
async def create_bet_scheme(
    payload: BetSchemeCreate, session: AsyncSession = Depends(get_db_session)
) -> BetScheme:
    """赛事中心串关确认入口:校验组合规则并保存方案。

    服务端按竞彩串关口径计算注数/总投入/单注最高赔率,
    注额为模拟数据,仅用于复盘,不涉及真实资金。
    """
    return await save_bet_scheme(
        session,
        user_id=payload.user_id,
        parlay_size=payload.parlay_size,
        stake_per_bet=payload.stake_per_bet,
        picks=[
            ParlayPick(
                match_id=i.match_id,
                match_name=i.match_name,
                pool_code=i.pool_code,
                play_name=i.play_name,
                option_code=i.option_code,
                option_label=i.option_label,
                odds=i.odds,
            )
            for i in payload.items
        ],
    )


@router.get("/bet-schemes", response_model=list[BetSchemeRead])
async def list_schemes(
    user_id: int | None = Query(default=None, description="按用户过滤"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """分页查询串关虚拟投注方案,可按用户过滤,按创建时间倒序。

    响应附加读时计算的逐腿赛果/命中与方案盈亏
    (盈亏不落库,每次查询实时结算)。
    """
    schemes = await list_bet_schemes(
        session, user_id=user_id, offset=offset, limit=limit
    )
    annotations = await settlement.load_scheme_annotations(session, schemes)
    payloads: list[dict] = []
    for scheme in schemes:
        annotation = annotations[scheme.scheme_id]
        item_hits: dict[int, tuple[str | None, bool | None]] = annotation["items"]
        payloads.append(
            {
                "scheme_id": scheme.scheme_id,
                "user_id": scheme.user_id,
                "parlay_size": scheme.parlay_size,
                "stake_per_bet": scheme.stake_per_bet,
                "bet_count": scheme.bet_count,
                "total_stake": scheme.total_stake,
                "max_odds": scheme.max_odds,
                "status": scheme.status,
                "created_at": scheme.created_at,
                "profit_loss": annotation["profit_loss"],
                "items": [
                    {
                        "item_id": item.item_id,
                        "match_id": item.match_id,
                        "match_name": item.match_name,
                        "pool_code": item.pool_code,
                        "play_name": item.play_name,
                        "option_code": item.option_code,
                        "option_label": item.option_label,
                        "odds": item.odds,
                        "result_label": item_hits[item.item_id][0],
                        "is_hit": item_hits[item.item_id][1],
                    }
                    for item in scheme.items
                ],
            }
        )
    return payloads


# ---------- 投注方案分析 /plan-analysis ----------

@router.post(
    "/plan-analysis",
    response_model=PlanAnalysisRead,
    status_code=status.HTTP_200_OK,
    summary="投注方案分析(中奖概率与期望值)",
)
async def analyze_bet_plan(
    payload: PlanAnalysisRequest, session: AsyncSession = Depends(get_db_session)
) -> PlanAnalysisRead:
    """基于赔率隐含概率(去水归一)分析投注方案,不落库。

    逐条选注输出隐含概率/公平赔率/单位期望/凯利比例;整体输出方案
    中奖概率与期望值:单关按各注独立结算,串关/混合按 N串1 组合口径
    (复式多选项)。赔率优先取库中当前在售值,勾选时点赔率兜底。
    注额为模拟数据,结果不构成投注建议。

    Raises:
        DataValidationError: 参数非法或选注不满足串关规则(422)。
    """
    picks = [
        ParlayPick(
            match_id=item.match_id,
            match_name=item.match_name,
            pool_code=item.pool_code,
            play_name=item.play_name,
            option_code=item.option_code,
            option_label=item.option_label,
            odds=item.odds,
        )
        for item in payload.selections
    ]
    result = await plan_analysis.analyze_plan(
        session,
        picks,
        payload.mode,
        payload.parlay_size,
        payload.stake_per_bet,
    )
    return PlanAnalysisRead(
        probability_source="implied",
        mode=result.mode,
        selections=[
            SelectionAnalysisRead.model_validate(a) for a in result.selections
        ],
        bet_count=result.bet_count,
        total_stake=result.total_stake,
        max_odds=result.max_odds,
        win_prob=result.win_prob,
        expected_return=result.expected_return,
        expected_value=result.expected_value,
        ev_pct=result.ev_pct,
    )


# ---------- 复盘结算 /settlement ----------

@router.post(
    "/settlement",
    response_model=SettlementResultRead,
    status_code=status.HTTP_200_OK,
    summary="复盘结算(按赛果判定输赢并计算盈亏)",
)
async def run_settlement(
    payload: SettlementRequest, session: AsyncSession = Depends(get_db_session)
) -> SettlementResultRead:
    """结算引擎入口:结算待结算的单关决策与串关方案。

    幂等:已结算记录不重复处理;未开奖/赔率不可解析的保持待结算。
    复盘页加载时自动触发,也可通过「立即结算」手动调用。
    """
    result = await settlement.run_settlement(session, payload.user_id)
    return SettlementResultRead(
        decision_wins=result.decision_wins,
        decision_losses=result.decision_losses,
        scheme_wins=result.scheme_wins,
        scheme_losses=result.scheme_losses,
    )


# ---------- 复盘统计 /review ----------

@router.get(
    "/review/stats",
    response_model=ReviewStatsRead,
    summary="复盘统计聚合(KPI/盈亏曲线/维度分析)",
)
async def get_review_stats(
    user_id: int | None = Query(default=None, description="按用户过滤"),
    session: AsyncSession = Depends(get_db_session),
) -> ReviewStatsRead:
    """聚合某用户的复盘统计:核心指标、盈亏曲线与维度分析。"""
    stats = await review.review_stats(session, user_id)
    return ReviewStatsRead(
        kpi=ReviewKpiRead(**stats.kpi._asdict()),
        profit_curve=[
            ProfitPointRead(label=p.label, cumulative_profit=p.cumulative_profit)
            for p in stats.profit_curve
        ],
        by_play=[
            DimensionStatRead(**d._asdict()) for d in stats.by_play
        ],
        by_odds_range=[
            DimensionStatRead(**d._asdict()) for d in stats.by_odds_range
        ],
        by_league=[
            DimensionStatRead(**d._asdict()) for d in stats.by_league
        ],
    )


@router.get(
    "/review/decisions",
    response_model=list[ReviewDecisionRead],
    summary="复盘单关决策富明细",
)
async def list_review_decisions(
    user_id: int | None = Query(default=None, description="按用户过滤"),
    result_status: DecisionStatus | None = Query(
        default=None, description="按结算状态过滤:WIN/LOSS/PUSH"
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[ReviewDecisionRead]:
    """查询单关决策富明细(赛事/玩法/选项/赔率/赛果/盈亏联表)。"""
    rows = await review.list_review_decisions(
        session,
        user_id=user_id,
        result_status=result_status,
        offset=offset,
        limit=limit,
    )
    return [ReviewDecisionRead(**row._asdict()) for row in rows]


# ---------- 凯利指数 /kelly ----------

@router.post(
    "/kelly",
    response_model=KellyResponse,
    status_code=status.HTTP_200_OK,
    summary="凯利指数计算",
)
async def calculate_kelly(request: KellyRequest) -> KellyResponse:
    """衡量市场赔率与模型预测概率的偏差,输出建议资金比例。

    本接口仅用于量化分析与教学演示,不构成任何投注建议。
    """
    return KellyResponse(
        kelly_fraction=kelly_fraction(
            model_prob=request.model_prob,
            decimal_odds=request.decimal_odds,
        )
    )
