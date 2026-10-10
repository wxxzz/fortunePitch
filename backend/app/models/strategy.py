"""策略与赔率模块(Strategy Module):fp_strategy_ 前缀。

对接外部市场数据并存储系统的分析产出。

合规说明:fp_strategy_user_decisions 中的注额为**模拟**数据,
仅用于用户复盘与个人战绩统计,系统不涉及任何真实资金流转。
"""

import datetime
import enum

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, BigIntPK


class OddsHistory(Base):
    """赔率与盘口表(fp_strategy_odds_history):机构赔率变化轨迹。"""

    __tablename__ = "fp_strategy_odds_history"

    odds_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(
        ForeignKey("fp_match_games.match_id"), index=True, nullable=False
    )
    # 机构名称,如 "Bet365" / "澳门"
    bookmaker: Mapped[str] = mapped_column(String(64), nullable=False)
    # 市场类型:ASIAN_HANDICAP(亚洲让球盘)/ EURO_ODDS(欧赔)/ OVER_UNDER(大小球)
    market_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 初盘水位/赔率
    initial_value: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    # 即时水位/赔率
    current_value: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    update_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class Recommendation(Base):
    """策略推荐记录表(fp_strategy_recommendations):AI 引擎分析方案与归因。"""

    __tablename__ = "fp_strategy_recommendations"

    recommend_id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True
    )
    match_id: Mapped[str] = mapped_column(
        ForeignKey("fp_match_games.match_id"), index=True, nullable=False
    )
    # 策略类型:WIN_DRAW_LOSS / HANDICAP / SCORE
    # (文档原文 "trategy_type",系排版丢字,规范为 strategy_type)
    strategy_type: Mapped[str] = mapped_column(String(32), nullable=False)
    predicted_outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    # 模型置信度(0.00 - 1.00)
    confidence_score: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    # 推导逻辑标签,如 ["核心缺阵", "盘口浅开"]
    logic_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )


class DecisionStatus(str, enum.Enum):
    """模拟决策结算状态枚举。"""

    WIN = "WIN"
    LOSS = "LOSS"
    PUSH = "PUSH"


class UserDecision(Base):
    """用户决策记录表(fp_strategy_user_decisions):用户复盘与战绩统计。

    注:文档未定义用户表,此处 user_id 暂存外部用户编号。
    """

    __tablename__ = "fp_strategy_user_decisions"

    decision_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigIntPK, index=True, nullable=False)
    recommend_id: Mapped[int] = mapped_column(
        ForeignKey("fp_strategy_recommendations.recommend_id"), nullable=False
    )
    # 用户选择的玩法
    user_bet_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 模拟注额(文档原文 "take_amount",系排版丢字,规范为 stake_amount)
    stake_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    result_status: Mapped[DecisionStatus] = mapped_column(
        Enum(DecisionStatus, native_enum=True),
        nullable=False,
        default=DecisionStatus.PUSH,
    )
    # 盈亏金额(复盘时由系统结算生成,模拟数据)
    profit_loss: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)


class BetScheme(Base):
    """串关投注方案表(fp_strategy_bet_schemes):虚拟投注的串关方案。

    注额均为模拟数据(虚拟投注),仅用于方案留存与复盘,
    不涉及任何真实资金流转。注数与单注最高赔率由服务端按
    串关组合规则计算,不信任前端上传值。
    """

    __tablename__ = "fp_strategy_bet_schemes"

    scheme_id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(BigIntPK, index=True, nullable=False)
    # 串关场次:N串1 的 N(如 2串1 / 3串1 / 4串1)
    parlay_size: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    # 每注模拟注额
    stake_per_bet: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    # 总注数(N 场组合数 x 各场复式选项数,由服务端计算)
    bet_count: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    # 总投入 = 每注注额 x 总注数
    total_stake: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # 单注最高赔率(组合内各场最高赔率乘积的最大值)
    max_odds: Mapped[float] = mapped_column(Numeric(12, 2), nullable=True)
    # 虚拟结算状态:PENDING=待结算 / WIN=全部命中 / LOSS=未全中
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )

    items: Mapped[list["BetSchemeItem"]] = relationship(
        back_populates="scheme", cascade="all, delete-orphan", passive_deletes=True
    )


class BetSchemeItem(Base):
    """串关方案选注明细表(fp_strategy_bet_scheme_items)。

    每条选注一行,挂在某个方案下;记录勾选时点的赔率快照,
    与串关组合规则共同决定注数(同场多选项=复式)。
    """

    __tablename__ = "fp_strategy_bet_scheme_items"

    item_id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True
    )
    scheme_id: Mapped[int] = mapped_column(
        ForeignKey("fp_strategy_bet_schemes.scheme_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    match_id: Mapped[str] = mapped_column(
        ForeignKey("fp_match_games.match_id"), nullable=False
    )
    # 比赛对阵快照(如 "巴塞罗那 vs 皇家马德里")
    match_name: Mapped[str] = mapped_column(String(128), nullable=False)
    pool_code: Mapped[str] = mapped_column(String(8), nullable=False)
    play_name: Mapped[str] = mapped_column(String(16), nullable=False)
    option_code: Mapped[str] = mapped_column(String(16), nullable=False)
    option_label: Mapped[str] = mapped_column(String(32), nullable=False)
    # 勾选时点的赔率快照
    odds: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)

    scheme: Mapped["BetScheme"] = relationship(back_populates="items")


