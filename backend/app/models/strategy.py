"""策略与赔率模块(Strategy Module):fp_strategy_ 前缀。

对接外部市场数据并存储系统的分析产出。

合规说明:fp_strategy_user_decisions 中的注额为**模拟**数据,
仅用于用户复盘与个人战绩统计,系统不涉及任何真实资金流转。
"""

import datetime
import enum

from sqlalchemy import (
    JSON,
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
