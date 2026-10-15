"""比赛与赛果模块 Pydantic Schema:比赛 / 事件。"""

import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models import MatchStatus
from app.services.match_extra_info import MAX_FIELD_LENGTH

if TYPE_CHECKING:
    from app.services.insights import MatchInsights, TeamForm


# ---------- 比赛 ----------

class MatchGameCreate(BaseModel):
    """创建比赛请求体。"""

    match_id: str = Field(max_length=64, description="比赛全局唯一标识(外部数据源)")
    match_num_str: str = Field(
        default="", max_length=16, description="场次编号,如 周二002"
    )
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
    match_num_str: str = Field(default="", description="场次编号,如 周二002")
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


# ---------- 比赛补充信息(人工录入) ----------


class MatchExtraInfoUpsert(BaseModel):
    """保存比赛补充信息请求体(整体覆盖语义,空文本等同清空)。"""

    injuries: str = Field(
        default="",
        max_length=MAX_FIELD_LENGTH,
        description="伤停信息(自由文本,双方伤停/停赛球员与影响)",
    )
    formations: str = Field(
        default="",
        max_length=MAX_FIELD_LENGTH,
        description="阵型信息(自由文本,预计首发阵型/战术打法)",
    )
    other_notes: str = Field(
        default="",
        max_length=MAX_FIELD_LENGTH,
        description="其他补充(自由文本,天气/裁判/战意等)",
    )


class MatchExtraInfoRead(BaseModel):
    """比赛补充信息响应模型(未录入时返回空记录,updated_at 为 null)。"""

    model_config = ConfigDict(from_attributes=True)

    match_id: str
    injuries: str | None = Field(default=None, description="伤停信息;未录入为 null")
    formations: str | None = Field(default=None, description="阵型信息;未录入为 null")
    other_notes: str | None = Field(default=None, description="其他补充;未录入为 null")
    updated_at: datetime.datetime | None = Field(
        default=None, description="最近一次保存时间;从未录入为 null"
    )


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


class LlmRequestLogRead(BaseModel):
    """大模型调用日志响应模型(完整请求参数与响应结果,供排障查看)。"""

    model_config = ConfigDict(from_attributes=True)

    log_id: int
    provider: str = Field(description="服务商:qwen / ark")
    model: str = Field(description="实际使用的模型名")
    base_url: str = Field(description="OpenAI 兼容接口地址")
    request_messages: list[dict[str, Any]] = Field(
        description="完整提示词(system + user),JSON 数组原样保存"
    )
    request_params: dict[str, Any] = Field(
        description="调用参数:temperature / max_tokens / timeout_seconds / analysis_type"
    )
    response_content: str | None = Field(
        default=None, description="模型原始输出(解析前);失败时也可能保留用于排障"
    )
    status: str = Field(description="SUCCESS / FAILED")
    http_status: int | None = Field(default=None, description="接口 HTTP 状态码")
    prompt_tokens: int | None = Field(default=None, description="提示词 token 数")
    completion_tokens: int | None = Field(default=None, description="输出 token 数")
    total_tokens: int | None = Field(default=None, description="总 token 数")
    duration_ms: int = Field(description="调用耗时(毫秒)")
    error_message: str | None = Field(default=None, description="失败摘要")
    error_detail: str | None = Field(default=None, description="失败详情")
    created_at: datetime.datetime = Field(description="调用时间")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def analysis_type(self) -> str:
        """调用类型:analysis=综合分析 / fundamental=基本面 / odds_trend=赔率走势。

        早期综合分析日志未写入该键,按缺省回退为 analysis。
        """
        return str(self.request_params.get("analysis_type") or "analysis")


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


# ---------- AI 分析结果查询 ----------

