"""比赛与赛果模块路由:fp_match_ 表的增删查接口。"""

import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.match.schemas import (
    LlmAnalysisRead,
    LlmFundamentalAnalysisRead,
    LlmRecommendationRowRead,
    LlmTrendAnalysisRead,
    MatchEventCreate,
    MatchEventRead,
    MatchGameCreate,
    MatchGameRead,
    MatchOddsSnapshotRead,
    MatchResultRead,
    MatchScoreUpdate,
)
from app.collector.sync import result_sync
from app.core.database import get_db_session
from app.core.exceptions import DataValidationError, ResourceNotFoundError
from app.core.security import verify_api_key
from app.models import (
    MatchEvent,
    MatchGame,
    MatchOdds,
    MatchOddsSnapshot,
    MatchStatus,
)
from app.services import crud, llm, llm_fundamental, llm_odds_trend, llm_query

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
    输出场次编号/主客队/玩法推荐与次选(附选项最新赔率)/置信度/依据,按置信度倒序。
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


# ---------- 赛果开奖 /results ----------

@router.get(
    "/results", response_model=list[MatchResultRead], summary="按售卖日查询赛果开奖"
)
async def list_results(
    date: datetime.date = Query(description="售卖日(YYYY-MM-DD),与赛事中心口径一致"),
    session: AsyncSession = Depends(get_db_session),
) -> list[MatchResultRead]:
    """查询指定售卖日的赛果开奖列表(含各玩法开奖结果与 SP)。

    按比赛的竞彩售卖日(fp_match_games.business_date)过滤,次日凌晨开赛的
    比赛归属前一售卖日。数据由采集模块的赛果同步写入,未同步的日期返回空列表。
    """
    pairs = await result_sync.list_results_by_business_date(session, date)
    return [
        MatchResultRead(
            match_id=result.match_id,
            match_num_str=result.match_num_str,
            league_name=game.league.league_name,
            home_team_name=game.home_team.team_name,
            away_team_name=game.away_team.team_name,
            match_time=game.match_time,
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
            pool_status=result.pool_status,
        )
        for result, game in pairs
    ]


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
