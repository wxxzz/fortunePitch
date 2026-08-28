"""数据采集模块测试:赛果开奖同步。

外部 sporttery 接口通过 monkeypatch 替换为离线样本,
覆盖 解析 -> 同步入库/比分回写 -> 接口 的完整链路。
"""

import datetime
import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.collector.parsers import result as result_parser
from app.collector.sources import sporttery
from app.collector.sync import result_sync
from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import app
from app.models import League, MatchGame, MatchResult, MatchStatus, Team

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# ---------- 离线样本 ----------

# 2041028(客胜)/ 2041030(主胜+让球)/ 2041102 未入库 / 2041103 取消场次
SAMPLE_RESULTS: list[dict[str, typing.Any]] = [
    {
        "matchId": 2041028,
        "matchNumStr": "周一001",
        "leagueName": "西班牙甲级联赛",
        "homeTeam": "巴萨",
        "awayTeam": "皇马",
        "allHomeTeam": "巴塞罗那",
        "allAwayTeam": "皇家马德里",
        "matchDate": "2026-08-24",
        "sectionsNo1": "0:1",
        "sectionsNo999": "1:2",
        "winFlag": "A",
        "goalLine": "-1",
        "h": "2.13",
        "d": "2.98",
        "a": "3.08",
        "poolStatus": "Payout",
    },
    {
        "matchId": 2041030,
        "matchNumStr": "周一004",
        "leagueName": "西班牙甲级联赛",
        "homeTeam": "巴萨",
        "awayTeam": "桑坦德",
        "allHomeTeam": "巴塞罗那",
        "allAwayTeam": "桑坦德竞技",
        "matchDate": "2026-08-25",
        "sectionsNo1": "2:0",
        "sectionsNo999": "3:1",
        "winFlag": "H",
        "goalLine": "-1",
        "h": "1.85",
        "d": "3.40",
        "a": "4.20",
        "poolStatus": "Payout",
    },
    {
        # 场次未入库,应被跳过
        "matchId": 2041102,
        "matchNumStr": "周一003",
        "leagueName": "西班牙甲级联赛",
        "homeTeam": "奥萨苏纳",
        "awayTeam": "巴萨",
        "allHomeTeam": "奥萨苏纳",
        "allAwayTeam": "巴塞罗那",
        "matchDate": "2026-08-24",
        "sectionsNo1": "1:1",
        "sectionsNo999": "2:2",
        "winFlag": "D",
        "goalLine": "",
        "h": "3.10",
        "d": "3.00",
        "a": "2.20",
        "poolStatus": "Payout",
    },
    {
        # 已入库但取消,比分无效,不应回写比分
        "matchId": 2041031,
        "matchNumStr": "周一005",
        "leagueName": "西班牙甲级联赛",
        "homeTeam": "皇马",
        "awayTeam": "桑坦德",
        "allHomeTeam": "皇家马德里",
        "allAwayTeam": "桑坦德竞技",
        "matchDate": "2026-08-24",
        "sectionsNo1": "取消",
        "sectionsNo999": "无效场次",
        "winFlag": "",
        "goalLine": "",
        "h": "",
        "d": "",
        "a": "",
        "poolStatus": "Cancelled",
    },
]


async def _fetch_match_results(date: str) -> list[dict[str, typing.Any]]:
    return [item for item in SAMPLE_RESULTS if item["matchDate"] == date]


