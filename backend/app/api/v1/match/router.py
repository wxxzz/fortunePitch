"""比赛与赛果模块路由:fp_match_ 表的增删查接口。"""

import datetime
import typing

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.match.schemas import (
    LlmAnalysisRead,
    LlmFundamentalAnalysisRead,
    LlmLessonSummaryRead,
    LlmRecommendationRowRead,
    LlmRetrospectComparisonItemRead,
    LlmRetrospectRead,
    LlmRetrospectViewRead,
    LlmTrendAnalysisRead,
    MatchEventCreate,
    MatchExtraInfoRead,
    MatchExtraInfoUpsert,
    MatchResultStatsRead,
    MatchEventRead,
    MatchGameCreate,
    MatchGameRead,
    MatchInsightsRead,
    LlmRequestLogRead,
    MatchOddsSnapshotRead,
    MatchResultRead,
    MatchScoreUpdate,
)
from app.collector.sync import result_sync
from app.core.database import get_db_session
from app.core.exceptions import DataValidationError, ResourceNotFoundError
from app.core.security import verify_api_key
from app.models import (
    LlmRequestLog,
    MatchEvent,
    MatchGame,
    MatchLlmLessonSummary,
    MatchOdds,
    MatchOddsSnapshot,
    MatchStatus,
)
from app.services import (
    crud,
    insights,
    llm,
    llm_fundamental,
    llm_lessons,
    llm_odds_trend,
    llm_query,
    llm_retrospect,
    match_extra_info,
    settlement,
)

router = APIRouter(prefix="/match", tags=["match"], dependencies=[Depends(verify_api_key)])


# ---------- 比赛 /games ----------

@router.post("/games", response_model=MatchGameRead, status_code=status.HTTP_201_CREATED)
async def create_game(
    payload: MatchGameCreate, session: AsyncSession = Depends(get_db_session)
) -> MatchGame:
    """新增比赛。

    Raises:
        DataValidationError: 主客队相同。
    """
    if payload.home_team_id == payload.away_team_id:
        raise DataValidationError("主队与客队不能是同一支球队")
    game = await crud.create_entity(session, MatchGame, payload.model_dump())
    # 新建比赛无赔率记录,显式加载关系避免响应序列化时懒加载
    await session.refresh(game, attribute_names=["odds"])
    return game


@router.get("/games", response_model=list[MatchGameRead])
async def list_games(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    start_date: datetime.date | None = Query(
        default=None, description="售卖日起(含),格式 YYYY-MM-DD"
    ),
    end_date: datetime.date | None = Query(
        default=None, description="售卖日止(含),格式 YYYY-MM-DD"
    ),
    session: AsyncSession = Depends(get_db_session),
) -> list[MatchGame]:
    """分页查询比赛列表(含在售玩法赔率),支持按售卖日范围过滤。

    售卖日与竞彩官网日期一致:次日凌晨开赛的比赛归属前一售卖日。
    默认按场次编号(如 周二002)升序,无编号的场次排最后(按开赛时间兜底)。
    """
    stmt = select(MatchGame).options(selectinload(MatchGame.odds))
    if start_date is not None:
        stmt = stmt.where(MatchGame.business_date >= start_date)
    if end_date is not None:
        stmt = stmt.where(MatchGame.business_date <= end_date)
    stmt = stmt.order_by(
        MatchGame.match_num_str == "",
        MatchGame.match_num_str,
        MatchGame.match_time,
    ).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/games/{match_id}", response_model=MatchGameRead)
async def get_game(match_id: str, session: AsyncSession = Depends(get_db_session)) -> MatchGame:
    """按比赛编号查询(含在售玩法赔率)。"""
    stmt = select(MatchGame).options(selectinload(MatchGame.odds)).where(
        MatchGame.match_id == match_id
    )
    game = (await session.execute(stmt)).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError(MatchGame.__tablename__, match_id)
    return game


