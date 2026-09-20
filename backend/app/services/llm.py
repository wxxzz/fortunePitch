"""大模型分析服务:组装比赛上下文提示词,调用 OpenAI 兼容接口生成分玩法推荐。

职责:
1. 从数据库聚合单场比赛的分析上下文(联赛 / 双方基本面 / 在售玩法赔率);
2. 构造中文提示词,要求模型输出结构化 JSON;
3. 调用 OpenAI 兼容 chat/completions 接口(千问 / 火山方舟可切换);
4. 解析并校验模型输出,转为带约束的推荐结果。

密钥一律来自环境配置,本模块不落任何凭证。
"""

import dataclasses
import datetime
import json
import logging
import time
import typing

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.core.database import AsyncSessionLocal
from app.core.exceptions import (
    LlmNotConfiguredError,
    LlmServiceError,
    ResourceNotFoundError,
)
from app.models import (
    LlmRequestLog,
    MatchGame,
    MatchLlmAnalysis,
    MatchLlmFundAnalysis,
    MatchLlmPlayRec,
    MatchLlmTrendAnalysis,
    MatchStatus,
    TeamFundamentals,
)

logger = logging.getLogger(__name__)

# 竞彩 5 种玩法编码 -> 展示名(提示词与结果校验共用)
PLAY_NAMES: dict[str, str] = {
    "HAD": "胜平负",
    "HHAD": "让球胜平负",
    "CRS": "比分",
    "TTG": "总进球",
    "HAFU": "半全场",
}

# 比赛状态 -> 展示名
_STATUS_LABELS: dict[MatchStatus, str] = {
    MatchStatus.PENDING: "未开赛",
    MatchStatus.LIVE: "进行中",
    MatchStatus.FINISHED: "已完赛",
}

# 服务商名 -> Settings 字段前缀
_PROVIDER_PREFIXES: dict[str, str] = {"qwen": "QWEN", "ark": "ARK"}

# 基本面维度优劣倾向 -> 展示名(渲染历史基本面AI分析结论用)
_EDGE_LABELS: dict[str, str] = {
    "home": "主队占优",
    "away": "客队占优",
    "even": "势均力敌",
}

# 单场比赛保留的历史分析条数上限(倒序取最近 N 条)
_ANALYSIS_HISTORY_LIMIT = 20

# 综合分析的各路证据权重(写入系统提示词,合计须为 1.0)
_WEIGHT_OWN_FUNDAMENTAL = 0.30  # 自身基本面推理(积分榜/主客场/攻防)
_WEIGHT_OWN_ODDS = 0.20  # 自身赔率定价推理(隐含概率归一)
_WEIGHT_AI_FUNDAMENTAL = 0.30  # AI 基本面分析结论(历史生成)
_WEIGHT_AI_TREND = 0.20  # AI 赔率走势分析结论(历史生成)
# 证据方向冲突时对应玩法置信度的压低上限
_CONFLICT_CONFIDENCE_CAP = 0.45


# ---------- 上下文与结果模型 ----------


@dataclasses.dataclass(frozen=True)
class MatchAnalysisContext:
    """单场比赛的分析上下文(服务端聚合,提示词唯一数据来源)。"""

    match_id: str
    league_name: str
    season: str
    match_time: datetime.datetime
    match_status: MatchStatus
    home_team_name: str
    away_team_name: str
    home_fundamentals: TeamFundamentals | None
    away_fundamentals: TeamFundamentals | None
    pools: list[dict[str, typing.Any]]
    # 历史生成的 AI 基本面分析 / AI 赔率走势分析结论(未生成过为 None),
    # 作为综合分析的逻辑依据随提示词一并注入
    fundamental_analysis: MatchLlmFundAnalysis | None = None
    trend_analysis: MatchLlmTrendAnalysis | None = None


class LlmPlayRecommendation(BaseModel):
    """单种玩法的推荐方案(模型输出经校验后的载体)。"""

    play_code: str = Field(description="玩法编码:HAD/HHAD/CRS/TTG/HAFU")
    play_name: str = Field(description="玩法展示名,如 胜平负")
    recommendation: str = Field(description="推荐选项,如 主胜 / 1:2 / 3球 / 胜胜")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度,0~1")
    reasoning: str = Field(description="推荐理由(引用基本面或赔率数据)")
    alternatives: list[str] = Field(default_factory=list, description="次选选项,最多2个")


