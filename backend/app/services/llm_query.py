"""AI 分析结果查询服务:按售卖日期/置信度/玩法查询已保存的分玩法推荐。

数据来源为深度分析页"AI 分析"落库的结果
(fp_match_llm_analyses + fp_match_llm_play_recs)。
口径:每场比赛只取最近一次分析(历史保留多份,查询以最新为准),
再按玩法与置信度过滤,供"AI 分析结果查询"页展示。
"""

import datetime
import typing

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import DataValidationError
from app.models import MatchGame, MatchLlmAnalysis, MatchLlmPlayRec

# 竞彩玩法编码(五种玩法选项卡)
PLAY_CODES = ("HAD", "HHAD", "CRS", "TTG", "HAFU")

# 玩法编码 -> fp_match_results 中的开奖结果字段
RESULT_FIELD_BY_PLAY = {
    "HAD": "had",
    "HHAD": "hhad",
    "CRS": "crs",
    "TTG": "ttg",
    "HAFU": "hafu",
}


def resolve_recommendation_option(
    pools: list[dict[str, typing.Any]] | None,
    play_code: str,
    recommendation: str,
) -> dict[str, typing.Any] | None:
    """从当前在售赔率池中解析推荐选项,返回匹配的完整选项。

    匹配顺序(逐级回退,全部失败返回 None):
    1. 归一化精确匹配(处理让球"让球主胜"vs"主胜"、总进球
       "3球"vs"3"这类文案差异,与命中比对口径一致);
    2. 原始展示名精确匹配;
    3. "推荐文案包含选项名"的最长子串匹配(避免"平"抢先命中
       "让球平"这类文案);
    4. 仅接受赔率可转 float 且 > 0 的选项。

    Args:
        pools: fp_match_odds.pools 归一化玩法列表(可为 None)。
        play_code: 玩法编码。
        recommendation: 推荐选项展示名。

    Returns:
        匹配的选项 dict(含 code/label/odds);无法解析时为 None。
    """
    if not pools:
        return None
    pool = next((p for p in pools if p.get("poolCode") == play_code), None)
    if pool is None:
        return None
    options = [o for o in pool.get("options") or [] if isinstance(o, dict)]
    text = str(recommendation or "").strip()
    if not text:
        return None
    normalized_text = _normalize_play_label(play_code, text)

    def _valid(option: dict[str, typing.Any]) -> bool:
        try:
            return float(option.get("odds")) > 0
        except (TypeError, ValueError):
            return False

    candidates = [o for o in options if _valid(o)]
    # 1. 归一化精确匹配
    matched = next(
        (
            o
            for o in candidates
            if _normalize_play_label(play_code, str(o.get("label") or ""))
            == normalized_text
        ),
        None,
    )
    # 2. 原始展示名精确匹配
    if matched is None:
        matched = next(
            (o for o in candidates if str(o.get("label") or "") == text), None
        )
    # 3. 最长子串回退
    if matched is None:
        substring_hits = [
            o
            for o in candidates
            if str(o.get("label") or "") and str(o["label"]) in text
        ]
        matched = max(substring_hits, key=lambda o: len(str(o["label"])), default=None)
    return matched


def resolve_recommendation_odds(
    pools: list[dict[str, typing.Any]] | None,
    play_code: str,
    recommendation: str,
) -> float | None:
    """从当前在售赔率池中解析推荐选项的最新赔率。

    resolve_recommendation_option 的薄包装,仅取匹配选项的赔率;
    未开售或赔率未同步时返回 None。
    """
    matched = resolve_recommendation_option(pools, play_code, recommendation)
    if matched is None:
        return None
    try:
        value = float(matched.get("odds"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _normalize_play_label(play_code: str, text: str) -> str:
    """归一化玩法选项文案,便于推荐与开奖结果比对。

    去掉两端空白;让球玩法模型可能带/不带"让球"前缀(如"让球主胜" vs
    开奖"让球主胜"或推荐"主胜"),统一剥掉;总进球推荐常带"球"后缀
    (如"3球" vs 开奖"3"),统一剥掉。
    """
    normalized = str(text or "").strip()
    if normalized.startswith("让球"):
        normalized = normalized[2:]
    if play_code == "TTG" and normalized.endswith("球"):
        normalized = normalized[:-1]
    return normalized


def resolve_recommendation_hit(
    play_code: str,
    recommendation: str,
    result: str | None,
) -> bool | None:
    """比对推荐选项与该玩法的赛果开奖结果。

    推荐与开奖文案均归一化后精确比对(模型输出与开奖页口径可能存在
    "让球"前缀/"球"后缀差异)。未同步赛果(未开奖)时返回 None。

    Args:
        play_code: 玩法编码。
        recommendation: 推荐选项展示名。
        result: 该玩法的开奖结果标签(如"客胜"/"让球主胜"/"1:2"/"3"/"负负")。

    Returns:
        命中为 True,未中为 False,未开奖为 None。
    """
    if not result:
        return None
    return _normalize_play_label(play_code, recommendation) == _normalize_play_label(
        play_code, result
    )


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
            # 当前在售赔率池,用于解析推荐选项的最新赔率
            joinedload(MatchLlmPlayRec.analysis)
            .joinedload(MatchLlmAnalysis.game)
            .joinedload(MatchGame.odds),
            # 赛果开奖数据,用于推荐与赛果的命中比对
            joinedload(MatchLlmPlayRec.analysis)
            .joinedload(MatchLlmAnalysis.game)
            .joinedload(MatchGame.result),
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
