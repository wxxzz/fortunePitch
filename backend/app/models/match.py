"""比赛与赛果模块(Match Module):fp_match_ 前缀。

系统的业务枢纽,记录赛事流转与结果。
"""

import datetime
import enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
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
