"""比赛与赛果模块 Pydantic Schema:比赛 / 事件。"""

import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import MatchStatus


# ---------- 比赛 ----------

class MatchGameCreate(BaseModel):
    """创建比赛请求体。"""

    match_id: str = Field(max_length=64, description="比赛全局唯一标识(外部数据源)")
    league_id: int
    home_team_id: int
    away_team_id: int
    referee_id: int | None = None
    match_time: datetime.datetime
    business_date: datetime.date | None = Field(
        default=None, description="竞彩售卖日(次日凌晨开赛归属前一售卖日)"
    )
    match_status: MatchStatus = MatchStatus.PENDING
    home_score: int | None = Field(default=None, ge=0)
    away_score: int | None = Field(default=None, ge=0)


class MatchOddsOptionRead(BaseModel):
    """玩法选项响应模型。"""

    code: str = Field(description="选项编码,如 h / s01s02 / hh")
    label: str = Field(description="选项展示名,如 主胜 / 1:2 / 胜胜")
    odds: float = Field(description="十进制赔率")


class MatchOddsPoolRead(BaseModel):
    """单种玩法赔率响应模型。"""

    poolCode: str = Field(description="玩法编码:HAD/HHAD/CRS/TTG/HAFU")
    playName: str = Field(description="玩法展示名:胜平负/让球胜平负/比分/总进球/半全场")
    goalLine: str | None = Field(default=None, description="让球盘口(仅让球玩法)")
    options: list[MatchOddsOptionRead] = Field(description="选项与赔率列表")


class MatchOddsRead(BaseModel):
    """比赛玩法赔率响应模型。"""

    match_id: str
    pools: list[MatchOddsPoolRead] = Field(description="已开售玩法列表")
    update_time: datetime.datetime


class MatchOddsSnapshotRead(BaseModel):
    """比赛赔率快照响应模型(采集同步留存的历史时点)。"""

    model_config = ConfigDict(from_attributes=True)

    snapshot_id: int = Field(description="快照记录 ID")
    match_id: str
    pools: list[MatchOddsPoolRead] = Field(description="快照时点的玩法与赔率")
    snapshot_time: datetime.datetime = Field(description="快照采集时间")


class MatchGameRead(BaseModel):
    """比赛响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    match_id: str
    league_id: int
    home_team_id: int
    away_team_id: int
    referee_id: int | None
    match_time: datetime.datetime
    business_date: datetime.date | None
    match_status: MatchStatus
    home_score: int | None
    away_score: int | None
    # 竞彩在售玩法赔率(未同步或未开售时为空)
    odds: MatchOddsRead | None = None


class MatchScoreUpdate(BaseModel):
    """更新比分请求体(完赛录入)。"""

    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)


# ---------- 大模型分析 ----------

class LlmPlayRecommendationRead(BaseModel):
    """单种玩法推荐方案响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    play_code: str = Field(description="玩法编码:HAD/HHAD/CRS/TTG/HAFU")
    play_name: str = Field(description="玩法展示名,如 胜平负")
    recommendation: str = Field(description="推荐选项,如 主胜 / 1:2 / 3球 / 胜胜")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度,0~1")
    reasoning: str = Field(description="推荐理由")
    alternatives: list[str] = Field(default_factory=list, description="次选选项")


class LlmAnalysisRead(BaseModel):
    """大模型分析结果响应模型(整体研判 + 分玩法推荐 + 风险提示)。"""

    model_config = ConfigDict(from_attributes=True)

    analysis_id: int = Field(description="分析记录 ID(落库主键)")
    match_id: str
    provider: str = Field(description="服务商:qwen / ark")
    model: str = Field(description="实际使用的模型名")
    summary: str = Field(description="整体研判")
    plays: list[LlmPlayRecommendationRead] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list, description="风险提示")
    created_at: datetime.datetime = Field(description="生成时间")


# ---------- 大模型基本面分析 ----------


