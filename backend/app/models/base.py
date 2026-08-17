"""基础档案模块(Base Module):fp_base_ 前缀。

存储系统的基础实体数据:联赛、球队、球员。
字段定义与《智能足彩数据分析系统 (FortunePitch) 数据库设计文档》对齐。
"""

import datetime

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class League(Base):
    """联赛信息表(fp_base_leagues):全球各级别足球联赛的静态档案。"""

    __tablename__ = "fp_base_leagues"

    league_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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

    team_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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


class Player(Base):
    """球员信息表(fp_base_players):球员基础资料与身价变动。"""

    __tablename__ = "fp_base_players"

    player_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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
