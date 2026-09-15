"""基础档案模块测试:球队看板查询接口。

直接 seed 联赛/球队/档案映射/看板比赛,覆盖聚合查询、
筛选、统计与 404 场景。
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
from app.models import League, Team, TeamMatch, TeamProfile
from app.services import team_dashboard as dashboard_service

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

LEAGUE_LA_LIGA = 24
LEAGUE_UCL = 30


def seed_rows() -> list[dict[str, typing.Any]]:
    """看板比赛样本:巴萨(uniformTeamId=246)。"""
    base = dict(
        uniform_league_id=LEAGUE_LA_LIGA,
        league_name="西甲",
        home_team_name="巴萨",
        away_team_name="皇马",
        uniform_home_team_id=246,
        uniform_away_team_id=514,
        is_home=True,
        update_time=datetime.datetime(2026, 9, 15),
    )
    return [
        # 未来赛事(升序)
        {**base, "uniform_match_id": 9001, "match_time": datetime.datetime(2026, 9, 20, 22, 0)},
        {**base, "uniform_match_id": 9002, "match_time": datetime.datetime(2026, 9, 27, 23, 0), "is_home": False, "home_team_name": "皇家社会", "away_team_name": "巴萨", "uniform_home_team_id": 900, "uniform_away_team_id": 246},
        # 赛程赛果(降序):胜、胜(客)、平、负 + 欧冠胜
        {**base, "uniform_match_id": 8001, "match_time": datetime.datetime(2026, 9, 10), "half_home_score": 1, "half_away_score": 0, "full_home_score": 2, "full_away_score": 1, "team_result": "W"},
        {**base, "uniform_match_id": 8002, "match_time": datetime.datetime(2026, 9, 3), "is_home": False, "home_team_name": "奥萨苏纳", "away_team_name": "巴萨", "uniform_home_team_id": 700, "uniform_away_team_id": 246, "half_home_score": 0, "half_away_score": 1, "full_home_score": 0, "full_away_score": 3, "team_result": "W"},
        {**base, "uniform_match_id": 8003, "match_time": datetime.datetime(2026, 8, 28), "away_team_name": "塞维利亚", "uniform_away_team_id": 620, "half_home_score": 1, "half_away_score": 1, "full_home_score": 1, "full_away_score": 1, "team_result": "D"},
        {**base, "uniform_match_id": 8004, "match_time": datetime.datetime(2026, 8, 24), "away_team_name": "马竞", "uniform_away_team_id": 630, "half_home_score": 0, "half_away_score": 1, "full_home_score": 0, "full_away_score": 2, "team_result": "L"},
        {**base, "uniform_match_id": 8005, "match_time": datetime.datetime(2026, 9, 18), "uniform_league_id": LEAGUE_UCL, "league_name": "欧冠", "away_team_name": "本菲卡", "uniform_away_team_id": 220, "full_home_score": 3, "full_away_score": 0, "team_result": "W"},
    ]


@pytest.fixture
async def client() -> typing.AsyncGenerator[AsyncClient, None]:
    """内存 SQLite + seed 看板数据的测试客户端。

    返回 (客户端, 巴萨 team_id) 需两份数据,故改为在 fixture 内
    seed 并将 team_id 存入模块级变量。
    """
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        league = League(league_name="西甲", country="西班牙")
        session.add(league)
        await session.flush()
        team = Team(team_name="巴塞罗那", league_id=league.league_id)
        session.add(team)
        await session.flush()
        session.add(
            TeamProfile(
                team_id=team.team_id,
                uniform_team_id=246,
                gm_team_id=233,
                abbrev_name="巴萨",
                full_name="巴塞罗那",
                country_name="西班牙",
                logo_url="//static.sporttery.cn/logo.png",
            )
        )
        for row in seed_rows():
            session.add(TeamMatch(**row, team_id=team.team_id))
        await session.commit()
        barca_team_id = team.team_id

    async def override_session() -> object:
        async with factory() as session:
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
            async_client.team_id = barca_team_id  # type: ignore[attr-defined]
            yield async_client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


class TestTeamDashboardApi:
    """/api/v1/base/teams/{team_id}/dashboard 接口测试。"""

    async def test_dashboard_aggregates_all(
        self, client: AsyncClient
    ) -> None:
        team_id: int = client.team_id  # type: ignore[attr-defined]
        response = await client.get(f"/api/v1/base/teams/{team_id}/dashboard")
        assert response.status_code == 200
        body = response.json()

        assert body["team"]["team_name"] == "巴塞罗那"
        assert body["profile"]["abbrev_name"] == "巴萨"
        assert body["profile"]["uniform_team_id"] == 246
        # 未来赛事升序,赛程赛果降序
        assert [m["uniform_match_id"] for m in body["future_matches"]] == [9001, 9002]
        assert [m["uniform_match_id"] for m in body["match_results"]] == [
            8005, 8001, 8002, 8003, 8004,
        ]
        # 5 场已完赛:3 胜 1 平 1 负,进 9 失 4
        stats = body["statistics"]
        assert stats["played"] == 5
        assert stats["wins"] == 3
        assert stats["draws"] == 1
        assert stats["losses"] == 1
        assert stats["goals_for"] == 9
        assert stats["goals_against"] == 4
        assert stats["goal_diff"] == 5
        assert stats["win_rate"] == 60.0
        # 参赛联赛列表
        assert {lg["league_name"] for lg in body["leagues"]} == {"西甲", "欧冠"}

    async def test_dashboard_league_filter(self, client: AsyncClient) -> None:
        team_id: int = client.team_id  # type: ignore[attr-defined]
        response = await client.get(
            f"/api/v1/base/teams/{team_id}/dashboard",
            params={"uniform_league_id": LEAGUE_UCL},
        )
        assert response.status_code == 200
        body = response.json()
        assert [m["uniform_match_id"] for m in body["match_results"]] == [8005]
        assert body["future_matches"] == []
        assert body["statistics"]["played"] == 1

    async def test_dashboard_home_filter(self, client: AsyncClient) -> None:
        team_id: int = client.team_id  # type: ignore[attr-defined]
        response = await client.get(
            f"/api/v1/base/teams/{team_id}/dashboard",
            params={"home_away": "home"},
        )
        assert response.status_code == 200
        body = response.json()
        # 主场:未来 9001 + 赛果 8001/8003/8004/8005
        assert [m["uniform_match_id"] for m in body["future_matches"]] == [9001]
        assert [m["uniform_match_id"] for m in body["match_results"]] == [
            8005, 8001, 8003, 8004,
        ]
        # 2 胜 1 平 1 负,进 6 失 4
        assert body["statistics"]["wins"] == 2
        assert body["statistics"]["draws"] == 1
        assert body["statistics"]["losses"] == 1

    async def test_dashboard_away_filter(self, client: AsyncClient) -> None:
        team_id: int = client.team_id  # type: ignore[attr-defined]
        response = await client.get(
            f"/api/v1/base/teams/{team_id}/dashboard",
            params={"home_away": "away"},
        )
        assert response.status_code == 200
        body = response.json()
        # 客场:未来 9002 + 赛果 8002
        assert [m["uniform_match_id"] for m in body["future_matches"]] == [9002]
        assert [m["uniform_match_id"] for m in body["match_results"]] == [8002]
        assert body["statistics"]["wins"] == 1

    async def test_dashboard_result_limit(self, client: AsyncClient) -> None:
        team_id: int = client.team_id  # type: ignore[attr-defined]
        response = await client.get(
            f"/api/v1/base/teams/{team_id}/dashboard",
            params={"result_limit": 2, "future_limit": 1},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["match_results"]) == 2
        assert len(body["future_matches"]) == 1
        # 统计不受条数上限约束,仍覆盖全部已完赛行
        assert body["statistics"]["played"] == 5

    async def test_dashboard_unknown_team(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/base/teams/999/dashboard")
        assert response.status_code == 404

    async def test_dashboard_empty_profile(
        self, client: AsyncClient
    ) -> None:
        # 另建一支未同步看板数据的球队:profile 为空、看板为空但接口可用
        response = await client.post(
            "/api/v1/base/teams",
            json={"team_name": "瓦伦西亚", "league_id": 1},
        )
        assert response.status_code == 201
        team_id = response.json()["team_id"]

        response = await client.get(f"/api/v1/base/teams/{team_id}/dashboard")
        assert response.status_code == 200
        body = response.json()
        assert body["profile"] is None
        assert body["future_matches"] == []
        assert body["match_results"] == []
        assert body["statistics"]["played"] == 0
        assert body["statistics"]["win_rate"] == 0.0

    async def test_dashboard_requires_api_key(self, client: AsyncClient) -> None:
        team_id: int = client.team_id  # type: ignore[attr-defined]
        response = await client.get(
            f"/api/v1/base/teams/{team_id}/dashboard",
            headers={"X-API-Key": "wrong"},
        )
        assert response.status_code == 401


class TestStatisticsFallback:
    """统计兜底:比分在而 team_result 缺失时按比分推导,保证口径一致。"""

    def test_derives_result_from_scores(self) -> None:
        row = TeamMatch(
            team_id=1,
            uniform_match_id=1,
            match_time=datetime.datetime(2026, 9, 10),
            home_team_name="巴萨",
            away_team_name="皇马",
            is_home=True,
            full_home_score=2,
            full_away_score=1,
            team_result=None,
        )
        stats = dashboard_service._compute_statistics([row])
        assert stats.played == 1
        assert stats.wins == 1
        assert stats.win_rate == 100.0

    def test_skips_row_without_scores(self) -> None:
        row = TeamMatch(
            team_id=1,
            uniform_match_id=2,
            match_time=datetime.datetime(2026, 9, 20),
            home_team_name="巴萨",
            away_team_name="皇马",
            is_home=True,
        )
        stats = dashboard_service._compute_statistics([row])
        assert stats.played == 0
        assert stats.win_rate == 0.0
