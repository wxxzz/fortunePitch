"""高阶数据分析模块 Pydantic Schema:球队指标 / 球员表现 / 泊松预测。"""

from pydantic import BaseModel, ConfigDict, Field


# ---------- 球队高阶指标 ----------

class TeamStatCreate(BaseModel):
    """创建球队单场指标请求体。"""

    match_id: str = Field(max_length=64)
    team_id: int
    xg: float | None = Field(default=None, ge=0, le=20, description="预期进球 xG")
    xga: float | None = Field(default=None, ge=0, le=20, description="预期失球 xGA")
    possession: float | None = Field(default=None, ge=0, le=100, description="控球率(%)")
    shot_accuracy: float | None = Field(default=None, ge=0, le=100)
    ppda: float | None = Field(default=None, ge=0, le=30, description="防守压迫指数")


class TeamStatRead(BaseModel):
    """球队单场指标响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    stat_id: int
    match_id: str
    team_id: int
    xg: float | None
    xga: float | None
    possession: float | None
    shot_accuracy: float | None
    ppda: float | None


# ---------- 球员单场表现 ----------

class PlayerStatCreate(BaseModel):
    """创建球员单场表现请求体。"""

    match_id: str = Field(max_length=64)
    player_id: int
    minutes_played: int | None = Field(default=None, ge=0, le=130)
    goals: int = Field(default=0, ge=0)
    assists: int = Field(default=0, ge=0)
    key_passes: int = Field(default=0, ge=0)
    rating: float | None = Field(default=None, ge=0, le=10)


class PlayerStatRead(BaseModel):
    """球员单场表现响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    performance_id: int
    match_id: str
    player_id: int
    minutes_played: int | None
    goals: int
    assists: int
    key_passes: int
    rating: float | None


# ---------- 泊松预测 ----------

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