class LlmRecommendationRowRead(BaseModel):
    """AI 分析结果查询行的响应模型(推荐 + 比赛上下文)。"""

    analysis_id: int = Field(description="所属分析记录 ID(每场取最近一次)")
    match_id: str = Field(description="比赛编号")
    match_num_str: str = Field(
        default="", description="场次编号,如 周二002(缺失时为空串)"
    )
    league_name: str | None = Field(description="联赛名称")
    match_time: datetime.datetime = Field(description="开赛时间")
    business_date: datetime.date | None = Field(description="竞彩售卖日")
    home_team_name: str | None = Field(description="主队名称")
    away_team_name: str | None = Field(description="客队名称")
    play_code: str = Field(description="玩法编码:HAD/HHAD/CRS/TTG/HAFU")
    play_name: str = Field(description="玩法展示名,如 胜平负")
    recommendation: str = Field(description="推荐选项,如 主胜 / 1:2 / 3球 / 胜胜")
    recommendation_odds: float | None = Field(
        default=None,
        description="推荐选项的当前在售赔率(最新,未开售或未同步时为 None)"
    )
    alternative_odds: list[float | None] = Field(
        default_factory=list,
        description="次选选项的当前在售赔率,与 alternatives 按位对齐(无法解析时为 None)",
    )
    result: str | None = Field(
        default=None,
        description="该玩法的赛果开奖结果(如 客胜/让球主胜/1:2/3/负负,未同步赛果时为 None)",
    )
    is_hit: bool | None = Field(
        default=None,
        description="推荐与开奖的比对结论(命中 True/未中 False,未开奖为 None)",
    )
    confidence: float = Field(description="置信度,0~1")
    reasoning: str = Field(description="推荐依据")
    alternatives: list[str] = Field(default_factory=list, description="次选选项")
    created_at: datetime.datetime = Field(description="分析生成时间")


# ---------- 赛果开奖 ----------

class ResultStatItemRead(BaseModel):
    """单个统计条目(标签 / 次数 / 占比)。"""

    label: str = Field(description="统计标签,如 主胜 / 3 / 2:1 / 胜胜")
    count: int = Field(description="出现次数")
    pct: float = Field(ge=0.0, le=1.0, description="该维度有效场次中的占比,0~1")


class ResultLeagueStatRead(BaseModel):
    """按联赛的赛果统计行。"""

    league_name: str = Field(description="联赛名称")
    total: int = Field(description="该联赛已开赛场次")
    home_win: int = Field(description="主胜场次")
    draw: int = Field(description="平局场次")
    away_win: int = Field(description="客胜场次")
    avg_total_goals: float | None = Field(
        default=None, description="场均总进球(无已开赛场次时为 None)"
    )


class MatchResultStatsRead(BaseModel):
    """赛果开奖多维度统计响应模型。"""

    start_date: datetime.date = Field(description="售卖日起(含)")
    end_date: datetime.date = Field(description="售卖日止(含)")
    total: int = Field(description="范围内总场次(含取消/无效)")
    settled: int = Field(description="已开赛场次(有有效比分)")
    cancelled: int = Field(description="取消/无效场次")
    had: list[ResultStatItemRead] = Field(description="胜平负开奖分布(主胜/平/客胜)")
    hhad: list[ResultStatItemRead] = Field(
        description="让球胜平负开奖分布(让球主胜/让球平/让球客胜)"
    )
    ttg: list[ResultStatItemRead] = Field(description="总进球分布(按进球数升序,7+ 合并)")
    crs: list[ResultStatItemRead] = Field(description="比分分布(按次数倒序)")
    hafu: list[ResultStatItemRead] = Field(description="半全场分布(按次数倒序)")
    leagues: list[ResultLeagueStatRead] = Field(
        description="按联赛统计(按已开赛场次倒序)"
    )


class MatchResultRead(BaseModel):
    """赛果开奖响应模型(开奖页展示口径)。"""

    match_id: str = Field(description="比赛全局唯一标识")
    match_num_str: str = Field(description="场次编号,如 周二002")
    league_name: str = Field(description="联赛名称")
    home_team_name: str = Field(description="主队名称")
    away_team_name: str = Field(description="客队名称")
    match_time: datetime.datetime = Field(description="开赛时间")
    business_date: datetime.date | None = Field(
        default=None, description="竞彩售卖日(次日凌晨开赛归属前一售卖日)"
    )
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


# ---------- 高阶数据(insights) ----------

class InsightsFormEntryRead(BaseModel):
    """近况明细行(看板球队视角)。"""

    match_time: datetime.datetime = Field(description="开赛时间")
    league_name: str | None = Field(default=None, description="赛事名称")
    opponent_name: str = Field(description="对手名称")
    is_home: bool = Field(description="看板球队是否为主队")
    score: str = Field(description="全场比分(主:客),如 2:1")
    result: str = Field(description="看板球队视角结果:W/D/L")


