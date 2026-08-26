"""数据采集模块路由:外部数据源同步接口。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.base.schemas import LeagueRead
from app.api.v1.collector.schemas import (
    LeagueSyncRequest,
    LeagueSyncResultRead,
    MatchSyncRequest,
    MatchSyncResultRead,
    PlayerSyncResultRead,
    TeamPlayerCountRead,
    TeamSyncResultRead,
)
from app.collector.sync import league_sync, match_sync, player_sync, team_sync
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
        skipped_leagues=result.skipped_league_names,
        skipped_matches=result.skipped_matches,
    )
