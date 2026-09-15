"""大模型基本面分析服务:基于球队档案、赛程赛果与积分榜做多维基本面研判。

职责:
1. 从 fp_base_team_profiles / fp_base_team_matches / fp_base_team_fundamentals
   聚合单场比赛的基本面上下文(近期战绩 / 主客场表现 / 后续赛程 / 历史交锋);
2. 构造固定六维度的中文提示词,要求模型输出结构化 JSON;
3. 调用 OpenAI 兼容接口(复用 llm 模块的调用与日志基础设施);
4. 解析并校验模型输出,按维度给出优劣倾向。

密钥一律来自环境配置,本模块不落任何凭证。
"""

import dataclasses
import datetime
import json
import logging
import time
import typing

from pydantic import BaseModel, Field

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    LlmNotConfiguredError,
    LlmServiceError,
    ResourceNotFoundError,
)
from app.core.config import get_settings
from app.models import (
    MatchGame,
    MatchLlmFundAnalysis,
    MatchLlmFundDim,
    MatchStatus,
    TeamFundamentals,
    TeamMatch,
    TeamProfile,
)
from app.services import llm

logger = logging.getLogger(__name__)

# 固定分析维度:编码 -> 展示名(输出顺序与提示词要求一致)
DIMENSION_TITLES: dict[str, str] = {
    "RECENT_FORM": "近期状态",
    "HOME_AWAY": "主客场表现",
    "ATTACK_DEFENSE": "攻防效率",
    "MOTIVATION": "战意与动机",
    "H2H": "历史交锋",
    "OTHER": "其他相关因素",
}

# 优劣倾向合法值
_EDGES = {"home", "away", "even"}

# 近期已赛场次与后续赛程的取样条数
RECENT_MATCH_LIMIT = 8
UPCOMING_MATCH_LIMIT = 2


# ---------- 上下文与结果模型 ----------


@dataclasses.dataclass(frozen=True)
class FundamentalAnalysisContext:
    """单场比赛的基本面分析上下文(服务端聚合,提示词唯一数据来源)。"""

    match_id: str
    league_name: str
    season: str
    match_time: datetime.datetime
    match_status: MatchStatus
    home_team_name: str
    away_team_name: str
    home_profile: TeamProfile | None
    away_profile: TeamProfile | None
    home_fundamentals: TeamFundamentals | None
    away_fundamentals: TeamFundamentals | None
    # 双方近期已赛(按时间倒序)
    home_recent: tuple[TeamMatch, ...]
    away_recent: tuple[TeamMatch, ...]
    # 双方赛后赛程(按时间正序,战意与赛程密度参考)
    home_upcoming: tuple[TeamMatch, ...]
    away_upcoming: tuple[TeamMatch, ...]
    # 历史交锋(从主队看板视角,按时间倒序)
    h2h: tuple[TeamMatch, ...]


class LlmFundamentalDimension(BaseModel):
    """单个基本面维度的分析结论。"""

    code: str = Field(description="维度编码,如 RECENT_FORM")
    title: str = Field(description="维度展示名,如 近期状态")
    edge: str = Field(description="优劣倾向:home=主队占优 / away=客队占优 / even=势均力敌")
    content: str = Field(description="维度分析结论,须引用数据")


class LlmFundamentalAnalysis(BaseModel):
    """大模型基本面分析结果(整体研判 + 六维度结论 + 风险提示)。"""

    match_id: str
    provider: str = Field(description="服务商:qwen / ark")
    model: str = Field(description="实际使用的模型名")
    summary: str = Field(description="整体研判")
    dimensions: list[LlmFundamentalDimension] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


# ---------- 上下文聚合 ----------