@pytest.fixture(autouse=True)
def stub_sporttery(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有测试统一打桩 sporttery 数据源。"""
    monkeypatch.setattr(sporttery, "fetch_match_results", _fetch_match_results)


# ---------- 解析层 ----------


class TestResultParsers:
    """parsers/result.py 单元测试。"""

    def test_build_result_fields_away_win(self) -> None:
        fields = result_parser.build_result_fields(SAMPLE_RESULTS[0])
        assert fields["match_id"] == "2041028"
        assert fields["match_num_str"] == "周一001"
        assert fields["home_team_name"] == "巴塞罗那"
        assert (fields["half_home_score"], fields["half_away_score"]) == (0, 1)
        assert (fields["full_home_score"], fields["full_away_score"]) == (1, 2)
        assert fields["had"] == "客胜"
        # 1 + (-1) = 0 < 2 -> 让球客胜
        assert fields["hhad"] == "让球客胜"
        assert fields["crs"] == "1:2"
        assert fields["ttg"] == "3"
        assert fields["hafu"] == "负负"
        assert fields["goal_line"] == "-1"
        assert (fields["sp_h"], fields["sp_d"], fields["sp_a"]) == (2.13, 2.98, 3.08)
        assert fields["pool_status"] == "Payout"

    def test_build_result_fields_home_win_with_handicap(self) -> None:
        fields = result_parser.build_result_fields(SAMPLE_RESULTS[1])
        assert fields["had"] == "主胜"
        # 3 + (-1) = 2 > 1 -> 让球主胜
        assert fields["hhad"] == "让球主胜"
        assert fields["hafu"] == "胜胜"
        assert fields["ttg"] == "4"

    def test_build_result_fields_cancelled(self) -> None:
        fields = result_parser.build_result_fields(SAMPLE_RESULTS[3])
        assert fields["full_home_score"] is None
        assert fields["had"] is None
        assert fields["crs"] is None
        assert fields["pool_status"] == "Cancelled"
        assert fields["goal_line"] is None
        assert fields["sp_h"] is None

    def test_build_result_fields_requires_match_id(self) -> None:
        with pytest.raises(Exception):
            result_parser.build_result_fields({"sectionsNo999": "1:2"})

    def test_derive_play_results_draw(self) -> None:
        fields = result_parser.derive_play_results(1, 1, 0, 0, 0)
        assert fields["had"] == "平"
        assert fields["hhad"] == "让球平"
        assert fields["hafu"] == "平平"
        assert fields["ttg"] == "2"


# ---------- 同步层 ----------


@pytest.fixture
async def session_factory() -> typing.AsyncGenerator[async_sessionmaker, None]:  # type: ignore[type-args]
    """内存 SQLite 库(启用外键),预置西甲联赛、三支球队与两场比赛。"""
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
        league = League(
            league_name="西班牙甲级联赛", country="西班牙", tier=1, season="2026-2027"
        )
        session.add(league)
        await session.flush()
        team_ids: dict[str, int] = {}
        for name in ("巴塞罗那", "皇家马德里", "桑坦德竞技"):
            team = Team(league_id=league.league_id, team_name=name)
            session.add(team)
            await session.flush()
            team_ids[name] = team.team_id
        for match_id, match_time, home, away in (
            ("2041028", datetime.datetime(2026, 8, 24, 20, 0), "巴塞罗那", "皇家马德里"),
            ("2041030", datetime.datetime(2026, 8, 25, 1, 30), "巴塞罗那", "桑坦德竞技"),
            ("2041031", datetime.datetime(2026, 8, 24, 22, 0), "皇家马德里", "桑坦德竞技"),
        ):
            session.add(
                MatchGame(
                    match_id=match_id,
                    league_id=league.league_id,
                    home_team_id=team_ids[home],
                    away_team_id=team_ids[away],
                    match_time=match_time,
                    match_status=MatchStatus.PENDING,
                )
            )
        await session.commit()
    yield factory
    await engine.dispose()


class TestResultSync:
    """赛果同步测试。"""

    async def test_sync_creates_results_and_updates_games(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            result = await result_sync.sync_results_by_date(session, "2026-08-24")
            await session.commit()

        # 2041030 的比赛日为 08-25,不计入;2041102 未入库被跳过
        assert result.day_result_count == 3
        assert result.created_count == 2
        assert result.updated_count == 0
        assert result.game_updated_count == 1
        assert len(result.skipped_matches) == 1
        assert "奥萨苏纳" in result.skipped_matches[0]

        async with session_factory() as session:
            # 客胜场次回写比分与状态
            game = await session.get(MatchGame, "2041028")
            assert game is not None
            assert (game.home_score, game.away_score) == (1, 2)
            assert game.match_status == MatchStatus.FINISHED
            # 取消场次不改写比分,状态保持未开
            cancelled = await session.get(MatchGame, "2041031")
            assert cancelled is not None
            assert cancelled.home_score is None
            assert cancelled.match_status == MatchStatus.PENDING
            # 赛果记录内容
            record = await session.get(MatchResult, "2041028")
            assert record is not None
            assert record.had == "客胜"
            assert record.hafu == "负负"
            assert len((await session.scalars(select(MatchResult))).all()) == 2

    async def test_sync_is_idempotent(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            await result_sync.sync_results_by_date(session, "2026-08-24")
            await session.commit()
        async with session_factory() as session:
            result = await result_sync.sync_results_by_date(session, "2026-08-24")
            await session.commit()

        assert result.created_count == 0
        assert result.updated_count == 2
        async with session_factory() as session:
            assert len((await session.scalars(select(MatchResult))).all()) == 2

    async def test_list_results_by_date_filters_and_orders(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            await result_sync.sync_results_by_date(session, "2026-08-24")
            await session.commit()
        async with session_factory() as session:
            pairs = await result_sync.list_results_by_date(
                session, datetime.date(2026, 8, 24)
            )

        # 2041030 开赛时间为次日 01:30,不计入 08-24
        assert [result.match_id for result, _ in pairs] == ["2041028", "2041031"]
        record, game = pairs[0]
        assert game.league.league_name == "西班牙甲级联赛"
        assert game.home_team.team_name == "巴塞罗那"

    async def test_sync_empty_day_reports_zero(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            result = await result_sync.sync_results_by_date(session, "2026-09-01")
            await session.commit()

        assert result.day_result_count == 0
        assert result.created_count == 0
        assert result.skipped_matches == []


# ---------- 接口层 ----------


@pytest.fixture
async def client(session_factory: async_sessionmaker) -> typing.AsyncGenerator[AsyncClient, None]:  # type: ignore[type-args]
    """将应用数据库会话替换为内存库。"""

    async def override_session() -> typing.AsyncGenerator[None, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()


class TestResultAPI:
    """POST /collector/results/sync 与 GET /match/results 接口测试。"""

    async def test_sync_results_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/results/sync",
            json={"date": "2026-08-24"},
            headers=HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["date"] == "2026-08-24"
        assert body["day_result_count"] == 3
        assert body["created_count"] == 2
        assert body["game_updated_count"] == 1
        assert len(body["skipped_matches"]) == 1
        assert body["source"] == "sporttery"

    async def test_list_results_endpoint(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/collector/results/sync",
            json={"date": "2026-08-24"},
            headers=HEADERS,
        )
        response = await client.get(
            "/api/v1/match/results",
            params={"date": "2026-08-24"},
            headers=HEADERS,
        )
        assert response.status_code == 200
        results = response.json()
        assert [r["match_id"] for r in results] == ["2041028", "2041031"]
        first = results[0]
        assert first["match_num_str"] == "周一001"
        assert first["league_name"] == "西班牙甲级联赛"
        assert first["home_team_name"] == "巴塞罗那"
        assert first["half_score"] == "0:1"
        assert first["full_score"] == "1:2"
        assert first["had"] == "客胜"
        assert first["hhad"] == "让球客胜"
        assert first["ttg"] == "3"
        assert first["hafu"] == "负负"
        assert first["sp_a"] == 3.08
        assert first["pool_status"] == "Payout"
        # 取消场次比分与玩法结果为空,保留状态
        cancelled = results[1]
        assert cancelled["full_score"] is None
        assert cancelled["had"] is None
        assert cancelled["pool_status"] == "Cancelled"

    async def test_list_results_empty_before_sync(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/match/results",
            params={"date": "2026-08-24"},
            headers=HEADERS,
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_endpoints_reject_bad_date(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/results/sync",
            json={"date": "not-a-date"},
            headers=HEADERS,
        )
        assert response.status_code == 422
        response = await client.get(
            "/api/v1/match/results",
            params={"date": "not-a-date"},
            headers=HEADERS,
        )
        assert response.status_code == 422
