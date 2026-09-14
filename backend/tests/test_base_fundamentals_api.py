"""基础档案模块接口测试:球队基本面查询(/api/v1/base/teams/{id}/fundamentals)。

SQLite 内存库 + FastAPI 依赖覆盖,基本面数据直接由会话预置,
覆盖 已同步(200)/未同步(404) 两种状态。
"""

import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import app
from app.models import League, Team, TeamFundamentals

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}


@pytest.fixture
async def env() -> typing.AsyncGenerator[
    tuple[AsyncClient, async_sessionmaker], None
]:
    """返回测试客户端与会话工厂(会话用于预置基本面数据)。"""
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> object:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=HEADERS
        ) as async_client:
            yield async_client, session_factory
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def _seed_team(session_factory: async_sessionmaker) -> int:
    """预置联赛 + 球队,返回球队 ID。"""
    async with session_factory() as session:
        league = League(league_name="西班牙甲级联赛", country="西班牙", tier=1)
        session.add(league)
        await session.flush()
        team = Team(team_name="巴塞罗那", league_id=league.league_id)
        session.add(team)
        await session.flush()
        team_id = team.team_id
        await session.commit()
    return team_id


class TestTeamFundamentalsEndpoint:
    """GET /api/v1/base/teams/{team_id}/fundamentals 测试。"""

    async def test_returns_synced_fundamentals(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        client, session_factory = env
        team_id = await _seed_team(session_factory)
        async with session_factory() as session:
            session.add(
                TeamFundamentals(
                    team_id=team_id,
                    season="2026-2027",
                    ranking=1,
                    played=4,
                    wins=4,
                    draws=0,
                    losses=0,
                    goals_for=17,
                    goals_against=2,
                    goal_diff=15,
                    points=12,
                    win_rate=100.0,
                    home_played=2,
                    home_wins=2,
                    away_played=2,
                    away_wins=2,
                )
            )
            await session.commit()

        response = await client.get(f"/api/v1/base/teams/{team_id}/fundamentals")
        assert response.status_code == 200
        body = response.json()
        assert body["team_id"] == team_id
        assert body["season"] == "2026-2027"
        assert body["ranking"] == 1
        assert body["played"] == 4
        assert body["points"] == 12
        assert body["win_rate"] == 100.0
        assert body["home_played"] == 2
        assert body["away_played"] == 2

    async def test_returns_404_when_not_synced(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        client, session_factory = env
        team_id = await _seed_team(session_factory)

        response = await client.get(f"/api/v1/base/teams/{team_id}/fundamentals")
        assert response.status_code == 404

    async def test_returns_404_for_unknown_team(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        client, _ = env
        response = await client.get("/api/v1/base/teams/999999/fundamentals")
        assert response.status_code == 404