async def _load_team_matches(
    session: AsyncSession,
    *,
    team_id: int,
    finished: bool | None,
    since: datetime.datetime | None,
    limit: int,
    order_desc: bool,
    opponent_uniform_id: int | None = None,
) -> tuple[TeamMatch, ...]:
    """按条件加载看板赛程赛果(通用查询助手)。

    Args:
        finished: True=只要已赛(比分非空),False=只要未开赛,None=不限。
        since: 只要该时间之后的比赛(取后续赛程用);None=不限。
        opponent_uniform_id: 限定对手(历史交锋用);None=不限。
    """
    stmt = select(TeamMatch).where(TeamMatch.team_id == team_id)
    if finished is True:
        stmt = stmt.where(TeamMatch.full_home_score.is_not(None))
    elif finished is False:
        stmt = stmt.where(TeamMatch.full_home_score.is_(None))
    if since is not None:
        stmt = stmt.where(TeamMatch.match_time > since)
    if opponent_uniform_id is not None:
        stmt = stmt.where(
            or_(
                TeamMatch.uniform_home_team_id == opponent_uniform_id,
                TeamMatch.uniform_away_team_id == opponent_uniform_id,
            )
        )
    stmt = stmt.order_by(
        TeamMatch.match_time.desc() if order_desc else TeamMatch.match_time
    ).limit(limit)
    return tuple((await session.execute(stmt)).scalars().all())


