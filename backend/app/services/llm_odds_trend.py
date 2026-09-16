"""大模型赔率走势分析服务:基于赔率快照序列做市场动向研判。

职责:
1. 从 fp_match_odds_snapshots 聚合单场比赛的赔率走势上下文(时间正序);
2. 构造中文提示词,要求模型输出结构化 JSON(整体研判 + 分玩法走势结论);
3. 调用 OpenAI 兼容接口(复用 llm 模块的调用与日志基础设施);
4. 解析并校验模型输出,按玩法给出走势信号与置信度。

密钥一律来自环境配置,本模块不落任何凭证。
"""

import dataclasses
import datetime
import json
import logging
import time
import typing

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    DataValidationError,
    LlmNotConfiguredError,
    LlmServiceError,
    ResourceNotFoundError,
)
from app.core.config import get_settings
from app.models import (
    MatchGame,
    MatchLlmTrendAnalysis,
    MatchLlmTrendPlay,
    MatchOddsSnapshot,
)
from app.services import llm

logger = logging.getLogger(__name__)

# 提示词最多携带的快照条数(时间正序取最近 N 条,防止提示词过长)
_SNAPSHOT_LIMIT = 50

# 输出字段截断上限(与库表列宽对齐,避免超长输出在调用成功后落库失败)
_SIGNAL_MAX_LENGTH = 32
_REASONING_MAX_LENGTH = 500


# ---------- 上下文与结果模型 ----------


@dataclasses.dataclass(frozen=True)
class TrendAnalysisContext:
    """单场比赛的赔率走势分析上下文(服务端聚合,提示词唯一数据来源)。"""

    match_id: str
    league_name: str
    season: str
    match_time: datetime.datetime
    home_team_name: str
    away_team_name: str
    # 赔率快照(时间正序,最多最近 50 条)
    snapshots: tuple[MatchOddsSnapshot, ...]


class LlmTrendPlayConclusion(BaseModel):
    """单种玩法的走势结论(模型输出经校验后的载体)。"""

    play_code: str = Field(description="玩法编码:HAD/HHAD/CRS/TTG/HAFU")
    play_name: str = Field(description="玩法展示名,如 胜平负")
    signal: str = Field(description="走势信号,如 主胜走强 / 平局赔率抬升 / 盘口稳定")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度,0~1")
    reasoning: str = Field(description="走势解读,必须引用快照赔率数据")


class LlmTrendAnalysis(BaseModel):
    """大模型赔率走势分析结果(整体研判 + 分玩法走势结论 + 风险提示)。"""

    match_id: str
    provider: str = Field(description="服务商:qwen / ark")
    model: str = Field(description="实际使用的模型名")
    summary: str = Field(description="整体研判")
    plays: list[LlmTrendPlayConclusion] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


# ---------- 上下文聚合 ----------


async def build_trend_context(session: AsyncSession, match_id: str) -> TrendAnalysisContext:
    """聚合单场比赛的赔率走势上下文,比赛不存在抛 404,无快照抛 422。

    快照按时间正序取最近 _SNAPSHOT_LIMIT 条(倒序查询后反转),
    保证提示词呈现的是离当前最近的完整走势区间。
    """
    game_stmt = (
        select(MatchGame)
        .options(
            selectinload(MatchGame.league),
            selectinload(MatchGame.home_team),
            selectinload(MatchGame.away_team),
        )
        .where(MatchGame.match_id == match_id)
    )
    game = (await session.execute(game_stmt)).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError(MatchGame.__tablename__, match_id)

    snapshot_stmt = (
        select(MatchOddsSnapshot)
        .where(MatchOddsSnapshot.match_id == match_id)
        .order_by(MatchOddsSnapshot.snapshot_time.desc())
        .limit(_SNAPSHOT_LIMIT)
    )
    rows = (await session.execute(snapshot_stmt)).scalars().all()
    snapshots = tuple(reversed(list(rows)))
    if not snapshots:
        raise DataValidationError(
            "暂无赔率走势数据,请先在数据采集页执行赛事同步,生成赔率快照后再分析"
        )

    return TrendAnalysisContext(
        match_id=game.match_id,
        league_name=game.league.league_name,
        season=game.league.season,
        match_time=game.match_time,
        home_team_name=game.home_team.team_name,
        away_team_name=game.away_team.team_name,
        snapshots=snapshots,
    )


# ---------- 提示词构造 ----------


