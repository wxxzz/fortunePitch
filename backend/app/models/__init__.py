"""FortunePitch ORM 模型定义(SQLAlchemy 2.0 风格)。

表结构对齐《智能足彩数据分析系统 (FortunePitch) 数据库设计文档》:
- base.py     基础档案模块(fp_base_)
- match.py    比赛与赛果模块(fp_match_)
- analytics.py 高阶数据分析模块(fp_analytics_)
- strategy.py 策略与赔率模块(fp_strategy_)
- llm.py      大模型日志模块(fp_llm_)
"""

from app.models.analytics import PlayerMatchPerformance, TeamMatchStat
from app.models.llm import LlmRequestLog
from app.models.base import (
    League,
    Player,
    Team,
    TeamFundamentals,
    TeamMatch,
    TeamProfile,
)
from app.models.match import (
    MatchEvent,
    MatchGame,
    MatchLlmAnalysis,
    MatchLlmFundAnalysis,
    MatchLlmFundDim,
    MatchLlmPlayRec,
    MatchLlmTrendAnalysis,
    MatchLlmTrendPlay,
    MatchOdds,
    MatchOddsSnapshot,
    MatchResult,
    MatchStatus,
)
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
    "TeamFundamentals",
    "TeamProfile",
    "TeamMatch",
    "MatchGame",
    "MatchEvent",
    "MatchOdds",
    "MatchOddsSnapshot",
    "MatchResult",
    "MatchStatus",
    "MatchLlmAnalysis",
    "MatchLlmFundAnalysis",
    "MatchLlmFundDim",
    "MatchLlmPlayRec",
    "MatchLlmTrendAnalysis",
    "MatchLlmTrendPlay",
    "LlmRequestLog",
    "TeamMatchStat",
    "PlayerMatchPerformance",
    "OddsHistory",
    "Recommendation",
    "UserDecision",
    "DecisionStatus",
]
