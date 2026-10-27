"""大模型复盘经验总结服务:归纳各场 AI 复盘的共性经验,供后续综合分析参考。

职责:
1. 收集复盘样本:每场比赛取最近一次赛事复盘(重新生成过复盘的场次
   不重复计),按复盘生成时间倒序取最近 N 场;
2. 构造中文提示词,要求模型归纳跨场次可复用的分析方法经验;
3. 调用 OpenAI 兼容接口(复用 llm 模块的调用与日志基础设施);
4. 解析校验后落库;最近一次总结由 llm 模块注入综合分析提示词。

经验总结仅供改进分析方法参考,不构成投注建议。
密钥一律来自环境配置,本模块不落任何凭证。
"""

import dataclasses
import datetime
import json
import logging
import time

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.exceptions import DataValidationError, LlmServiceError
from app.models import (
    MatchGame,
    MatchLlmLessonSummary,
    MatchLlmRetrospect,
)
from app.services import llm

logger = logging.getLogger(__name__)

# 单次总结输入的复盘场次上限(每场取最近一次复盘,按生成时间倒序)
_INPUT_RETROSPECT_LIMIT = 30

# 归纳后经验条数上限(与提示词约定一致,超出部分截断)
_MAX_LESSONS = 10

# 经验总结调用在请求日志中的 match_id 标识(非比赛 ID,
# 与球队维度分析的 "team:{id}" 同类约定)
LOG_MATCH_ID = "lessons:summary"


# ---------- 上下文与结果模型 ----------


@dataclasses.dataclass(frozen=True)
class RetrospectSample:
    """单场复盘样本(经验总结提示词的最小单元)。"""

    # 场次标识,如 "2026-10-15 英超 阿森纳 vs 埃弗顿"
    match_label: str
    # 该场复盘的总结
    summary: str
    # 该场复盘的经验教训
    lessons: tuple[str, ...]
    # 该场复盘的命中统计(已开奖玩法口径)
    hit_count: int
    total_count: int
    created_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class LessonSummaryContext:
    """经验总结上下文(服务端聚合,提示词唯一数据来源)。"""

    samples: tuple[RetrospectSample, ...]
    # 输入复盘的合计命中统计
    total_hit: int
    total_decided: int


class LlmLessonSummaryResult(BaseModel):
    """大模型经验总结结果(归纳总结 + 共性经验)。"""

    provider: str = Field(description="服务商:qwen / ark")
    model: str = Field(description="实际使用的模型名")
    summary: str = Field(description="经验归纳总结")
    lessons: list[str] = Field(default_factory=list, description="共性经验(5~10条)")
    retrospect_count: int = Field(description="输入覆盖的复盘场次数")
    total_hit: int = Field(description="输入复盘的合计命中数")
    total_decided: int = Field(description="输入复盘的合计已开奖玩法数")
    # 本次总结的请求日志 ID(日志写失败为 None)
    log_id: int | None = Field(default=None)


# ---------- 样本收集与上下文构造 ----------


async def collect_retrospect_samples(
    session: AsyncSession,
) -> tuple[RetrospectSample, ...]:
    """收集复盘样本:每场比赛取最近一次复盘,按生成时间倒序限量。

    重新生成过复盘的场次只计最新一次,避免同场重复加权;
    直接联查比赛/联赛/球队渲染场次标识。
    """
    latest_ids = (
        select(func.max(MatchLlmRetrospect.retrospect_id))
        .group_by(MatchLlmRetrospect.match_id)
        .scalar_subquery()
    )
    stmt = (
        select(MatchLlmRetrospect)
        .options(
            selectinload(MatchLlmRetrospect.game).selectinload(MatchGame.league),
            selectinload(MatchLlmRetrospect.game).selectinload(MatchGame.home_team),
            selectinload(MatchLlmRetrospect.game).selectinload(MatchGame.away_team),
        )
        .where(MatchLlmRetrospect.retrospect_id.in_(latest_ids))
        .order_by(MatchLlmRetrospect.retrospect_id.desc())
        .limit(_INPUT_RETROSPECT_LIMIT)
    )
    rows = list((await session.execute(stmt)).scalars().all())

    samples: list[RetrospectSample] = []
    for row in rows:
        game = row.game
        samples.append(
            RetrospectSample(
                match_label=(
                    f"{game.match_time.strftime('%Y-%m-%d')} {game.league.league_name} "
                    f"{game.home_team.team_name} vs {game.away_team.team_name}"
                ),
                summary=row.summary,
                lessons=tuple(row.lessons),
                hit_count=row.hit_count,
                total_count=row.total_count,
                created_at=row.created_at,
            )
        )
    return tuple(samples)


