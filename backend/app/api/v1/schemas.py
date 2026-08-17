"""API v1 Pydantic 请求/响应模型。

所有外部输入输出必须经由本模块的 Schema 校验,
禁止在业务逻辑中直接使用原生 dict。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiEnvelope(BaseModel):
    """统一 API 响应封装。"""

    success: bool = True
    data: BaseModel | list[BaseModel] | None = None
    error: dict[str, str] | None = None


class MatchBrief(BaseModel):
    """比赛简要信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    league: str
    kickoff_at: datetime
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int


class PoissonPredictRequest(BaseModel):
    """Dixon-Coles 泊松预测请求体。"""

    home_xg: float = Field(gt=0, le=10, description="主队期望进球(来自 xG 聚合)")
    away_xg: float = Field(gt=0, le=10, description="客队期望进球(来自 xG 聚合)")
    rho: float = Field(default=-0.10, ge=-0.2, le=0.2, description="Dixon-Coles 相关系数")


class MatchProbabilities(BaseModel):
    """胜平负概率预测结果。"""

    home_win: float = Field(ge=0, le=1)
    draw: float = Field(ge=0, le=1)
    away_win: float = Field(ge=0, le=1)


class ScoreProbability(BaseModel):
    """单个比分的概率。"""

    home_goals: int
    away_goals: int
    probability: float = Field(ge=0, le=1)


class PoissonPredictResponse(BaseModel):
    """Dixon-Coles 泊松预测响应。"""

    probabilities: MatchProbabilities
    top_scores: list[ScoreProbability] = Field(description="概率最高的前 5 个比分")
    total_goals_expected: float


class KellyRequest(BaseModel):
    """凯利指数计算请求体。"""

    model_prob: float = Field(gt=0, lt=1, description="模型预测概率")
    decimal_odds: float = Field(gt=1, description="欧洲十进制赔率")


class KellyResponse(BaseModel):
    """凯利指数计算响应。"""

    kelly_fraction: float = Field(ge=0, description="建议资金比例,0 表示无正期望价值")