class LlmFundamentalDimensionRead(BaseModel):
    """单个基本面维度结论响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    code: str = Field(description="维度编码,如 RECENT_FORM")
    title: str = Field(description="维度展示名,如 近期状态")
    edge: str = Field(description="优劣倾向:home=主队占优 / away=客队占优 / even=势均力敌")
    content: str = Field(description="维度分析结论")


class LlmFundamentalAnalysisRead(BaseModel):
    """大模型基本面分析结果响应模型(整体研判 + 六维度结论 + 风险提示)。"""

    model_config = ConfigDict(from_attributes=True)

    analysis_id: int = Field(description="分析记录 ID(落库主键)")
    match_id: str
    provider: str = Field(description="服务商:qwen / ark")
    model: str = Field(description="实际使用的模型名")
    summary: str = Field(description="整体研判")
    dimensions: list[LlmFundamentalDimensionRead] = Field(
        description="六维度结论,按 近期状态/主客场表现/攻防效率/战意与动机/历史交锋/其他相关因素 顺序"
    )
    risks: list[str] = Field(default_factory=list, description="风险提示")
    created_at: datetime.datetime = Field(description="生成时间")


# ---------- 大模型赔率走势分析 ----------


class LlmTrendPlayRead(BaseModel):
    """单种玩法走势结论响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    play_code: str = Field(description="玩法编码:HAD/HHAD/CRS/TTG/HAFU")
    play_name: str = Field(description="玩法展示名,如 胜平负")
    signal: str = Field(description="走势信号,如 主胜走强 / 平局赔率抬升 / 盘口稳定")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度,0~1")
    reasoning: str = Field(description="走势解读")


class LlmTrendAnalysisRead(BaseModel):
    """大模型赔率走势分析结果响应模型(整体研判 + 分玩法走势结论 + 风险提示)。"""

    model_config = ConfigDict(from_attributes=True)

    analysis_id: int = Field(description="分析记录 ID(落库主键)")
    match_id: str
    provider: str = Field(description="服务商:qwen / ark")
    model: str = Field(description="实际使用的模型名")
    summary: str = Field(description="整体研判")
    plays: list[LlmTrendPlayRead] = Field(
        default_factory=list, description="分玩法走势结论"
    )
    risks: list[str] = Field(default_factory=list, description="风险提示")
    created_at: datetime.datetime = Field(description="生成时间")


# ---------- 赛果开奖 ----------

class MatchResultRead(BaseModel):
    """赛果开奖响应模型(开奖页展示口径)。"""

    match_id: str = Field(description="比赛全局唯一标识")
    match_num_str: str = Field(description="场次编号,如 周二002")
    league_name: str = Field(description="联赛名称")
    home_team_name: str = Field(description="主队名称")
    away_team_name: str = Field(description="客队名称")
    match_time: datetime.datetime = Field(description="开赛时间")
    goal_line: str | None = Field(default=None, description="让球盘口,如 -1")
    half_score: str | None = Field(default=None, description="半场比分,如 0:1")
    full_score: str | None = Field(default=None, description="全场比分,如 1:2")
    had: str | None = Field(default=None, description="胜平负开奖结果,如 客胜")
    hhad: str | None = Field(default=None, description="让球胜平负开奖结果,如 让球客胜")
    crs: str | None = Field(default=None, description="比分开奖结果,如 1:2")
    ttg: str | None = Field(default=None, description="总进球开奖结果,如 3")
    hafu: str | None = Field(default=None, description="半全场开奖结果,如 负负")
    sp_h: float | None = Field(default=None, description="主胜开奖 SP")
    sp_d: float | None = Field(default=None, description="平局开奖 SP")
    sp_a: float | None = Field(default=None, description="客胜开奖 SP")
    pool_status: str = Field(description="开奖状态,如 Payout=已开奖")


# ---------- 比赛事件 ----------

class MatchEventCreate(BaseModel):
    """创建比赛事件请求体。"""

    match_id: str = Field(max_length=64)
    event_type: str = Field(
        max_length=32, description="GOAL / RED_CARD / YELLOW_CARD / SUBSTITUTION"
    )
    event_minute: int = Field(ge=0, le=130)
    player_id: int | None = None
    is_home_team: bool = True


class MatchEventRead(BaseModel):
    """比赛事件响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    event_id: int
    match_id: str
    event_type: str
    event_minute: int
    player_id: int | None
    is_home_team: bool
