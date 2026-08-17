"""比赛分析相关接口:泊松比分预测与凯利指数计算。"""

from fastapi import APIRouter, Depends, status

from app.api.v1.schemas import (
    KellyRequest,
    KellyResponse,
    MatchProbabilities,
    PoissonPredictRequest,
    PoissonPredictResponse,
    ScoreProbability,
)
from app.core.security import verify_api_key
from app.services.poisson import kelly_fraction, predict_score_grid

router = APIRouter(prefix="/analysis", tags=["analysis"], dependencies=[Depends(verify_api_key)])

# 响应中展示的 Top 比分数量
TOP_SCORES_LIMIT: int = 5


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
    top_scores = sorted(flat_scores, key=lambda s: s.probability, reverse=True)[:TOP_SCORES_LIMIT]

    return PoissonPredictResponse(
        probabilities=MatchProbabilities(
            home_win=grid_result.home_win_prob,
            draw=grid_result.draw_prob,
            away_win=grid_result.away_win_prob,
        ),
        top_scores=top_scores,
        total_goals_expected=grid_result.total_goals_expected,
    )


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
