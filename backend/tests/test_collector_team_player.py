"""数据采集模块测试:球队与球员同步。

外部 sporttery 接口通过 monkeypatch 替换为离线样本,
覆盖 解析 -> 同步入库 -> 接口 的完整链路。
"""

import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.collector.parsers import player as player_parser
from app.collector.parsers import team as team_parser
from app.collector.sync import player_sync, team_sync
from app.collector.sync import league_sync
from app.collector.sources import sporttery
from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import app
from app.models import League, Player, Team

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
# 赛季 -> 比赛列表(倒序展示为按日期降序)
SAMPLE_MATCHES = {
    15485: [
        {
            "matchDate": "2026-08-21",
            "gmMatchId": 1001,
            "wbsjMatchScDesc": "已完成",
            "uniformHomeTeamId": 3000,
            "uniformAwayTeamId": 246,
        }
    ],
    13440: [
        {
            "matchDate": "2026-05-24",
            "gmMatchId": 1002,
            "wbsjMatchScDesc": "已完成",
            "uniformHomeTeamId": 514,
            "uniformAwayTeamId": 246,
        },
        {
            "matchDate": "2026-05-25",
            "gmMatchId": 1003,
            "wbsjMatchScDesc": "未开赛",
            "uniformHomeTeamId": 514,
            "uniformAwayTeamId": 3000,
        },
    ],
}
SAMPLE_MATCH_PLAYERS = {
    1001: {
        "home": {
            "uniformTeamId": 3000,
            "teamShortName": "桑坦德",
            "playerList": [
                {
                    "personId": 1,
                    "personName": "门神A",
                    "playerPositionCode": "Goalkeeper",
                }
            ],
        },
        "away": {
            "uniformTeamId": 246,
            "teamShortName": "巴萨",
            "playerList": [
                {
                    "personId": 2,
                    "personName": "射手B",
                    "playerPositionCode": "Forward",
                },
                {
                    "personId": 3,
                    "personName": "中场C",
                    "playerPositionCode": "Midfielder",
                },
            ],
        },
    },
    1002: {
        "home": {
            "uniformTeamId": 514,
            "teamShortName": "皇马",
            "playerList": [
                {
                    "personId": 4,
                    "personName": "后卫D",
                    "playerPositionCode": "Defender",
                }
            ],
        },
        "away": {
            "uniformTeamId": 246,
            "teamShortName": "巴萨",
            "playerList": [
                {
                    "personId": 5,
                    "personName": "替补E",
                    "playerPositionCode": "Forward",
                }
            ],
        },
    },
}


async def _fetch_league_list() -> list[dict[str, typing.Any]]:
    return SAMPLE_LIST


async def _fetch_league_detail(uniform_league_id: int) -> dict[str, typing.Any]:
    assert uniform_league_id == 24
    return SAMPLE_DETAIL


async def _fetch_league_standings(season_id: int) -> list[dict[str, typing.Any]]:
    assert season_id == 15485
    return SAMPLE_STANDINGS


async def _fetch_team_infos(
    uniform_team_ids: list[int],
) -> list[dict[str, typing.Any]]:
    return [SAMPLE_TEAM_INFOS.get(tid, {}) for tid in uniform_team_ids]


async def _fetch_season_matches(
    season_id: int, uniform_league_id: int
) -> list[dict[str, typing.Any]]:
    assert uniform_league_id == 24
    return SAMPLE_MATCHES.get(season_id, [])


async def _fetch_match_players(
    gm_match_id: int, term_limits: int = 50
) -> dict[str, typing.Any] | None:
    value = SAMPLE_MATCH_PLAYERS.get(gm_match_id)
    if value is None:
        return None
    return value


