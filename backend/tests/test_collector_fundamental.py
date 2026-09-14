"""数据采集模块测试:球队基本面同步。

外部 sporttery 接口通过 monkeypatch 替换为离线样本,
覆盖 解析 -> 同步入库 -> 接口 的完整链路。
"""

import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.collector.parsers import fundamental as fundamental_parser
from app.collector.sync import fundamental_sync, league_sync, team_sync
from app.collector.sources import sporttery
from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import app
from app.models import Team, TeamFundamentals

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# ---------- 离线样本 ----------

SAMPLE_LIST: list[dict[str, typing.Any]] = [
    {
        "group": "hot",
        "tier": 1,
        "leagueAbbCnName": "西甲",
        "uniformLeagueId": 24,
        "seasonList": [
            {"seasonId": 15485, "seasonName": "2026/2027"},
            {"seasonId": 13440, "seasonName": "2025/2026"},
        ],
    }
]
SAMPLE_DETAIL = {
    "cnName": "西班牙甲级联赛",
    "isHot": 1,
    "uniformLeagueId": 24,
}
SAMPLE_STANDINGS = [
    {"abbCnName": "巴萨", "uniformTeamId": 246},
    {"abbCnName": "皇马", "uniformTeamId": 514},
    {"abbCnName": "桑坦德", "uniformTeamId": 3000},
]
SAMPLE_TEAM_INFOS = {
    246: {"allCnName": "巴塞罗那", "countryCnName": "西班牙", "uniformTeamId": 246},
    514: {"allCnName": "皇家马德里", "countryCnName": "西班牙", "uniformTeamId": 514},
    3000: {"allCnName": "桑坦德竞技", "countryCnName": "西班牙", "uniformTeamId": 3000},
}


def _table_row(
    team_id: int,
    ranking: int,
    played: int,
    wins: int,
    draws: int,
    losses: int,
    goals_for: int,
    goals_against: int,
    points: int,
    win_rate: str,
) -> dict[str, typing.Any]:
    """构造积分榜行(字段名与竞彩网接口一致,计数为字符串)。"""
    return {
        "abbCnName": "球队",
        "uniformTeamId": team_id,
        "ranking": str(ranking),
        "totalLegCnt": played,
        "winGoalMatchCnt": wins,
        "drawMatchCnt": draws,
        "lossGoalMatchCnt": losses,
        "goalCnt": goals_for,
        "lossGoalCnt": goals_against,
        "netGoal": goals_for - goals_against,
        "points": str(points),
        "winProbability": win_rate,
    }


# 三榜样本:桑坦德(3000)不在总榜中 -> 进 skipped
SAMPLE_FUNDAMENTALS = {
    "total": [
        _table_row(246, 1, 2, 2, 0, 0, 10, 0, 6, "100%"),
        _table_row(514, 2, 2, 1, 1, 0, 4, 2, 4, "50%"),
    ],
    "home": [
        _table_row(246, 1, 1, 1, 0, 0, 5, 0, 3, "100%"),
        _table_row(514, 2, 1, 0, 1, 0, 1, 1, 1, "0%"),
    ],
    "away": [
        _table_row(246, 1, 1, 1, 0, 0, 5, 0, 3, "100%"),
        _table_row(514, 2, 1, 1, 0, 0, 3, 1, 3, "100%"),
    ],
}


async def _fetch_league_list() -> list[dict[str, typing.Any]]:
    return SAMPLE_LIST


async def _fetch_league_detail(uniform_league_id: int) -> dict[str, typing.Any]:
    assert uniform_league_id == 24
    return SAMPLE_DETAIL


async def _fetch_league_standings(season_id: int) -> list[dict[str, typing.Any]]:
    return SAMPLE_STANDINGS


async def _fetch_team_infos(
    uniform_team_ids: list[int],
) -> list[dict[str, typing.Any]]:
    return [SAMPLE_TEAM_INFOS.get(tid, {}) for tid in uniform_team_ids]


async def _fetch_season_matches(
    season_id: int, uniform_league_id: int
) -> list[dict[str, typing.Any]]:
    return []


async def _fetch_league_fundamentals(
    season_id: int,
) -> dict[str, list[dict[str, typing.Any]]] | None:
    if season_id == 15485:
        return SAMPLE_FUNDAMENTALS
    return None


