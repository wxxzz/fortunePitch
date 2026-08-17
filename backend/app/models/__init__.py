"""FortunePitch ORM 模型定义(SQLAlchemy 2.0 风格)。

表结构对齐《智能足彩数据分析系统 (FortunePitch) 数据库设计文档》:
- base.py     基础档案模块(fp_base_)
- match.py    比赛与赛果模块(fp_match_)
- analytics.py 高阶数据分析模块(fp_analytics_)
- strategy.py 策略与赔率模块(fp_strategy_)
"""

from app.models.analytics import PlayerMatchPerformance, TeamMatchStat
from app.models.base import League, Player, Team
from app.models.match import MatchEvent, MatchGame, MatchStatus
from app.models.strategy import (
    DecisionStatus,
    OddsHistory,
    Recommendation,
    UserDecision,
)

__all__ = [
    "League",
    "Team",
    "Player",
    "MatchGame",
    "MatchEvent",
    "MatchStatus",
    "TeamMatchStat",
    "PlayerMatchPerformance",
    "OddsHistory",
    "Recommendation",
    "UserDecision",
    "DecisionStatus",
]
