"""基础档案模块(Base Module):fp_base_ 前缀。

存储系统的基础实体数据:联赛、球队、球员。
字段定义与《智能足彩数据分析系统 (FortunePitch) 数据库设计文档》对齐。
"""

import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
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
    profile: Mapped["TeamProfile | None"] = relationship(back_populates="team")
    team_matches: Mapped[list["TeamMatch"]] = relationship(back_populates="team")


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


class TeamProfile(Base):
    """竞彩网球队档案表(fp_base_team_profiles):球队看板数据源映射。

    每队一行,由采集模块从竞彩网球队专栏(sporttery.cn/zqlszl/qdzl)
    写入,维护本地球队与竞彩网统一球队 ID 的映射及名称/国家/队徽,
    供球队看板同步与查询使用。
    """

    __tablename__ = "fp_base_team_profiles"

    team_id: Mapped[int] = mapped_column(
        ForeignKey("fp_base_teams.team_id", ondelete="CASCADE"), primary_key=True
    )
    # 竞彩网统一球队 ID(球队专栏页 URL 的 tid)
    uniform_team_id: Mapped[int] = mapped_column(BigIntPK, unique=True, index=True)
    # 竞彩网赛事库球队 ID / 外部数据源球队 ID
    gm_team_id: Mapped[int | None] = mapped_column(BigIntPK)
    wbsj_team_id: Mapped[int | None] = mapped_column(BigIntPK)
    # 球队简称(竞彩网赛程赛果使用的队名)
    abbrev_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 球队全称与所属国家
    full_name: Mapped[str | None] = mapped_column(String(128))
    country_name: Mapped[str | None] = mapped_column(String(64))
    logo_url: Mapped[str | None] = mapped_column(String(512))
    update_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )

    team: Mapped["Team"] = relationship(back_populates="profile")


class TeamMatch(Base):
    """球队看板赛程表(fp_base_team_matches):未来赛事与赛程赛果。

    以看板球队视角存储竞彩网球队专栏的未来赛事与赛程赛果,
    比分为空表示未开赛;同一场比赛在两支球队的看板中视角不同
    (is_home / team_result),故按 (team_id, uniform_match_id) 复合主键。
    """

    __tablename__ = "fp_base_team_matches"

    team_id: Mapped[int] = mapped_column(
        ForeignKey("fp_base_teams.team_id", ondelete="CASCADE"), primary_key=True
    )
    uniform_match_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    uniform_league_id: Mapped[int | None] = mapped_column(BigIntPK, index=True)
    league_name: Mapped[str | None] = mapped_column(String(128))
    match_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # 轮次与阶段(如欧冠 League Stage)
    gameweek: Mapped[str | None] = mapped_column(String(32))
    phase_name: Mapped[str | None] = mapped_column(String(64))
    home_team_name: Mapped[str] = mapped_column(String(128), nullable=False)
    away_team_name: Mapped[str] = mapped_column(String(128), nullable=False)
    uniform_home_team_id: Mapped[int | None] = mapped_column(BigIntPK)
    uniform_away_team_id: Mapped[int | None] = mapped_column(BigIntPK)
    # 看板球队是否为主队
    is_home: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # 半场/全场比分(未开赛为 NULL)
    half_home_score: Mapped[int | None] = mapped_column(Integer)
    half_away_score: Mapped[int | None] = mapped_column(Integer)
    full_home_score: Mapped[int | None] = mapped_column(Integer)
    full_away_score: Mapped[int | None] = mapped_column(Integer)
    # 看板球队视角的比赛结果:W=胜 D=平 L=负(未开赛为 NULL)
    team_result: Mapped[str | None] = mapped_column(String(1))
    update_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )

    team: Mapped["Team"] = relationship(back_populates="team_matches")
