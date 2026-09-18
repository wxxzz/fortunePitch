"""数据采集模块测试:赛事(在售赛程)同步。

外部 sporttery 接口通过 monkeypatch 替换为离线样本,
覆盖 解析 -> 同步入库 -> 接口 的完整链路。
"""

import datetime
import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.collector.parsers import match as match_parser
from app.collector.parsers import odds as odds_parser
from app.collector.sync import match_sync
from app.collector.sources import sporttery
from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.core.exceptions import ExternalSourceError
from app.main import app
from app.models import League, MatchGame, MatchOdds, MatchOddsSnapshot, MatchStatus, Team

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# ---------- 离线样本 ----------

SAMPLE_MATCHES: list[dict[str, typing.Any]] = [
    # 目标售卖日:西甲场次(球队可入库)+ 意甲场次(联赛未入库)
    {
        "businessDate": "2026-08-24",
        "matchId": 2041028,
        "matchNumStr": "周一001",
        "matchDate": "2026-08-24",
        "matchTime": "20:00",
        "leagueAllName": "西班牙甲级联赛",
        "homeTeamAllName": "巴塞罗那",
        "awayTeamAllName": "皇家马德里",
        "matchStatus": "Selling",
    },
    {
        # 次日凌晨开赛,仍归属 2026-08-24 售卖日
        "businessDate": "2026-08-24",
        "matchId": 2041030,
        "matchNumStr": "周一004",
        "matchDate": "2026-08-25",
        "matchTime": "01:30",
        "leagueAllName": "西班牙甲级联赛",
        "homeTeamAllName": "巴塞罗那",
        "awayTeamAllName": "桑坦德竞技",
        "matchStatus": "Define",
    },
    {
        "businessDate": "2026-08-24",
        "matchId": 2041101,
        "matchNumStr": "周一002",
        "matchDate": "2026-08-24",
        "matchTime": "21:00",
        "leagueAllName": "意大利甲级联赛",
        "homeTeamAllName": "博洛尼亚",
        "awayTeamAllName": "拉齐奥",
        "matchStatus": "Selling",
    },
    {
        # 目标售卖日但主队未入库
        "businessDate": "2026-08-24",
        "matchId": 2041102,
        "matchNumStr": "周一003",
        "matchDate": "2026-08-24",
        "matchTime": "22:00",
        "leagueAllName": "西班牙甲级联赛",
        "homeTeamAllName": "奥萨苏纳",
        "awayTeamAllName": "巴塞罗那",
        "matchStatus": "Selling",
    },
    # 其他售卖日,应被过滤
    {
        "businessDate": "2026-08-25",
        "matchId": 2041201,
        "matchNumStr": "周二001",
        "matchDate": "2026-08-25",
        "matchTime": "20:00",
        "leagueAllName": "西班牙甲级联赛",
        "homeTeamAllName": "皇家马德里",
        "awayTeamAllName": "巴塞罗那",
        "matchStatus": "Selling",
    },
]


async def _fetch_match_day_list() -> list[dict[str, typing.Any]]:
    return SAMPLE_MATCHES


