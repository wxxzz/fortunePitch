"""高阶数据分析模块(Analytics Module):fp_analytics_ 前缀。

存储算法引擎计算得出的深度量化数据。
"""

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TeamMatchStat(Base):
    """球队高阶指标表(fp_analytics_team_stats):按场次记录球队量化数据。

    xG / xGA / possession / ppda 等指标的计算口径
    参见 docs/algorithm.md 与 app/services/xg.py。
    """

    __tablename__ = "fp_analytics_team_stats"

    # 记录 ID(文档原文 "tat_id",系排版丢字,规范为 stat_id)
    stat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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


class PlayerMatchPerformance(Base):
    """球员单场表现表(fp_analytics_player_stats):球员单场深度发挥。"""

    __tablename__ = "fp_analytics_player_stats"

    performance_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
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
