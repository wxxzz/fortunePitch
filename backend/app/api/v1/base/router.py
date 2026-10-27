"""基础档案模块路由:fp_base_ 各表的增删查接口。"""

from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.base.schemas import (
    DashboardLeagueRead,
    DashboardStatisticsRead,
    LabelCountRead,
    LeagueCreate,
    LeagueDashboardRead,
    LeagueFavoriteStatsRead,
    LeagueInsightsRead,
    LeagueMatchRowRead,
    LeagueRead,
    LeagueStandingRowRead,
    PlayerCreate,
    PlayerRead,
    TeamCreate,
    TeamDashboardRead,
    TeamFundamentalsRead,
    TeamLlmAnalysisRead,
    TeamMatchRead,
    TeamProfileRead,
    TeamRead,
)
from app.core.database import get_db_session
from app.core.exceptions import ResourceNotFoundError
from app.core.security import verify_api_key
from app.models import League, Player, Team, TeamFundamentals, TeamLlmAnalysis
from app.services import crud, league_dashboard, league_insights, llm_team, team_dashboard

router = APIRouter(prefix="/base", tags=["base"], dependencies=[Depends(verify_api_key)])


# ---------- 联赛 /leagues ----------

@router.post("/leagues", response_model=LeagueRead, status_code=status.HTTP_201_CREATED)
async def create_league(
    payload: LeagueCreate, session: AsyncSession = Depends(get_db_session)
) -> League:
    """新增联赛档案。"""
    return await crud.create_entity(session, League, payload.model_dump())


@router.get("/leagues", response_model=list[LeagueRead])
async def list_leagues(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[League]:
    """分页查询联赛列表。"""
    return list(await crud.list_entities(session, League, offset, limit))


@router.get("/leagues/{league_id}", response_model=LeagueRead)
async def get_league(
    league_id: int, session: AsyncSession = Depends(get_db_session)
) -> League:
    """按 ID 查询联赛。"""
    return await crud.get_entity(session, League, league_id)


@router.delete("/leagues/{league_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_league(
    league_id: int, session: AsyncSession = Depends(get_db_session)
) -> None:
    """删除联赛。"""
    await crud.delete_entity(session, League, league_id)


@router.get("/leagues/{league_id}/dashboard", response_model=LeagueDashboardRead)
async def get_league_dashboard(
    league_id: int,
    result_limit: int = Query(default=10, ge=1, le=50, description="近期赛果条数"),
    fixture_limit: int = Query(default=10, ge=1, le=50, description="近期赛程条数"),
    session: AsyncSession = Depends(get_db_session),
) -> LeagueDashboardRead:
    """查询联赛看板:基本信息、球队数、积分榜(总榜)与近期赛程赛果。

    积分榜来自球队基本面(数据采集页"同步基本面"写入,未同步的球队
    排末尾);赛程赛果来自竞彩比赛档案,可按 match_id 进入比赛详情。

    Raises:
        ResourceNotFoundError: 联赛不存在。
    """
    data = await league_dashboard.get_league_dashboard(
        session,
        league_id,
        result_limit=result_limit,
        fixture_limit=fixture_limit,
    )
    return LeagueDashboardRead(
        league=LeagueRead.model_validate(data.league),
        team_count=data.team_count,
        standings=[
            LeagueStandingRowRead(
                team_id=row.team_id,
                team_name=row.team_name,
                **(
                    dict(
                        season=row.fundamentals.season,
                        ranking=row.fundamentals.ranking,
                        played=row.fundamentals.played,
                        wins=row.fundamentals.wins,
                        draws=row.fundamentals.draws,
                        losses=row.fundamentals.losses,
                        goals_for=row.fundamentals.goals_for,
                        goals_against=row.fundamentals.goals_against,
                        goal_diff=row.fundamentals.goal_diff,
                        points=row.fundamentals.points,
                        win_rate=row.fundamentals.win_rate,
                    )
                    if row.fundamentals is not None
                    else {}
                ),
            )
            for row in data.standings
        ],
        recent_results=[
            LeagueMatchRowRead(
                match_id=row.match_id,
                match_num_str=row.match_num_str,
                match_time=row.match_time,
                match_status=row.match_status,
                home_team_name=row.home_team_name,
                away_team_name=row.away_team_name,
                home_score=row.home_score,
                away_score=row.away_score,
            )
            for row in data.recent_results
        ],
        upcoming_fixtures=[
            LeagueMatchRowRead(
                match_id=row.match_id,
                match_num_str=row.match_num_str,
                match_time=row.match_time,
                match_status=row.match_status,
                home_team_name=row.home_team_name,
                away_team_name=row.away_team_name,
                home_score=row.home_score,
                away_score=row.away_score,
            )
            for row in data.upcoming_fixtures
        ],
    )


@router.get("/leagues/{league_id}/insights", response_model=LeagueInsightsRead)
async def get_league_insights(
    league_id: int, session: AsyncSession = Depends(get_db_session)
) -> LeagueInsightsRead:
    """联赛多维度分析:对已完赛场次统计多维度分布。

    维度:胜平负分布、进球(场均/3 球及以上/双方进球)、总进球分布、
    半全场分布、让球胜平负分布、热门命中(胜平负 SP 最低项的开奖
    命中率)。统计口径为该联赛全部已完赛且有比分的场次(不限赛季)。

    Raises:
        ResourceNotFoundError: 联赛不存在。
    """
    data = await league_insights.get_league_insights(session, league_id)
    favorite = (
        LeagueFavoriteStatsRead(
            count=data.favorite.count,
            hit_count=data.favorite.hit_count,
            hit_rate=data.favorite.hit_rate,
            avg_sp=data.favorite.avg_sp,
        )
        if data.favorite is not None
        else None
    )
    return LeagueInsightsRead(
        league_id=data.league.league_id,
        league_name=data.league.league_name,
        season=data.season,
        finished_count=data.finished_count,
        home_win=data.home_win,
        draw=data.draw,
        away_win=data.away_win,
        home_win_rate=data.home_win_rate,
        draw_rate=data.draw_rate,
        away_win_rate=data.away_win_rate,
        avg_total_goals=data.avg_total_goals,
        avg_home_goals=data.avg_home_goals,
        avg_away_goals=data.avg_away_goals,
        over2_5_count=data.over2_5_count,
        over2_5_rate=data.over2_5_rate,
        btts_count=data.btts_count,
        btts_rate=data.btts_rate,
        total_goals=[
            LabelCountRead(label=row.label, count=row.count)
            for row in data.total_goals
        ],
        half_full=[
            LabelCountRead(label=row.label, count=row.count)
            for row in data.half_full
        ],
        handicap=[
            LabelCountRead(label=row.label, count=row.count)
            for row in data.handicap
        ],
        favorite=favorite,
    )


# ---------- 球队 /teams ----------

@router.post("/teams", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamCreate, session: AsyncSession = Depends(get_db_session)
) -> Team:
    """新增球队档案。"""
    return await crud.create_entity(session, Team, payload.model_dump())


@router.get("/teams", response_model=list[TeamRead])
async def list_teams(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    league_id: int | None = Query(default=None, description="按所属联赛过滤"),
    session: AsyncSession = Depends(get_db_session),
) -> list[Team]:
    """分页查询球队列表,支持按所属联赛过滤。"""
    filters = {"league_id": league_id} if league_id is not None else None
    return list(
        await crud.list_entities(session, Team, offset, limit, filters=filters)
    )


@router.get("/teams/{team_id}", response_model=TeamRead)
async def get_team(team_id: int, session: AsyncSession = Depends(get_db_session)) -> Team:
    """按 ID 查询球队。"""
    return await crud.get_entity(session, Team, team_id)


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: int, session: AsyncSession = Depends(get_db_session)) -> None:
    """删除球队。"""
    await crud.delete_entity(session, Team, team_id)