class LlmAnalysis(BaseModel):
    """大模型分析结果(整体研判 + 分玩法推荐 + 风险提示)。"""

    match_id: str
    provider: str = Field(description="服务商:qwen / ark")
    model: str = Field(description="实际使用的模型名")
    summary: str = Field(description="整体研判")
    plays: list[LlmPlayRecommendation] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class LlmCallResult:
    """单次 chat/completions 调用的原始结果(含计量信息)。"""

    content: str
    http_status: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    duration_ms: int


# 请求日志的独立会话工厂:日志必须不受业务请求事务回滚影响,
# 因此不复用请求级会话,单独开连接写入并提交。
# 测试通过 monkeypatch 该属性指向 SQLite 测试库。
_log_session_factory: async_sessionmaker = AsyncSessionLocal


# ---------- 上下文聚合 ----------


async def build_match_analysis_context(
    session: AsyncSession, match_id: str
) -> MatchAnalysisContext:
    """聚合单场比赛的分析上下文,比赛不存在时抛 404。

    基本面未同步按 None 处理,赔率未同步按空玩法处理;
    另附带最近一次已保存的 AI 基本面分析与 AI 赔率走势分析结论
    (由深度分析页对应 Tab 生成,未生成过按 None 处理),
    由提示词明确告知模型数据缺口并压低置信度。
    """
    stmt = (
        select(MatchGame)
        .options(
            selectinload(MatchGame.league),
            selectinload(MatchGame.home_team),
            selectinload(MatchGame.away_team),
            selectinload(MatchGame.odds),
        )
        .where(MatchGame.match_id == match_id)
    )
    game = (await session.execute(stmt)).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError(MatchGame.__tablename__, match_id)

    team_ids = [game.home_team_id, game.away_team_id]
    fundamentals_rows = (
        (await session.execute(select(TeamFundamentals).where(TeamFundamentals.team_id.in_(team_ids))))
        .scalars()
        .all()
    )
    fundamentals_by_team = {row.team_id: row for row in fundamentals_rows}

    # 最近一次已保存的 AI 基本面 / 赔率走势分析(含明细,直接查询避免服务间循环依赖)
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

    pools = list(game.odds.pools) if game.odds is not None else []
    return MatchAnalysisContext(
        match_id=game.match_id,
        league_name=game.league.league_name,
        season=game.league.season,
        match_time=game.match_time,
        match_status=game.match_status,
        home_team_name=game.home_team.team_name,
        away_team_name=game.away_team.team_name,
        home_fundamentals=fundamentals_by_team.get(game.home_team_id),
        away_fundamentals=fundamentals_by_team.get(game.away_team_id),
        pools=pools,
        fundamental_analysis=fundamental_analysis,
        trend_analysis=trend_analysis,
    )


# ---------- 提示词构造 ----------


def _format_fundamentals(team_name: str, f: TeamFundamentals | None, prefix: str) -> str:
    """把单支球队某一维度(总/主/客)的战绩渲染为一行中文摘要。"""
    if f is None:
        return f"- {team_name}:未同步基本面数据(数据不足,需降低置信度)"

    def num(field: str) -> str:
        value = getattr(f, prefix + field)
        return "-" if value is None else str(value)

    if prefix == "":
        dimension = "总战绩"
        ranking = f"排名 {num('ranking')},"
    else:
        dimension = "主场战绩" if prefix == "home_" else "客场战绩"
        ranking = ""
    return (
        f"- {team_name}{dimension}:{ranking}{num('played')} 赛 {num('wins')} 胜 "
        f"{num('draws')} 平 {num('losses')} 负,进 {num('goals_for')} 失 "
        f"{num('goals_against')},净胜 {num('goal_diff')},积分 {num('points')},"
        f"胜率 {num('win_rate')}%"
    )


