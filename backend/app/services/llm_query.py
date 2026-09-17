"""AI 分析结果查询服务:按售卖日期/置信度/玩法查询已保存的分玩法推荐。

数据来源为深度分析页"AI 分析"落库的结果
(fp_match_llm_analyses + fp_match_llm_play_recs)。
口径:每场比赛只取最近一次分析(历史保留多份,查询以最新为准),
再按玩法与置信度过滤,供"AI 分析结果查询"页展示。
"""

import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import DataValidationError
from app.models import MatchGame, MatchLlmAnalysis, MatchLlmPlayRec

# 竞彩玩法编码(五种玩法选项卡)
PLAY_CODES = ("HAD", "HHAD", "CRS", "TTG", "HAFU")


def current_business_date() -> datetime.date:
    """当前日期(售卖日缺省值,独立函数便于测试打桩)。"""
    return datetime.date.today()


async def query_play_recommendations(
    session: AsyncSession,
    *,
    business_date: datetime.date,
    min_confidence: float = 0.0,
    play_code: str | None = None,
) -> list[MatchLlmPlayRec]:
    """查询某售卖日各场比赛最近一次 AI 分析的分玩法推荐。

    Args:
        session: 异步数据库会话。
        business_date: 竞彩售卖日。
        min_confidence: 置信度下限(含),0~1。
        play_code: 玩法编码过滤,为空返回全部五种玩法。

    Returns:
        推荐明细列表(含比赛/联赛/主客队信息),按置信度倒序。

    Raises:
        DataValidationError: 玩法编码非法。
    """
    if play_code is not None and play_code not in PLAY_CODES:
        raise DataValidationError(
            f"玩法编码必须是 {PLAY_CODES} 之一: {play_code}"
        )

    # 每场比赛最近一次分析的 analysis_id(仅限售卖日当天)
    latest_analysis = (
        select(func.max(MatchLlmAnalysis.analysis_id).label("analysis_id"))
        .select_from(MatchLlmAnalysis)
        .join(MatchGame, MatchGame.match_id == MatchLlmAnalysis.match_id)
        .where(MatchGame.business_date == business_date)
        .group_by(MatchLlmAnalysis.match_id)
        .subquery()
    )

    stmt = (
        select(MatchLlmPlayRec)
        .join(MatchLlmAnalysis, MatchLlmPlayRec.analysis)
        .join(latest_analysis, MatchLlmAnalysis.analysis_id == latest_analysis.c.analysis_id)
        .options(
            joinedload(MatchLlmPlayRec.analysis)
            .joinedload(MatchLlmAnalysis.game)
            .joinedload(MatchGame.home_team),
            joinedload(MatchLlmPlayRec.analysis)
            .joinedload(MatchLlmAnalysis.game)
            .joinedload(MatchGame.away_team),
            joinedload(MatchLlmPlayRec.analysis)
            .joinedload(MatchLlmAnalysis.game)
            .joinedload(MatchGame.league),
        )
        .where(MatchLlmPlayRec.confidence >= min_confidence)
        .order_by(
            MatchLlmPlayRec.confidence.desc(),
            MatchLlmAnalysis.created_at.desc(),
        )
    )
    if play_code is not None:
        stmt = stmt.where(MatchLlmPlayRec.play_code == play_code)
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())