@router.get(
    "/games/{match_id}/extra-info",
    response_model=MatchExtraInfoRead,
    summary="查询比赛补充信息(伤停/阵型等人工录入)",
)
async def get_extra_info(
    match_id: str, session: AsyncSession = Depends(get_db_session)
) -> MatchExtraInfoRead:
    """查询比赛的补充信息,未录入过时返回空记录(updated_at 为 null)。

    Raises:
        ResourceNotFoundError: 比赛不存在。
    """
    game = await session.get(MatchGame, match_id)
    if game is None:
        raise ResourceNotFoundError(MatchGame.__tablename__, match_id)
    row = await match_extra_info.load_extra_info(session, match_id)
    if row is None:
        return MatchExtraInfoRead(match_id=match_id)
    return MatchExtraInfoRead.model_validate(row)


@router.put(
    "/games/{match_id}/extra-info",
    response_model=MatchExtraInfoRead,
    summary="保存比赛补充信息(伤停/阵型等人工录入)",
)
async def save_extra_info(
    match_id: str,
    payload: MatchExtraInfoUpsert,
    session: AsyncSession = Depends(get_db_session),
) -> MatchExtraInfoRead:
    """保存(整体覆盖)比赛的补充信息,每场一行,重复保存为更新。

    保存后由 AI 分析(综合/基本面)聚合为"人工录入补充信息"证据段,
    随提示词注入大模型推理。

    Raises:
        ResourceNotFoundError: 比赛不存在。
    """
    row = await match_extra_info.upsert_extra_info(
        session,
        match_id=match_id,
        injuries=payload.injuries,
        formations=payload.formations,
        other_notes=payload.other_notes,
    )
    return MatchExtraInfoRead.model_validate(row)