def _format_fundamental_conclusion(analysis: MatchLlmFundAnalysis | None) -> str:
    """把历史 AI 基本面分析结论渲染为文本块;未生成过时给出明确提示。"""
    if analysis is None:
        return "- 尚未生成 AI 基本面分析(该维度参考缺失,对应玩法置信度应降低)"
    lines = [f"- 整体研判:{analysis.summary}"]
    for dim in analysis.dimensions:
        edge = _EDGE_LABELS.get(dim.edge, dim.edge)
        lines.append(f"- {dim.title}({edge}):{dim.content}")
    return "\n".join(lines)


def _format_trend_conclusion(analysis: MatchLlmTrendAnalysis | None) -> str:
    """把历史 AI 赔率走势分析结论渲染为文本块;未生成过时给出明确提示。"""
    if analysis is None:
        return "- 尚未生成 AI 赔率走势分析(该维度参考缺失,对应玩法置信度应降低)"
    lines = [f"- 整体研判:{analysis.summary}"]
    for play in analysis.plays:
        lines.append(
            f"- {play.play_name}:{play.signal},置信度 {float(play.confidence):.2f}"
            f"({play.reasoning})"
        )
    return "\n".join(lines)


def _format_pools(pools: list[dict[str, typing.Any]]) -> str:
    """把在售玩法赔率渲染为分玩法文本块;未同步时给出明确提示。"""
    if not pools:
        return "暂无在售玩法赔率数据(未同步或未开售,胜平负类玩法可基于基本面推断,但置信度必须显著降低)"

    blocks: list[str] = []
    for pool in pools:
        code = str(pool.get("poolCode", ""))
        play_name = PLAY_NAMES.get(code, str(pool.get("playName", code)))
        goal_line = pool.get("goalLine")
        header = f"{play_name}({code})" + (f",让球盘口 {goal_line}" if goal_line else "")
        options = pool.get("options") or []
        option_text = "、".join(
            f"{opt.get('label')} {opt.get('odds')}" for opt in options
        )
        blocks.append(f"- {header}:{option_text or '无选项'}")
    return "\n".join(blocks)


