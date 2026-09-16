"""策略与赔率模块 Pydantic Schema:赔率历史 / 推荐记录 / 用户决策 / 凯利。"""

import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import DecisionStatus

# 允许的策略类型与玩法取值
STRATEGY_TYPES = ("WIN_DRAW_LOSS", "HANDICAP", "SCORE")
# 用户自选决策允许的玩法编码(与竞彩玩法对应,宽于 STRATEGY_TYPES)
USER_PICK_POOL_CODES = ("HAD", "HHAD", "CRS", "TTG", "HAFU")


# ---------- 赔率与盘口 ----------

class OddsHistoryCreate(BaseModel):
    """创建赔率记录请求体。"""

    match_id: str = Field(max_length=64)
    bookmaker: str = Field(max_length=64)
    market_type: str = Field(
        max_length=32, description="ASIAN_HANDICAP / EURO_ODDS / OVER_UNDER"
    )
    initial_value: float = Field(gt=0, description="初盘水位/赔率")
    current_value: float = Field(gt=0, description="即时水位/赔率")
    update_time: datetime.datetime


class OddsHistoryRead(BaseModel):
    """赔率记录响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    odds_id: int
    match_id: str
    bookmaker: str
    market_type: str
    initial_value: float
    current_value: float
    update_time: datetime.datetime


# ---------- 策略推荐 ----------

class RecommendationCreate(BaseModel):
    """创建策略推荐请求体。"""

    match_id: str = Field(max_length=64)
    strategy_type: str = Field(description="WIN_DRAW_LOSS / HANDICAP / SCORE")
    predicted_outcome: str = Field(max_length=64)
    confidence_score: float = Field(ge=0, le=1, description="模型置信度 0.00-1.00")
    logic_tags: list[str] | None = Field(
        default=None, description='推导逻辑标签,如 ["核心缺阵","盘口浅开"]'
    )


class RecommendationRead(BaseModel):
    """策略推荐响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    recommend_id: int
    match_id: str
    strategy_type: str
    predicted_outcome: str
    confidence_score: float
    logic_tags: list[str] | None
    created_at: datetime.datetime


# ---------- 用户决策(模拟) ----------

class UserDecisionCreate(BaseModel):
    """创建用户决策请求体(注额为模拟数据,仅用于复盘统计)。"""

    user_id: int
    recommend_id: int
    user_bet_type: str = Field(max_length=32)
    stake_amount: float = Field(gt=0, le=10_000, description="模拟注额")
    result_status: DecisionStatus = DecisionStatus.PUSH
    profit_loss: float | None = None


class UserDecisionRead(BaseModel):
    """用户决策响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    decision_id: int
    user_id: int
    recommend_id: int
    user_bet_type: str
    stake_amount: float
    result_status: DecisionStatus
    profit_loss: float | None


class UserPickSelection(BaseModel):
    """批量模拟决策中的单条自选。"""

    match_id: str = Field(max_length=64, description="比赛编号")
    pool_code: str = Field(
        description="玩法编码:HAD/HHAD/CRS/TTG/HAFU", examples=["HAD"]
    )
    option_code: str = Field(max_length=16, description="选项编码,如 h / s01s02", examples=["h"])
    option_label: str = Field(max_length=32, description="选项展示名,如 主胜", examples=["主胜"])


class UserDecisionsBatchCreate(BaseModel):
    """批量创建用户模拟决策请求体(赛事中心自选玩法确认)。"""

    user_id: int
    stake_amount: float = Field(gt=0, le=10_000, description="每条自选的模拟注额")
    selections: list[UserPickSelection] = Field(min_length=1, max_length=20)


class UserDecisionsBatchResult(BaseModel):
    """批量创建用户模拟决策结果。"""

    decision_count: int = Field(description="创建的决策条数")
    decisions: list[UserDecisionRead]


# ---------- 凯利指数 ----------

class KellyRequest(BaseModel):
    """凯利指数计算请求体。"""

    # model_prob 中的 "model_" 前缀与 Pydantic 保护命名空间冲突,显式关闭
    model_config = ConfigDict(protected_namespaces=())

    model_prob: float = Field(gt=0, lt=1, description="模型预测概率")
    decimal_odds: float = Field(gt=1, description="欧洲十进制赔率")


class KellyResponse(BaseModel):
    """凯利指数计算响应。"""

    kelly_fraction: float = Field(ge=0, description="建议资金比例,0 表示无正期望价值")


# ---------- 串关虚拟投注方案 /bet-schemes ----------

class BetSchemeItemCreate(BaseModel):
    """串关方案中的单条选注(勾选时点快照)。"""

    match_id: str = Field(max_length=64, description="比赛编号")
    match_name: str = Field(max_length=128, description="对阵快照,如 巴塞罗那 vs 皇家马德里")
    pool_code: str = Field(max_length=8, description="玩法编码:HAD/HHAD/CRS/TTG/HAFU")
    play_name: str = Field(max_length=16, description="玩法名称,如 胜平负")
    option_code: str = Field(max_length=16, description="选项编码,如 h / s01s02")
    option_label: str = Field(max_length=32, description="选项展示名,如 主胜")
    odds: float = Field(gt=0, le=1_000, description="勾选时点赔率快照")


class BetSchemeCreate(BaseModel):
    """创建串关虚拟投注方案请求体。

    注数与单注最高赔率由服务端按串关组合规则计算,
    不信任前端上传值。
    """

    user_id: int
    parlay_size: int = Field(ge=2, le=8, description="N串1 的 N,如 2串1 / 3串1")
    stake_per_bet: float = Field(gt=0, le=10_000, description="每注模拟注额")
    items: list[BetSchemeItemCreate] = Field(min_length=2, max_length=30)


class BetSchemeItemRead(BaseModel):
    """串关方案选注明细响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    item_id: int
    match_id: str
    match_name: str
    pool_code: str
    play_name: str
    option_code: str
    option_label: str
    odds: float


class BetSchemeRead(BaseModel):
    """串关虚拟投注方案响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    scheme_id: int
    user_id: int
    parlay_size: int
    stake_per_bet: float
    bet_count: int
    total_stake: float
    max_odds: float | None
    status: str
    created_at: datetime.datetime
    items: list[BetSchemeItemRead]