# 2041028 已入库(西甲);2041201 属其他售卖日未入库;2041300 全玩法未开售
SAMPLE_ODDS: list[dict[str, typing.Any]] = [
    {
        "matchId": 2041028,
        "pools": {
            "had": {
                "h": "2.15", "d": "3.40", "a": "3.20",
                "updateDate": "2026-08-24", "updateTime": "10:00:00",
            },
            "hhad": {
                "h": "1.55", "d": "3.80", "a": "5.50", "goalLine": "-1",
                "updateDate": "2026-08-24", "updateTime": "10:00:01",
            },
            "ttg": {
                "s0": "8.50", "s1": "4.20", "s2": "3.10", "s3": "3.50",
                "s4": "4.00", "s5": "8.00", "s6": "15.00", "s7": "25.00",
                "updateDate": "2026-08-24", "updateTime": "10:00:02",
            },
            "crs": {
                "s01s00": "7.00", "s01s01": "6.50", "s1sh": "30.00",
                # 线上真实响应还包含 f 后缀副本键与元数据键,解析时必须跳过
                "s01s00f": "7.10", "s1shf": "31.00", "goalLine": "-1",
                "goalLineValue": "-1.0",
                "updateDate": "2026-08-24", "updateTime": "10:00:03",
            },
            "hafu": {
                "hh": "3.50", "hd": "14.00", "aa": "5.00",
                "updateDate": "2026-08-24", "updateTime": "10:00:04",
            },
        },
        "updateTime": "2026-08-24 10:00:04",
    },
    {
        "matchId": 2041201,
        "pools": {
            "had": {"h": "1.80", "d": "3.20", "a": "4.10"},
        },
        "updateTime": "2026-08-24 10:00:00",
    },
    {
        "matchId": 2041300,
        "pools": {"crs": {"s01s00": "0", "s1sh": ""}},
        "updateTime": "2026-08-24 10:00:00",
    },
]


async def _fetch_match_odds() -> list[dict[str, typing.Any]]:
    return SAMPLE_ODDS