@pytest.fixture(autouse=True)
def stub_sporttery(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有测试统一打桩 sporttery 数据源。"""
    monkeypatch.setattr(sporttery, "fetch_league_list", _fetch_league_list)
    monkeypatch.setattr(sporttery, "fetch_league_detail", _fetch_league_detail)
    monkeypatch.setattr(sporttery, "fetch_league_standings", _fetch_league_standings)
    monkeypatch.setattr(sporttery, "fetch_team_infos", _fetch_team_infos)
    monkeypatch.setattr(sporttery, "fetch_season_matches", _fetch_season_matches)
    monkeypatch.setattr(sporttery, "fetch_match_players", _fetch_match_players)


# ---------- 解析层 ----------


class TestParsers:
    """parsers/team.py 与 parsers/player.py 单元测试。"""

    def test_build_team_fields_prefers_full_name(self) -> None:
        fields = team_parser.build_team_fields(
            SAMPLE_STANDINGS[0], SAMPLE_TEAM_INFOS[246]
        )
        assert fields == {"team_name": "巴塞罗那"}

    def test_build_team_fields_falls_back_to_abbr(self) -> None:
        fields = team_parser.build_team_fields({"abbCnName": "巴萨", "uniformTeamId": 1}, {})
        assert fields == {"team_name": "巴萨"}

    def test_uniform_team_ids(self) -> None:
        assert team_parser.uniform_team_ids(SAMPLE_STANDINGS) == [246, 514, 3000]

    def test_map_position(self) -> None:
        assert player_parser.map_position("Forward") == "ST"
        assert player_parser.map_position("Midfielder") == "MF"
        assert player_parser.map_position("Defender") == "DF"
        assert player_parser.map_position("Goalkeeper") == "GK"
        assert player_parser.map_position("Unknown") is None
        assert player_parser.map_position(None) is None

    def test_parse_match_players(self) -> None:
        teams = player_parser.parse_match_players(SAMPLE_MATCH_PLAYERS[1001])
        assert set(teams) == {3000, 246}
        assert teams[3000] == [{"player_name": "门神A", "position": "GK"}]
        assert teams[246][0] == {"player_name": "射手B", "position": "ST"}


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


class TestTeamSync:
    """球队同步测试。"""

    async def test_sync_creates_league_and_teams(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            result = await team_sync.sync_league_teams(session, "西甲")
            await session.commit()

        assert result.created_count == 3
        assert result.updated_count == 0
        assert [t.team_name for t in result.teams] == [
            "巴塞罗那",
            "皇家马德里",
            "桑坦德竞技",
        ]
        assert set(result.uniform_team_map) == {246, 514, 3000}
        assert result.league.league_name == "西班牙甲级联赛"

        async with session_factory() as session:
            teams = (await session.scalars(select(Team))).all()
            assert len(teams) == 3
            assert all(t.league_id == result.league.league_id for t in teams)

    async def test_sync_is_idempotent(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            await team_sync.sync_league_teams(session, "西甲")
            await session.commit()
        async with session_factory() as session:
            second = await team_sync.sync_league_teams(session, "西甲")
            await session.commit()

        assert second.created_count == 0
        assert second.updated_count == 3
        async with session_factory() as session:
            assert len((await session.scalars(select(Team))).all()) == 3

    async def test_sync_falls_back_when_latest_season_empty(
        self, session_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 最新赛季 2026/2027 未开赛、积分榜为空 -> 回溯 2025/2026
        async def standings(season_id: int) -> list[dict[str, typing.Any]]:
            return [] if season_id == 15485 else SAMPLE_STANDINGS

        monkeypatch.setattr(sporttery, "fetch_league_standings", standings)
        async with session_factory() as session:
            result = await team_sync.sync_league_teams(session, "西甲")
            await session.commit()

        assert result.created_count == 3
        assert [t.team_name for t in result.teams] == [
            "巴塞罗那",
            "皇家马德里",
            "桑坦德竞技",
        ]
        # 联赛档案赛季校正为实际取数的赛季
        assert result.league.season == "2025-2026"

    async def test_sync_merges_qualifier_teams_from_latest_matches(
        self, session_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 资格赛参赛队不在积分榜(如欧冠 8 月附加赛),以最新赛季赛程补齐;
        # 已在积分榜的球队(巴萨)按 uniformTeamId 去重
        async def matches(
            season_id: int, uniform_league_id: int
        ) -> list[dict[str, typing.Any]]:
            assert uniform_league_id == 24
            if season_id != 15485:
                return []
            return [
                {
                    "matchDate": "2026-08-26",
                    "gmMatchId": 0,
                    "wbsjMatchScDesc": "未开始",
                    "homeAbbCnName": "巴萨",
                    "uniformHomeTeamId": 246,
                    "awayAbbCnName": "塞维利亚",
                    "uniformAwayTeamId": 999,
                }
            ]

        monkeypatch.setattr(sporttery, "fetch_season_matches", matches)
        async with session_factory() as session:
            result = await team_sync.sync_league_teams(session, "西甲")
            await session.commit()

        assert result.created_count == 4
        assert {t.team_name for t in result.teams} == {
            "巴塞罗那",
            "皇家马德里",
            "桑坦德竞技",
            "塞维利亚",
        }
        assert set(result.uniform_team_map) == {246, 514, 3000, 999}

    async def test_sync_cup_falls_back_to_match_teams(
        self, session_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 纯淘汰赛制杯赛(如英联赛杯)各赛季均无积分榜 -> 从赛程参赛队提取
        async def empty_standings(season_id: int) -> list[dict[str, typing.Any]]:
            return []

        cup_matches = {
            15485: [
                {
                    "matchDate": "2026-08-28",
                    "gmMatchId": 0,
                    "wbsjMatchScDesc": "未开始",
                    "homeAbbCnName": "巴萨",
                    "uniformHomeTeamId": 246,
                    "awayAbbCnName": "桑坦德",
                    "uniformAwayTeamId": 3000,
                }
            ],
            13440: [
                {
                    "matchDate": "2026-01-15",
                    "gmMatchId": 1004,
                    "wbsjMatchScDesc": "已完成",
                    "homeAbbCnName": "皇马",
                    "uniformHomeTeamId": 514,
                    "awayAbbCnName": "巴萨",
                    "uniformAwayTeamId": 246,
                }
            ],
        }

        async def matches(
            season_id: int, uniform_league_id: int
        ) -> list[dict[str, typing.Any]]:
            assert uniform_league_id == 24
            return cup_matches.get(season_id, [])

        monkeypatch.setattr(sporttery, "fetch_league_standings", empty_standings)
        monkeypatch.setattr(sporttery, "fetch_season_matches", matches)
        async with session_factory() as session:
            result = await team_sync.sync_league_teams(session, "西甲")
            await session.commit()

        assert result.created_count == 3
        # 最新赛季在前(巴萨、桑坦德),历史赛季补齐皇马;按 uniformTeamId 去重
        assert [t.team_name for t in result.teams] == [
            "巴塞罗那",
            "桑坦德竞技",
            "皇家马德里",
        ]
        assert set(result.uniform_team_map) == {246, 3000, 514}
        assert result.league.season == "2026-2027"

    async def test_sync_raises_when_all_seasons_empty(
        self, session_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.exceptions import ExternalSourceError

        async def empty_standings(season_id: int) -> list[dict[str, typing.Any]]:
            return []

        async def empty_matches(
            season_id: int, uniform_league_id: int
        ) -> list[dict[str, typing.Any]]:
            return []

        monkeypatch.setattr(sporttery, "fetch_league_standings", empty_standings)
        monkeypatch.setattr(sporttery, "fetch_season_matches", empty_matches)
        async with session_factory() as session:
            with pytest.raises(ExternalSourceError):
                await team_sync.sync_league_teams(session, "西甲")


class TestPlayerSync:
    """球员同步测试(含跨赛季回溯)。"""

    async def test_sync_collects_players_across_seasons(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            result = await player_sync.sync_league_players(session, "西甲")
            await session.commit()

        # 当前赛季 1 场覆盖 桑坦德+巴萨,上一赛季 1 场补齐皇马;
        # 未开赛场次(1003)被跳过
        assert result.matches_scanned == 2
        assert result.created_count == 4
        assert result.updated_count == 0
        assert result.skipped_team_names == []
        counts = dict(result.team_player_counts)
        assert counts == {"桑坦德竞技": 1, "巴塞罗那": 2, "皇家马德里": 1}

        async with session_factory() as session:
            players = (await session.scalars(select(Player))).all()
            assert len(players) == 4
            positions = {p.player_name: p.position for p in players}
            assert positions["门神A"] == "GK"
            assert positions["射手B"] == "ST"
            assert positions["中场C"] == "MF"
            assert positions["后卫D"] == "DF"

    async def test_sync_is_idempotent(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            await player_sync.sync_league_players(session, "西甲")
            await session.commit()
        async with session_factory() as session:
            second = await player_sync.sync_league_players(session, "西甲")
            await session.commit()

        assert second.created_count == 0
        assert second.updated_count == 4
        async with session_factory() as session:
            assert len((await session.scalars(select(Player))).all()) == 4

    async def test_sync_reports_skipped_teams(
        self, session_factory: async_sessionmaker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 所有场次都拿不到球员数据 -> 全部球队进入 skipped
        async def no_players(gm_match_id: int, term_limits: int = 50) -> None:
            return None

        monkeypatch.setattr(sporttery, "fetch_match_players", no_players)
        async with session_factory() as session:
            result = await player_sync.sync_league_players(session, "西甲")
            await session.commit()

        assert result.created_count == 0
        assert set(result.skipped_team_names) == {"巴塞罗那", "皇家马德里", "桑坦德竞技"}


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


class TestSyncApi:
    """/api/v1/collector/teams|players/sync 接口测试。"""

    async def test_sync_teams_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/teams/sync", json={"league_name": "西甲"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["team_count"] == 3
        assert body["created_count"] == 3
        assert body["league"]["league_name"] == "西班牙甲级联赛"
        assert body["source"] == "sporttery"

    async def test_sync_players_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/players/sync", json={"league_name": "西甲"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["team_count"] == 3
        assert body["player_count"] == 4
        assert body["matches_scanned"] == 2
        assert body["skipped_teams"] == []
        names = {t["team_name"] for t in body["team_player_counts"]}
        assert names == {"巴塞罗那", "皇家马德里", "桑坦德竞技"}

    async def test_sync_players_unknown_league(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/players/sync", json={"league_name": "中超"}
        )
        assert response.status_code == 422

    async def test_sync_requires_api_key(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/teams/sync",
            json={"league_name": "西甲"},
            headers={"X-API-Key": "wrong"},
        )
        assert response.status_code == 401
