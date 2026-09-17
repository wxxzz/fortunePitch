"""数据采集模块测试:球队看板同步(竞彩网球队专栏)。

外部 sporttery 接口通过 monkeypatch 替换为离线样本,
覆盖 解析 -> 同步入库 -> 接口 的完整链路。
"""

import datetime
import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.collector.parsers import team_dashboard as dashboard_parser
from app.collector.sync import team_dashboard_sync, team_sync
from app.collector.sources import sporttery
from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import app
from app.models import League, Team, TeamMatch, TeamProfile

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# 看板球队:巴萨(竞彩网统一球队 ID 246)
UNIFORM_TEAM_ID = 246

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
    246: {
        "abbCnName": "巴萨",
        "allCnName": "巴塞罗那",
        "countryCnName": "西班牙",
        "countryEnName": "Spain",
        "gmTeamId": 233,
        "uniformTeamId": 246,
        "wbsjTeamId": 1234,
        "uniformCountryId": 110,
        "logoUrl": "//static.sporttery.cn/res_1_0/jcw/upload/teamlogo/fc246.png",
    },
    514: {"allCnName": "皇家马德里", "countryCnName": "西班牙", "uniformTeamId": 514},
    3000: {"allCnName": "桑坦德竞技", "countryCnName": "西班牙", "uniformTeamId": 3000},
}


def sample_future_matches() -> list[dict[str, typing.Any]]:
    """未来赛事样本(开赛时间升序)。"""
    return [
        {
            "homeAbbCnName": "皇家社会",
            "awayAbbCnName": "巴萨",
            "gameweek": "7",
            "gmMatchId": 0,
            "groupId": 0,
            "groupName": "",
            "leagueAbbCnName": "西甲",
            "leagueCnName": "西班牙甲级联赛",
            "leagueId": 0,
            "matchDateTime": "2026-09-27 23:00",
            "phaseId": 48638,
            "phaseName": "Regular Season",
            "tournamentId": 140,
            "uniformAwayTeamId": 246,
            "uniformHomeTeamId": 900,
            "uniformLeagueId": 24,
            "uniformMatchId": 9002,
            "wbsjMatchId": 0,
        },
        {
            "homeAbbCnName": "巴萨",
            "awayAbbCnName": "皇马",
            "gameweek": "6",
            "gmMatchId": 0,
            "leagueAbbCnName": "西甲",
            "matchDateTime": "2026-09-20 22:00",
            "phaseName": "Regular Season",
            "uniformAwayTeamId": 514,
            "uniformHomeTeamId": 246,
            "uniformLeagueId": 24,
            "uniformMatchId": 9001,
        },
    ]


def sample_league_list() -> list[dict[str, typing.Any]]:
    """参赛联赛列表样本。"""
    return [
        {"leagueAbbCnName": "西甲", "uniformLeagueId": 24},
        {"leagueAbbCnName": "欧冠", "uniformLeagueId": 30},
    ]


def sample_match_results() -> dict[str, typing.Any]:
    """赛程赛果样本(西甲 4 场 + 欧冠 1 场)。"""
    return {
        "matchList": [
            {
                "awayAbbCnName": "本菲卡",
                "gmMatchId": 2042005,
                "homeAbbCnName": "巴萨",
                "leagueAbbCnName": "欧冠",
                "leagueShowFlag": 1,
                "matchDate": "2026-09-18",
                "sectionsNo1": "2:0",
                "sectionsNo999": "3:0",
                "uniformAwayTeamId": 220,
                "uniformHomeTeamId": 246,
                "uniformLeagueId": 30,
                "uniformMatchId": 8005,
            },
            {
                "awayAbbCnName": "皇马",
                "gmMatchId": 2042001,
                "homeAbbCnName": "巴萨",
                "leagueAbbCnName": "西甲",
                "leagueShowFlag": 1,
                "matchDate": "2026-09-10",
                "sectionsNo1": "1:0",
                "sectionsNo999": "2:1",
                "uniformAwayTeamId": 514,
                "uniformHomeTeamId": 246,
                "uniformLeagueId": 24,
                "uniformMatchId": 8001,
            },
            {
                "awayAbbCnName": "巴萨",
                "gmMatchId": 2042002,
                "homeAbbCnName": "奥萨苏纳",
                "leagueAbbCnName": "西甲",
                "leagueShowFlag": 1,
                "matchDate": "2026-09-03",
                "sectionsNo1": "0:1",
                "sectionsNo999": "0:3",
                "uniformAwayTeamId": 246,
                "uniformHomeTeamId": 700,
                "uniformLeagueId": 24,
                "uniformMatchId": 8002,
            },
            {
                "awayAbbCnName": "塞维利亚",
                "gmMatchId": 2042003,
                "homeAbbCnName": "巴萨",
                "leagueAbbCnName": "西甲",
                "leagueShowFlag": 1,
                "matchDate": "2026-08-28",
                "sectionsNo1": "1:1",
                "sectionsNo999": "1:1",
                "uniformAwayTeamId": 620,
                "uniformHomeTeamId": 246,
                "uniformLeagueId": 24,
                "uniformMatchId": 8003,
            },
            {
                "awayAbbCnName": "马竞",
                "gmMatchId": 2042004,
                "homeAbbCnName": "巴萨",
                "leagueAbbCnName": "西甲",
                "leagueShowFlag": 1,
                "matchDate": "2026-08-24",
                "sectionsNo1": "0:1",
                "sectionsNo999": "0:2",
                "uniformAwayTeamId": 630,
                "uniformHomeTeamId": 246,
                "uniformLeagueId": 24,
                "uniformMatchId": 8004,
            },
        ],
        "statistics": {"totalLegCnt": 5},
    }


