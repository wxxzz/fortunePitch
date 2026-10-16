"""大模型赛事复盘服务:对比赛事结果与 AI 分析结果,生成复盘总结与经验教训。

职责:
1. 聚合复盘上下文:比赛信息、官方开奖结果、最近一次 AI 综合分析
   (分玩法推荐)与逐玩法命中比对,另附基本面/走势分析结论与人工录入
   补充信息作为归因参考;
2. 构造中文提示词,要求模型输出结构化 JSON(总结 / 逐玩法归因 / 经验);
3. 调用 OpenAI 兼容接口(复用 llm 模块的调用与日志基础设施);
4. 解析并校验模型输出,连同比对明细快照一并落库。

复盘仅供改进分析方法参考,不构成投注建议。
密钥一律来自环境配置,本模块不落任何凭证。
"""

import dataclasses
import datetime
import json
import logging
import time
import typing

from pydantic import BaseModel, Field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.exceptions import (
    DataValidationError,
    LlmServiceError,
    ResourceNotFoundError,
)
from app.models import (
    MatchGame,
    MatchLlmAnalysis,
    MatchLlmFundAnalysis,
    MatchLlmRetrospect,
    MatchLlmRetrospectItem,
    MatchLlmTrendAnalysis,
    MatchResult,
)
from app.services import llm, llm_query, match_extra_info

logger = logging.getLogger(__name__)

# 复盘经验条数上限(与提示词约定一致,超出部分截断)
_MAX_LESSONS = 5

# 逐玩法归因的长度上限(与明细列宽 String(500) 对齐)
_MAX_REVIEW_LENGTH = 500


# ---------- 上下文与结果模型 ----------


@dataclasses.dataclass(frozen=True)
class RetrospectComparisonItem:
    """单玩法的比对结论(AI 推荐 vs 官方开奖,系统计算,不经模型)。"""

    play_code: str
    play_name: str
    recommendation: str
    confidence: float
    alternatives: list[str]
    # 该玩法的官方开奖结果(未开奖/未开售为 None)
    result: str | None
    # 命中 True / 未中 False / 未开奖 None
    is_hit: bool | None
    # AI 当时的推荐理由
    reasoning: str


@dataclasses.dataclass(frozen=True)
class RetrospectContext:
    """单场比赛的复盘上下文(服务端聚合,提示词唯一数据来源)。"""

    match_id: str
    league_name: str
    season: str
    match_time: datetime.datetime
    home_team_name: str
    away_team_name: str
    # 官方赛果(生成复盘前已校验非空)
    result: MatchResult
    # 被复盘的最近一次 AI 综合分析(含分玩法明细)
    analysis: MatchLlmAnalysis
    # 逐玩法比对结论(全量玩法;未开奖项 result/is_hit 为 None)
    comparison: tuple[RetrospectComparisonItem, ...]
    # 归因参考(未生成过为 None,不注入提示词)
    fundamental_analysis: MatchLlmFundAnalysis | None = None
    trend_analysis: MatchLlmTrendAnalysis | None = None
    # 人工录入补充信息文本块(未录入或全空为 None,不注入提示词)
    extra_info_text: str | None = None


class LlmRetrospectResult(BaseModel):
    """大模型复盘结果(总结 + 逐玩法归因 + 经验教训)。"""

    match_id: str
    analysis_id: int = Field(description="被复盘的综合分析记录 ID")
    provider: str = Field(description="服务商:qwen / ark")
    model: str = Field(description="实际使用的模型名")
    summary: str = Field(description="复盘总结")
    lessons: list[str] = Field(default_factory=list, description="经验教训")
    # 逐玩法事后归因,键为玩法编码;模型未覆盖的玩法无键
    reviews: dict[str, str] = Field(default_factory=dict)


# ---------- 比对与上下文聚合 ----------


