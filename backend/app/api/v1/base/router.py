"""基础档案模块路由:fp_base_ 三张表的增删查接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.base.schemas import (
    LeagueCreate,
    LeagueRead,
    PlayerCreate,
    PlayerRead,
    TeamCreate,
    TeamFundamentalsRead,
    TeamRead,
)
from app.core.database import get_db_session
from app.core.security import verify_api_key
from app.models import League, Player, Team, TeamFundamentals
from app.services import crud

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
