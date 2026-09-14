"""比赛与赛果模块路由:fp_match_ 表的增删查接口。"""

import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.match.schemas import (
    LlmAnalysisRead,
    MatchEventCreate,
    MatchEventRead,
    MatchGameCreate,
    MatchGameRead,
    MatchResultRead,
    MatchScoreUpdate,
)
from app.collector.sync import result_sync
from app.core.database import get_db_session
from app.core.exceptions import DataValidationError, ResourceNotFoundError
from app.core.security import verify_api_key
from app.models import MatchEvent, MatchGame, MatchOdds, MatchStatus
from app.services import crud, llm

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
    session: AsyncSession = Depends(get_db_session),
) -> list[MatchGame]:
    """分页查询比赛列表(含在售玩法赔率)。"""
    stmt = (
        select(MatchGame)
        .options(selectinload(MatchGame.odds))
        .order_by(MatchGame.match_time)
        .offset(offset)
        .limit(limit)
    )
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


# ---------- 赛果开奖 /results ----------

@router.get("/results", response_model=list[MatchResultRead], summary="按比赛日查询赛果开奖")
async def list_results(
    date: datetime.date = Query(description="比赛日(YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_db_session),
) -> list[MatchResultRead]:
    """查询指定比赛日的赛果开奖列表(含各玩法开奖结果与 SP)。

    数据由采集模块的赛果同步写入,未同步的日期返回空列表。
    """
    pairs = await result_sync.list_results_by_date(session, date)
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
