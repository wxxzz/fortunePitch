"""球队与比赛的 ORM 模型定义。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Team(Base):
    """球队实体。"""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # Elo 评分,初始值 1500,由 app.services.elo 模块维护
    elo_rating: Mapped[float] = mapped_column(Float, default=1500.0)
    league: Mapped[str | None] = mapped_column(String(64), nullable=True)

    home_matches: Mapped[list["Match"]] = relationship(
        back_populates="home_team", foreign_keys="Match.home_team_id"
    )
    away_matches: Mapped[list["Match"]] = relationship(
        back_populates="away_team", foreign_keys="Match.away_team_id"
    )


class Match(Base):
    """比赛实体。

    一个 Match 记录一场比赛的基本信息、实际比分(已完赛)
    以及一条可选的 OddsRecord 赔率快照。
    """

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 外部数据源的比赛唯一编号,用于幂等导入
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    league: Mapped[str] = mapped_column(String(64), index=True)
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    home_team: Mapped["Team"] = relationship(
        back_populates="home_matches", foreign_keys=[home_team_id]
    )
    away_team: Mapped["Team"] = relationship(
        back_populates="away_matches", foreign_keys=[away_team_id]
    )

    # 已完赛时填充;-1 表示尚未开赛
    home_goals: Mapped[int] = mapped_column(Integer, default=-1)
    away_goals: Mapped[int] = mapped_column(Integer, default=-1)

    odds_records: Mapped[list["OddsRecord"]] = relationship(back_populates="match")


class OddsRecord(Base):
    """赔率快照(胜/平/负 欧赔),按时间采集用于走势分析。

    同一场比赛可有多条快照,记录市场预期的变化轨迹。
    """

    __tablename__ = "odds_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 欧赔:主胜 / 平局 / 客胜
    home_win_odds: Mapped[float] = mapped_column(Float)
    draw_odds: Mapped[float] = mapped_column(Float)
    away_win_odds: Mapped[float] = mapped_column(Float)

    match: Mapped["Match"] = relationship(back_populates="odds_records")