def build_analysis_messages(context: MatchAnalysisContext) -> list[dict[str, str]]:
    """构造 system + user 双段提示词。"""
    system_prompt = (
        "你是一名资深足球数据分析师,为中国体育彩票竞彩玩法提供数据分析和参考方案。\n"
        "\n"
        "职责与边界:\n"
        "1. 只做数据分析,不做投注引导;结论是概率研判,不构成投注建议。\n"
        "2. 严格基于用户提供的联赛信息、球队基本面(积分榜战绩)和竞彩赔率推理,不得编造数据。\n"
        "3. 赔率隐含概率 = 1/赔率;可将各选项隐含概率归一后,与基本面强弱对照,判断分歧点。\n"
        "4. 数据缺失时(如某队未同步基本面)必须明确说明数据不足,并压低对应玩法置信度。\n"
        "\n"
        "证据权重(综合研判按以下权重融合各路证据后得出最终结论):\n"
        f"- 自身对原始数据的独立推理,合计 {_WEIGHT_OWN_FUNDAMENTAL + _WEIGHT_OWN_ODDS:.0%}:\n"
        f"  · 基本面推理(积分榜/主客场战绩/攻防数据)占 {_WEIGHT_OWN_FUNDAMENTAL:.0%};\n"
        f"  · 赔率隐含概率与市场定价分析占 {_WEIGHT_OWN_ODDS:.0%}。\n"
        f"- AI 基本面分析结论(用户提供,占 {_WEIGHT_AI_FUNDAMENTAL:.0%}):六维基本面的历史研判。\n"
        "  融合时须先校验其结论与当前积分榜数据是否一致,过时或矛盾的结论降权使用。\n"
        f"- AI 赔率走势分析结论(用户提供,占 {_WEIGHT_AI_TREND:.0%}):市场资金动向研判。\n"
        "  融合时须先校验其走势信号与当前赔率水平是否一致,以最新赔率数据为准修正。\n"
        "- 任一路证据缺失时(如未生成对应的 AI 分析),其权重并入自身独立推理;\n"
        "  两路 AI 分析均缺失时,完全依据自身独立推理。\n"
        "- 各路证据方向一致时,可适度上调对应玩法置信度;\n"
        "  方向冲突时不得简单折中取平均,必须在 reasoning 中点明分歧,\n"
        f"  并显著压低该玩法置信度(通常压至 {_CONFLICT_CONFIDENCE_CAP:.2f} 以下)。\n"
        "\n"
        "输出要求(必须严格遵守):\n"
        "- 只输出一个 JSON 对象,不得输出 JSON 以外的任何文字(包括解释和 Markdown 代码块标记)。\n"
        "- JSON 结构:\n"
        '{\n'
        '  "summary": "整体研判,150字以内,按证据权重融合双方基本面与赔率分歧",\n'
        '  "plays": [\n'
        "    {\n"
        '      "playCode": "HAD",\n'
        '      "recommendation": "推荐选项中文展示名,如 主胜 / 平 / 客胜 / 1:2 / 3球 / 胜胜",\n'
        '      "confidence": 0.55,\n'
        '      "reasoning": "推荐理由,80字以内,须体现证据权重与交叉验证结论,引用基本面或赔率数据",\n'
        '      "alternatives": ["次选选项名,最多2个,可为空数组"]\n'
        "    }\n"
        "  ],\n"
        '  "risks": ["风险提示,1~3条,如伤停/盘口异动/AI历史结论过时/数据不足"]\n'
        "}\n"
        "- plays 必须覆盖输入数据中给出的每一种在售玩法,playCode 取 HAD/HHAD/CRS/TTG/HAFU。\n"
        "- confidence 为 0~1 的小数;数据不足、证据冲突或选项间分歧大时给低值。\n"
        "- 全部用简体中文作答。"
    )

    status_label = _STATUS_LABELS.get(context.match_status, context.match_status.value)
    user_prompt = (
        f"请分析以下竞彩比赛并输出分玩法推荐方案:\n"
        f"\n"
        f"【比赛信息】\n"
        f"- 联赛:{context.league_name}(赛季 {context.season})\n"
        f"- 对阵:{context.home_team_name}(主)vs {context.away_team_name}(客)\n"
        f"- 开赛时间:{context.match_time.strftime('%Y-%m-%d %H:%M')},状态:{status_label}\n"
        f"\n"
        f"【主队基本面(积分榜)】\n"
        f"{_format_fundamentals(context.home_team_name, context.home_fundamentals, '')}\n"
        f"{_format_fundamentals(context.home_team_name, context.home_fundamentals, 'home_')}\n"
        f"{_format_fundamentals(context.home_team_name, context.home_fundamentals, 'away_')}\n"
        f"\n"
        f"【客队基本面(积分榜)】\n"
        f"{_format_fundamentals(context.away_team_name, context.away_fundamentals, '')}\n"
        f"{_format_fundamentals(context.away_team_name, context.away_fundamentals, 'home_')}\n"
        f"{_format_fundamentals(context.away_team_name, context.away_fundamentals, 'away_')}\n"
        f"\n"
        f"【在售玩法赔率】\n"
        f"{_format_pools(context.pools)}\n"
        f"\n"
        f"【AI 基本面分析结论(历史生成,综合分析参考依据)】\n"
        f"{_format_fundamental_conclusion(context.fundamental_analysis)}\n"
        f"\n"
        f"【AI 赔率走势分析结论(历史生成,综合分析参考依据)】\n"
        f"{_format_trend_conclusion(context.trend_analysis)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ---------- 模型调用与输出解析 ----------


def _resolve_provider_config(settings: Settings) -> tuple[str, str, str, str]:
    """按 LLM_PROVIDER 解析 (provider, base_url, api_key, model)。"""
    provider = settings.LLM_PROVIDER.strip().lower()
    prefix = _PROVIDER_PREFIXES.get(provider)
    if prefix is None:
        raise LlmNotConfiguredError(
            f"未知的大模型服务商: {settings.LLM_PROVIDER}(可选 qwen / ark)"
        )
    base_url = getattr(settings, f"LLM_{prefix}_BASE_URL").rstrip("/")
    api_key = getattr(settings, f"LLM_{prefix}_API_KEY")
    model = getattr(settings, f"LLM_{prefix}_MODEL")
    if not api_key:
        raise LlmNotConfiguredError(
            f"大模型服务未配置:请在 .env 中填写 LLM_{prefix}_API_KEY"
        )
    return provider, base_url, api_key, model


def _usage_int(usage: dict[str, typing.Any], key: str) -> int | None:
    """从 usage 字典安全取整数计量值。"""
    value = usage.get(key)
    return value if isinstance(value, int) else None


async def _call_chat(
    base_url: str, api_key: str, model: str, messages: list[dict[str, str]], settings: Settings
) -> LlmCallResult:
    """调用 OpenAI 兼容 chat/completions,返回原始输出与计量信息。

    单独成函数便于测试打桩(mock 网络层)。
    """
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": settings.LLM_MAX_TOKENS,
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise LlmServiceError(
            "大模型服务调用失败(网络错误)", detail=f"{type(exc).__name__}: {exc}"
        ) from exc
    duration_ms = int((time.monotonic() - started) * 1000)

    if response.status_code != 200:
        raise LlmServiceError(
            f"大模型服务返回错误(HTTP {response.status_code})",
            detail=response.text[:500],
            http_status=response.status_code,
        )
    try:
        body = response.json()
        content = str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmServiceError(
            "大模型服务响应结构异常", detail=str(exc), http_status=response.status_code
        ) from exc
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    return LlmCallResult(
        content=content,
        http_status=response.status_code,
        prompt_tokens=_usage_int(usage, "prompt_tokens"),
        completion_tokens=_usage_int(usage, "completion_tokens"),
        total_tokens=_usage_int(usage, "total_tokens"),
        duration_ms=duration_ms,
    )


def _extract_json_text(content: str) -> str:
    """从模型输出中提取 JSON 文本:去掉代码块围栏与前后缀说明。"""
    text = content.strip()
    if text.startswith("```"):
        # 去掉 ```json / ``` 围栏行
        text = text.strip("`")
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LlmServiceError("大模型输出中未找到 JSON 对象", detail=content[:300])
    return text[start : end + 1]


def _parse_analysis(content: str, context: MatchAnalysisContext) -> tuple[str, list[LlmPlayRecommendation], list[str]]:
    """解析并校验模型 JSON 输出,返回 (summary, plays, risks)。"""
    try:
        payload = json.loads(_extract_json_text(content))
    except json.JSONDecodeError as exc:
        raise LlmServiceError("大模型输出 JSON 解析失败", detail=f"{exc}: {content[:300]}") from exc

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise LlmServiceError("大模型输出缺少 summary 字段", detail=content[:300])

    risks = payload.get("risks", [])
    if not isinstance(risks, list):
        risks = []

    plays: list[LlmPlayRecommendation] = []
    for item in payload.get("plays", []):
        if not isinstance(item, dict) or item.get("playCode") not in PLAY_NAMES:
            continue
        try:
            plays.append(
                LlmPlayRecommendation(
                    play_code=item["playCode"],
                    play_name=PLAY_NAMES[item["playCode"]],
                    recommendation=str(item.get("recommendation", "")),
                    confidence=float(item.get("confidence", 0.0)),
                    reasoning=str(item.get("reasoning", "")),
                    alternatives=[str(a) for a in item.get("alternatives", [])][:2],
                )
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            logger.warning("忽略一条无法解析的玩法推荐: %r", item)
    if not plays:
        raise LlmServiceError("大模型输出中没有有效的玩法推荐", detail=content[:300])
    return summary, plays, [str(r) for r in risks]


async def _write_request_log(
    *,
    match_id: str,
    provider: str,
    model: str,
    base_url: str,
    messages: list[dict[str, str]],
    request_params: dict[str, typing.Any],
    response: LlmCallResult | None,
    status: str,
    duration_ms: int,
    error: LlmServiceError | None,
) -> None:
    """落一条大模型请求日志(独立会话写入并提交)。

    只依赖 match_id 字符串,不依赖具体分析上下文类型,
    供分玩法推荐(llm)与基本面分析(llm_fundamental)共用。
    日志失败只记录 warning,绝不影响主流程 —— 请求日志的意义
    正是在业务请求失败(事务回滚)时也能留存调用痕迹。
    """
    log_row = LlmRequestLog(
        match_id=match_id,
        provider=provider,
        model=model,
        base_url=base_url,
        request_messages=messages,
        request_params=request_params,
        response_content=response.content if response is not None else None,
        status=status,
        http_status=(
            response.http_status if response is not None else (error.http_status if error else None)
        ),
        prompt_tokens=response.prompt_tokens if response is not None else None,
        completion_tokens=response.completion_tokens if response is not None else None,
        total_tokens=response.total_tokens if response is not None else None,
        duration_ms=duration_ms,
        error_message=error.message if error is not None else None,
        error_detail=error.detail if error is not None else None,
    )
    try:
        async with _log_session_factory() as log_session:
            log_session.add(log_row)
            await log_session.commit()
    except Exception:
        logger.warning("大模型请求日志写入失败", exc_info=True)


async def analyze_match(context: MatchAnalysisContext) -> LlmAnalysis:
    """完整分析流程:配置解析 -> 提示词 -> 调用 -> 解析校验,全程记录请求日志。"""
    settings = get_settings()
    provider, base_url, api_key, model = _resolve_provider_config(settings)
    messages = build_analysis_messages(context)
    request_params = {
        "temperature": 0.3,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
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
        result = await _call_chat(base_url, api_key, model, messages, settings)
    except LlmServiceError as exc:
        await _write_request_log(
            **log_base,
            response=None,
            status="FAILED",
            duration_ms=int((time.monotonic() - started) * 1000),
            error=exc,
        )
        raise
    try:
        summary, plays, risks = _parse_analysis(result.content, context)
    except LlmServiceError as exc:
        await _write_request_log(
            **log_base,
            response=result,
            status="FAILED",
            duration_ms=result.duration_ms,
            error=exc,
        )
        raise
    await _write_request_log(
        **log_base,
        response=result,
        status="SUCCESS",
        duration_ms=result.duration_ms,
        error=None,
    )
    return LlmAnalysis(
        match_id=context.match_id,
        provider=provider,
        model=model,
        summary=summary,
        plays=plays,
        risks=risks,
    )


# ---------- 结果持久化 ----------


async def save_analysis(session: AsyncSession, analysis: LlmAnalysis) -> MatchLlmAnalysis:
    """把一次分析结果落库(主表 + 分玩法明细),返回带主键的 ORM 行。

    明细通过 relationship 级联写入,flush 后即可读取 analysis_id / created_at;
    实际提交由请求级会话依赖完成。
    """
    row = MatchLlmAnalysis(
        match_id=analysis.match_id,
        provider=analysis.provider,
        model=analysis.model,
        summary=analysis.summary,
        risks=list(analysis.risks),
    )
    row.plays = [
        MatchLlmPlayRec(
            play_code=play.play_code,
            play_name=play.play_name,
            recommendation=play.recommendation,
            confidence=play.confidence,
            reasoning=play.reasoning,
            alternatives=list(play.alternatives),
        )
        for play in analysis.plays
    ]
    session.add(row)
    await session.flush()
    return row


async def get_latest_analysis(session: AsyncSession, match_id: str) -> MatchLlmAnalysis | None:
    """查询比赛最近一次已保存的分析(含分玩法明细),无记录返回 None。"""
    stmt = (
        select(MatchLlmAnalysis)
        .options(selectinload(MatchLlmAnalysis.plays))
        .where(MatchLlmAnalysis.match_id == match_id)
        .order_by(MatchLlmAnalysis.analysis_id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_match_analyses(session: AsyncSession, match_id: str) -> list[MatchLlmAnalysis]:
    """查询比赛的历史分析列表(含明细),按生成时间倒序,最多保留最近 20 条。"""
    stmt = (
        select(MatchLlmAnalysis)
        .options(selectinload(MatchLlmAnalysis.plays))
        .where(MatchLlmAnalysis.match_id == match_id)
        .order_by(MatchLlmAnalysis.analysis_id.desc())
        .limit(_ANALYSIS_HISTORY_LIMIT)
    )
    return list((await session.execute(stmt)).scalars().all())