@pytest.fixture(autouse=True)
def stub_sporttery(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有测试统一打桩 sporttery 数据源。"""
    monkeypatch.setattr(sporttery, "fetch_match_day_list", _fetch_match_day_list)
    monkeypatch.setattr(sporttery, "fetch_match_odds", _fetch_match_odds)


# ---------- 解析层 ----------


class TestParsers:
    """parsers/match.py 单元测试。"""

    def test_filter_matches_by_date_keeps_business_date(self) -> None:
        kept = match_parser.filter_matches_by_date(SAMPLE_MATCHES, "2026-08-24")
        assert [m["matchId"] for m in kept] == [2041028, 2041030, 2041101, 2041102]

    def test_filter_matches_by_date_empty_when_no_sale(self) -> None:
        assert match_parser.filter_matches_by_date(SAMPLE_MATCHES, "2026-09-01") == []

    def test_filter_matches_by_date_rejects_bad_format(self) -> None:
        with pytest.raises(Exception):
            match_parser.filter_matches_by_date(SAMPLE_MATCHES, "2026/08/24")

    def test_build_match_fields(self) -> None:
        fields = match_parser.build_match_fields(SAMPLE_MATCHES[1])
        assert fields == {
            "match_id": "2041030",
            "match_num_str": "周一004",
            "match_time": datetime.datetime(2026, 8, 25, 1, 30),
            # 次日凌晨开赛,售卖日仍是前一天
            "business_date": datetime.date(2026, 8, 24),
            "league_name": "西班牙甲级联赛",
            "home_team_name": "巴塞罗那",
            "away_team_name": "桑坦德竞技",
            "match_status": MatchStatus.PENDING,
        }

    def test_build_match_fields_defaults_empty_num(self) -> None:
        # matchNumStr 缺失时场次编号为空串(不影响其余字段)
        sub = {k: v for k, v in SAMPLE_MATCHES[0].items() if k != "matchNumStr"}
        fields = match_parser.build_match_fields(sub)
        assert fields["match_id"] == "2041028"
        assert fields["match_num_str"] == ""

    def test_build_business_date_missing(self) -> None:
        assert match_parser.build_business_date({"matchId": 1}) is None

    def test_build_business_date_rejects_bad_format(self) -> None:
        with pytest.raises(Exception):
            match_parser.build_business_date({"businessDate": "2026/08/24"})

    def test_build_match_fields_requires_names(self) -> None:
        with pytest.raises(Exception):
            match_parser.build_match_fields({"matchId": 1, "matchDate": "2026-08-24"})

    def test_build_match_fields_requires_time(self) -> None:
        with pytest.raises(Exception):
            match_parser.build_match_fields(
                {
                    "matchId": 1,
                    "leagueAllName": "西甲",
                    "homeTeamAllName": "A",
                    "awayTeamAllName": "B",
                    "matchDate": "2026-08-24",
                }
            )


class TestOddsParsers:
    """parsers/odds.py 单元测试。"""

    def test_build_odds_pools_normalizes_all_plays(self) -> None:
        pools = odds_parser.build_odds_pools(SAMPLE_ODDS[0]["pools"])
        assert [p["poolCode"] for p in pools] == ["HAD", "HHAD", "CRS", "TTG", "HAFU"]
        had = pools[0]
        assert had["playName"] == "胜平负"
        assert had["options"] == [
            {"code": "h", "label": "主胜", "odds": 2.15},
            {"code": "d", "label": "平", "odds": 3.4},
            {"code": "a", "label": "客胜", "odds": 3.2},
        ]
        hhad = pools[1]
        assert hhad["playName"] == "让球胜平负"
        assert hhad["goalLine"] == "-1"
        crs = pools[2]
        assert [o["label"] for o in crs["options"]] == ["1:0", "1:1", "胜其他"]
        ttg = pools[3]
        assert [o["label"] for o in ttg["options"]] == [
            "0", "1", "2", "3", "4", "5", "6", "7+",
        ]
        hafu = pools[4]
        assert hafu["options"][0] == {"code": "hh", "label": "胜胜", "odds": 3.5}

    def test_build_odds_pools_drops_unsold_plays(self) -> None:
        # 全部赔率无效 -> 空列表
        assert odds_parser.build_odds_pools({"crs": {"s01s00": "0", "s1sh": ""}}) == []
        # 部分选项无效 -> 仅保留有效选项
        pools = odds_parser.build_odds_pools({"had": {"h": "2.15"}})
        assert len(pools) == 1
        assert [o["code"] for o in pools[0]["options"]] == ["h"]

    def test_build_odds_pools_skips_crs_noise_keys(self) -> None:
        # f 后缀副本键 / 元数据键不进入比分选项,不抛异常
        pools = odds_parser.build_odds_pools(
            {
                "crs": {
                    "s00s01": "8.00", "s00s01f": "8.10",
                    "s1sh": "30.00", "s1shf": "31.00",
                    "s1sa": "50.00", "s1saf": "51.00",
                    "goalLine": "-1", "goalLineValue": "-1.0",
                    "updateDate": "2026-08-26", "updateTime": "10:00:00",
                }
            }
        )
        assert len(pools) == 1
        assert [o["code"] for o in pools[0]["options"]] == ["s00s01", "s1sh", "s1sa"]

    def test_build_odds_record(self) -> None:
        fields = odds_parser.build_odds_record(SAMPLE_ODDS[0])
        assert fields is not None
        assert fields["match_id"] == "2041028"
        assert len(fields["pools"]) == 5
        # 全玩法未开售 -> None
        assert odds_parser.build_odds_record(SAMPLE_ODDS[2]) is None

    def test_build_odds_record_requires_match_id(self) -> None:
        with pytest.raises(Exception):
            odds_parser.build_odds_record({"pools": {"had": {"h": "2.15"}}})


# ---------- 同步层 ----------


@pytest.fixture
async def session_factory() -> typing.AsyncGenerator[async_sessionmaker, None]:  # type: ignore[type-args]
    """内存 SQLite 库(启用外键),预置西甲联赛与三支球队。"""
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
        for name in ("巴塞罗那", "皇家马德里", "桑坦德竞技"):
            session.add(Team(league_id=league.league_id, team_name=name))
        await session.commit()
    yield factory
    await engine.dispose()


class TestMatchSync:
    """赛事同步测试。"""

    async def test_sync_creates_matches_for_archived_league(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            result = await match_sync.sync_matches_by_date(session, "2026-08-24")
            await session.commit()

        assert result.day_match_count == 4
        assert result.created_count == 2
        assert result.updated_count == 0
        assert result.skipped_league_names == ["意大利甲级联赛"]
        assert len(result.skipped_matches) == 1
        assert "奥萨苏纳" in result.skipped_matches[0]

        async with session_factory() as session:
            games = (await session.scalars(select(MatchGame))).all()
            assert sorted(g.match_id for g in games) == ["2041028", "2041030"]
            barca = await session.scalar(select(Team).where(Team.team_name == "巴塞罗那"))
            game = await session.get(MatchGame, "2041028")
            assert game is not None
            assert game.home_team_id == barca.team_id
            assert game.match_status == MatchStatus.PENDING
            assert game.match_time == datetime.datetime(2026, 8, 24, 20, 0)
            assert game.home_score is None
            # 场次编号随赛程同步落库
            assert game.match_num_str == "周一001"
            # 售卖日落库:次日凌晨开赛的 2041030 仍归属 8-24 售卖日
            assert game.business_date == datetime.date(2026, 8, 24)
            late_game = await session.get(MatchGame, "2041030")
            assert late_game is not None
            assert late_game.match_num_str == "周一004"
            assert late_game.match_time == datetime.datetime(2026, 8, 25, 1, 30)
            assert late_game.business_date == datetime.date(2026, 8, 24)

    async def test_sync_is_idempotent_and_keeps_scores(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            await match_sync.sync_matches_by_date(session, "2026-08-24")
            await session.commit()

        # 模拟赛果回填后的状态与比分
        async with session_factory() as session:
            game = await session.get(MatchGame, "2041028")
            assert game is not None
            game.match_status = MatchStatus.FINISHED
            game.home_score = 2
            game.away_score = 1
            await session.commit()

        async with session_factory() as session:
            result = await match_sync.sync_matches_by_date(session, "2026-08-24")
            await session.commit()

        assert result.created_count == 0
        assert result.updated_count == 2
        async with session_factory() as session:
            game = await session.get(MatchGame, "2041028")
            assert game is not None
            assert game.match_status == MatchStatus.FINISHED
            assert (game.home_score, game.away_score) == (2, 1)

    async def test_sync_empty_day_reports_zero(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            result = await match_sync.sync_matches_by_date(session, "2026-09-01")
            await session.commit()

        assert result.day_match_count == 0
        assert result.created_count == 0
        assert result.skipped_league_names == []

    async def test_sync_persists_odds_for_archived_matches(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            result = await match_sync.sync_matches_by_date(session, "2026-08-24")
            await session.commit()

        # 已入库场次 2041028 写入赔率;未入库的 2041201 / 全未开售的 2041300 跳过
        assert result.odds_count == 1
        async with session_factory() as session:
            odds = await session.get(MatchOdds, "2041028")
            assert odds is not None
            pool_codes = [p["poolCode"] for p in odds.pools]
            assert pool_codes == ["HAD", "HHAD", "CRS", "TTG", "HAFU"]
            assert odds.pools[1]["goalLine"] == "-1"
            assert len((await session.scalars(select(MatchOdds))).all()) == 1

    async def test_sync_odds_is_idempotent(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            await match_sync.sync_matches_by_date(session, "2026-08-24")
            await session.commit()
        async with session_factory() as session:
            result = await match_sync.sync_matches_by_date(session, "2026-08-24")
            await session.commit()

        assert result.odds_count == 1
        async with session_factory() as session:
            assert len((await session.scalars(select(MatchOdds))).all()) == 1

    async def test_sync_snapshots_odds_on_first_write(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            result = await match_sync.sync_matches_by_date(session, "2026-08-24")
            await session.commit()

        # 首次写入赔率 -> 追加 1 条快照
        assert result.odds_snapshot_count == 1
        async with session_factory() as session:
            snapshots = (
                await session.scalars(
                    select(MatchOddsSnapshot).where(
                        MatchOddsSnapshot.match_id == "2041028"
                    )
                )
            ).all()
            assert len(snapshots) == 1
            pool_codes = [p["poolCode"] for p in snapshots[0].pools]
            assert pool_codes == ["HAD", "HHAD", "CRS", "TTG", "HAFU"]
            assert snapshots[0].snapshot_time is not None

    async def test_sync_skips_snapshot_when_odds_unchanged(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with session_factory() as session:
            await match_sync.sync_matches_by_date(session, "2026-08-24")
            await session.commit()
        async with session_factory() as session:
            result = await match_sync.sync_matches_by_date(session, "2026-08-24")
            await session.commit()

        # 赔率未变 -> 不新增快照
        assert result.odds_snapshot_count == 0
        async with session_factory() as session:
            snapshots = (
                await session.scalars(select(MatchOddsSnapshot))
            ).all()
            assert len(snapshots) == 1

    async def test_sync_snapshots_odds_when_changed(
        self,
        session_factory: async_sessionmaker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async with session_factory() as session:
            await match_sync.sync_matches_by_date(session, "2026-08-24")
            await session.commit()

        # 赔率变化:主胜 2.15 -> 2.05
        changed_odds = [
            {
                "matchId": 2041028,
                "pools": {
                    "had": {"h": "2.05", "d": "3.40", "a": "3.20"},
                    "hhad": {
                        "h": "1.55", "d": "3.80", "a": "5.50", "goalLine": "-1"
                    },
                    "ttg": {
                        "s0": "8.50", "s1": "4.20", "s2": "3.10", "s3": "3.50",
                        "s4": "4.00", "s5": "8.00", "s6": "15.00", "s7": "25.00",
                    },
                    "crs": {
                        "s01s00": "7.00", "s01s01": "6.50", "s1sh": "30.00",
                        "s01s00f": "7.10", "s1shf": "31.00", "goalLine": "-1",
                        "goalLineValue": "-1.0",
                    },
                    "hafu": {"hh": "3.50", "hd": "14.00", "aa": "5.00"},
                },
                "updateTime": "2026-08-24 12:00:04",
            }
        ]

        async def fetch_changed_odds() -> list[dict[str, typing.Any]]:
            return changed_odds

        monkeypatch.setattr(sporttery, "fetch_match_odds", fetch_changed_odds)
        async with session_factory() as session:
            result = await match_sync.sync_matches_by_date(session, "2026-08-24")
            await session.commit()

        assert result.odds_snapshot_count == 1
        async with session_factory() as session:
            snapshots = (
                await session.scalars(
                    select(MatchOddsSnapshot)
                    .where(MatchOddsSnapshot.match_id == "2041028")
                    .order_by(MatchOddsSnapshot.snapshot_id)
                )
            ).all()
            assert len(snapshots) == 2
            had_by_snapshot = [
                next(
                    o["odds"]
                    for p in s.pools
                    if p["poolCode"] == "HAD"
                    for o in p["options"]
                    if o["code"] == "h"
                )
                for s in snapshots
            ]
            assert had_by_snapshot == [2.15, 2.05]
            # 即时赔率同步刷新为最新值
            odds = await session.get(MatchOdds, "2041028")
            assert odds is not None
            had = next(
                o["odds"] for o in odds.pools[0]["options"] if o["code"] == "h"
            )
            assert had == 2.05

    async def test_sync_survives_odds_source_failure(
        self,
        session_factory: async_sessionmaker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def broken_odds() -> list[dict[str, typing.Any]]:
            raise ExternalSourceError("竞彩赔率拉取失败")

        monkeypatch.setattr(sporttery, "fetch_match_odds", broken_odds)
        async with session_factory() as session:
            result = await match_sync.sync_matches_by_date(session, "2026-08-24")
            await session.commit()

        # 赛程照常入库,赔率计 0
        assert result.created_count == 2
        assert result.odds_count == 0
        async with session_factory() as session:
            assert len((await session.scalars(select(MatchOdds))).all()) == 0


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


class TestSyncAPI:
    """POST /api/v1/collector/matches/sync 接口测试。"""

    async def test_sync_matches_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/matches/sync",
            json={"date": "2026-08-24"},
            headers=HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["date"] == "2026-08-24"
        assert body["day_match_count"] == 4
        assert body["created_count"] == 2
        assert body["odds_count"] == 1
        assert body["odds_snapshot_count"] == 1
        assert body["skipped_leagues"] == ["意大利甲级联赛"]
        assert body["source"] == "sporttery"

    async def test_list_games_returns_odds(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/collector/matches/sync",
            json={"date": "2026-08-24"},
            headers=HEADERS,
        )
        response = await client.get(
            "/api/v1/match/games", params={"limit": 50}, headers=HEADERS
        )
        assert response.status_code == 200
        games = response.json()
        by_id = {g["match_id"]: g for g in games}
        with_odds = by_id["2041028"]
        assert with_odds["odds"] is not None
        pools = with_odds["odds"]["pools"]
        assert [p["poolCode"] for p in pools] == ["HAD", "HHAD", "CRS", "TTG", "HAFU"]
        assert pools[0]["options"][0] == {
            "code": "h", "label": "主胜", "odds": 2.15,
        }
        assert with_odds["odds"]["pools"][1]["goalLine"] == "-1"
        # 未同步赔率的场次 odds 为空
        assert by_id["2041030"]["odds"] is None

    async def test_list_games_orders_by_match_num_str(
        self, client: AsyncClient, session_factory: async_sessionmaker
    ) -> None:
        await client.post(
            "/api/v1/collector/matches/sync",
            json={"date": "2026-08-24"},
            headers=HEADERS,
        )
        # 手工场次无编号(编号为空串),应排在有编号场次之后
        async with session_factory() as session:
            league = await session.scalar(select(League))
            team = await session.scalar(select(Team))
            session.add(
                MatchGame(
                    match_id="m-manual-1",
                    league_id=league.league_id,
                    home_team_id=team.team_id,
                    away_team_id=team.team_id,
                    match_time=datetime.datetime(2026, 8, 24, 19, 0),
                    business_date=datetime.date(2026, 8, 24),
                )
            )
            await session.commit()

        response = await client.get(
            "/api/v1/match/games", params={"limit": 50}, headers=HEADERS
        )
        assert response.status_code == 200
        games = response.json()
        # 默认按场次编号升序:周一001 -> 周一004 -> 无编号手工场次
        assert [g["match_id"] for g in games] == [
            "2041028", "2041030", "m-manual-1",
        ]
        assert [g["match_num_str"] for g in games] == ["周一001", "周一004", ""]

    async def test_list_games_filters_by_business_date(
        self, client: AsyncClient
    ) -> None:
        await client.post(
            "/api/v1/collector/matches/sync",
            json={"date": "2026-08-24"},
            headers=HEADERS,
        )
        # 售卖日范围过滤:8-24 当天(含次日凌晨场 2041030)
        response = await client.get(
            "/api/v1/match/games",
            params={"start_date": "2026-08-24", "end_date": "2026-08-24"},
            headers=HEADERS,
        )
        assert response.status_code == 200
        assert sorted(g["match_id"] for g in response.json()) == [
            "2041028", "2041030",
        ]
        assert all(g["business_date"] == "2026-08-24" for g in response.json())
        # 范围之外返回空
        response = await client.get(
            "/api/v1/match/games",
            params={"start_date": "2026-08-25"},
            headers=HEADERS,
        )
        assert response.json() == []

    async def test_sync_matches_rejects_bad_date(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/matches/sync",
            json={"date": "not-a-date"},
            headers=HEADERS,
        )
        assert response.status_code == 422
