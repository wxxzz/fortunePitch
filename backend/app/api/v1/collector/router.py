"""数据采集模块路由:外部数据源同步接口。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.base.schemas import LeagueRead
from app.api.v1.collector.schemas import LeagueSyncRequest, LeagueSyncResultRead
from app.collector.sync import league_sync
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
