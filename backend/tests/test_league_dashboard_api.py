"""基础档案模块接口测试:联赛看板(/api/v1/base/leagues/{id}/dashboard)。

SQLite 内存库 + FastAPI 依赖覆盖,覆盖:
- 看板聚合(基本信息/球队数/积分榜排序/近期赛果倒序/近期赛程正序);
- 联赛隔离(他队他场不串入);
- 基本面未同步的球队排积分榜末尾且战绩字段为空;
- 联赛不存在 404;条数上限参数。
"""

import datetime
import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import app
from app.models import League, MatchGame, Team, TeamFundamentals

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# 测试基准时间(近期赛程/赛果围绕该时刻前后展开)
BASE_TIME = datetime.datetime(2026, 10, 1, 21, 0)


@pytest.fixture
async def env() -> typing.AsyncGenerator[
    tuple[AsyncClient, async_sessionmaker], None
]:
    """返回测试客户端与会话工厂(会话用于预置看板数据)。"""
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
        with_session = session_factory()
        async with with_session as session:
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


async def _seed(env: tuple[AsyncClient, async_sessionmaker]) -> int:
    """预置两个联赛:目标联赛 3 队(2 队有基本面)+ 4 场比赛,
    干扰联赛 1 队 1 场;返回目标联赛 ID。"""
    _, session_factory = env
    async with session_factory() as session:
        liga = League(league_name="西班牙甲级联赛", country="西班牙", tier=1)
        premier = League(league_name="英格兰超级联赛", country="英格兰", tier=1)
        session.add_all([liga, premier])
        await session.flush()

        barca = Team(team_name="巴塞罗那", league_id=liga.league_id)
        real = Team(team_name="皇家马德里", league_id=liga.league_id)
        sevilla = Team(team_name="塞维利亚", league_id=liga.league_id)
        city = Team(team_name="曼城", league_id=premier.league_id)
        session.add_all([barca, real, sevilla, city])
        await session.flush()

        # 基本面:皇马第 1 / 巴萨第 2;塞维利亚未同步;曼城属他联赛
        session.add(
            TeamFundamentals(
                team_id=real.team_id,
                season="2026-2027",
                ranking=1,
                played=8,
                wins=6,
                draws=2,
                losses=0,
                goals_for=20,
                goals_against=6,
                goal_diff=14,
                points=20,
                win_rate=75.0,
            )
        )
        session.add(
            TeamFundamentals(
                team_id=barca.team_id,
                season="2026-2027",
                ranking=2,
                played=8,
                wins=5,
                draws=2,
                losses=1,
                goals_for=18,
                goals_against=9,
                goal_diff=9,
                points=17,
                win_rate=62.5,
            )
        )

        matches = [
            # 目标联赛:两场已完赛(时间倒序断言)+ 两场未开赛(时间正序断言)
            MatchGame(
                match_id="lg-r1",
                match_num_str="周五001",
                league_id=liga.league_id,
                home_team_id=real.team_id,
                away_team_id=barca.team_id,
                match_time=BASE_TIME - datetime.timedelta(days=2),
                match_status="FINISHED",
                home_score=2,
                away_score=1,
            ),
            MatchGame(
                match_id="lg-r2",
                match_num_str="周五002",
                league_id=liga.league_id,
                home_team_id=sevilla.team_id,
                away_team_id=real.team_id,
                match_time=BASE_TIME - datetime.timedelta(days=1),
                match_status="FINISHED",
                home_score=0,
                away_score=3,
            ),
            MatchGame(
                match_id="lg-f1",
                match_num_str="周六001",
                league_id=liga.league_id,
                home_team_id=barca.team_id,
                away_team_id=sevilla.team_id,
                match_time=BASE_TIME + datetime.timedelta(days=1),
                match_status="PENDING",
            ),
            MatchGame(
                match_id="lg-f2",
                match_num_str="周六002",
                league_id=liga.league_id,
                home_team_id=real.team_id,
                away_team_id=sevilla.team_id,
                match_time=BASE_TIME + datetime.timedelta(days=2),
                match_status="PENDING",
            ),
            # 干扰联赛:不应出现在目标联赛看板
            MatchGame(
                match_id="other-1",
                match_num_str="周六101",
                league_id=premier.league_id,
                home_team_id=city.team_id,
                away_team_id=city.team_id,
                match_time=BASE_TIME,
                match_status="PENDING",
            ),
        ]
        session.add_all(matches)
        await session.commit()
        return liga.league_id


class TestLeagueDashboardEndpoint:
    """GET /api/v1/base/leagues/{league_id}/dashboard 测试。"""

    async def test_returns_aggregated_dashboard(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        client, _ = env
        league_id = await _seed(env)

        # Act
        response = await client.get(f"/api/v1/base/leagues/{league_id}/dashboard")

        # Assert:基本信息 + 球队数
        assert response.status_code == 200
        body = response.json()
        assert body["league"]["league_name"] == "西班牙甲级联赛"
        assert body["league"]["country"] == "西班牙"
        assert body["team_count"] == 3

        # 积分榜:按排名升序,未同步基本面(塞维利亚)排末尾且战绩为空
        standings = body["standings"]
        assert [row["team_name"] for row in standings] == [
            "皇家马德里", "巴塞罗那", "塞维利亚",
        ]
        top = standings[0]
        assert top["ranking"] == 1
        assert top["points"] == 20
        assert top["goals_for"] == 20
        assert top["win_rate"] == 75.0
        unsynced = standings[2]
        assert unsynced["ranking"] is None
        assert unsynced["points"] is None

        # 近期赛果:已完赛按开赛时间倒序(近的在前)
        results = body["recent_results"]
        assert [row["match_id"] for row in results] == ["lg-r2", "lg-r1"]
        assert results[0]["home_team_name"] == "塞维利亚"
        assert results[0]["away_team_name"] == "皇家马德里"
        assert results[0]["home_score"] == 0
        assert results[0]["away_score"] == 3

        # 近期赛程:未完赛按开赛时间正序(近的在前),无比分
        fixtures = body["upcoming_fixtures"]
        assert [row["match_id"] for row in fixtures] == ["lg-f1", "lg-f2"]
        assert fixtures[0]["home_score"] is None
        assert fixtures[0]["match_status"] == "PENDING"

        # 联赛隔离:他联赛比赛不串入
        all_match_ids = {row["match_id"] for row in results + fixtures}
        assert "other-1" not in all_match_ids

    async def test_respects_limit_params(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        client, _ = env
        league_id = await _seed(env)

        # Act
        response = await client.get(
            f"/api/v1/base/leagues/{league_id}/dashboard",
            params={"result_limit": 1, "fixture_limit": 1},
        )

        # Assert:各取最近 1 条
        assert response.status_code == 200
        body = response.json()
        assert [row["match_id"] for row in body["recent_results"]] == ["lg-r2"]
        assert [row["match_id"] for row in body["upcoming_fixtures"]] == ["lg-f1"]

    async def test_returns_404_for_unknown_league(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange / Act
        client, _ = env
        response = await client.get("/api/v1/base/leagues/999/dashboard")

        # Assert
        assert response.status_code == 404