@router.get("/teams/{team_id}/fundamentals", response_model=TeamFundamentalsRead)
async def get_team_fundamentals(
    team_id: int, session: AsyncSession = Depends(get_db_session)
) -> TeamFundamentals:
    """查询球队基本面(积分榜总/主/客三维度赛季战绩)。

    数据由数据采集页“同步基本面”写入;未同步过基本面时返回 404。
    """
    return await crud.get_entity(session, TeamFundamentals, team_id)


@router.get("/teams/{team_id}/dashboard", response_model=TeamDashboardRead)
async def get_team_dashboard(
    team_id: int,
    uniform_league_id: int | None = Query(
        default=None, description="按参赛联赛过滤(竞彩网统一联赛 ID)"
    ),
    home_away: Literal["home", "away"] | None = Query(
        default=None, description="主客过滤:home=仅主场,away=仅客场"
    ),
    future_limit: int = Query(default=10, ge=1, le=50, description="未来赛事条数"),
    result_limit: int = Query(default=10, ge=1, le=100, description="赛程赛果条数"),
    session: AsyncSession = Depends(get_db_session),
) -> TeamDashboardRead:
    """查询球队看板:档案、未来赛事、赛程赛果与近期战绩统计。

    数据由数据采集页“球队看板同步”(竞彩网球队专栏)写入;
    支持按参赛联赛与主客场筛选,统计覆盖筛选后的全部已完赛行。
    """
    data = await team_dashboard.get_team_dashboard(
        session,
        team_id,
        uniform_league_id=uniform_league_id,
        home_away=home_away,
        future_limit=future_limit,
        result_limit=result_limit,
    )
    return TeamDashboardRead(
        team=TeamRead.model_validate(data.team),
        profile=TeamProfileRead.model_validate(data.profile)
        if data.profile is not None
        else None,
        leagues=[
            DashboardLeagueRead(uniform_league_id=league_id, league_name=name)
            for league_id, name in data.leagues
        ],
        future_matches=[
            TeamMatchRead.model_validate(row) for row in data.future_matches
        ],
        match_results=[TeamMatchRead.model_validate(row) for row in data.match_results],
        statistics=DashboardStatisticsRead(
            played=data.statistics.played,
            wins=data.statistics.wins,
            draws=data.statistics.draws,
            losses=data.statistics.losses,
            goals_for=data.statistics.goals_for,
            goals_against=data.statistics.goals_against,
            goal_diff=data.statistics.goal_diff,
            win_rate=data.statistics.win_rate,
        ),
    )