def build_comparison(
    analysis: MatchLlmAnalysis, result: MatchResult
) -> tuple[RetrospectComparisonItem, ...]:
    """把最近一次综合分析的分玩法推荐与官方开奖逐玩法比对。

    命中口径复用 llm_query.resolve_recommendation_hit(归一化
    "让球"前缀/"球"后缀),与 AI 分析结果查询页一致;
    未开奖/未开售玩法的 result 与 is_hit 为 None。
    """
    items: list[RetrospectComparisonItem] = []
    for play in analysis.plays:
        play_result: str | None = getattr(
            result, llm_query.RESULT_FIELD_BY_PLAY[play.play_code], None
        )
        items.append(
            RetrospectComparisonItem(
                play_code=play.play_code,
                play_name=play.play_name,
                recommendation=play.recommendation,
                confidence=float(play.confidence),
                alternatives=list(play.alternatives),
                result=play_result,
                is_hit=llm_query.resolve_recommendation_hit(
                    play.play_code, play.recommendation, play_result
                ),
                reasoning=play.reasoning,
            )
        )
    return tuple(items)


def has_drawn_result(result: MatchResult) -> bool:
    """赛果是否已有任一玩法开奖(draw 取"开奖/开彩"义,非平局)。

    取消/无效场次全部开奖字段为空,视为未开奖。
    """
    return any(
        getattr(result, field, None) is not None
        for field in llm_query.RESULT_FIELD_BY_PLAY.values()
    )


