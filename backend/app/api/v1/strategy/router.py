"""策略与赔率模块路由:三张表 CRUD + 凯利指数计算。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.strategy.schemas import (
    OddsHistoryCreate,
    OddsHistoryRead,
    RecommendationCreate,
    RecommendationRead,
    UserDecisionCreate,
    UserDecisionRead,
    STRATEGY_TYPES,
    KellyRequest,
    KellyResponse,
)
from app.core.database import get_db_session
from app.core.exceptions import DataValidationError
from app.core.security import verify_api_key
from app.models import MatchGame, OddsHistory, Recommendation, UserDecision
from app.services import crud
from app.services.poisson import kelly_fraction

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
    "/user-decisions", response_model=UserDecisionRead, status_code=status.HTTP_201_CREATED
)
async def create_user_decision(
    payload: UserDecisionCreate, session: AsyncSession = Depends(get_db_session)
) -> UserDecision:
    """录入用户模拟决策(用于复盘与战绩统计,不涉及真实资金)。"""
    await crud.get_entity(session, Recommendation, payload.recommend_id)
    return await crud.create_entity(session, UserDecision, payload.model_dump())


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
