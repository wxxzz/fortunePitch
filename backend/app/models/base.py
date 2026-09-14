"""基础档案模块(Base Module):fp_base_ 前缀。

存储系统的基础实体数据:联赛、球队、球员。
字段定义与《智能足彩数据分析系统 (FortunePitch) 数据库设计文档》对齐。
"""

import datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, BigIntPK


class League(Base):
    """联赛信息表(fp_base_leagues):全球各级别足球联赛的静态档案。"""

    __tablename__ = "fp_base_leagues"

    league_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    league_name: Mapped[str] = mapped_column(String(128), nullable=False)
    country: Mapped[str] = mapped_column(String(64), nullable=False)
    # 联赛级别:1=顶级,2=次级
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 当前赛季标识,如 "2025-2026"(文档原文 "eason",系排版丢字,规范为 season)
    season: Mapped[str] = mapped_column(String(16), nullable=False, default="2025-2026")

    teams: Mapped[list["Team"]] = relationship(back_populates="league")
    games: Mapped[list["MatchGame"]] = relationship(back_populates="league")


class Team(Base):
    """球队信息表(fp_base_teams):参赛球队的静态属性与战术框架。"""

    __tablename__ = "fp_base_teams"

    team_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    team_name: Mapped[str] = mapped_column(String(128), nullable=False)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("fp_base_leagues.league_id"), index=True, nullable=False
    )
    # 主场馆名称(文档原文 "tadium",系排版丢字,规范为 stadium)
    stadium: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manager: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 常规首发阵型,如 "4-3-3"
    formation: Mapped[str | None] = mapped_column(String(8), nullable=True)

    league: Mapped["League"] = relationship(back_populates="teams")
    players: Mapped[list["Player"]] = relationship(back_populates="team")
    fundamentals: Mapped["TeamFundamentals | None"] = relationship(
        back_populates="team"
    )


class Player(Base):
    """球员信息表(fp_base_players):球员基础资料与身价变动。"""

    __tablename__ = "fp_base_players"

    player_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    player_name: Mapped[str] = mapped_column(String(128), nullable=False)
    team_id: Mapped[int] = mapped_column(
        ForeignKey("fp_base_teams.team_id"), index=True, nullable=False
    )
    # 场上位置,如 CB / CAM / ST
    position: Mapped[str | None] = mapped_column(String(8), nullable=True)
    birth_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    # 当前市场身价(单位:欧元)
    market_value: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)

    team: Mapped["Team"] = relationship(back_populates="players")


class TeamFundamentals(Base):
    """球队基本面表(fp_base_team_fundamentals):积分榜推导的赛季战绩档案。

    每队一行,由采集模块从竞彩网积分榜(总/主/客三榜)写入,
    覆盖排名、场次、胜负平、进失球、净胜球、积分与胜率。
    """

    __tablename__ = "fp_base_team_fundamentals"

    team_id: Mapped[int] = mapped_column(
        ForeignKey("fp_base_teams.team_id"), primary_key=True
    )
    # 赛季标识,如 "2026-2027"
    season: Mapped[str] = mapped_column(String(16), nullable=False)
    # 总榜排名
    ranking: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 总战绩
    played: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    draws: Mapped[int | None] = mapped_column(Integer, nullable=True)
    losses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goals_for: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goals_against: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goal_diff: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 胜率(百分数 0-100)
    win_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # 主场战绩(主榜排名 + 与总战绩同构的指标)
    home_ranking: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_played: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_wins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_draws: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_losses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_goals_for: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_goals_against: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_goal_diff: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_win_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # 客场战绩(客榜排名 + 与总战绩同构的指标)
    away_ranking: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_played: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_wins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_draws: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_losses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_goals_for: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_goals_against: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_goal_diff: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_win_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    update_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )

    team: Mapped["Team"] = relationship(back_populates="fundamentals")