def _format_snapshot(snapshot: MatchOddsSnapshot) -> str:
    """把一条赔率快照渲染为一行中文文本(时间 + 各玩法赔率)。"""
    timestamp = snapshot.snapshot_time.strftime("%m-%d %H:%M")
    blocks: list[str] = []
    for pool in snapshot.pools:
        code = str(pool.get("poolCode", ""))
        play_name = llm.PLAY_NAMES.get(code, str(pool.get("playName", code)))
        goal_line = pool.get("goalLine")
        header = play_name + (f"({goal_line})" if goal_line else "")
        options = pool.get("options") or []
        option_text = "/".join(
            f"{opt.get('label')}{opt.get('odds')}" for opt in options
        )
        blocks.append(f"{header}:{option_text or '无选项'}")
    return f"- {timestamp} {' ; '.join(blocks)}"


def build_trend_messages(context: TrendAnalysisContext) -> list[dict[str, str]]:
    """构造赔率走势分析的 system + user 双段提示词。"""
    system_prompt = (
        "你是一名资深竞彩赔率分析师,为中国体育彩票竞彩玩法提供赔率走势维度的数据分析。\n"
        "\n"
        "职责与边界:\n"
        "1. 只做数据分析,不做投注引导;结论是市场动向研判,不构成投注建议。\n"
        "2. 严格基于用户提供的赔率快照序列(时间正序)推理,不得编造数据。\n"
        "3. 赔率下降表示市场资金看好该选项,赔率上升表示看淡;"
        "可将各选项隐含概率(1/赔率)归一后对照走势变化,判断市场倾向的迁移。\n"
        "4. 快照序列仅 1 条时,说明暂无变化趋势可供研判,必须在对应玩法"
        "明确说明数据不足,并将置信度显著降低。\n"
        "5. 关注走势中的异动点:单边持续走低、反向抬升、水位反复震荡,"
        "并区分正常升降与临场突变。\n"
        "\n"
        "输出要求(必须严格遵守):\n"
        "- 只输出一个 JSON 对象,不得输出 JSON 以外的任何文字(包括解释和 Markdown 代码块标记)。\n"
        "- JSON 结构:\n"
        "{\n"
        '  "summary": "整体研判,150字以内,概括市场资金倾向与赔率异动",\n'
        '  "plays": [\n'
        "    {\n"
        '      "playCode": "HAD",\n'
        '      "signal": "走势信号,如 主胜走强 / 平局赔率抬升 / 盘口稳定",\n'
        '      "confidence": 0.55,\n'
        '      "reasoning": "走势解读,80字以内,必须引用快照中的具体赔率变化"\n'
        "    }\n"
        "  ],\n"
        '  "risks": ["风险提示,1~3条,如临场异动/快照不足/水位反复"]\n'
        "}\n"
        "- plays 必须覆盖快照数据中出现的每一种玩法,playCode 取 HAD/HHAD/CRS/TTG/HAFU。\n"
        "- confidence 为 0~1 的小数;快照条数少或走势反复无明确方向时给低值。\n"
        "- 全部用简体中文作答。"
    )

    user_prompt = (
        f"请基于以下赔率走势快照对比赛做市场动向分析:\n"
        f"\n"
        f"【比赛信息】\n"
        f"- 联赛:{context.league_name}(赛季 {context.season})\n"
        f"- 对阵:{context.home_team_name}(主)vs {context.away_team_name}(客)\n"
        f"- 开赛时间:{context.match_time.strftime('%Y-%m-%d %H:%M')}\n"
        f"\n"
        f"【赔率走势快照(时间正序,共 {len(context.snapshots)} 条)】\n"
        + "\n".join(_format_snapshot(s) for s in context.snapshots)
    )
    if len(context.snapshots) == 1:
        user_prompt += "\n\n(注意:当前仅有 1 条快照,暂无变化趋势,各玩法置信度必须显著降低)"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ---------- 输出解析 ----------