@router.get(
    "/games/{match_id}/odds-snapshots",
    response_model=list[MatchOddsSnapshotRead],
    summary="查询比赛赔率快照历史(赔率走势)",
)
async def list_odds_snapshots(
    match_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[MatchOddsSnapshot]:
    """查询比赛的赔率快照历史,按快照时间升序,供走势图按时间轴回放。

    快照由赛事同步在赔率发生变化时追加(未变不落),每条含当次采集的
    全部玩法与赔率。

    Raises:
        ResourceNotFoundError: 比赛不存在。
    """
    game = await session.get(MatchGame, match_id)
    if game is None:
        raise ResourceNotFoundError(MatchGame.__tablename__, match_id)
    stmt = (
        select(MatchOddsSnapshot)
        .where(MatchOddsSnapshot.match_id == match_id)
        .order_by(MatchOddsSnapshot.snapshot_time)
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/games/{match_id}/insights",
    response_model=MatchInsightsRead,
    summary="查询比赛高阶数据(近况/交锋/Elo/攻防强度/泊松概率)",
)
async def get_match_insights(
    match_id: str,
    form_limit: int = Query(default=6, ge=1, le=20),
    h2h_limit: int = Query(default=10, ge=1, le=30),
    session: AsyncSession = Depends(get_db_session),
) -> MatchInsightsRead:
    """查询单场比赛高阶数据(读时实时派生,不落库)。

    - 球队近况 / 历史交锋:来自 fp_base_team_matches 已完赛看板行;
    - Elo 快照:来自 fp_analytics_team_ratings(POST /analytics/team-ratings/recompute 重算);
    - 攻防强度 λ/μ 与泊松概率:积分榜主客拆分 × 近况混合 + Dixon-Coles 模型。

    Raises:
        ResourceNotFoundError: 比赛不存在。
    """
    data = await insights.get_match_insights(
        session, match_id, form_limit=form_limit, h2h_limit=h2h_limit
    )
    return MatchInsightsRead.from_insights(data)


@router.patch("/games/{match_id}/score", response_model=MatchGameRead)
async def update_score(
    match_id: str,
    payload: MatchScoreUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> MatchGame:
    """录入完赛比分并将状态置为 FINISHED。"""
    game = await crud.get_entity(session, MatchGame, match_id)
    game.home_score = payload.home_score
    game.away_score = payload.away_score
    game.match_status = MatchStatus.FINISHED
    await session.flush()
    # 显式加载赔率关系,避免响应序列化时异步懒加载
    await session.refresh(game, attribute_names=["odds"])
    return game


@router.delete("/games/{match_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_game(match_id: str, session: AsyncSession = Depends(get_db_session)) -> None:
    """删除比赛。"""
    await crud.delete_entity(session, MatchGame, match_id)


@router.post(
    "/games/{match_id}/llm-analysis",
    response_model=LlmAnalysisRead,
    summary="大模型分析(分玩法推荐,生成后保存)",
)
async def analyze_game(
    match_id: str, session: AsyncSession = Depends(get_db_session)
) -> LlmAnalysisRead:
    """调用大模型分析单场比赛并落库,输出各竞彩玩法的推荐方案。

    服务端聚合联赛信息、双方基本面(积分榜)与在售玩法赔率后,
    构造提示词调用 OpenAI 兼容接口;每次生成保存一条历史记录。
    结果为数据分析参考,不构成投注建议。

    Raises:
        ResourceNotFoundError: 比赛不存在。
        LlmNotConfiguredError: 未配置 LLM API Key(503)。
        LlmServiceError: 大模型调用或输出解析失败(502)。
    """
    context = await llm.build_match_analysis_context(session, match_id)
    analysis = await llm.analyze_match(context)
    saved = await llm.save_analysis(session, analysis)
    return LlmAnalysisRead.model_validate(saved)


@router.get(
    "/games/{match_id}/llm-analysis",
    response_model=LlmAnalysisRead,
    summary="查询最近一次已保存的大模型分析",
)
async def get_latest_llm_analysis(
    match_id: str, session: AsyncSession = Depends(get_db_session)
) -> LlmAnalysisRead:
    """查询比赛最近一次已保存的大模型分析(含分玩法明细)。

    Raises:
        ResourceNotFoundError: 该比赛尚未生成过分析。
    """
    analysis = await llm.get_latest_analysis(session, match_id)
    if analysis is None:
        raise ResourceNotFoundError("大模型分析结果", match_id)
    return LlmAnalysisRead.model_validate(analysis)


@router.get(
    "/games/{match_id}/llm-analyses",
    response_model=list[LlmAnalysisRead],
    summary="查询比赛的大模型分析历史",
)
async def list_llm_analyses(
    match_id: str, session: AsyncSession = Depends(get_db_session)
) -> list[LlmAnalysisRead]:
    """查询比赛的历史分析列表,按生成时间倒序,最多返回最近 20 条。"""
    return [
        LlmAnalysisRead.model_validate(row)
        for row in await llm.list_match_analyses(session, match_id)
    ]


@router.get(
    "/games/{match_id}/llm-request-logs",
    response_model=list[LlmRequestLogRead],
    summary="查询比赛的大模型调用日志(请求参数与响应结果)",
)
async def list_llm_request_logs(
    match_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[LlmRequestLogRead]:
    """查询比赛的大模型调用日志,按调用时间倒序,供深度分析页排障查看。

    含综合分析 / 基本面分析 / 赔率走势分析三类调用,以
    analysis_type 区分;每条含完整提示词、调用参数、模型原始输出、
    token 计量与耗时,失败调用同样留痕。

    Raises:
        ResourceNotFoundError: 比赛不存在。
    """
    game = await session.get(MatchGame, match_id)
    if game is None:
        raise ResourceNotFoundError(MatchGame.__tablename__, match_id)
    return [
        LlmRequestLogRead.model_validate(row)
        for row in await llm.list_request_logs(session, match_id, limit=limit)
    ]


@router.get(
    "/llm-recommendations",
    response_model=list[LlmRecommendationRowRead],
    summary="AI 分析结果查询(按售卖日/置信度/玩法)",
)
async def list_llm_recommendations(
    business_date: datetime.date | None = Query(
        default=None, description="竞彩售卖日,缺省为当天"
    ),
    min_confidence: float = Query(
        default=0.0, ge=0.0, le=1.0, description="置信度下限(含)"
    ),
    play_code: str | None = Query(
        default=None, description="玩法编码过滤,缺省返回全部五种玩法"
    ),
    session: AsyncSession = Depends(get_db_session),
) -> list[LlmRecommendationRowRead]:
    """按售卖日查询各场比赛最近一次 AI 分析的分玩法推荐。

    每场比赛仅取最近一次分析(历史多份时以最新为准),
    输出场次编号/主客队/玩法推荐与次选(附选项最新赔率)/赛果开奖
    与命中比对/置信度/依据,按置信度倒序。
    结果为数据分析参考,不构成投注建议。

    Raises:
        DataValidationError: 玩法编码非法。
    """
    recs = await llm_query.query_play_recommendations(
        session,
        business_date=business_date or llm_query.current_business_date(),
        min_confidence=min_confidence,
        play_code=play_code,
    )
    rows: list[LlmRecommendationRowRead] = []
    for rec in recs:
        game = rec.analysis.game
        pools = game.odds.pools if game.odds else None
        # 该玩法的赛果开奖结果(未同步赛果时为 None)
        play_result = (
            getattr(
                game.result, llm_query.RESULT_FIELD_BY_PLAY[rec.play_code], None
            )
            if game.result is not None
            else None
        )
        rows.append(
            LlmRecommendationRowRead(
                analysis_id=rec.analysis.analysis_id,
                match_id=game.match_id,
                match_num_str=game.match_num_str,
                league_name=game.league.league_name if game.league else None,
                match_time=game.match_time,
                business_date=game.business_date,
                home_team_name=game.home_team.team_name if game.home_team else None,
                away_team_name=game.away_team.team_name if game.away_team else None,
                play_code=rec.play_code,
                play_name=rec.play_name,
                recommendation=rec.recommendation,
                recommendation_odds=llm_query.resolve_recommendation_odds(
                    pools, rec.play_code, rec.recommendation
                ),
                alternative_odds=[
                    llm_query.resolve_recommendation_odds(pools, rec.play_code, alt)
                    for alt in rec.alternatives
                ],
                result=play_result,
                is_hit=llm_query.resolve_recommendation_hit(
                    rec.play_code, rec.recommendation, play_result
                ),
                confidence=rec.confidence,
                reasoning=rec.reasoning,
                alternatives=rec.alternatives,
                created_at=rec.analysis.created_at,
            )
        )
    return rows


@router.post(
    "/games/{match_id}/llm-fundamentals",
    response_model=LlmFundamentalAnalysisRead,
    summary="大模型基本面分析(多维度,生成后保存)",
)
async def analyze_game_fundamentals(
    match_id: str, session: AsyncSession = Depends(get_db_session)
) -> LlmFundamentalAnalysisRead:
    """调用大模型做基本面多维度分析并落库:近期状态 / 主客场表现 / 攻防效率 /
    战意与动机 / 历史交锋 / 其他相关因素。

    服务端聚合球队档案、积分榜战绩、看板赛程赛果后构造提示词调用
    OpenAI 兼容接口;调用过程写入请求日志表(fp_llm_request_logs),
    每次生成保存一条历史记录(fp_match_llm_fund_analyses)。
    结果为数据分析参考,不构成投注建议。

    Raises:
        ResourceNotFoundError: 比赛不存在。
        LlmNotConfiguredError: 未配置 LLM API Key(503)。
        LlmServiceError: 大模型调用或输出解析失败(502)。
    """
    context = await llm_fundamental.build_fundamental_context(session, match_id)
    analysis = await llm_fundamental.analyze_fundamentals(context)
    saved = await llm_fundamental.save_fundamental(session, analysis)
    return LlmFundamentalAnalysisRead.model_validate(saved)


@router.get(
    "/games/{match_id}/llm-fundamentals",
    response_model=LlmFundamentalAnalysisRead,
    summary="查询最近一次已保存的大模型基本面分析",
)
async def get_latest_llm_fundamental(
    match_id: str, session: AsyncSession = Depends(get_db_session)
) -> LlmFundamentalAnalysisRead:
    """查询比赛最近一次已保存的大模型基本面分析(含维度明细)。

    Raises:
        ResourceNotFoundError: 该比赛尚未生成过基本面分析。
    """
    analysis = await llm_fundamental.get_latest_fundamental(session, match_id)
    if analysis is None:
        raise ResourceNotFoundError("大模型基本面分析结果", match_id)
    return LlmFundamentalAnalysisRead.model_validate(analysis)


@router.get(
    "/games/{match_id}/llm-fund-analyses",
    response_model=list[LlmFundamentalAnalysisRead],
    summary="查询比赛的大模型基本面分析历史",
)
async def list_llm_fundamentals(
    match_id: str, session: AsyncSession = Depends(get_db_session)
) -> list[LlmFundamentalAnalysisRead]:
    """查询比赛的历史基本面分析列表,按生成时间倒序,最多返回最近 20 条。"""
    return [
        LlmFundamentalAnalysisRead.model_validate(row)
        for row in await llm_fundamental.list_fundamentals(session, match_id)
    ]


@router.post(
    "/games/{match_id}/llm-odds-trend",
    response_model=LlmTrendAnalysisRead,
    summary="大模型赔率走势分析(生成后保存)",
)
async def analyze_game_odds_trend(
    match_id: str, session: AsyncSession = Depends(get_db_session)
) -> LlmTrendAnalysisRead:
    """调用大模型基于赔率快照序列做市场动向分析并落库,分玩法给出走势结论。

    服务端聚合 fp_match_odds_snapshots 中该场的时间正序快照(最多最近 50 条)
    后构造提示词调用 OpenAI 兼容接口;调用过程写入请求日志表
    (fp_llm_request_logs),每次生成保存一条历史记录
    (fp_match_llm_trend_analyses)。结果为数据分析参考,不构成投注建议。

    Raises:
        ResourceNotFoundError: 比赛不存在。
        DataValidationError: 该场尚无赔率快照(422)。
        LlmNotConfiguredError: 未配置 LLM API Key(503)。
        LlmServiceError: 大模型调用或输出解析失败(502)。
    """
    context = await llm_odds_trend.build_trend_context(session, match_id)
    analysis = await llm_odds_trend.analyze_odds_trend(context)
    saved = await llm_odds_trend.save_trend_analysis(session, analysis)
    return LlmTrendAnalysisRead.model_validate(saved)


@router.get(
    "/games/{match_id}/llm-odds-trend",
    response_model=LlmTrendAnalysisRead,
    summary="查询最近一次已保存的大模型赔率走势分析",
)
async def get_latest_llm_odds_trend(
    match_id: str, session: AsyncSession = Depends(get_db_session)
) -> LlmTrendAnalysisRead:
    """查询比赛最近一次已保存的赔率走势分析(含分玩法明细)。

    Raises:
        ResourceNotFoundError: 该比赛尚未生成过走势分析。
    """
    analysis = await llm_odds_trend.get_latest_trend_analysis(session, match_id)
    if analysis is None:
        raise ResourceNotFoundError("大模型赔率走势分析结果", match_id)
    return LlmTrendAnalysisRead.model_validate(analysis)


@router.get(
    "/games/{match_id}/llm-odds-trend-analyses",
    response_model=list[LlmTrendAnalysisRead],
    summary="查询比赛的大模型赔率走势分析历史",
)
async def list_llm_odds_trends(
    match_id: str, session: AsyncSession = Depends(get_db_session)
) -> list[LlmTrendAnalysisRead]:
    """查询比赛的历史走势分析列表,按生成时间倒序,最多返回最近 20 条。"""
    return [
        LlmTrendAnalysisRead.model_validate(row)
        for row in await llm_odds_trend.list_trend_analyses(session, match_id)
    ]


# ---------- 大模型赛事复盘 /llm-retrospect ----------


@router.get(
    "/games/{match_id}/llm-retrospect",
    response_model=LlmRetrospectViewRead,
    summary="查询赛事复盘视图(比对预览 + 最近一次已保存复盘)",
)
async def get_llm_retrospect_view(
    match_id: str, session: AsyncSession = Depends(get_db_session)
) -> LlmRetrospectViewRead:
    """查询比赛的赛事复盘 Tab 视图数据。

    比对预览(comparison)为系统实时计算:最近一次 AI 综合分析的
    分玩法推荐与官方开奖的逐玩法比对(命中口径与 AI 分析结果查询页
    一致);赛果未同步或未生成分析时为空列表,由 result_available /
    analysis_available 标记缺失原因。retrospect 为最近一次已保存的
    复盘结果(含逐玩法比对明细快照与经验教训),未生成过为 null。
    复盘仅供改进分析方法参考,不构成投注建议。

    Raises:
        ResourceNotFoundError: 比赛不存在。
    """
    game, result, analysis, comparison = await llm_retrospect.load_retrospect_view(
        session, match_id
    )
    retrospect = await llm_retrospect.get_latest_retrospect(session, match_id)
    return LlmRetrospectViewRead(
        match_id=game.match_id,
        result_available=result is not None
        and llm_retrospect.has_drawn_result(result),
        analysis_available=analysis is not None,
        comparison=[
            LlmRetrospectComparisonItemRead(
                play_code=item.play_code,
                play_name=item.play_name,
                recommendation=item.recommendation,
                confidence=item.confidence,
                alternatives=list(item.alternatives),
                result=item.result,
                is_hit=item.is_hit,
                reasoning=item.reasoning,
            )
            for item in comparison
        ],
        retrospect=(
            LlmRetrospectRead.model_validate(retrospect) if retrospect else None
        ),
    )


@router.post(
    "/games/{match_id}/llm-retrospect",
    response_model=LlmRetrospectRead,
    summary="大模型赛事复盘(对比赛果与 AI 分析,生成后保存)",
)
async def generate_llm_retrospect(
    match_id: str, session: AsyncSession = Depends(get_db_session)
) -> LlmRetrospectRead:
    """对比赛事结果与 AI 分析结果,调用大模型生成复盘总结并落库。

    流程:服务端先比对最近一次 AI 综合分析的推荐与官方开奖结果
    (逐玩法命中比对),把开奖结果、赛前 AI 推荐与理由、比对结论、
    基本面/走势分析结论与人工录入补充信息(如有)作为归因上下文
    构造提示词,调用 OpenAI 兼容接口输出复盘总结、逐玩法归因与
    经验教训;每次生成保存一条历史记录(fp_match_llm_retrospects,
    明细快照至 fp_match_llm_retrospect_items),调用过程写入请求
    日志表(analysis_type=retrospect)。
    复盘仅供改进分析方法参考,不构成投注建议。

    Raises:
        ResourceNotFoundError: 比赛不存在。
        DataValidationError: 赛果未同步 / 未生成过 AI 综合分析 /
            无已开奖玩法可比对(422)。
        LlmNotConfiguredError: 未配置 LLM API Key(503)。
        LlmServiceError: 大模型调用或输出解析失败(502)。
    """
    context = await llm_retrospect.build_retrospect_context(session, match_id)
    result = await llm_retrospect.analyze_retrospect(context)
    saved = await llm_retrospect.save_retrospect(session, result, context)
    return LlmRetrospectRead.model_validate(saved)


# ---------- 大模型复盘经验总结 /llm-lesson-summaries ----------


@router.get(
    "/llm-lesson-summaries",
    response_model=list[LlmLessonSummaryRead],
    summary="查询 AI 复盘经验总结历史",
)
async def list_llm_lesson_summaries(
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[LlmLessonSummaryRead]:
    """查询复盘经验总结历史,按生成时间倒序。

    每次总结一行(总结段落 + 共性经验条目 + 输入复盘统计),
    最近一次会注入后续 AI 综合分析的提示词。
    """
    return [
        LlmLessonSummaryRead.model_validate(row)
        for row in await llm_lessons.list_lesson_summaries(session, limit=limit)
    ]


@router.post(
    "/llm-lesson-summaries",
    response_model=LlmLessonSummaryRead,
    summary="生成 AI 复盘经验总结(归纳各场复盘的共性经验)",
)
async def generate_llm_lesson_summary(
    session: AsyncSession = Depends(get_db_session),
) -> LlmLessonSummaryRead:
    """调用大模型对各场 AI 复盘做共性归纳,输出可复用的分析方法经验。

    流程:取每场比赛最近一次赛事复盘(重新生成过复盘的场次不重复计),
    按生成时间倒序取最近 30 场,把各场总结与经验教训作为归纳上下文
    构造提示词,调用 OpenAI 兼容接口输出归纳总结与共性经验(5~10 条);
    每次生成保存一条历史记录(fp_match_llm_lesson_summaries),调用
    过程写入请求日志表(analysis_type=lesson_summary)并以 log_id 关联。
    最近一次总结由综合分析自动注入提示词,用于校准分析方法。
    经验总结仅供改进分析方法参考,不构成投注建议。

    Raises:
        DataValidationError: 尚无任何已生成的 AI 复盘(422)。
        LlmNotConfiguredError: 未配置 LLM API Key(503)。
        LlmServiceError: 大模型调用或输出解析失败(502)。
    """
    context = await llm_lessons.build_lesson_context(session)
    result = await llm_lessons.analyze_lessons(context)
    saved = await llm_lessons.save_lesson_summary(session, result)
    return LlmLessonSummaryRead.model_validate(saved)


@router.get(
    "/llm-lesson-summaries/{summary_id}/request-log",
    response_model=LlmRequestLogRead,
    summary="查询某次经验总结的请求日志(输入输出内容)",
)
async def get_llm_lesson_summary_log(
    summary_id: int, session: AsyncSession = Depends(get_db_session)
) -> LlmRequestLogRead:
    """查询某次经验总结的完整请求日志,供查看该次总结的输入(提示词)与输出(模型原始响应)。

    Raises:
        ResourceNotFoundError: 总结记录不存在 / 该次总结没有关联日志。
    """
    summary_row = await session.get(MatchLlmLessonSummary, summary_id)
    if summary_row is None:
        raise ResourceNotFoundError(MatchLlmLessonSummary.__tablename__, summary_id)
    if summary_row.log_id is None:
        raise ResourceNotFoundError("经验总结关联的请求日志", summary_id)
    log_row = await session.get(LlmRequestLog, summary_row.log_id)
    if log_row is None:
        raise ResourceNotFoundError("经验总结关联的请求日志", summary_row.log_id)
    return LlmRequestLogRead.model_validate(log_row)


# ---------- 赛果开奖 /results ----------

@router.get(
    "/results",
    response_model=list[MatchResultRead],
    summary="按售卖日范围查询赛果开奖",
)
async def list_results(
    start_date: datetime.date = Query(description="售卖日起(含,YYYY-MM-DD)"),
    end_date: datetime.date = Query(description="售卖日止(含,YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_db_session),
) -> list[MatchResultRead]:
    """查询指定售卖日范围的赛果开奖列表(含各玩法开奖结果、SP 与中奖赔率)。

    按比赛的竞彩售卖日(fp_match_games.business_date)过滤,次日凌晨开赛的
    比赛归属前一售卖日;跨多日时按售卖日 + 场次编号排序。数据由采集模块的
    赛果同步写入,未同步的日期返回空列表。

    各玩法中奖选项的开奖赔率(如比分 5:2@100)由在售赔率池比对推导,
    胜平负优先取赛果记录的开奖 SP。
    """
    pairs = await result_sync.list_results_by_business_date(session, start_date, end_date)
    # 批量加载在售赔率池,逐场解析各玩法中奖选项赔率
    match_ids = [result.match_id for result, _ in pairs]
    pools_by_match: dict[str, list[dict[str, typing.Any]]] = {}
    if match_ids:
        odds_rows = (
            await session.execute(
                select(MatchOdds).where(MatchOdds.match_id.in_(match_ids))
            )
        ).scalars().all()
        pools_by_match = {row.match_id: row.pools for row in odds_rows}
    return [
        MatchResultRead(
            match_id=result.match_id,
            match_num_str=result.match_num_str,
            league_name=game.league.league_name,
            home_team_name=game.home_team.team_name,
            away_team_name=game.away_team.team_name,
            match_time=game.match_time,
            business_date=game.business_date,
            goal_line=result.goal_line,
            half_score=(
                f"{result.half_home_score}:{result.half_away_score}"
                if result.half_home_score is not None
                else None
            ),
            full_score=(
                f"{result.full_home_score}:{result.full_away_score}"
                if result.full_home_score is not None
                else None
            ),
            had=result.had,
            hhad=result.hhad,
            crs=result.crs,
            ttg=result.ttg,
            hafu=result.hafu,
            sp_h=result.sp_h,
            sp_d=result.sp_d,
            sp_a=result.sp_a,
            **settlement.resolve_result_play_odds(
                result, pools_by_match.get(result.match_id)
            ),
            pool_status=result.pool_status,
        )
        for result, game in pairs
    ]


@router.get(
    "/results/stats",
    response_model=MatchResultStatsRead,
    summary="按售卖日范围统计赛果开奖的多维度分布",
)
async def get_result_stats(
    start_date: datetime.date = Query(description="售卖日起(含,YYYY-MM-DD)"),
    end_date: datetime.date = Query(description="售卖日止(含,YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_db_session),
) -> MatchResultStatsRead:
    """统计指定售卖日范围内赛果的多维度分布,供开奖页分析区展示。

    维度:胜平负/让球胜平负/总进球(7+ 合并)/比分/半全场的开奖分布,
    以及按联赛的胜负分布与场均进球。取消/无效场次不参与统计;
    数据由采集模块的赛果同步写入,未同步的日期各维度为空。
    """
    stats = await result_sync.build_result_stats(session, start_date, end_date)
    return MatchResultStatsRead(start_date=start_date, end_date=end_date, **stats)


# ---------- 比赛事件 /events ----------

@router.post("/events", response_model=MatchEventRead, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: MatchEventCreate, session: AsyncSession = Depends(get_db_session)
) -> MatchEvent:
    """新增比赛事件(进球/红黄牌/换人)。"""
    await crud.get_entity(session, MatchGame, payload.match_id)
    return await crud.create_entity(session, MatchEvent, payload.model_dump())


@router.get("/events", response_model=list[MatchEventRead])
async def list_events(
    match_id: str = Query(description="按比赛过滤"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[MatchEvent]:
    """查询指定比赛的事件列表,按发生时间升序。"""
    stmt = (
        select(MatchEvent)
        .where(MatchEvent.match_id == match_id)
        .order_by(MatchEvent.event_minute)
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(event_id: int, session: AsyncSession = Depends(get_db_session)) -> None:
    """删除比赛事件。"""
    await crud.delete_entity(session, MatchEvent, event_id)


@router.get("/events/{event_id}", response_model=MatchEventRead, include_in_schema=False)
async def get_event(event_id: int, session: AsyncSession = Depends(get_db_session)) -> MatchEvent:
    """按 ID 查询事件。"""
    return await crud.get_entity(session, MatchEvent, event_id)