class InsightsTeamFormRead(BaseModel):
    """球队近况汇总。"""

    team_id: int = Field(description="球队 ID")
    team_name: str = Field(description="球队名称")
    entries: list[InsightsFormEntryRead] = Field(description="近况明细(时间倒序)")
    results: str = Field(description="结果串(时间倒序,最早在左),如 WWDLLW")
    wins: int = Field(description="胜场数")
    draws: int = Field(description="平局数")
    losses: int = Field(description="负场数")
    goals_for_avg: float = Field(description="场均进球")
    goals_against_avg: float = Field(description="场均失球")
    streak_label: str = Field(description="状态标签,如 连胜 3 场")


class InsightsH2HEntryRead(BaseModel):
    """历史交锋明细行(按行自身主队视角)。"""

    match_time: datetime.datetime = Field(description="开赛时间")
    league_name: str | None = Field(default=None, description="赛事名称")
    home_team_name: str = Field(description="该场主队名称")
    away_team_name: str = Field(description="该场客队名称")
    score: str = Field(description="全场比分(主:客)")
    home_result: str = Field(description="该场主队视角结果:W/D/L")


class InsightsH2HRead(BaseModel):
    """历史交锋汇总(胜平负以本场主队视角)。"""

    entries: list[InsightsH2HEntryRead] = Field(description="交锋明细(时间倒序)")
    home_wins: int = Field(description="本场主队胜场数")
    draws: int = Field(description="平局数")
    away_wins: int = Field(description="本场客队胜场数")
    avg_total_goals: float | None = Field(default=None, description="场均总进球")


class InsightsEloRead(BaseModel):
    """双方 Elo 快照(未重算时 rating 各值为 None)。"""

    home_rating: float | None = Field(default=None, description="主队 Elo 评分")
    away_rating: float | None = Field(default=None, description="客队 Elo 评分")
    rating_diff: float | None = Field(default=None, description="评分差(主-客)")
    home_expected_score: float | None = Field(
        default=None, description="主队期望得分(含主场优势)"
    )
    home_matches_played: int = Field(description="主队参与评分场次")
    away_matches_played: int = Field(description="客队参与评分场次")


class InsightsStrengthRead(BaseModel):
    """攻防强度与期望进球估计。"""

    league_avg_home_goals: float | None = Field(
        default=None, description="联赛主队场均进球"
    )
    league_avg_away_goals: float | None = Field(
        default=None, description="联赛客队场均进球"
    )
    home_attack: float | None = Field(
        default=None, description="主队进攻强度(1.00=联赛均值)"
    )
    home_defense: float | None = Field(default=None, description="主队防守强度(失球比)")
    away_attack: float | None = Field(default=None, description="客队进攻强度")
    away_defense: float | None = Field(default=None, description="客队防守强度")
    lam: float | None = Field(default=None, description="主队期望进球")
    mu: float | None = Field(default=None, description="客队期望进球")


class InsightsScoreProbRead(BaseModel):
    """比分概率条目。"""

    home_goals: int = Field(description="主队进球数")
    away_goals: int = Field(description="客队进球数")
    probability: float = Field(description="概率(0~1)")


class InsightsTtgBinRead(BaseModel):
    """总进球分布桶。"""

    goals: int = Field(description="总进球数(0..6,7 表示 7+)")
    probability: float = Field(description="概率(0~1)")


class InsightsPoissonRead(BaseModel):
    """Dixon-Coles 泊松比分预测。"""

    home_win: float = Field(description="主胜概率")
    draw: float = Field(description="平局概率")
    away_win: float = Field(description="客胜概率")
    top_scores: list[InsightsScoreProbRead] = Field(
        description="最可能比分(前5,概率降序)"
    )
    over_2_5: float = Field(description="大于 2.5 球概率")
    under_2_5: float = Field(description="不大于 2.5 球概率")
    total_goals_dist: list[InsightsTtgBinRead] = Field(
        description="总进球分布(0..6 与 7+)"
    )
    total_goals_expected: float = Field(description="总进球期望")


