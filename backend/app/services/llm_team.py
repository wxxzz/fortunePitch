"""大模型球队维度分析服务:进攻/防守/主客等多维度研判单支球队。

职责:
1. 从 fp_base_teams / fp_base_team_profiles / fp_base_team_fundamentals /
   fp_base_team_matches / fp_analytics_team_ratings 聚合单支球队的档案上下文
   (赛季战绩 / 近期赛果 / 后续赛程 / Elo 评分);
2. 构造固定六维度的中文提示词,要求模型输出结构化 JSON;
3. 调用 OpenAI 兼容接口(复用 llm 模块的调用与日志基础设施);
4. 解析并校验模型输出,按维度给出强/中/弱评级。

调用日志写入 fp_llm_request_logs(match_id 列存 "team:{team_id}" 标识,
request_params.analysis_type="team");密钥一律来自环境配置,本模块不落任何凭证。
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

from app.core.exceptions import (
    LlmNotConfiguredError,
    LlmServiceError,
    ResourceNotFoundError,
)
from app.core.config import get_settings
from app.models import (
    League,
    Team,
    TeamFundamentals,
    TeamLlmAnalysis,
    TeamLlmAnalysisDim,
    TeamMatch,
    TeamProfile,
    TeamRating,
)
from app.services import llm, llm_fundamental

logger = logging.getLogger(__name__)

# 固定分析维度:编码 -> 展示名(输出顺序与提示词要求一致)
DIMENSION_TITLES: dict[str, str] = {
    "ATTACK": "进攻能力",
    "DEFENSE": "防守能力",
    "HOME_FORM": "主场表现",
    "AWAY_FORM": "客场表现",
    "RECENT_FORM": "近期状态",
    "OTHER": "其他因素",
}

# 维度评级合法值
_RATINGS = {"strong", "average", "weak"}

# 维度结论最大长度(与 fp_llm_team_analysis_dims.dim_content 列宽一致)
_DIM_CONTENT_MAX = 1000

# 近期已赛场次与后续赛程的取样条数
RECENT_MATCH_LIMIT = 10
UPCOMING_MATCH_LIMIT = 3

# 球队维度分析在请求日志中的调用类型标识
ANALYSIS_TYPE = "team"


# ---------- 上下文与结果模型 ----------


@dataclasses.dataclass(frozen=True)
class TeamAnalysisContext:
    """单支球队的分析上下文(服务端聚合,提示词唯一数据来源)。"""

    team_id: int
    team_name: str
    league_name: str
    season: str
    profile: TeamProfile | None
    fundamentals: TeamFundamentals | None
    # 近期已赛(按时间倒序)
    recent: tuple[TeamMatch, ...]
    # 后续赛程(按时间正序,赛程密度参考)
    upcoming: tuple[TeamMatch, ...]
    # Elo 评分(未重算过为 None)
    elo: TeamRating | None


class LlmTeamDimension(BaseModel):
    """单个球队维度的分析结论。"""

    code: str = Field(description="维度编码,如 ATTACK")
    title: str = Field(description="维度展示名,如 进攻能力")
    rating: str = Field(description="评级:strong=强 / average=中 / weak=弱")
    content: str = Field(description="维度分析结论,须引用数据")


class LlmTeamAnalysis(BaseModel):
    """大模型球队维度分析结果(整体研判 + 六维度结论 + 风险提示)。"""

    team_id: int
    provider: str = Field(description="服务商:qwen / ark")
    model: str = Field(description="实际使用的模型名")
    summary: str = Field(description="整体研判")
    dimensions: list[LlmTeamDimension] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


# ---------- 上下文聚合 ----------


async def build_team_context(
    session: AsyncSession, team_id: int
) -> TeamAnalysisContext:
    """聚合单支球队的分析上下文,球队不存在时抛 404。

    档案/基本面/赛程/Elo 未同步按空数据处理,由提示词明确告知模型
    数据缺口,不得臆造。
    """
    team = await session.get(Team, team_id)
    if team is None:
        raise ResourceNotFoundError(Team.__tablename__, str(team_id))
    league = await session.get(League, team.league_id)

    recent = await llm_fundamental._load_team_matches(
        session, team_id=team_id, finished=True, since=None,
        limit=RECENT_MATCH_LIMIT, order_desc=True,
    )
    upcoming = await llm_fundamental._load_team_matches(
        session, team_id=team_id, finished=False,
        since=datetime.datetime.now(), limit=UPCOMING_MATCH_LIMIT, order_desc=False,
    )

    return TeamAnalysisContext(
        team_id=team.team_id,
        team_name=team.team_name,
        league_name=league.league_name if league else "未知联赛",
        season=league.season if league else "-",
        profile=await session.get(TeamProfile, team_id),
        fundamentals=await session.get(TeamFundamentals, team_id),
        recent=recent,
        upcoming=upcoming,
        elo=await session.get(TeamRating, team_id),
    )


# ---------- 提示词构造 ----------


def _format_elo(context: TeamAnalysisContext) -> str:
    """渲染 Elo 评分行;未重算时给出明确提示。"""
    if context.elo is None:
        return f"- {context.team_name}:Elo 评分未重算(该维度数据缺失)"
    return (
        f"- {context.team_name}:当前评分 {float(context.elo.rating):.0f},"
        f"参与评分 {context.elo.matches_played} 场"
    )


def build_team_messages(context: TeamAnalysisContext) -> list[dict[str, str]]:
    """构造球队维度分析的 system + user 双段提示词。"""
    dimension_doc = "\n".join(
        f'    {{"code": "{code}", "title": "{title}", "rating": "strong|average|weak",\n'
        f'      "content": "{title}维度结论,200字以内,必须引用输入数据"}},'
        for code, title in DIMENSION_TITLES.items()
    )
    system_prompt = (
        "你是一名资深足球数据分析师,为中国体育彩票竞彩玩法提供球队档案维度的数据分析。\n"
        "\n"
        "职责与边界:\n"
        "1. 只做球队表现的数据分析,不做投注引导;结论是数据研判,不构成投注建议。\n"
        "2. 严格基于用户提供的球队档案、积分榜战绩、看板赛程赛果与 Elo 评分推理,"
        "不得编造数据。\n"
        "3. 数据缺失时(如未同步积分榜或近期赛果)必须在对应维度明确说明数据不足,"
        "不得臆测,并将该维度 rating 判为 average。\n"
        "\n"
        "分析维度(固定六个,按此顺序输出):\n"
        "1. ATTACK 进攻能力:场均进球、攻击输出稳定性、运动战与定位球得分能力;\n"
        "2. DEFENSE 防守能力:场均失球、零封能力、防守稳固程度;\n"
        "3. HOME_FORM 主场表现:主场战绩、主场攻防与主场优势;\n"
        "4. AWAY_FORM 客场表现:客场战绩、客场适应性与攻防表现;\n"
        "5. RECENT_FORM 近期状态:近几场的胜平负走势、连胜连败、进失球状态;\n"
        "6. OTHER 其他因素:球队档案、赛程密度、半场表现等其他值得注意的数据。\n"
        "\n"
        "输出要求(必须严格遵守):\n"
        "- 只输出一个 JSON 对象,不得输出 JSON 以外的任何文字(包括解释和 Markdown 代码块标记)。\n"
        "- JSON 结构:\n"
        "{\n"
        '  "summary": "整体研判,150字以内,综合各维度概括该队当前实力定位",\n'
        '  "dimensions": [\n'
        f"{dimension_doc}\n"
        "  ],\n"
        '  "risks": ["风险提示,1~3条,如数据缺失/状态波动/赛程影响"]\n'
        "}\n"
        "- rating 取值:strong=强(该维度表现突出),average=中(中游水平或数据不足),"
        "weak=弱(该维度存在明显短板)。\n"
        "- 全部用简体中文作答。"
    )

    profile = context.profile
    if profile is None:
        profile_text = "- 未同步球队档案"
    else:
        full_name = profile.full_name or profile.abbrev_name
        country = f",{profile.country_name}" if profile.country_name else ""
        profile_text = f"- 全称 {full_name}{country}"

    fmt = llm._format_fundamentals
    user_prompt = (
        f"请基于以下数据对该球队做多维度分析:\n"
        f"\n"
        f"【球队信息】\n"
        f"- 联赛:{context.league_name}(赛季 {context.season})\n"
        f"- 球队:{context.team_name}\n"
        f"{profile_text}\n"
        f"\n"
        f"【赛季基本面(积分榜)】\n"
        f"{fmt(context.team_name, context.fundamentals, '')}\n"
        f"{fmt(context.team_name, context.fundamentals, 'home_')}\n"
        f"{fmt(context.team_name, context.fundamentals, 'away_')}\n"
        f"\n"
        f"【近期比赛(时间倒序,以该队为主视角)】\n"
        f"{llm_fundamental._format_match_list(context.recent, '近期赛程赛果未同步(该维度数据不足)')}\n"
        f"\n"
        f"【后续赛程(赛程密度参考)】\n"
        f"{llm_fundamental._format_match_list(context.upcoming, '暂无后续赛程数据')}\n"
        f"\n"
        f"【Elo 评分(系统按看板赛果回放派生)】\n"
        f"{_format_elo(context)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ---------- 输出解析 ----------


def _parse_team(
    content: str,
) -> tuple[str, list[LlmTeamDimension], list[str]]:
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

    parsed_by_code: dict[str, LlmTeamDimension] = {}
    for item in payload.get("dimensions", []):
        if not isinstance(item, dict) or item.get("code") not in DIMENSION_TITLES:
            logger.warning("忽略一条无法识别的维度结论: %r", item)
            continue
        code = str(item["code"])
        rating = str(item.get("rating", "average"))
        if rating not in _RATINGS:
            rating = "average"
        content_text = str(item.get("content", "")).strip()
        if not content_text:
            continue
        # 与 dim_content 列宽(String(1000))对齐:模型超写时截断,避免落库 DataError
        content_text = content_text[:_DIM_CONTENT_MAX]
        parsed_by_code[code] = LlmTeamDimension(
            code=code,
            title=DIMENSION_TITLES[code],
            rating=rating,
            content=content_text,
        )

    # 按固定维度顺序输出;缺失维度用占位结论补齐,保证前端展示稳定
    dimensions: list[LlmTeamDimension] = []
    for code, title in DIMENSION_TITLES.items():
        dimensions.append(
            parsed_by_code.get(code)
            or LlmTeamDimension(
                code=code, title=title, rating="average",
                content="模型未给出该维度结论",
            )
        )
    if not parsed_by_code:
        raise LlmServiceError(
            "大模型输出中没有有效的维度结论", detail=content[:300]
        )
    return summary, dimensions, [str(r) for r in risks]


# ---------- 分析入口 ----------


async def analyze_team(context: TeamAnalysisContext) -> LlmTeamAnalysis:
    """完整球队分析流程:配置解析 -> 提示词 -> 调用 -> 解析校验,全程记录请求日志。

    日志写入 fp_llm_request_logs:match_id 列存 "team:{team_id}" 标识,
    request_params.analysis_type="team"。
    """
    settings = get_settings()
    # 复用 llm 模块的服务商解析与网络调用,保持各分析服务行为一致
    provider, base_url, api_key, model = llm._resolve_provider_config(settings)
    messages = build_team_messages(context)
    request_params = {
        "temperature": 0.3,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
        "analysis_type": ANALYSIS_TYPE,
    }
    log_base = {
        "match_id": f"team:{context.team_id}",
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
        summary, dimensions, risks = _parse_team(result.content)
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
    return LlmTeamAnalysis(
        team_id=context.team_id,
        provider=provider,
        model=model,
        summary=summary,
        dimensions=dimensions,
        risks=risks,
    )


# ---------- 结果持久化 ----------


async def save_team_analysis(
    session: AsyncSession, analysis: LlmTeamAnalysis
) -> TeamLlmAnalysis:
    """把一次球队分析结果落库(主表 + 维度明细),返回带主键的 ORM 行。

    明细通过 relationship 级联写入,flush 后即可读取 analysis_id / created_at;
    实际提交由请求级会话依赖完成。
    """
    row = TeamLlmAnalysis(
        team_id=analysis.team_id,
        provider=analysis.provider,
        model=analysis.model,
        summary=analysis.summary,
        risks=list(analysis.risks),
    )
    row.dimensions = [
        TeamLlmAnalysisDim(
            code=dim.code,
            title=dim.title,
            rating=dim.rating,
            content=dim.content,
        )
        for dim in analysis.dimensions
    ]
    session.add(row)
    await session.flush()
    return row


async def get_latest_team_analysis(
    session: AsyncSession, team_id: int
) -> TeamLlmAnalysis | None:
    """查询球队最近一次已保存的维度分析(含维度明细),无记录返回 None。"""
    stmt = (
        select(TeamLlmAnalysis)
        .options(selectinload(TeamLlmAnalysis.dimensions))
        .where(TeamLlmAnalysis.team_id == team_id)
        .order_by(TeamLlmAnalysis.analysis_id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_team_analyses(
    session: AsyncSession, team_id: int
) -> list[TeamLlmAnalysis]:
    """查询球队的历史维度分析列表(含明细),按生成时间倒序,最多保留最近 20 条。"""
    stmt = (
        select(TeamLlmAnalysis)
        .options(selectinload(TeamLlmAnalysis.dimensions))
        .where(TeamLlmAnalysis.team_id == team_id)
        .order_by(TeamLlmAnalysis.analysis_id.desc())
        .limit(llm._ANALYSIS_HISTORY_LIMIT)
    )
    return list((await session.execute(stmt)).scalars().all())


__all__ = [
    "ANALYSIS_TYPE",
    "DIMENSION_TITLES",
    "LlmNotConfiguredError",
    "TeamAnalysisContext",
    "LlmTeamDimension",
    "LlmTeamAnalysis",
    "build_team_context",
    "build_team_messages",
    "analyze_team",
    "save_team_analysis",
    "get_latest_team_analysis",
    "list_team_analyses",
]
