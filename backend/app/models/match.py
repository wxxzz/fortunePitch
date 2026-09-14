"""比赛与赛果模块(Match Module):fp_match_ 前缀。

系统的业务枢纽,记录赛事流转与结果。
"""

import datetime
import enum
import typing

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, BigIntPK
from app.models.base import League, Team


class MatchStatus(str, enum.Enum):
    """比赛状态枚举。"""

    PENDING = "PENDING"
    LIVE = "LIVE"
    FINISHED = "FINISHED"


class MatchGame(Base):
    """比赛基础信息表(fp_match_games):单场比赛的核心关联枢纽。"""

    __tablename__ = "fp_match_games"

    # 比赛全局唯一标识(来自外部数据源,故用 VARCHAR 而非自增)
    match_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("fp_base_leagues.league_id"), index=True, nullable=False
    )
    home_team_id: Mapped[int] = mapped_column(
        ForeignKey("fp_base_teams.team_id"), nullable=False
    )
    away_team_id: Mapped[int] = mapped_column(
        ForeignKey("fp_base_teams.team_id"), nullable=False
    )
    # 主裁判 ID(文档未定义裁判表,暂存外部编号)
    referee_id: Mapped[int | None] = mapped_column(BigIntPK, nullable=True)
    match_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    match_status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus, native_enum=True),
        nullable=False,
        default=MatchStatus.PENDING,
    )
    # 未完赛时比分记为 NULL,由 match_status 区分状态
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    league: Mapped["League"] = relationship(back_populates="games")
    home_team: Mapped["Team"] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped["Team"] = relationship(foreign_keys=[away_team_id])
    events: Mapped[list["MatchEvent"]] = relationship(back_populates="game")
    odds: Mapped["MatchOdds | None"] = relationship(back_populates="game")
    result: Mapped["MatchResult | None"] = relationship(back_populates="game")
    llm_analyses: Mapped[list["MatchLlmAnalysis"]] = relationship(
        back_populates="game"
    )


class MatchOdds(Base):
    """比赛玩法赔率表(fp_match_odds):竞彩在售 5 种玩法的即时赔率。

    每场比赛一行,``pools`` 为归一化玩法列表(由采集模块写入):
    ``[{"poolCode": "HAD", "playName": "胜平负", "goalLine": "-1",
    "options": [{"code": "h", "label": "主胜", "odds": 2.15}, ...]}, ...]``。
    历史赔率轨迹另由 fp_strategy_odds_history 承载。
    """

    __tablename__ = "fp_match_odds"

    match_id: Mapped[str] = mapped_column(
        ForeignKey("fp_match_games.match_id"), primary_key=True
    )
    pools: Mapped[list[dict[str, typing.Any]]] = mapped_column(JSON, nullable=False)
    update_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )

    game: Mapped["MatchGame"] = relationship(back_populates="odds")


class MatchResult(Base):
    """比赛赛果表(fp_match_results):竞彩赛果开奖数据。

    每场比赛一行,记录半/全场比分与 5 种玩法的开奖结果(由采集模块
    从比分与让球盘口推导),取消/无效场次比分为 NULL 仅保留状态。
    """

    __tablename__ = "fp_match_results"

    match_id: Mapped[str] = mapped_column(
        ForeignKey("fp_match_games.match_id"), primary_key=True
    )
    # 场次编号,如“周二002”
    match_num_str: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    # 让球盘口(如 "-1"),未开售让球玩法时为 NULL
    goal_line: Mapped[str | None] = mapped_column(String(8), nullable=True)
    half_home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    half_away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    full_home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    full_away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 各玩法开奖结果(中文标签,如“客胜”/“让球主胜”/“1:2”/“3”/“负负”)
    had: Mapped[str | None] = mapped_column(String(16), nullable=True)
    hhad: Mapped[str | None] = mapped_column(String(16), nullable=True)
    crs: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ttg: Mapped[str | None] = mapped_column(String(8), nullable=True)
    hafu: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # 胜平负开奖 SP 值
    sp_h: Mapped[float | None] = mapped_column(Float, nullable=True)
    sp_d: Mapped[float | None] = mapped_column(Float, nullable=True)
    sp_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 开奖状态(如 Payout=已开奖),取消场次保留原始状态
    pool_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    update_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )

    game: Mapped["MatchGame"] = relationship(back_populates="result")


class MatchEvent(Base):
    """比赛事件表(fp_match_events):滚球分析与事件驱动的关键节点。"""

    __tablename__ = "fp_match_events"

    event_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(
        ForeignKey("fp_match_games.match_id"), index=True, nullable=False
    )
    # 事件类型:GOAL / RED_CARD / YELLOW_CARD / SUBSTITUTION
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 发生时间(分钟,含伤停补时可为 45+2 的数值近似)
    event_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    player_id: Mapped[int | None] = mapped_column(
        ForeignKey("fp_base_players.player_id"), nullable=True
    )
    is_home_team: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    game: Mapped["MatchGame"] = relationship(back_populates="events")


class MatchLlmAnalysis(Base):
    """大模型分析结果表(fp_match_llm_analyses):每次生成一行,保留历史。

    由深度分析页“AI 分析”生成后落库,记录整体研判与风险提示;
    分玩法推荐明细另由 fp_match_llm_play_recs 承载。
    """

    __tablename__ = "fp_match_llm_analyses"

    analysis_id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True
    )
    match_id: Mapped[str] = mapped_column(
        ForeignKey("fp_match_games.match_id"), index=True, nullable=False
    )
    # 服务商(qwen / ark)与实际使用的模型名,便于回溯不同模型的历史效果
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    risks: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )

    game: Mapped["MatchGame"] = relationship(back_populates="llm_analyses")
    # 级联删除:主表删除时明细随数据库外键 ON DELETE CASCADE 一并清除
    plays: Mapped[list["MatchLlmPlayRec"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", passive_deletes=True
    )


class MatchLlmPlayRec(Base):
    """大模型分玩法推荐明细表(fp_match_llm_play_recs)。

    每种玩法一行,挂在某次分析下;(analysis_id, play_code) 唯一,
    即同一次分析内每种竞彩玩法至多一条推荐。
    """

    __tablename__ = "fp_match_llm_play_recs"
    __table_args__ = (
        UniqueConstraint("analysis_id", "play_code", name="uk_llm_analysis_play"),
    )

    rec_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("fp_match_llm_analyses.analysis_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 玩法编码 HAD/HHAD/CRS/TTG/HAFU 与展示名
    play_code: Mapped[str] = mapped_column(String(8), nullable=False)
    play_name: Mapped[str] = mapped_column(String(16), nullable=False)
    # 推荐选项展示名,如 主胜 / 1:2 / 3球 / 胜胜
    recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    # 置信度 0.000~1.000
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    reasoning: Mapped[str] = mapped_column(String(500), nullable=False)
    # 次选选项,最多 2 个
    alternatives: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    analysis: Mapped["MatchLlmAnalysis"] = relationship(back_populates="plays")