async def build_lesson_context(session: AsyncSession) -> LessonSummaryContext:
    """聚合经验总结上下文并做生成前置校验(POST 端点用,严格口径)。

    Raises:
        DataValidationError: 尚无任何已生成的 AI 复盘。
    """
    samples = await collect_retrospect_samples(session)
    if not samples:
        raise DataValidationError(
            "尚无已生成的 AI 复盘,无法总结经验;请先在深度分析页生成赛事复盘"
        )
    return LessonSummaryContext(
        samples=samples,
        total_hit=sum(sample.hit_count for sample in samples),
        total_decided=sum(sample.total_count for sample in samples),
    )


# ---------- 提示词构造 ----------


def _format_sample(sample: RetrospectSample) -> str:
    """把单场复盘样本渲染为一个文本块。"""
    lessons_text = "; ".join(sample.lessons) if sample.lessons else "无"
    return (
        f"- {sample.match_label} "
        f"(复盘生成于 {sample.created_at.strftime('%Y-%m-%d')}, "
        f"命中 {sample.hit_count}/{sample.total_count}):\n"
        f"  · 复盘总结:{sample.summary}\n"
        f"  · 经验教训:{lessons_text}"
    )


def build_lesson_messages(context: LessonSummaryContext) -> list[dict[str, str]]:
    """构造经验总结的 system + user 双段提示词。"""
    system_prompt = (
        "你是一名资深足球数据分析师,正在对多场已完赛比赛的 AI 复盘做二次归纳,\n"
        "提炼跨场次可复用的分析方法经验。\n"
        "\n"
        "职责与边界:\n"
        "1. 只做分析方法归纳,不做投注引导;结论仅供改进后续分析方法参考,不构成投注建议。\n"
        "2. 严格基于用户提供的复盘内容归纳,不得编造;共性 = 至少两场复盘中出现同类问题或结论。\n"
        "3. 区分\"推理正确命中\"与\"运气命中\"的归因;不得把偶发结果总结为规律。\n"
        "4. 经验必须具体、可执行、指向分析方法(如置信度校准、某类盘口的处理方式),\n"
        "   禁止\"下次注意\"式空话。\n"
        "5. 合并同类经验去重后输出 5~10 条;样本不足时允许少于 5 条,但须在 summary 中说明。\n"
        "\n"
        "输出要求(必须严格遵守):\n"
        "- 只输出一个 JSON 对象,不得输出 JSON 以外的任何文字(包括解释和 Markdown 代码块标记)。\n"
        "- JSON 结构:\n"
        "{\n"
        '  "summary": "经验归纳总结,200字以内:输入复盘的整体命中水平与共性偏差",\n'
        '  "lessons": ["共性经验,5~10条,每条指向可改进的分析方法"]\n'
        "}\n"
        "- 全部用简体中文作答。"
    )

    samples_text = "\n".join(_format_sample(sample) for sample in context.samples)
    user_prompt = (
        f"请对以下 {len(context.samples)} 场 AI 赛事复盘进行共性归纳,"
        f"输出可复用的分析方法经验:\n"
        f"\n"
        f"【复盘样本({len(context.samples)} 场,"
        f"合计命中 {context.total_hit}/{context.total_decided} 已开奖玩法)】\n"
        f"{samples_text}\n"
        f"\n"
        f"请按系统指令输出经验总结 JSON。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ---------- 输出解析 ----------


def _parse_lesson_summary(content: str) -> tuple[str, list[str]]:
    """解析并校验模型 JSON 输出,返回 (summary, lessons)。"""
    try:
        payload = json.loads(llm._extract_json_text(content))
    except json.JSONDecodeError as exc:
        raise LlmServiceError(
            "大模型输出 JSON 解析失败", detail=f"{exc}: {content[:300]}"
        ) from exc

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise LlmServiceError("大模型输出缺少 summary 字段", detail=content[:300])

    lessons_raw = payload.get("lessons", [])
    if not isinstance(lessons_raw, list):
        lessons_raw = []
    lessons = [str(lesson) for lesson in lessons_raw if str(lesson).strip()][
        :_MAX_LESSONS
    ]
    if not lessons:
        raise LlmServiceError("大模型输出中没有有效的经验条目", detail=content[:300])
    return summary, lessons


# ---------- 总结入口 ----------


async def analyze_lessons(context: LessonSummaryContext) -> LlmLessonSummaryResult:
    """完整总结流程:配置解析 -> 提示词 -> 调用 -> 解析校验,全程记录请求日志。"""
    settings = get_settings()
    # 复用 llm 模块的服务商解析与网络调用,保持各 LLM 服务行为一致
    provider, base_url, api_key, model = llm._resolve_provider_config(settings)
    messages = build_lesson_messages(context)
    request_params = {
        "temperature": 0.3,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
        "analysis_type": "lesson_summary",
    }
    log_base = {
        "match_id": LOG_MATCH_ID,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "messages": messages,
        "request_params": request_params,
    }
    log_id: int | None = None
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
        summary, lessons = _parse_lesson_summary(result.content)
    except LlmServiceError as exc:
        await llm._write_request_log(
            **log_base,
            response=result,
            status="FAILED",
            duration_ms=result.duration_ms,
            error=exc,
        )
        raise
    log_id = await llm._write_request_log(
        **log_base,
        response=result,
        status="SUCCESS",
        duration_ms=result.duration_ms,
        error=None,
    )
    return LlmLessonSummaryResult(
        provider=provider,
        model=model,
        summary=summary,
        lessons=lessons,
        retrospect_count=len(context.samples),
        total_hit=context.total_hit,
        total_decided=context.total_decided,
        log_id=log_id,
    )


# ---------- 结果持久化与查询 ----------


async def save_lesson_summary(
    session: AsyncSession, result: LlmLessonSummaryResult
) -> MatchLlmLessonSummary:
    """把一次经验总结结果落库,返回带主键的 ORM 行。

    flush 后即可读取 summary_id;实际提交由请求级会话依赖完成。
    """
    row = MatchLlmLessonSummary(
        provider=result.provider,
        model=result.model,
        summary=result.summary,
        lessons=list(result.lessons),
        retrospect_count=result.retrospect_count,
        total_hit=result.total_hit,
        total_decided=result.total_decided,
        log_id=result.log_id,
    )
    session.add(row)
    await session.flush()
    return row


async def list_lesson_summaries(
    session: AsyncSession, *, limit: int = 20
) -> list[MatchLlmLessonSummary]:
    """查询经验总结历史,按生成时间倒序。"""
    stmt = (
        select(MatchLlmLessonSummary)
        .order_by(MatchLlmLessonSummary.summary_id.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


__all__ = [
    "RetrospectSample",
    "LessonSummaryContext",
    "LlmLessonSummaryResult",
    "LOG_MATCH_ID",
    "collect_retrospect_samples",
    "build_lesson_context",
    "build_lesson_messages",
    "analyze_lessons",
    "save_lesson_summary",
    "list_lesson_summaries",
]