# ---------- 数据源打桩 ----------


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
    return []


async def _fetch_team_future_matches(
    uniform_team_id: int,
) -> list[dict[str, typing.Any]]:
    assert uniform_team_id == UNIFORM_TEAM_ID
    return sample_future_matches()


async def _fetch_team_league_list(
    uniform_team_id: int,
) -> list[dict[str, typing.Any]]:
    assert uniform_team_id == UNIFORM_TEAM_ID
    return sample_league_list()


async def _fetch_team_match_results(
    uniform_team_id: int,
    uniform_league_ids: list[int] | None = None,
    home_away_flag: str | None = None,
    term_limits: int = 20,
) -> dict[str, typing.Any]:
    assert uniform_team_id == UNIFORM_TEAM_ID
    assert uniform_league_ids == [24, 30]
    return sample_match_results()


@pytest.fixture(autouse=True)
def stub_sporttery(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有测试统一打桩 sporttery 数据源。"""
    monkeypatch.setattr(sporttery, "fetch_league_list", _fetch_league_list)
    monkeypatch.setattr(sporttery, "fetch_league_detail", _fetch_league_detail)
    monkeypatch.setattr(sporttery, "fetch_league_standings", _fetch_league_standings)
    monkeypatch.setattr(sporttery, "fetch_team_infos", _fetch_team_infos)
    monkeypatch.setattr(sporttery, "fetch_season_matches", _fetch_season_matches)
    monkeypatch.setattr(
        sporttery, "fetch_team_future_matches", _fetch_team_future_matches
    )
    monkeypatch.setattr(sporttery, "fetch_team_league_list", _fetch_team_league_list)
    monkeypatch.setattr(
        sporttery, "fetch_team_match_results", _fetch_team_match_results
    )


# ---------- 解析层 ----------


class TestParsers:
    """parsers/team_dashboard.py 单元测试。"""

    def test_parse_match_time_with_clock(self) -> None:
        assert dashboard_parser.parse_match_time("2026-09-20 22:00") == (
            datetime.datetime(2026, 9, 20, 22, 0)
        )

    def test_parse_match_time_date_only(self) -> None:
        assert dashboard_parser.parse_match_time("2026-09-10") == (
            datetime.datetime(2026, 9, 10, 0, 0)
        )

    def test_parse_match_time_invalid(self) -> None:
        from app.core.exceptions import DataValidationError

        with pytest.raises(DataValidationError):
            dashboard_parser.parse_match_time("2026/09/10")
        with pytest.raises(DataValidationError):
            dashboard_parser.parse_match_time("")

    def test_split_score(self) -> None:
        assert dashboard_parser.split_score("3:1") == (3, 1)
        assert dashboard_parser.split_score("0:0") == (0, 0)
        assert dashboard_parser.split_score(None) == (None, None)
        assert dashboard_parser.split_score("退赛") == (None, None)

    def test_compute_result(self) -> None:
        assert dashboard_parser.compute_result(2, 1, True) == "W"
        assert dashboard_parser.compute_result(2, 1, False) == "L"
        assert dashboard_parser.compute_result(1, 2, False) == "W"
        assert dashboard_parser.compute_result(1, 1, True) == "D"
        assert dashboard_parser.compute_result(None, 1, True) is None

    def test_build_future_match_fields(self) -> None:
        fields = dashboard_parser.build_future_match_fields(
            UNIFORM_TEAM_ID, sample_future_matches()[0]
        )
        assert fields["uniform_match_id"] == 9002
        assert fields["is_home"] is False  # 巴萨客场
        assert fields["match_time"] == datetime.datetime(2026, 9, 27, 23, 0)
        assert fields["league_name"] == "西甲"
        assert fields["full_home_score"] is None
        assert fields["team_result"] is None

    def test_build_result_match_fields(self) -> None:
        fields = dashboard_parser.build_result_match_fields(
            UNIFORM_TEAM_ID, sample_match_results()["matchList"][1]
        )
        assert fields["uniform_match_id"] == 8001
        assert fields["is_home"] is True
        assert fields["half_home_score"] == 1
        assert fields["half_away_score"] == 0
        assert fields["full_home_score"] == 2
        assert fields["full_away_score"] == 1
        assert fields["team_result"] == "W"

    def test_build_fields_requires_names(self) -> None:
        from app.core.exceptions import DataValidationError

        with pytest.raises(DataValidationError):
            dashboard_parser.build_future_match_fields(
                UNIFORM_TEAM_ID, {"uniformMatchId": 1, "homeAbbCnName": "巴萨"}
            )

    def test_build_profile_fields_drops_invalid_logo(self) -> None:
        """非白名单 scheme 的 logo_url 一律置空(防注入)。"""
        fields = team_dashboard_sync.build_profile_fields(
            {"uniformTeamId": 246, "logoUrl": "javascript:alert(1)"}, "巴萨"
        )
        assert fields["logo_url"] is None
        fields = team_dashboard_sync.build_profile_fields(
            {"uniformTeamId": 246, "logoUrl": "//static.sporttery.cn/logo.png"},
            "巴萨",
        )
        assert fields["logo_url"] is not None


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


@pytest.fixture
async def barca_team_id(session_factory: async_sessionmaker) -> int:
    """先同步西甲球队清单(建立巴萨的竞彩网档案映射),返回其本地 ID。"""
    async with session_factory() as session:
        result = await team_sync.sync_league_teams(session, "西甲")
        await session.commit()
    for team in result.teams:
        if team.team_name == "巴塞罗那":
            return team.team_id
    raise AssertionError("巴萨未入库")


class TestTeamDashboardSync:
    """球队看板同步测试。"""

    async def test_sync_creates_profile_and_matches(
        self, session_factory: async_sessionmaker, barca_team_id: int
    ) -> None:
        async with session_factory() as session:
            result = await team_dashboard_sync.sync_team_dashboard(
                session, team_id=barca_team_id
            )
            await session.commit()

        # 档案映射已由球队清单同步建立,看板同步只刷新
        assert result.profile_created is False
        assert result.uniform_team_id == UNIFORM_TEAM_ID
        assert result.future_count == 2
        assert result.result_count == 5
        assert result.created_count == 7
        assert result.updated_count == 0
        assert result.pruned_count == 0

        async with session_factory() as session:
            matches = (await session.scalars(select(TeamMatch))).all()
            assert len(matches) == 7
            profile = await session.get(TeamProfile, barca_team_id)
            assert profile is not None
            assert profile.uniform_team_id == UNIFORM_TEAM_ID
            assert profile.abbrev_name == "巴萨"
            assert profile.logo_url is not None

    async def test_sync_by_uniform_team_id(
        self, session_factory: async_sessionmaker, barca_team_id: int
    ) -> None:
        async with session_factory() as session:
            result = await team_dashboard_sync.sync_team_dashboard(
                session, uniform_team_id=UNIFORM_TEAM_ID
            )
            await session.commit()

        assert result.team.team_id == barca_team_id
        assert result.created_count == 7

    async def test_sync_is_idempotent(
        self, session_factory: async_sessionmaker, barca_team_id: int
    ) -> None:
        async with session_factory() as session:
            await team_dashboard_sync.sync_team_dashboard(
                session, team_id=barca_team_id
            )
            await session.commit()
        async with session_factory() as session:
            second = await team_dashboard_sync.sync_team_dashboard(
                session, team_id=barca_team_id
            )
            await session.commit()

        assert second.created_count == 0
        assert second.updated_count == 7
        async with session_factory() as session:
            assert len((await session.scalars(select(TeamMatch))).all()) == 7

    async def test_future_row_updated_by_result(
        self,
        session_factory: async_sessionmaker,
        barca_team_id: int,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 第一次同步:8001 还在未来赛事中;第二次同步:8001 已完赛出现在赛果里
        async def first_future(uniform_team_id: int) -> list[dict[str, typing.Any]]:
            return [
                {
                    "homeAbbCnName": "巴萨",
                    "awayAbbCnName": "皇马",
                    "gameweek": "5",
                    "leagueAbbCnName": "西甲",
                    "matchDateTime": "2026-09-10 22:00",
                    "uniformAwayTeamId": 514,
                    "uniformHomeTeamId": 246,
                    "uniformLeagueId": 24,
                    "uniformMatchId": 8001,
                }
            ]

        monkeypatch.setattr(sporttery, "fetch_team_future_matches", first_future)
        async with session_factory() as session:
            await team_dashboard_sync.sync_team_dashboard(
                session, team_id=barca_team_id
            )
            await session.commit()

        # 恢复默认未来赛事样本(9001/9002,不含 8001)
        monkeypatch.setattr(
            sporttery, "fetch_team_future_matches", _fetch_team_future_matches
        )
        async with session_factory() as session:
            second = await team_dashboard_sync.sync_team_dashboard(
                session, team_id=barca_team_id
            )
            await session.commit()

        # 第二次同步只有 2 场新未来赛事入库;5 条赛果全部更新既有行
        # (8001 原地补上比分,不重复计数为新建)
        assert second.created_count == 2
        assert second.updated_count == 5
        async with session_factory() as session:
            row = await session.get(TeamMatch, (barca_team_id, 8001))
            assert row is not None
            assert row.full_home_score == 2
            assert row.full_away_score == 1
            assert row.team_result == "W"
            # 赛果接口不带轮次,保留未来赛事带来的旧值
            assert row.gameweek == "5"

    async def test_sync_prunes_stale_future_rows(
        self,
        session_factory: async_sessionmaker,
        barca_team_id: int,
    ) -> None:
        # 预置一条不在本次抓取集合中的未开赛行(赛程改期产生的脏数据)
        async with session_factory() as session:
            session.add(
                TeamMatch(
                    team_id=barca_team_id,
                    uniform_match_id=9999,
                    match_time=datetime.datetime(2026, 9, 30, 22, 0),
                    home_team_name="巴萨",
                    away_team_name="瓦伦西亚",
                    is_home=True,
                )
            )
            await session.commit()

        async with session_factory() as session:
            result = await team_dashboard_sync.sync_team_dashboard(
                session, team_id=barca_team_id
            )
            await session.commit()

        assert result.pruned_count == 1
        async with session_factory() as session:
            assert await session.get(TeamMatch, (barca_team_id, 9999)) is None

    async def test_sync_prunes_all_stale_when_no_future(
        self,
        session_factory: async_sessionmaker,
        barca_team_id: int,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """未来赛事返回为空时,库存的未开赛行全部视为脏数据修剪。"""

        async def no_future(uniform_team_id: int) -> list[dict[str, typing.Any]]:
            return []

        async with session_factory() as session:
            await team_dashboard_sync.sync_team_dashboard(
                session, team_id=barca_team_id
            )
            await session.commit()

        monkeypatch.setattr(sporttery, "fetch_team_future_matches", no_future)
        async with session_factory() as session:
            second = await team_dashboard_sync.sync_team_dashboard(
                session, team_id=barca_team_id
            )
            await session.commit()

        assert second.pruned_count == 2
        async with session_factory() as session:
            matches = (await session.scalars(select(TeamMatch))).all()
            assert len(matches) == 5
            assert all(m.full_home_score is not None for m in matches)

    async def test_sync_rejects_ambiguous_ids(
        self, session_factory: async_sessionmaker, barca_team_id: int
    ) -> None:
        from app.core.exceptions import DataValidationError

        async with session_factory() as session:
            with pytest.raises(DataValidationError):
                await team_dashboard_sync.sync_team_dashboard(session)
            with pytest.raises(DataValidationError):
                await team_dashboard_sync.sync_team_dashboard(
                    session,
                    team_id=barca_team_id,
                    uniform_team_id=UNIFORM_TEAM_ID,
                )

    async def test_sync_unknown_team_id(self, session_factory: async_sessionmaker) -> None:
        from app.core.exceptions import ResourceNotFoundError

        async with session_factory() as session:
            with pytest.raises(ResourceNotFoundError):
                await team_dashboard_sync.sync_team_dashboard(session, team_id=999)

    async def test_sync_team_without_profile(
        self, session_factory: async_sessionmaker
    ) -> None:
        from app.core.exceptions import DataValidationError

        async with session_factory() as session:
            league = League(league_name="西甲", country="西班牙")
            session.add(league)
            await session.flush()
            team = Team(team_name="瓦伦西亚", league_id=league.league_id)
            session.add(team)
            await session.flush()
            with pytest.raises(DataValidationError):
                await team_dashboard_sync.sync_team_dashboard(
                    session, team_id=team.team_id
                )

    async def test_sync_cup_team_reuses_same_name_profile(
        self, session_factory: async_sessionmaker, barca_team_id: int
    ) -> None:
        """杯赛联赛下的同名球队行缺档案时,借用国内联赛行的档案映射。"""
        async with session_factory() as session:
            cup_league = League(league_name="欧冠", country="欧洲")
            session.add(cup_league)
            await session.flush()
            cup_team = Team(team_name="巴塞罗那", league_id=cup_league.league_id)
            session.add(cup_team)
            await session.flush()
            cup_team_id = cup_team.team_id

            result = await team_dashboard_sync.sync_team_dashboard(
                session, team_id=cup_team_id
            )
            await session.commit()

        # uniform_team_id 复用西甲巴塞罗那行的档案;比赛挂在杯赛球队行下
        assert result.uniform_team_id == UNIFORM_TEAM_ID
        assert result.team.team_id == cup_team_id
        assert result.created_count == 7
        # 档案已被西甲行持有,杯赛行不会新建冲突档案
        assert result.profile_created is False
        assert await session.get(TeamProfile, cup_team_id) is None

        async with session_factory() as session:
            matches = (await session.scalars(select(TeamMatch))).all()
            assert len(matches) == 7
            assert {m.team_id for m in matches} == {cup_team_id}

    async def test_team_sync_persists_profile(
        self, session_factory: async_sessionmaker
    ) -> None:
        """球队清单同步捎带写入档案映射(巴萨详情含简称/Logo)。"""
        async with session_factory() as session:
            await team_sync.sync_league_teams(session, "西甲")
            await session.commit()

        async with session_factory() as session:
            profiles = (await session.scalars(select(TeamProfile))).all()
            assert len(profiles) == 3
            by_uniform = {p.uniform_team_id: p for p in profiles}
            assert by_uniform[246].abbrev_name == "巴萨"
            assert by_uniform[246].full_name == "巴塞罗那"
            assert by_uniform[246].logo_url is not None
            # 皇马/桑坦德详情无简称字段,回退本地球队名
            assert by_uniform[514].abbrev_name == "皇家马德里"


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
            # 预置联赛/球队/档案映射(等价于先执行球队清单同步)
            async with factory() as session:
                await team_sync.sync_league_teams(session, "西甲")
                await session.commit()
            yield async_client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


class TestSyncApi:
    """/api/v1/collector/team-dashboard/sync 接口测试。"""

    async def test_sync_by_team_id(self, client: AsyncClient) -> None:
        teams = (await client.get("/api/v1/base/teams", params={"limit": 100})).json()
        barca = next(t for t in teams if t["team_name"] == "巴塞罗那")
        response = await client.post(
            "/api/v1/collector/team-dashboard/sync",
            json={"team_id": barca["team_id"]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["uniform_team_id"] == UNIFORM_TEAM_ID
        assert body["future_count"] == 2
        assert body["result_count"] == 5
        assert body["created_count"] == 7
        assert body["team"]["team_name"] == "巴塞罗那"
        assert body["source"] == "sporttery"

    async def test_sync_by_uniform_team_id(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/team-dashboard/sync",
            json={"uniform_team_id": UNIFORM_TEAM_ID},
        )
        assert response.status_code == 200
        assert response.json()["created_count"] == 7

    async def test_sync_rejects_both_ids(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/team-dashboard/sync",
            json={"team_id": 1, "uniform_team_id": UNIFORM_TEAM_ID},
        )
        assert response.status_code == 422

    async def test_sync_unknown_uniform_team_id(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/team-dashboard/sync",
            json={"uniform_team_id": 424242},
        )
        assert response.status_code == 422

    async def test_sync_requires_api_key(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/team-dashboard/sync",
            json={"uniform_team_id": UNIFORM_TEAM_ID},
            headers={"X-API-Key": "wrong"},
        )
        assert response.status_code == 401
