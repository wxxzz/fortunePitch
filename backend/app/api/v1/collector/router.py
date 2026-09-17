"""数据采集模块路由:外部数据源同步接口。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.base.schemas import LeagueRead, TeamRead
from app.api.v1.collector.schemas import (
    LeagueSyncRequest,
    LeagueSyncResultRead,
    MatchSyncRequest,
    MatchSyncResultRead,
    PlayerSyncResultRead,
    ResultSyncRequest,
    ResultSyncResultRead,
    TeamDashboardSyncRequest,
    TeamDashboardSyncResultRead,
    TeamFundamentalsSyncResultRead,
    TeamPlayerCountRead,
    TeamSyncResultRead,
)
from app.collector.sync import (
    fundamental_sync,
    league_sync,
    match_sync,
    player_sync,
    result_sync,
    team_dashboard_sync,
    team_sync,
)
from app.core.database import get_db_session
from app.core.security import verify_api_key
from app.models import League

router = APIRouter(
    prefix="/collector", tags=["collector"], dependencies=[Depends(verify_api_key)]
)


@router.post(
    "/leagues/sync",
    response_model=LeagueSyncResultRead,
    status_code=status.HTTP_200_OK,
    summary="按名称同步联赛信息",
)
async def sync_league(
    payload: LeagueSyncRequest, session: AsyncSession = Depends(get_db_session)
) -> LeagueSyncResultRead:
    """从中国竞彩网联赛资料拉取指定联赛信息,并幂等写入联赛档案。

    数据来源:https://www.sporttery.cn/zqlszl/
    """
    result = await league_sync.sync_league_by_name(session, payload.league_name)
    league: League = result.league
    return LeagueSyncResultRead(
        league=LeagueRead.model_validate(league),
        action=result.action,
        uniform_league_id=result.uniform_league_id,
    )


@router.post(
    "/teams/sync",
    response_model=TeamSyncResultRead,
    status_code=status.HTTP_200_OK,
    summary="按联赛名称同步球队清单",
)
async def sync_teams(
    payload: LeagueSyncRequest, session: AsyncSession = Depends(get_db_session)
) -> TeamSyncResultRead:
    """从竞彩网当前赛季积分榜拉取指定联赛的球队清单。

    会自动先同步联赛档案;竞彩网不提供主场/主教练/阵型,相应字段为空。
    """
    result = await team_sync.sync_league_teams(session, payload.league_name)
    return TeamSyncResultRead(
        league=LeagueRead.model_validate(result.league),
        team_count=len(result.teams),
        created_count=result.created_count,
        updated_count=result.updated_count,
        uniform_league_id=result.uniform_league_id,
    )


@router.post(
    "/players/sync",
    response_model=PlayerSyncResultRead,
    status_code=status.HTTP_200_OK,
    summary="按联赛名称同步球员名单",
)
async def sync_players(
    payload: LeagueSyncRequest, session: AsyncSession = Depends(get_db_session)
) -> PlayerSyncResultRead:
    """从竞彩网比赛球员数据收集指定联赛的球员名单并入库。

    会自动先同步联赛档案与球队清单;赛季初未完赛球队自动回溯上一赛季,
    仍无数据的球队会在 skipped_teams 中列出。
    """
    result = await player_sync.sync_league_players(session, payload.league_name)
    return PlayerSyncResultRead(
        league=LeagueRead.model_validate(result.league),
        team_count=len(result.team_player_counts),
        player_count=result.created_count + result.updated_count,
        created_count=result.created_count,
        updated_count=result.updated_count,
        matches_scanned=result.matches_scanned,
        team_player_counts=[
            TeamPlayerCountRead(team_name=name, player_count=count)
            for name, count in result.team_player_counts
        ],
        skipped_teams=list(result.skipped_team_names),
    )


@router.post(
    "/fundamentals/sync",
    response_model=TeamFundamentalsSyncResultRead,
    status_code=status.HTTP_200_OK,
    summary="按联赛名称同步球队基本面",
)
async def sync_team_fundamentals(
    payload: LeagueSyncRequest, session: AsyncSession = Depends(get_db_session)
) -> TeamFundamentalsSyncResultRead:
    """从竞彩网积分榜(总/主/客三榜)拉取指定联赛的球队基本面并入库。

    会自动先同步联赛档案与球队清单;覆盖排名、场次、胜负平、
    进失球、净胜球、积分与胜率。积分榜未覆盖的球队在结果中列出。
    """
    result = await fundamental_sync.sync_league_fundamentals(session, payload.league_name)
    return TeamFundamentalsSyncResultRead(
        league=LeagueRead.model_validate(result.league),
        season=result.season,
        team_count=result.team_count,
        created_count=result.created_count,
        updated_count=result.updated_count,
        skipped_teams=list(result.skipped_team_names),
        uniform_league_id=result.uniform_league_id,
    )


@router.post(
    "/matches/sync",
    response_model=MatchSyncResultRead,
    status_code=status.HTTP_200_OK,
    summary="按售卖日同步竞彩在售赛程",
)
async def sync_matches(
    payload: MatchSyncRequest, session: AsyncSession = Depends(get_db_session)
) -> MatchSyncResultRead:
    """从中国竞彩网赛程赛果页拉取指定售卖日的在售赛事并入库。

    数据来源:https://www.sporttery.cn/jc/zqszsc/
    联赛与球队须已在基础档案中,未入库的联赛/场次在结果中列出。
    """
    result = await match_sync.sync_matches_by_date(session, payload.date.isoformat())
    return MatchSyncResultRead(
        date=result.date,
        day_match_count=result.day_match_count,
        created_count=result.created_count,
        updated_count=result.updated_count,
        odds_count=result.odds_count,
        odds_snapshot_count=result.odds_snapshot_count,
        skipped_leagues=result.skipped_league_names,
        skipped_matches=result.skipped_matches,
    )


@router.post(
    "/team-dashboard/sync",
    response_model=TeamDashboardSyncResultRead,
    status_code=status.HTTP_200_OK,
    summary="按球队同步球队看板数据",
)
async def sync_team_dashboard(
    payload: TeamDashboardSyncRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TeamDashboardSyncResultRead:
    """从竞彩网球队专栏拉取球队未来赛事与赛程赛果并入库。

    数据来源:https://www.sporttery.cn/zqlszl/qdzl/ (tid=竞彩网统一球队 ID)。
    team_id 与 uniform_team_id 二选一;按 team_id 同步需先同步球队清单
    (建立竞彩网档案映射),重复同步幂等更新并修剪失效未开赛行。
    """
    result = await team_dashboard_sync.sync_team_dashboard(
        session,
        team_id=payload.team_id,
        uniform_team_id=payload.uniform_team_id,
        term_limits=payload.term_limits,
    )
    return TeamDashboardSyncResultRead(
        team=TeamRead.model_validate(result.team),
        uniform_team_id=result.uniform_team_id,
        profile_created=result.profile_created,
        future_count=result.future_count,
        result_count=result.result_count,
        created_count=result.created_count,
        updated_count=result.updated_count,
        pruned_count=result.pruned_count,
    )


@router.post(
    "/results/sync",
    response_model=ResultSyncResultRead,
    status_code=status.HTTP_200_OK,
    summary="按比赛日或售卖日同步竞彩赛果开奖数据",
)
async def sync_results(
    payload: ResultSyncRequest, session: AsyncSession = Depends(get_db_session)
) -> ResultSyncResultRead:
    """从中国竞彩网赛果开奖页拉取开奖结果并入库。

    数据来源:https://www.sporttery.cn/jc/zqsgkj/
    date_type=match 按比赛日拉取(与赛果开奖页的日期一致);date_type=sale
    按售卖日拉取(同时覆盖该日与次日凌晨的场次,与赛事中心口径一致)。
    场次须已在赛事档案中,未入库的场次在结果中列出;
    比分有效的场次会同步回写比赛比分与完赛状态。
    """
    result = await result_sync.sync_results_by_date(
        session, payload.date.isoformat(), date_type=payload.date_type
    )
    return ResultSyncResultRead(
        date=result.date,
        day_result_count=result.day_result_count,
        created_count=result.created_count,
        updated_count=result.updated_count,
        game_updated_count=result.game_updated_count,
        skipped_matches=result.skipped_matches,
    )