def _parse_trend(content: str) -> tuple[str, list[LlmTrendPlayConclusion], list[str]]:
    """解析并校验模型 JSON 输出,返回 (summary, plays, risks)。"""
    try:
        payload = json.loads(llm._extract_json_text(content))
    except json.JSONDecodeError as exc:
        raise LlmServiceError(
            "大模型输出 JSON 解析失败", detail=f"{exc}: {content[:300]}"
        ) from exc

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise LlmServiceError("大模型输出缺少 summary 字段", detail=content[:300])

    risks = payload.get("risks", [])
    if not isinstance(risks, list):
        risks = []

    plays: list[LlmTrendPlayConclusion] = []
    for item in payload.get("plays", []):
        if not isinstance(item, dict) or item.get("playCode") not in llm.PLAY_NAMES:
            continue
        try:
            plays.append(
                LlmTrendPlayConclusion(
                    play_code=item["playCode"],
                    play_name=llm.PLAY_NAMES[item["playCode"]],
                    # 截断到库表列宽,避免超长输出在调用成功后落库失败
                    signal=str(item.get("signal", ""))[:_SIGNAL_MAX_LENGTH],
                    confidence=float(item.get("confidence", 0.0)),
                    reasoning=str(item.get("reasoning", ""))[:_REASONING_MAX_LENGTH],
                )
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            logger.warning("忽略一条无法解析的走势结论: %r", item)
    if not plays:
        raise LlmServiceError("大模型输出中没有有效的走势结论", detail=content[:300])
    return summary, plays, [str(r) for r in risks]


# ---------- 分析入口 ----------


async def analyze_odds_trend(context: TrendAnalysisContext) -> LlmTrendAnalysis:
    """完整走势分析流程:配置解析 -> 提示词 -> 调用 -> 解析校验,全程记录请求日志。"""
    settings = get_settings()
    # 复用 llm 模块的服务商解析与网络调用,保持各分析服务行为一致
    provider, base_url, api_key, model = llm._resolve_provider_config(settings)
    messages = build_trend_messages(context)
    request_params = {
        "temperature": 0.3,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
        "analysis_type": "odds_trend",
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
        summary, plays, risks = _parse_trend(result.content)
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
    return LlmTrendAnalysis(
        match_id=context.match_id,
        provider=provider,
        model=model,
        summary=summary,
        plays=plays,
        risks=risks,
    )


# ---------- 结果持久化 ----------


async def save_trend_analysis(
    session: AsyncSession, analysis: LlmTrendAnalysis
) -> MatchLlmTrendAnalysis:
    """把一次走势分析结果落库(主表 + 分玩法明细),返回带主键的 ORM 行。

    明细通过 relationship 级联写入,flush 后即可读取 analysis_id / created_at;
    实际提交由请求级会话依赖完成。
    """
    row = MatchLlmTrendAnalysis(
        match_id=analysis.match_id,
        provider=analysis.provider,
        model=analysis.model,
        summary=analysis.summary,
        risks=list(analysis.risks),
    )
    row.plays = [
        MatchLlmTrendPlay(
            play_code=play.play_code,
            play_name=play.play_name,
            signal=play.signal,
            confidence=play.confidence,
            reasoning=play.reasoning,
        )
        for play in analysis.plays
    ]
    session.add(row)
    await session.flush()
    return row


async def get_latest_trend_analysis(
    session: AsyncSession, match_id: str
) -> MatchLlmTrendAnalysis | None:
    """查询比赛最近一次已保存的走势分析(含分玩法明细),无记录返回 None。"""
    stmt = (
        select(MatchLlmTrendAnalysis)
        .options(selectinload(MatchLlmTrendAnalysis.plays))
        .where(MatchLlmTrendAnalysis.match_id == match_id)
        .order_by(MatchLlmTrendAnalysis.analysis_id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_trend_analyses(
    session: AsyncSession, match_id: str
) -> list[MatchLlmTrendAnalysis]:
    """查询比赛的历史走势分析列表(含明细),按生成时间倒序,最多保留最近 20 条。"""
    stmt = (
        select(MatchLlmTrendAnalysis)
        .options(selectinload(MatchLlmTrendAnalysis.plays))
        .where(MatchLlmTrendAnalysis.match_id == match_id)
        .order_by(MatchLlmTrendAnalysis.analysis_id.desc())
        .limit(llm._ANALYSIS_HISTORY_LIMIT)
    )
    return list((await session.execute(stmt)).scalars().all())


__all__ = [
    "TrendAnalysisContext",
    "LlmTrendPlayConclusion",
    "LlmTrendAnalysis",
    "LlmNotConfiguredError",
    "build_trend_context",
    "build_trend_messages",
    "analyze_odds_trend",
    "save_trend_analysis",
    "get_latest_trend_analysis",
    "list_trend_analyses",
]
