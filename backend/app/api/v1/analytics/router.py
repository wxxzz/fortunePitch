"""高阶数据分析模块路由:球队指标 / 球员表现 CRUD + 泊松比分预测。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.analytics.schemas import (
    PlayerStatCreate,
    PlayerStatRead,
    PoissonPredictRequest,
    PoissonPredictResponse,
    MatchProbabilities,
    ScoreProbability,
    TeamStatCreate,
    TeamStatRead,
)
from app.core.database import get_db_session
from app.core.security import verify_api_key
from app.models import MatchGame, PlayerMatchPerformance, TeamMatchStat
from app.services import crud
from app.services.poisson import predict_score_grid

router = APIRouter(
    prefix="/analytics", tags=["analytics"], dependencies=[Depends(verify_api_key)]
)

# 泊松预测响应中展示的 Top 比分数量
TOP_SCORES_LIMIT: int = 5


# ---------- 球队指标 /team-stats ----------

@router.post("/team-stats", response_model=TeamStatRead, status_code=status.HTTP_201_CREATED)
async def create_team_stat(
    payload: TeamStatCreate, session: AsyncSession = Depends(get_db_session)
) -> TeamMatchStat:
    """录入球队单场高阶指标。"""
    await crud.get_entity(session, MatchGame, payload.match_id)
    return await crud.create_entity(session, TeamMatchStat, payload.model_dump())


@router.get("/team-stats", response_model=list[TeamStatRead])
async def list_team_stats(
    match_id: str | None = Query(default=None, description="按比赛过滤"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[TeamMatchStat]:
    """分页查询球队高阶指标,可按比赛过滤。"""
    stmt = select(TeamMatchStat).offset(offset).limit(limit)
    if match_id is not None:
        stmt = stmt.where(TeamMatchStat.match_id == match_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.delete("/team-stats/{stat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team_stat(
    stat_id: int, session: AsyncSession = Depends(get_db_session)
) -> None:
    """删除球队指标记录。"""
    await crud.delete_entity(session, TeamMatchStat, stat_id)


# ---------- 球员表现 /player-stats ----------

@router.post(
    "/player-stats", response_model=PlayerStatRead, status_code=status.HTTP_201_CREATED
)
async def create_player_stat(
    payload: PlayerStatCreate, session: AsyncSession = Depends(get_db_session)
) -> PlayerMatchPerformance:
    """录入球员单场表现。"""
    await crud.get_entity(session, MatchGame, payload.match_id)
    return await crud.create_entity(session, PlayerMatchPerformance, payload.model_dump())


@router.get("/player-stats", response_model=list[PlayerStatRead])
async def list_player_stats(
    match_id: str | None = Query(default=None, description="按比赛过滤"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[PlayerMatchPerformance]:
    """分页查询球员单场表现,可按比赛过滤。"""
    stmt = select(PlayerMatchPerformance).offset(offset).limit(limit)
    if match_id is not None:
        stmt = stmt.where(PlayerMatchPerformance.match_id == match_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.delete(
    "/player-stats/{performance_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_player_stat(
    performance_id: int, session: AsyncSession = Depends(get_db_session)
) -> None:
    """删除球员表现记录。"""
    await crud.delete_entity(session, PlayerMatchPerformance, performance_id)


# ---------- 泊松预测 /poisson ----------

@router.post(
    "/poisson",
    response_model=PoissonPredictResponse,
    status_code=status.HTTP_200_OK,
    summary="Dixon-Coles 泊松比分预测",
)
async def predict_by_poisson(request: PoissonPredictRequest) -> PoissonPredictResponse:
    """基于主客队期望进球(xG)预测比分分布与胜平负概率。"""
    grid_result = predict_score_grid(
        lam=request.home_xg,
        mu=request.away_xg,
        rho=request.rho,
    )

    flat_scores = [
        ScoreProbability(home_goals=i, away_goals=j, probability=grid_result.grid[i][j])
        for i in range(len(grid_result.grid))
        for j in range(len(grid_result.grid[i]))
    ]
    top_scores = sorted(flat_scores, key=lambda s: s.probability, reverse=True)[
        :TOP_SCORES_LIMIT
    ]

    return PoissonPredictResponse(
        probabilities=MatchProbabilities(
            home_win=grid_result.home_win_prob,
            draw=grid_result.draw_prob,
            away_win=grid_result.away_win_prob,
        ),
        top_scores=top_scores,
        total_goals_expected=grid_result.total_goals_expected,
    )
