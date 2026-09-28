"""高阶数据分析模块(Analytics Module):fp_analytics_ 前缀。

存储算法引擎计算得出的深度量化数据。
"""

import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, BigIntPK


class TeamMatchStat(Base):
    """球队高阶指标表(fp_analytics_team_stats):按场次记录球队量化数据。

    xG / xGA / possession / ppda 等指标的计算口径
    参见 docs/algorithm.md 与 app/services/xg.py。
    """

    __tablename__ = "fp_analytics_team_stats"

    # 记录 ID(文档原文 "tat_id",系排版丢字,规范为 stat_id)
    stat_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(
        ForeignKey("fp_match_games.match_id"), index=True, nullable=False
    )
    team_id: Mapped[int] = mapped_column(
        ForeignKey("fp_base_teams.team_id"), index=True, nullable=False
    )
    # 预期进球(Expected Goals)
    xg: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # 预期失球(Expected Goals Against)
    xga: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # 控球率(百分数 0-100)
    possession: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # 射门转化率(文档原文 "hot_accuracy",系排版丢字,规范为 shot_accuracy)
    shot_accuracy: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # 防守压迫指数(Passes Per Defensive Action,越低压迫越强)
    ppda: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)


class TeamRating(Base):
    """球队 Elo 评分表(fp_analytics_team_ratings):每队一行当前评分。

    由 services/team_rating.recompute_team_ratings 按时间序回放全部
    已完赛看板比赛(fp_base_team_matches)幂等重算(全量重建),
    不保留评分历史——历史可随时由原始赛果重建。
    """

    __tablename__ = "fp_analytics_team_ratings"

    team_id: Mapped[int] = mapped_column(
        ForeignKey("fp_base_teams.team_id", ondelete="CASCADE"), primary_key=True
    )
    # 当前 Elo 评分(默认起点 1500,见 services/elo.py)
    rating: Mapped[float] = mapped_column(Float, nullable=False, default=1500.0)
    # 参与评分的比赛场数(用于前端展示数据充分性)
    matches_played: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 最近一场参与评分比赛的开赛时间(评分时新度)
    last_match_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    update_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )

    # 单向关系,避免改动 base.py 的 Team 映射
    team: Mapped["Team"] = relationship()


class PlayerMatchPerformance(Base):
    """球员单场表现表(fp_analytics_player_stats):球员单场深度发挥。"""

    __tablename__ = "fp_analytics_player_stats"

    performance_id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True
    )
    match_id: Mapped[str] = mapped_column(
        ForeignKey("fp_match_games.match_id"), index=True, nullable=False
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("fp_base_players.player_id"), index=True, nullable=False
    )
    minutes_played: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goals: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    assists: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    key_passes: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    # 赛后综合评分(如 Whoscored 口径 0-10)
    rating: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)