async def _load_view_data(
    session: AsyncSession, match_id: str
) -> tuple[
    MatchGame,
    MatchResult | None,
    MatchLlmAnalysis | None,
    tuple[RetrospectComparisonItem, ...],
    MatchLlmFundAnalysis | None,
    MatchLlmTrendAnalysis | None,
    str | None,
]:
    """加载复盘 Tab 展示与生成共用的底层数据。

    不做生成前置校验(赛果缺失/未生成分析时按 None 处理),
    由调用方决定宽松展示(GET 预览)或严格校验(POST 生成)。
    """
    stmt = (
        select(MatchGame)
        .options(
            selectinload(MatchGame.league),
            selectinload(MatchGame.home_team),
            selectinload(MatchGame.away_team),
            selectinload(MatchGame.result),
        )
        .where(MatchGame.match_id == match_id)
    )
    game = (await session.execute(stmt)).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError(MatchGame.__tablename__, match_id)

    result = game.result
    analysis = (
        await session.execute(
            select(MatchLlmAnalysis)
            .options(selectinload(MatchLlmAnalysis.plays))
            .where(MatchLlmAnalysis.match_id == match_id)
            .order_by(MatchLlmAnalysis.analysis_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    comparison: tuple[RetrospectComparisonItem, ...] = ()
    if result is not None and analysis is not None:
        comparison = build_comparison(analysis, result)

    fundamental_analysis = (
        await session.execute(
            select(MatchLlmFundAnalysis)
            .options(selectinload(MatchLlmFundAnalysis.dimensions))
            .where(MatchLlmFundAnalysis.match_id == match_id)
            .order_by(MatchLlmFundAnalysis.analysis_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    trend_analysis = (
        await session.execute(
            select(MatchLlmTrendAnalysis)
            .options(selectinload(MatchLlmTrendAnalysis.plays))
            .where(MatchLlmTrendAnalysis.match_id == match_id)
            .order_by(MatchLlmTrendAnalysis.analysis_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    # 人工录入补充信息(伤停/阵型等):读取失败只降级,不阻断复盘
    try:
        extra_row = await match_extra_info.load_extra_info(session, match_id)
        extra_info_text = match_extra_info.format_extra_info_text(extra_row)
    except Exception:
        logger.warning("补充信息读取失败,跳过归因参考段", exc_info=True)
        extra_info_text = None

    return (
        game,
        result,
        analysis,
        comparison,
        fundamental_analysis,
        trend_analysis,
        extra_info_text,
    )


async def load_retrospect_view(
    session: AsyncSession, match_id: str
) -> tuple[MatchGame, MatchResult | None, MatchLlmAnalysis | None,
           tuple[RetrospectComparisonItem, ...]]:
    """加载复盘 Tab 的比对预览数据(GET 端点用,宽松口径)。

    返回 (比赛, 赛果, 最近一次综合分析, 逐玩法比对);
    赛果未同步或未生成分析时对应项为 None / 空元组。
    """
    game, result, analysis, comparison, _, _, _ = await _load_view_data(
        session, match_id
    )
    return game, result, analysis, comparison


async def build_retrospect_context(
    session: AsyncSession, match_id: str
) -> RetrospectContext:
    """聚合复盘上下文并做生成前置校验(POST 端点用,严格口径)。

    Raises:
        ResourceNotFoundError: 比赛不存在。
        DataValidationError: 赛果未同步 / 未生成过 AI 综合分析 /
            没有任何已开奖玩法可比对。
    """
    game, result, analysis, comparison, fundamental_analysis, trend_analysis, extra_info_text = (
        await _load_view_data(session, match_id)
    )
    if result is None or not has_drawn_result(result):
        raise DataValidationError("赛果未同步或尚未开奖,无法复盘;请先在赛果开奖页同步赛果")
    if analysis is None:
        raise DataValidationError("尚未生成 AI 综合分析,无法复盘;请先在 AI 分析页签生成分析")
    decided = [item for item in comparison if item.is_hit is not None]
    if not decided:
        raise DataValidationError("没有已开奖玩法可比对,无法复盘")

    return RetrospectContext(
        match_id=game.match_id,
        league_name=game.league.league_name,
        season=game.league.season,
        match_time=game.match_time,
        home_team_name=game.home_team.team_name,
        away_team_name=game.away_team.team_name,
        result=result,
        analysis=analysis,
        comparison=comparison,
        fundamental_analysis=fundamental_analysis,
        trend_analysis=trend_analysis,
        extra_info_text=extra_info_text,
    )


# ---------- 提示词构造 ----------


def _or_pending(value: str | None) -> str:
    """开奖字段渲染;未开奖显示占位。"""
    return value if value else "未开奖"


def _format_draw_section(result: MatchResult) -> str:
    """渲染官方开奖结果段(含胜平负 SP)。"""
    sp_values = [result.sp_h, result.sp_d, result.sp_a]
    sp_text = (
        f"(SP {result.sp_h:.2f}/{result.sp_d:.2f}/{result.sp_a:.2f})"
        if all(value is not None for value in sp_values)
        else ""
    )
    goal_line = f"(盘口 {result.goal_line})" if result.goal_line else ""
    lines = [
        f"- 胜平负:{_or_pending(result.had)}{sp_text}",
        f"- 让球胜平负{goal_line}:{_or_pending(result.hhad)}",
        f"- 比分:{_or_pending(result.crs)}",
        f"- 总进球:{_or_pending(result.ttg)}",
        f"- 半全场:{_or_pending(result.hafu)}",
    ]
    return "\n".join(lines)


def _format_comparison_section(context: RetrospectContext) -> str:
    """渲染 AI 推荐与开奖的逐玩法比对段(已开奖玩法逐条列出)。"""
    decided: list[str] = []
    undecided: list[str] = []
    for item in context.comparison:
        line = (
            f"- {item.play_name}({item.play_code}):推荐 {item.recommendation}"
            f"(置信度 {item.confidence:.2f}"
            + (f",次选 {'、'.join(item.alternatives)}" if item.alternatives else "")
            + f")→ 开奖 {item.result} → "
            + ("命中" if item.is_hit else "未中")
            + f"\n  · 当时理由:{item.reasoning}"
        )
        if item.is_hit is None:
            undecided.append(f"{item.play_name}({item.play_code})")
        else:
            decided.append(line)
    section = "\n".join(decided)
    if undecided:
        section += f"\n(另有 {len(undecided)} 种玩法未开奖,不参与复盘:{'、'.join(undecided)})"
    return section


def build_retrospect_messages(context: RetrospectContext) -> list[dict[str, str]]:
    """构造赛事复盘的 system + user 双段提示词。"""
    system_prompt = (
        "你是一名资深足球数据分析师,正在对一场已完赛比赛的 AI 预测做事后复盘。\n"
        "\n"
        "职责与边界:\n"
        "1. 复盘对象是\"AI 综合分析\"的分玩法推荐(赛前生成),比对依据是官方开奖结果;\n"
        "   你的任务是评估分析质量并提炼可复用的经验教训。\n"
        "2. 只做分析方法复盘,不做投注引导;结论仅供改进后续分析方法参考,不构成投注建议。\n"
        "3. 严格基于用户提供的开奖结果与赛前分析数据推理,不得编造比分、赔率或过程。\n"
        "4. 归因须区分\"推理正确\"与\"运气命中\":命中项也要检验推理链是否成立;\n"
        "   未中项须指出是证据缺失、证据权重失衡,还是小概率事件本身。\n"
        "5. 经验教训必须具体、可执行、指向分析方法(如\"某情形应压低置信度或放弃推荐\"),\n"
        "   禁止\"下次注意\"式空话;不得把偶然结果总结为规律。\n"
        "6. 未开奖或取消的玩法不参与复盘,直接跳过。\n"
        "\n"
        "输出要求(必须严格遵守):\n"
        "- 只输出一个 JSON 对象,不得输出 JSON 以外的任何文字(包括解释和 Markdown 代码块标记)。\n"
        "- JSON 结构:\n"
        "{\n"
        '  "summary": "复盘总结,200字以内:整体命中情况与分析偏差的核心原因",\n'
        '  "playReviews": [\n'
        '    {"playCode": "HAD", "review": "该玩法命中/未中归因,60字以内,指出推理链哪里成立或断裂"}\n'
        "  ],\n"
        '  "lessons": ["经验教训,1~5条,每条指向可改进的分析方法"]\n'
        "}\n"
        "- playReviews 须覆盖输入比对表中的每一种已开奖玩法。\n"
        "- 全部用简体中文作答。"
    )

    result = context.result
    half_score = (
        f"{result.half_home_score}:{result.half_away_score}"
        if result.half_home_score is not None and result.half_away_score is not None
        else "未同步"
    )
    full_score = (
        f"{result.full_home_score}:{result.full_away_score}"
        if result.full_home_score is not None and result.full_away_score is not None
        else "未同步"
    )
    risks_text = ";".join(context.analysis.risks) if context.analysis.risks else "无"
    # 归因参考段(基本面/走势结论/人工情报):未生成或未录入时不注入
    reference_sections = ""
    if context.fundamental_analysis is not None:
        reference_sections += (
            f"【AI 基本面分析结论(赛前,归因参考)】\n"
            f"{llm._format_fundamental_conclusion(context.fundamental_analysis)}\n"
            f"\n"
        )
    if context.trend_analysis is not None:
        reference_sections += (
            f"【AI 赔率走势分析结论(赛前,归因参考)】\n"
            f"{llm._format_trend_conclusion(context.trend_analysis)}\n"
            f"\n"
        )
    if context.extra_info_text:
        reference_sections += (
            f"【人工录入补充信息(赛前,评估该情报是否有效)】\n"
            f"{context.extra_info_text}\n"
            f"\n"
        )
    user_prompt = (
        f"请对以下已完赛比赛的 AI 分析结果做事后复盘:\n"
        f"\n"
        f"【比赛信息】\n"
        f"- 联赛:{context.league_name}(赛季 {context.season})\n"
        f"- 对阵:{context.home_team_name}(主)vs {context.away_team_name}(客)\n"
        f"- 开赛时间:{context.match_time.strftime('%Y-%m-%d %H:%M')}\n"
        f"- 半场比分 {half_score},全场比分 {full_score}\n"
        f"\n"
        f"【开奖结果(官方)】\n"
        f"{_format_draw_section(result)}\n"
        f"\n"
        f"【AI 综合分析(赛前生成于 {context.analysis.created_at.strftime('%Y-%m-%d %H:%M')},本次复盘对象)】\n"
        f"- 整体研判:{context.analysis.summary}\n"
        f"- 风险提示:{risks_text}\n"
        f"\n"
        f"【AI 推荐与开奖比对】\n"
        f"{_format_comparison_section(context)}\n"
        f"\n"
        f"{reference_sections}"
        f"请按系统指令输出复盘 JSON。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ---------- 输出解析 ----------


def _parse_retrospect(
    content: str, valid_play_codes: set[str]
) -> tuple[str, dict[str, str], list[str]]:
    """解析并校验模型 JSON 输出,返回 (summary, play_code->归因, lessons)。"""
    try:
        payload = json.loads(llm._extract_json_text(content))
    except json.JSONDecodeError as exc:
        raise LlmServiceError(
            "大模型输出 JSON 解析失败", detail=f"{exc}: {content[:300]}"
        ) from exc

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise LlmServiceError("大模型输出缺少 summary 字段", detail=content[:300])

    reviews: dict[str, str] = {}
    for item in payload.get("playReviews", []):
        if not isinstance(item, dict) or item.get("playCode") not in valid_play_codes:
            logger.warning("忽略一条无法识别的玩法归因: %r", item)
            continue
        review_text = str(item.get("review", "")).strip()[:_MAX_REVIEW_LENGTH]
        if review_text:
            reviews[str(item["playCode"])] = review_text

    lessons_raw = payload.get("lessons", [])
    if not isinstance(lessons_raw, list):
        lessons_raw = []
    lessons = [str(lesson) for lesson in lessons_raw if str(lesson).strip()][
        :_MAX_LESSONS
    ]
    if not lessons:
        raise LlmServiceError(
            "大模型输出中没有有效的经验教训", detail=content[:300]
        )
    return summary, reviews, lessons


# ---------- 复盘入口 ----------


async def analyze_retrospect(context: RetrospectContext) -> LlmRetrospectResult:
    """完整复盘流程:配置解析 -> 提示词 -> 调用 -> 解析校验,全程记录请求日志。"""
    settings = get_settings()
    # 复用 llm 模块的服务商解析与网络调用,保持各 LLM 服务行为一致
    provider, base_url, api_key, model = llm._resolve_provider_config(settings)
    messages = build_retrospect_messages(context)
    request_params = {
        "temperature": 0.3,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
        "analysis_type": "retrospect",
    }
    log_base = {
        "match_id": context.match_id,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "messages": messages,
        "request_params": request_params,
    }
    started = time.monotonic()
    try:
        result = await llm._call_chat(base_url, api_key, model, messages, settings)
    except LlmServiceError as exc:
        await llm._write_request_log(
            **log_base,
            response=None,
            status="FAILED",
            duration_ms=int((time.monotonic() - started) * 1000),
            error=exc,
        )
        raise
    try:
        valid_play_codes = {item.play_code for item in context.comparison}
        summary, reviews, lessons = _parse_retrospect(result.content, valid_play_codes)
    except LlmServiceError as exc:
        await llm._write_request_log(
            **log_base,
            response=result,
            status="FAILED",
            duration_ms=result.duration_ms,
            error=exc,
        )
        raise
    await llm._write_request_log(
        **log_base,
        response=result,
        status="SUCCESS",
        duration_ms=result.duration_ms,
        error=None,
    )
    return LlmRetrospectResult(
        match_id=context.match_id,
        analysis_id=context.analysis.analysis_id,
        provider=provider,
        model=model,
        summary=summary,
        lessons=lessons,
        reviews=reviews,
    )


# ---------- 结果持久化与查询 ----------


async def save_retrospect(
    session: AsyncSession, result: LlmRetrospectResult, context: RetrospectContext
) -> MatchLlmRetrospect:
    """把一次复盘结果落库(主表 + 比对明细快照),返回带主键的 ORM 行。

    明细通过 relationship 级联写入,flush 后即可读取 retrospect_id;
    实际提交由请求级会话依赖完成。
    """
    decided = [item for item in context.comparison if item.is_hit is not None]
    row = MatchLlmRetrospect(
        match_id=result.match_id,
        analysis_id=result.analysis_id,
        provider=result.provider,
        model=result.model,
        summary=result.summary,
        lessons=list(result.lessons),
        hit_count=sum(1 for item in decided if item.is_hit),
        total_count=len(decided),
    )
    row.items = [
        MatchLlmRetrospectItem(
            play_code=item.play_code,
            play_name=item.play_name,
            recommendation=item.recommendation,
            confidence=item.confidence,
            alternatives=list(item.alternatives),
            result=item.result,
            is_hit=item.is_hit,
            reasoning=item.reasoning,
            review=result.reviews.get(item.play_code),
        )
        for item in context.comparison
    ]
    session.add(row)
    await session.flush()
    return row


async def get_latest_retrospect(
    session: AsyncSession, match_id: str
) -> MatchLlmRetrospect | None:
    """查询比赛最近一次已保存的复盘(含比对明细),无记录返回 None。"""
    stmt = (
        select(MatchLlmRetrospect)
        .options(selectinload(MatchLlmRetrospect.items))
        .where(MatchLlmRetrospect.match_id == match_id)
        .order_by(MatchLlmRetrospect.retrospect_id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


__all__ = [
    "RetrospectComparisonItem",
    "RetrospectContext",
    "LlmRetrospectResult",
    "build_comparison",
    "has_drawn_result",
    "load_retrospect_view",
    "build_retrospect_context",
    "build_retrospect_messages",
    "analyze_retrospect",
    "save_retrospect",
    "get_latest_retrospect",
]
