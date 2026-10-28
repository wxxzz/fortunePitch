"""基础档案模块接口测试:联赛多维度分析(/api/v1/base/leagues/{id}/insights)。

SQLite 内存库 + FastAPI 依赖覆盖,覆盖:
- 各维度统计(胜平负分布与占比/场均进球/3 球及以上/双方进球/
  总进球分布/半全场/让球/热门命中);
- 联赛隔离与未完赛场次排除;
- 无完赛场次时零计数与空维度;
- 联赛不存在 404。
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
from app.models import League, MatchGame, MatchResult, Team

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

BASE_TIME = datetime.datetime(2026, 10, 1, 21, 0)


@pytest.fixture
async def env() -> typing.AsyncGenerator[
    tuple[AsyncClient, async_sessionmaker], None
]:
    """返回测试客户端与会话工厂(会话用于预置联赛/球队/比赛/赛果)。"""
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


def _game(
    match_id: str,
    league_id: int,
    home_id: int,
    away_id: int,
    days_offset: int,
    home_score: int | None,
    away_score: int | None,
) -> MatchGame:
    """构造一场比赛(比分为 None 即未完赛)。"""
    return MatchGame(
        match_id=match_id,
        match_num_str=f"周五{match_id[-3:]}",
        league_id=league_id,
        home_team_id=home_id,
        away_team_id=away_id,
        match_time=BASE_TIME + datetime.timedelta(days=days_offset),
        match_status="FINISHED" if home_score is not None else "PENDING",
        home_score=home_score,
        away_score=away_score,
    )


def _result(
    match_id: str,
    *,
    half_home: int,
    half_away: int,
    full_home: int,
    full_away: int,
    goal_line: int = 0,
    sp_h: float | None = None,
    sp_d: float | None = None,
    sp_a: float | None = None,
) -> MatchResult:
    """构造赛果快照(玩法标签由比分与盘口推导,口径同 parsers/result.py)。"""
    wdl = ("主胜", "平", "客胜")
    short = ("胜", "平", "负")

    def label(home: int, away: int) -> int:
        if home > away:
            return 0
        if home < away:
            return 2
        return 1

    adjusted = full_home + goal_line
    return MatchResult(
        match_id=match_id,
        half_home_score=half_home,
        half_away_score=half_away,
        full_home_score=full_home,
        full_away_score=full_away,
        goal_line=str(goal_line),
        had=wdl[label(full_home, full_away)],
        hhad=f"让球{wdl[label(adjusted, full_away)]}",
        crs=f"{full_home}:{full_away}",
        ttg=str(full_home + full_away),
        hafu=short[label(half_home, half_away)] + short[label(full_home, full_away)],
        sp_h=sp_h,
        sp_d=sp_d,
        sp_a=sp_a,
    )


async def _seed(env: tuple[AsyncClient, async_sessionmaker]) -> int:
    """预置两个联赛:目标联赛 3 场完赛(2 场有赛果快照)+ 1 场未完赛,
    干扰联赛 1 场完赛;返回目标联赛 ID。

    目标联赛完赛场次:
    - m1: 2:1(主胜,总 3 球,BTTS 是,半全场 胜胜,让 -1 → 让球平,SP 热门=主胜 命中)
    - m2: 1:1(平,总 2 球,BTTS 是,半全场 平平,让 0 → 让球平,SP 热门=客胜 未中)
    - m3: 0:2(客胜,总 2 球,BTTS 否,半全场 平负,无 SP → 不计热门)
    """
    _, session_factory = env
    async with session_factory() as session:
        liga = League(
            league_name="西班牙甲级联赛",
            country="西班牙",
            tier=1,
            season="2026-2027",
        )
        premier = League(league_name="英格兰超级联赛", country="英格兰", tier=1)
        session.add_all([liga, premier])
        await session.flush()
        barca = Team(team_name="巴塞罗那", league_id=liga.league_id)
        real = Team(team_name="皇家马德里", league_id=liga.league_id)
        sevilla = Team(team_name="塞维利亚", league_id=liga.league_id)
        city = Team(team_name="曼城", league_id=premier.league_id)
        session.add_all([barca, real, sevilla, city])
        await session.flush()

        session.add_all(
            [
                _game("m-001", liga.league_id, real.team_id, barca.team_id, -3, 2, 1),
                _game("m-002", liga.league_id, barca.team_id, sevilla.team_id, -2, 1, 1),
                _game("m-003", liga.league_id, sevilla.team_id, real.team_id, -1, 0, 2),
                _game("m-004", liga.league_id, real.team_id, sevilla.team_id, 1, None, None),
                _game("oth-01", premier.league_id, city.team_id, city.team_id, -1, 3, 0),
            ]
        )
        session.add_all(
            [
                _result(
                    "m-001",
                    half_home=1,
                    half_away=0,
                    full_home=2,
                    full_away=1,
                    goal_line=-1,
                    sp_h=1.50,
                    sp_d=4.20,
                    sp_a=6.00,
                ),
                _result(
                    "m-002",
                    half_home=0,
                    half_away=0,
                    full_home=1,
                    full_away=1,
                    goal_line=0,
                    sp_h=2.80,
                    sp_d=3.10,
                    sp_a=2.50,
                ),
                _result(
                    "m-003",
                    half_home=0,
                    half_away=0,
                    full_home=0,
                    full_away=2,
                    goal_line=0,
                ),
            ]
        )
        await session.commit()
        return liga.league_id


class TestLeagueInsightsEndpoint:
    """GET /api/v1/base/leagues/{league_id}/insights 测试。"""

    async def test_returns_multi_dimension_stats(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        client, _ = env
        league_id = await _seed(env)

        # Act
        response = await client.get(f"/api/v1/base/leagues/{league_id}/insights")

        # Assert:基本信息与样本数(未完赛场次与他联赛不计数)
        assert response.status_code == 200
        body = response.json()
        assert body["league_name"] == "西班牙甲级联赛"
        assert body["season"] == "2026-2027"
        assert body["finished_count"] == 3

        # 胜平负分布与占比
        assert (body["home_win"], body["draw"], body["away_win"]) == (1, 1, 1)
        assert body["home_win_rate"] == 0.333
        assert body["draw_rate"] == 0.333
        assert body["away_win_rate"] == 0.333

        # 进球维度:总进球 3+2+2=7,主队 2+1+0=3,客队 1+1+2=4
        assert body["avg_total_goals"] == 2.33
        assert body["avg_home_goals"] == 1.0
        assert body["avg_away_goals"] == 1.33
        assert body["over2_5_count"] == 1
        assert body["over2_5_rate"] == 0.333
        assert body["btts_count"] == 2
        assert body["btts_rate"] == 0.667

        # 总进球分布(固定顺序 0/1/2/3/4/5+)
        assert [(row["label"], row["count"]) for row in body["total_goals"]] == [
            ("0", 0), ("1", 0), ("2", 2), ("3", 1), ("4", 0), ("5+", 0),
        ]

        # 比分分布(次数降序,同频按标签升序):0:2 / 1:1 / 2:1
        assert [
            (row["label"], row["count"]) for row in body["score_distribution"]
        ] == [
            ("0:2", 1), ("1:1", 1), ("2:1", 1),
        ]

        # 半全场分布(次数降序,同频按标签升序):平平 / 平负 / 胜胜
        assert [(row["label"], row["count"]) for row in body["half_full"]] == [
            ("平平", 1), ("平负", 1), ("胜胜", 1),
        ]

        # 让球胜平负分布(m1 让 -1 后 1:1 → 让球平;m2/m3 盘口 0)
        assert [(row["label"], row["count"]) for row in body["handicap"]] == [
            ("让球平", 2), ("让球客胜", 1),
        ]

        # 热门命中:m1 SP 最低为主胜(1.50)且开奖主胜 → 命中;
        # m2 SP 最低为客胜(2.50)但开奖平 → 未中;m3 无 SP 不计
        favorite = body["favorite"]
        assert favorite is not None
        assert favorite["count"] == 2
        assert favorite["hit_count"] == 1
        assert favorite["hit_rate"] == 0.5
        assert favorite["avg_sp"] == 2.0

    async def test_empty_league_returns_zero_stats(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:联赛存在但无完赛场次
        client, session_factory = env
        async with session_factory() as session:
            liga = League(league_name="德国乙级联赛", country="德国", tier=2)
            session.add(liga)
            await session.commit()
            league_id = liga.league_id

        # Act
        response = await client.get(f"/api/v1/base/leagues/{league_id}/insights")

        # Assert:零计数、空维度、比率为空、无热门统计
        assert response.status_code == 200
        body = response.json()
        assert body["finished_count"] == 0
        assert body["home_win"] == 0
        assert body["avg_total_goals"] is None
        assert body["home_win_rate"] is None
        assert body["over2_5_rate"] is None
        assert body["btts_rate"] is None
        assert body["half_full"] == []
        assert body["handicap"] == []
        assert body["score_distribution"] == []
        assert body["favorite"] is None

    async def test_score_distribution_orders_by_count_desc(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """比分分布:按出现次数降序,同频按标签升序。"""
        client, session_factory = env
        async with session_factory() as session:
            liga = League(league_name="意大利甲级联赛", country="意大利", tier=1)
            session.add(liga)
            await session.flush()
            inter = Team(team_name="国际米兰", league_id=liga.league_id)
            milan = Team(team_name="AC米兰", league_id=liga.league_id)
            session.add_all([inter, milan])
            await session.flush()
            session.add_all(
                [
                    _game("s-001", liga.league_id, inter.team_id, milan.team_id, -3, 1, 1),
                    _game("s-002", liga.league_id, milan.team_id, inter.team_id, -2, 1, 1),
                    _game("s-003", liga.league_id, inter.team_id, milan.team_id, -1, 2, 0),
                ]
            )
            await session.commit()
            league_id = liga.league_id

        response = await client.get(f"/api/v1/base/leagues/{league_id}/insights")
        assert response.status_code == 200
        assert [
            (row["label"], row["count"])
            for row in response.json()["score_distribution"]
        ] == [("1:1", 2), ("2:0", 1)]

    async def test_returns_404_for_unknown_league(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange / Act
        client, _ = env
        response = await client.get("/api/v1/base/leagues/999/insights")

        # Assert
        assert response.status_code == 404