class MatchInsightsRead(BaseModel):
    """单场比赛高阶数据聚合响应(详情页 高阶数据/历史交锋 Tab)。"""

    match_id: str = Field(description="比赛 ID")
    league_name: str = Field(description="联赛名称")
    match_time: datetime.datetime = Field(description="开赛时间")
    home_team_name: str = Field(description="主队名称")
    away_team_name: str = Field(description="客队名称")
    elo: InsightsEloRead = Field(description="Elo 快照")
    home_form: InsightsTeamFormRead = Field(description="主队近况")
    away_form: InsightsTeamFormRead = Field(description="客队近况")
    h2h: InsightsH2HRead = Field(description="历史交锋")
    strength: InsightsStrengthRead = Field(description="攻防强度与期望进球")
    poisson: InsightsPoissonRead | None = Field(
        default=None, description="泊松预测(攻防数据不足时为 None)"
    )

    @classmethod
    def from_insights(cls, data: "MatchInsights") -> "MatchInsightsRead":
        """由服务层 MatchInsights NamedTuple 组装响应模型。"""
        game = data.game
        return cls(
            match_id=game.match_id,
            league_name=game.league.league_name,
            match_time=game.match_time,
            home_team_name=game.home_team.team_name,
            away_team_name=game.away_team.team_name,
            elo=InsightsEloRead(
                home_rating=data.elo.home_rating,
                away_rating=data.elo.away_rating,
                rating_diff=data.elo.rating_diff,
                home_expected_score=data.elo.home_expected_score,
                home_matches_played=data.elo.home_matches_played,
                away_matches_played=data.elo.away_matches_played,
            ),
            home_form=_form_to_read(data.home_form),
            away_form=_form_to_read(data.away_form),
            h2h=InsightsH2HRead(
                entries=[
                    InsightsH2HEntryRead(
                        match_time=entry.match_time,
                        league_name=entry.league_name,
                        home_team_name=entry.home_team_name,
                        away_team_name=entry.away_team_name,
                        score=f"{entry.home_goals}:{entry.away_goals}",
                        home_result=entry.home_result,
                    )
                    for entry in data.h2h.entries
                ],
                home_wins=data.h2h.home_wins,
                draws=data.h2h.draws,
                away_wins=data.h2h.away_wins,
                avg_total_goals=data.h2h.avg_total_goals,
            ),
            strength=InsightsStrengthRead(
                league_avg_home_goals=data.strength.league_avg_home_goals,
                league_avg_away_goals=data.strength.league_avg_away_goals,
                home_attack=data.strength.home_attack,
                home_defense=data.strength.home_defense,
                away_attack=data.strength.away_attack,
                away_defense=data.strength.away_defense,
                lam=data.strength.lam,
                mu=data.strength.mu,
            ),
            poisson=(
                InsightsPoissonRead(
                    home_win=data.poisson.home_win,
                    draw=data.poisson.draw,
                    away_win=data.poisson.away_win,
                    top_scores=[
                        InsightsScoreProbRead(
                            home_goals=home_goals,
                            away_goals=away_goals,
                            probability=probability,
                        )
                        for home_goals, away_goals, probability in data.poisson.top_scores
                    ],
                    over_2_5=data.poisson.over_2_5,
                    under_2_5=data.poisson.under_2_5,
                    total_goals_dist=[
                        InsightsTtgBinRead(goals=goals, probability=probability)
                        for goals, probability in data.poisson.total_goals_dist
                    ],
                    total_goals_expected=data.poisson.total_goals_expected,
                )
                if data.poisson is not None
                else None
            ),
        )


def _form_to_read(form: "TeamForm") -> InsightsTeamFormRead:
    """由服务层 TeamForm NamedTuple 组装近况响应模型。"""
    return InsightsTeamFormRead(
        team_id=form.team_id,
        team_name=form.team_name,
        entries=[
            InsightsFormEntryRead(
                match_time=entry.match_time,
                league_name=entry.league_name,
                opponent_name=entry.opponent_name,
                is_home=entry.is_home,
                score=f"{entry.home_goals}:{entry.away_goals}",
                result=entry.result,
            )
            for entry in form.entries
        ],
        results=form.results,
        wins=form.wins,
        draws=form.draws,
        losses=form.losses,
        goals_for_avg=form.goals_for_avg,
        goals_against_avg=form.goals_against_avg,
        streak_label=form.streak_label,
    )