# ---------- 大模型球队维度分析 /teams/{team_id}/llm-analysis ----------

@router.post(
    "/teams/{team_id}/llm-analysis",
    response_model=TeamLlmAnalysisRead,
    summary="大模型球队维度分析(生成后保存)",
)
async def analyze_team(
    team_id: int, session: AsyncSession = Depends(get_db_session)
) -> TeamLlmAnalysis:
    """调用大模型对单支球队做多维度分析并落库:进攻能力 / 防守能力 /
    主场表现 / 客场表现 / 近期状态 / 其他因素。

    服务端聚合球队档案、积分榜战绩、看板赛程赛果与 Elo 评分后构造提示词
    调用 OpenAI 兼容接口;调用过程写入请求日志表(fp_llm_request_logs,
    match_id 存 "team:{team_id}" 标识),每次生成保存一条历史记录
    (fp_llm_team_analyses + fp_llm_team_analysis_dims)。
    结果为数据分析参考,不构成投注建议。

    Raises:
        ResourceNotFoundError: 球队不存在。
        LlmNotConfiguredError: 未配置 LLM API Key(503)。
        LlmServiceError: 大模型调用或输出解析失败(502)。
    """
    context = await llm_team.build_team_context(session, team_id)
    analysis = await llm_team.analyze_team(context)
    saved = await llm_team.save_team_analysis(session, analysis)
    return TeamLlmAnalysisRead.model_validate(saved)


@router.get(
    "/teams/{team_id}/llm-analysis",
    response_model=TeamLlmAnalysisRead,
    summary="查询球队最近一次已保存的大模型维度分析",
)
async def get_latest_team_llm_analysis(
    team_id: int, session: AsyncSession = Depends(get_db_session)
) -> TeamLlmAnalysis:
    """查询球队最近一次已保存的维度分析(含维度明细)。

    Raises:
        ResourceNotFoundError: 该球队尚未生成过维度分析。
    """
    analysis = await llm_team.get_latest_team_analysis(session, team_id)
    if analysis is None:
        raise ResourceNotFoundError("大模型球队分析结果", str(team_id))
    return TeamLlmAnalysisRead.model_validate(analysis)


@router.get(
    "/teams/{team_id}/llm-analyses",
    response_model=list[TeamLlmAnalysisRead],
    summary="查询球队的大模型维度分析历史",
)
async def list_team_llm_analyses(
    team_id: int, session: AsyncSession = Depends(get_db_session)
) -> list[TeamLlmAnalysis]:
    """查询球队的历史维度分析列表,按生成时间倒序,最多返回最近 20 条。"""
    return await llm_team.list_team_analyses(session, team_id)


# ---------- 球员 /players ----------

@router.post("/players", response_model=PlayerRead, status_code=status.HTTP_201_CREATED)
async def create_player(
    payload: PlayerCreate, session: AsyncSession = Depends(get_db_session)
) -> Player:
    """新增球员档案。"""
    return await crud.create_entity(session, Player, payload.model_dump())


@router.get("/players", response_model=list[PlayerRead])
async def list_players(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    team_id: int | None = Query(default=None, description="按所属球队过滤"),
    session: AsyncSession = Depends(get_db_session),
) -> list[Player]:
    """分页查询球员列表,支持按所属球队过滤。"""
    filters = {"team_id": team_id} if team_id is not None else None
    return list(
        await crud.list_entities(session, Player, offset, limit, filters=filters)
    )


@router.get("/players/{player_id}", response_model=PlayerRead)
async def get_player(
    player_id: int, session: AsyncSession = Depends(get_db_session)
) -> Player:
    """按 ID 查询球员。"""
    return await crud.get_entity(session, Player, player_id)


@router.delete("/players/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_player(
    player_id: int, session: AsyncSession = Depends(get_db_session)
) -> None:
    """删除球员。"""
    await crud.delete_entity(session, Player, player_id)