async def build_fundamental_context(
    session: AsyncSession, match_id: str
) -> FundamentalAnalysisContext:
    """聚合单场比赛的基本面分析上下文,比赛不存在时抛 404。

    档案/基本面/赛程未同步按空数据处理,由提示词明确告知模型
    数据缺口,不得臆造。
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

    home_id = game.home_team_id
    away_id = game.away_team_id
    team_ids = [home_id, away_id]

    profiles_by_team = {
        row.team_id: row
        for row in (
            (await session.execute(select(TeamProfile).where(TeamProfile.team_id.in_(team_ids))))
            .scalars()
            .all()
        )
    }
    fundamentals_by_team = {
        row.team_id: row
        for row in (
            (
                await session.execute(
                    select(TeamFundamentals).where(TeamFundamentals.team_id.in_(team_ids))
                )
            )
            .scalars()
            .all()
        )
    }

    home_profile = profiles_by_team.get(home_id)
    away_profile = profiles_by_team.get(away_id)

    home_recent = await _load_team_matches(
        session, team_id=home_id, finished=True, since=None,
        limit=RECENT_MATCH_LIMIT, order_desc=True,
    )
    away_recent = await _load_team_matches(
        session, team_id=away_id, finished=True, since=None,
        limit=RECENT_MATCH_LIMIT, order_desc=True,
    )
    home_upcoming = await _load_team_matches(
        session, team_id=home_id, finished=False, since=game.match_time,
        limit=UPCOMING_MATCH_LIMIT, order_desc=False,
    )
    away_upcoming = await _load_team_matches(
        session, team_id=away_id, finished=False, since=game.match_time,
        limit=UPCOMING_MATCH_LIMIT, order_desc=False,
    )

    # 历史交锋:从主队看板视角筛出与客队交手的已赛记录,
    # 依赖双方的竞彩网统一球队 ID 映射;无映射时跳过该维度数据。
    away_uniform_id = away_profile.uniform_team_id if away_profile else None
    h2h: tuple[TeamMatch, ...] = ()
    if away_uniform_id is not None:
        h2h = await _load_team_matches(
            session, team_id=home_id, finished=True, since=None,
            limit=RECENT_MATCH_LIMIT, order_desc=True,
            opponent_uniform_id=away_uniform_id,
        )

    return FundamentalAnalysisContext(
        match_id=game.match_id,
        league_name=game.league.league_name,
        season=game.league.season,
        match_time=game.match_time,
        match_status=game.match_status,
        home_team_name=game.home_team.team_name,
        away_team_name=game.away_team.team_name,
        home_profile=home_profile,
        away_profile=away_profile,
        home_fundamentals=fundamentals_by_team.get(home_id),
        away_fundamentals=fundamentals_by_team.get(away_id),
        home_recent=home_recent,
        away_recent=away_recent,
        home_upcoming=home_upcoming,
        away_upcoming=away_upcoming,
        h2h=h2h,
    )


# ---------- 提示词构造 ----------


def _format_profile(team_name: str, profile: TeamProfile | None) -> str:
    """渲染球队档案一行;未同步时给出明确提示。"""
    if profile is None:
        return f"- {team_name}:未同步球队档案"
    full_name = profile.full_name or profile.abbrev_name
    country = f",{profile.country_name}" if profile.country_name else ""
    return f"- {team_name}:全称 {full_name}{country}"


def _format_dashboard_match(row: TeamMatch) -> str:
    """把单条看板赛程/赛果渲染为一行中文文本(以看板球队为视角)。"""
    date = row.match_time.strftime("%Y-%m-%d")
    round_label = row.gameweek or row.phase_name or ""
    comp = row.league_name or "未知赛事"
    if round_label:
        comp = f"{comp}({round_label})"
    opponent = row.away_team_name if row.is_home else row.home_team_name
    venue = "主" if row.is_home else "客"
    if row.full_home_score is None:
        return f"- {date} {comp} {venue}场 vs {opponent}(未开赛)"
    score = f"{row.full_home_score}:{row.full_away_score}"
    half = (
        f",半场 {row.half_home_score}:{row.half_away_score}"
        if row.half_home_score is not None
        else ""
    )
    result = {"W": "胜", "D": "平", "L": "负"}.get(row.team_result or "", "?")
    return f"- {date} {comp} {venue}场 {score} vs {opponent}{half} -> {result}"


def _format_match_list(rows: tuple[TeamMatch, ...], empty_hint: str) -> str:
    """渲染一组看板比赛;为空时输出缺失提示。"""
    if not rows:
        return f"- {empty_hint}"
    return "\n".join(f"- {_format_dashboard_match(row)}" for row in rows)


def build_fundamental_messages(context: FundamentalAnalysisContext) -> list[dict[str, str]]:
    """构造基本面分析的 system + user 双段提示词。"""
    dimension_doc = "\n".join(
        f'    {{"code": "{code}", "title": "{title}", "edge": "home|away|even",\n'
        f'      "content": "{title}维度结论,200字以内,必须引用输入数据"}},'
        for code, title in DIMENSION_TITLES.items()
    )
    system_prompt = (
        "你是一名资深足球数据分析师,为中国体育彩票竞彩玩法提供基本面维度的数据分析。\n"
        "\n"
        "职责与边界:\n"
        "1. 只做基本面数据分析,不做投注引导;结论是数据研判,不构成投注建议。\n"
        "2. 严格基于用户提供的球队档案、积分榜战绩、近期赛程赛果与历史交锋推理,不得编造数据。\n"
        "3. 数据缺失时(如某队未同步近期战绩)必须在对应维度明确说明数据不足,不得臆测,并将该维度 edge 判为 even。\n"
        "\n"
        "分析维度(固定六个,按此顺序输出):\n"
        "1. RECENT_FORM 近期状态:双方近几场的胜平负走势、连胜连败、进球状态;\n"
        "2. HOME_AWAY 主客场表现:主队主场战绩与客队客场战绩的对照;\n"
        "3. ATTACK_DEFENSE 攻防效率:场均进失球、净胜球、攻防两端强弱对比;\n"
        "4. MOTIVATION 战意与动机:积分排名位置、保级/争冠/欧战资格诉求、后续赛程密度;\n"
        "5. H2H 历史交锋:双方交锋往绩与心理优势;\n"
        "6. OTHER 其他相关因素:档案信息、赛程先后、半场表现等其他值得注意的数据。\n"
        "\n"
        "输出要求(必须严格遵守):\n"
        "- 只输出一个 JSON 对象,不得输出 JSON 以外的任何文字(包括解释和 Markdown 代码块标记)。\n"
        "- JSON 结构:\n"
        "{\n"
        '  "summary": "整体研判,150字以内,综合各维度给出基本面倾向",\n'
        '  "dimensions": [\n'
        f"{dimension_doc}\n"
        "  ],\n"
        '  "risks": ["风险提示,1~3条,如数据缺失/状态波动/赛程影响"]\n'
        "}\n"
        "- edge 取值:home=主队占优,away=客队占优,even=势均力敌或数据不足。\n"
        "- 全部用简体中文作答。"
    )

    status_label = llm._STATUS_LABELS.get(
        context.match_status, context.match_status.value
    )
    fmt = llm._format_fundamentals
    user_prompt = (
        f"请基于以下数据对比赛做基本面多维度分析:\n"
        f"\n"
        f"【比赛信息】\n"
        f"- 联赛:{context.league_name}(赛季 {context.season})\n"
        f"- 对阵:{context.home_team_name}(主)vs {context.away_team_name}(客)\n"
        f"- 开赛时间:{context.match_time.strftime('%Y-%m-%d %H:%M')},状态:{status_label}\n"
        f"\n"
        f"【球队档案】\n"
        f"{_format_profile(context.home_team_name, context.home_profile)}\n"
        f"{_format_profile(context.away_team_name, context.away_profile)}\n"
        f"\n"
        f"【主队基本面(积分榜)】\n"
        f"{fmt(context.home_team_name, context.home_fundamentals, '')}\n"
        f"{fmt(context.home_team_name, context.home_fundamentals, 'home_')}\n"
        f"{fmt(context.home_team_name, context.home_fundamentals, 'away_')}\n"
        f"\n"
        f"【客队基本面(积分榜)】\n"
        f"{fmt(context.away_team_name, context.away_fundamentals, '')}\n"
        f"{fmt(context.away_team_name, context.away_fundamentals, 'home_')}\n"
        f"{fmt(context.away_team_name, context.away_fundamentals, 'away_')}\n"
        f"\n"
        f"【主队近期比赛(时间倒序)】\n"
        f"{_format_match_list(context.home_recent, '主队近期赛程赛果未同步(该维度数据不足)')}\n"
        f"\n"
        f"【客队近期比赛(时间倒序)】\n"
        f"{_format_match_list(context.away_recent, '客队近期赛程赛果未同步(该维度数据不足)')}\n"
        f"\n"
        f"【主队后续赛程(战意与赛程密度参考)】\n"
        f"{_format_match_list(context.home_upcoming, '暂无后续赛程数据')}\n"
        f"\n"
        f"【客队后续赛程(战意与赛程密度参考)】\n"
        f"{_format_match_list(context.away_upcoming, '暂无后续赛程数据')}\n"
        f"\n"
        f"【双方历史交锋(从主队视角,时间倒序)】\n"
        f"{_format_match_list(context.h2h, '暂无双方交锋数据')}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ---------- 输出解析 ----------


def _parse_fundamental(
    content: str,
) -> tuple[str, list[LlmFundamentalDimension], list[str]]:
    """解析并校验模型 JSON 输出,返回 (summary, dimensions, risks)。"""
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

    parsed_by_code: dict[str, LlmFundamentalDimension] = {}
    for item in payload.get("dimensions", []):
        if not isinstance(item, dict) or item.get("code") not in DIMENSION_TITLES:
            logger.warning("忽略一条无法识别的维度结论: %r", item)
            continue
        code = str(item["code"])
        edge = str(item.get("edge", "even"))
        if edge not in _EDGES:
            edge = "even"
        content_text = str(item.get("content", "")).strip()
        if not content_text:
            continue
        parsed_by_code[code] = LlmFundamentalDimension(
            code=code,
            title=DIMENSION_TITLES[code],
            edge=edge,
            content=content_text,
        )

    # 按固定维度顺序输出;缺失维度用占位结论补齐,保证前端展示稳定
    dimensions: list[LlmFundamentalDimension] = []
    for code, title in DIMENSION_TITLES.items():
        dimensions.append(
            parsed_by_code.get(code)
            or LlmFundamentalDimension(
                code=code, title=title, edge="even", content="模型未给出该维度结论"
            )
        )
    if not parsed_by_code:
        raise LlmServiceError(
            "大模型输出中没有有效的维度结论", detail=content[:300]
        )
    return summary, dimensions, [str(r) for r in risks]


# ---------- 分析入口 ----------


async def analyze_fundamentals(context: FundamentalAnalysisContext) -> LlmFundamentalAnalysis:
    """完整基本面分析流程:配置解析 -> 提示词 -> 调用 -> 解析校验,全程记录请求日志。"""
    settings = get_settings()
    # 复用 llm 模块的服务商解析与网络调用,保持双服务行为一致
    provider, base_url, api_key, model = llm._resolve_provider_config(settings)
    messages = build_fundamental_messages(context)
    request_params = {
        "temperature": 0.3,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
        "analysis_type": "fundamental",
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
        summary, dimensions, risks = _parse_fundamental(result.content)
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
    return LlmFundamentalAnalysis(
        match_id=context.match_id,
        provider=provider,
        model=model,
        summary=summary,
        dimensions=dimensions,
        risks=risks,
    )


# ---------- 结果持久化 ----------


async def save_fundamental(
    session: AsyncSession, analysis: LlmFundamentalAnalysis
) -> MatchLlmFundAnalysis:
    """把一次基本面分析结果落库(主表 + 维度明细),返回带主键的 ORM 行。

    明细通过 relationship 级联写入,flush 后即可读取 analysis_id / created_at;
    实际提交由请求级会话依赖完成。
    """
    row = MatchLlmFundAnalysis(
        match_id=analysis.match_id,
        provider=analysis.provider,
        model=analysis.model,
        summary=analysis.summary,
        risks=list(analysis.risks),
    )
    row.dimensions = [
        MatchLlmFundDim(
            code=dim.code,
            title=dim.title,
            edge=dim.edge,
            content=dim.content,
        )
        for dim in analysis.dimensions
    ]
    session.add(row)
    await session.flush()
    return row


async def get_latest_fundamental(
    session: AsyncSession, match_id: str
) -> MatchLlmFundAnalysis | None:
    """查询比赛最近一次已保存的基本面分析(含维度明细),无记录返回 None。"""
    stmt = (
        select(MatchLlmFundAnalysis)
        .options(selectinload(MatchLlmFundAnalysis.dimensions))
        .where(MatchLlmFundAnalysis.match_id == match_id)
        .order_by(MatchLlmFundAnalysis.analysis_id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_fundamentals(
    session: AsyncSession, match_id: str
) -> list[MatchLlmFundAnalysis]:
    """查询比赛的历史基本面分析列表(含明细),按生成时间倒序,最多保留最近 20 条。"""
    stmt = (
        select(MatchLlmFundAnalysis)
        .options(selectinload(MatchLlmFundAnalysis.dimensions))
        .where(MatchLlmFundAnalysis.match_id == match_id)
        .order_by(MatchLlmFundAnalysis.analysis_id.desc())
        .limit(llm._ANALYSIS_HISTORY_LIMIT)
    )
    return list((await session.execute(stmt)).scalars().all())


__all__ = [
    "DIMENSION_TITLES",
    "FundamentalAnalysisContext",
    "LlmFundamentalDimension",
    "LlmFundamentalAnalysis",
    "LlmNotConfiguredError",
    "build_fundamental_context",
    "build_fundamental_messages",
    "analyze_fundamentals",
    "save_fundamental",
    "get_latest_fundamental",
    "list_fundamentals",
]