@pytest.fixture(autouse=True)
def stub_sporttery(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有测试统一打桩 sporttery 数据源。"""
    monkeypatch.setattr(sporttery, "fetch_league_list", _fetch_league_list)
    monkeypatch.setattr(sporttery, "fetch_league_detail", _fetch_league_detail)
    monkeypatch.setattr(sporttery, "fetch_league_standings", _fetch_league_standings)
    monkeypatch.setattr(sporttery, "fetch_team_infos", _fetch_team_infos)
    monkeypatch.setattr(sporttery, "fetch_season_matches", _fetch_season_matches)
    monkeypatch.setattr(
        sporttery, "fetch_league_fundamentals", _fetch_league_fundamentals
    )


# ---------- 解析层 ----------


class TestParser:
    """parsers/fundamental.py 单元测试。"""

    def test_build_fields_combines_three_views(self) -> None:
        fields = fundamental_parser.build_fundamental_fields(
            "2026/2027", SAMPLE_FUNDAMENTALS["total"][0],
            SAMPLE_FUNDAMENTALS["home"][0], SAMPLE_FUNDAMENTALS["away"][0],
        )
        assert fields["season"] == "2026-2027"
        assert fields["ranking"] == 1
        assert fields["played"] == 2
        assert fields["wins"] == 2
        assert fields["draws"] == 0
        assert fields["losses"] == 0
        assert fields["goals_for"] == 10
        assert fields["goals_against"] == 0
        assert fields["goal_diff"] == 10
        assert fields["points"] == 6
        assert fields["win_rate"] == 100.0
        assert fields["home_played"] == 1
        assert fields["home_win_rate"] == 100.0
        assert fields["away_played"] == 1
        assert fields["away_win_rate"] == 100.0

    def test_build_fields_tolerates_missing_views(self) -> None:
        fields = fundamental_parser.build_fundamental_fields(
            "2026/2027", SAMPLE_FUNDAMENTALS["total"][1]
        )
        # 主/客榜缺失时保留空缺,总榜数据完整
        assert fields["points"] == 4
        assert fields["win_rate"] == 50.0
        assert "home_played" not in fields
        assert "away_played" not in fields

    def test_build_fields_skips_invalid_values(self) -> None:
        row = {**SAMPLE_FUNDAMENTALS["total"][0], "points": "-", "ranking": None}
        fields = fundamental_parser.build_fundamental_fields("2026/2027", row)
        assert "points" not in fields
        assert "ranking" not in fields
        assert fields["played"] == 2

    def test_build_fields_parses_win_rate_string(self) -> None:
        fields = fundamental_parser.build_fundamental_fields(
            "2026/2027",
            {**SAMPLE_FUNDAMENTALS["total"][0], "winProbability": "66.7%"},
        )
        assert fields["win_rate"] == 66.7


# ---------- 同步层 ----------


@pytest.fixture
async def session_factory() -> typing.AsyncGenerator[async_sessionmaker, None]:  # type: ignore[type-args]
    """内存 SQLite 库(启用外键)。"""
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class TestFundamentalSync:
    """球队基本面同步测试。"""

    async def test_sync_creates_league_teams_and_fundamentals(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            result = await fundamental_sync.sync_league_fundamentals(session, "西甲")
            await session.commit()

        assert result.season == "2026-2027"
        assert result.created_count == 2
        assert result.updated_count == 0
        assert result.team_count == 2
        # 档案全称入库,基本面按 uniformTeamId 关联而非按名匹配
        assert result.skipped_team_names == ["桑坦德竞技"]

        async with session_factory() as session:
            fundamentals = (
                await session.scalars(select(TeamFundamentals))
            ).all()
            assert len(fundamentals) == 2
            team_names = {
                team.team_id: team.team_name
                for team in (await session.scalars(select(Team))).all()
            }
            barca = next(
                f for f in fundamentals if team_names[f.team_id] == "巴塞罗那"
            )
            assert barca.ranking == 1
            assert barca.played == 2
            assert barca.wins == 2
            assert barca.goals_for == 10
            assert barca.goal_diff == 10
            assert barca.points == 6
            assert float(barca.win_rate) == 100.0
            assert barca.home_played == 1
            assert barca.away_played == 1

    async def test_sync_is_idempotent(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            await fundamental_sync.sync_league_fundamentals(session, "西甲")
            await session.commit()
        async with session_factory() as session:
            second = await fundamental_sync.sync_league_fundamentals(session, "西甲")
            await session.commit()

        assert second.created_count == 0
        assert second.updated_count == 2
        async with session_factory() as session:
            assert len((await session.scalars(select(TeamFundamentals))).all()) == 2

    async def test_sync_raises_when_all_seasons_empty(
        self, session_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.exceptions import ExternalSourceError

        async def empty_tables(season_id: int) -> None:
            return None

        monkeypatch.setattr(sporttery, "fetch_league_fundamentals", empty_tables)
        async with session_factory() as session:
            with pytest.raises(ExternalSourceError):
                await fundamental_sync.sync_league_fundamentals(session, "西甲")


# ---------- 接口层 ----------


@pytest.fixture
async def client() -> typing.AsyncGenerator[AsyncClient, None]:
    """内存 SQLite + 打桩数据源的测试客户端。"""
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

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
            yield async_client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


class TestFundamentalSyncApi:
    """/api/v1/collector/fundamentals/sync 接口测试。"""

    async def test_sync_fundamentals_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/fundamentals/sync", json={"league_name": "西甲"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["league"]["league_name"] == "西班牙甲级联赛"
        assert body["season"] == "2026-2027"
        assert body["team_count"] == 2
        assert body["created_count"] == 2
        assert body["updated_count"] == 0
        assert body["skipped_teams"] == ["桑坦德竞技"]
        assert body["source"] == "sporttery"

    async def test_sync_fundamentals_requires_league_name(
        self, client: AsyncClient
    ) -> None:
        response = await client.post("/api/v1/collector/fundamentals/sync", json={})
        assert response.status_code == 422