class AiPickBatch(Base):
    """AI 策略推荐生成批次表(fp_strategy_ai_pick_batches)。

    策略页手动触发生成:按售卖日汇总各场最新 AI 分析的分玩法推荐。
    同售卖日重复生成时,旧 ACTIVE 批次置为 SUPERSEDED(历史保留,
    不删已转换决策的审计链),查询默认只看最新 ACTIVE 批次。
    """

    __tablename__ = "fp_strategy_ai_pick_batches"

    batch_id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True
    )
    # 竞彩售卖日
    business_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    # 本次生成使用的置信度阈值
    min_confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    # 入选单场推荐数
    pick_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # 因赔率不可解析/已开赛等原因跳过的推荐数
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # 生成的串关候选方案数
    plan_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # ACTIVE=当前生效 / SUPERSEDED=已被更新的批次取代
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )


class AiPick(Base):
    """AI 单场推荐明细表(fp_strategy_ai_picks):批次内一条可行动推荐。

    来源为 MatchLlmPlayRec(每场最新 AI 分析),落库前已解析出
    选项编码与生成时点赔率快照(EV/凯利计算与结算转换的前提);
    无法解析或已开赛的推荐不落库(计入批次 skipped_count)。
    """

    __tablename__ = "fp_strategy_ai_picks"

    pick_id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True
    )
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("fp_strategy_ai_pick_batches.batch_id"), nullable=False, index=True
    )
    match_id: Mapped[str] = mapped_column(
        ForeignKey("fp_match_games.match_id"), nullable=False, index=True
    )
    # 溯源到生成该推荐的那次 AI 分析
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("fp_match_llm_analyses.analysis_id"), nullable=False
    )
    # 玩法编码:HAD/HHAD/CRS/TTG/HAFU
    play_code: Mapped[str] = mapped_column(String(8), nullable=False)
    play_name: Mapped[str] = mapped_column(String(16), nullable=False)
    # LLM 原始推荐文案快照(如"让球主胜"/"3球")
    recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    # 解析出的选项编码(如 hh / s3,结算 user_bet_type 口径)
    option_code: Mapped[str] = mapped_column(String(16), nullable=False)
    # 赔率池中的标准选项展示名(结算比对口径)
    option_label: Mapped[str] = mapped_column(String(32), nullable=False)
    # 生成时点的赔率快照
    odds: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    # LLM 置信度(0~1)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    # 去水隐含概率(该玩法池全部选项归一)
    implied_prob: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    # 期望值 = confidence * odds - 1
    ev: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    # 凯利建议资金比例(无正期望为 0)
    kelly: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    # 逆向腿 = 置信度低于市场隐含概率(博冷/低置信方向)
    is_contrarian: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # LLM 推荐理由快照
    reasoning: Mapped[str] = mapped_column(String(500), nullable=False)
    # 转用户决策后回填(幂等指针,双击转换不重复建);
    # 决策被删除时置空,恢复该推荐的可转换状态
    decision_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "fp_strategy_user_decisions.decision_id", ondelete="SET NULL"
        ),
        nullable=True,
    )

    batch: Mapped["AiPickBatch"] = relationship()
    game: Mapped["MatchGame"] = relationship()


class AiParlayPlan(Base):
    """AI 串关候选方案表(fp_strategy_ai_parlay_plans):展示态候选。

    腿明细以 JSON 快照保存;用户确认保存时经 parlay.save_bet_scheme
    物化正式的 BetScheme+Items(唯一权威快照),本表不双写。
    组合置信度按腿间独立近似(浅盘日让平存在相关性,见校准教训文档)。
    """

    __tablename__ = "fp_strategy_ai_parlay_plans"

    plan_id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True
    )
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("fp_strategy_ai_pick_batches.batch_id"), nullable=False, index=True
    )
    # 2~4 串 1
    parlay_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # 方案名,如"稳胆 2串1" / "价值混合 4串1"
    plan_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # 组合逻辑一句话说明
    plan_desc: Mapped[str] = mapped_column(String(200), nullable=False)
    # 腿快照:[{match_id, match_name, match_num_str, play_code, play_name,
    # option_code, option_label, odds, confidence, is_contrarian}]
    legs: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    # 组合赔率 = Π odds
    combined_odds: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # 组合置信度 = Π confidence(腿间独立近似)
    combined_confidence: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    # 期望值 = combined_confidence * combined_odds - 1
    ev: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    kelly: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    # 逆向腿数(构建器保证 ≤ 2,校准规则)
    contrarian_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # 保存为正式串关方案后回填(幂等指针);方案被删除时置空
    scheme_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "fp_strategy_bet_schemes.scheme_id", ondelete="SET NULL"
        ),
        nullable=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )

    batch: Mapped["AiPickBatch"] = relationship()
