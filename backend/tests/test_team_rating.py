"""Elo 评分回放管线测试。

覆盖:
1. 单场回放数值手算比对(E_home / 双方新评分);
2. 零和性(全部评分之和 = 1500 × 球队数);
3. 幂等(连续两次重算结果完全一致);
4. 单侧看板(仅一队有该场行)经 TeamProfile 解析对手后仍计入;
5. 对手无 profile 映射 -> 该场跳过并计数;
6. 接口:POST /analytics/team-ratings/recompute 返回摘要;
7. 接口:GET /analytics/team-ratings/{id} 重算前 404 / 重算后返回评分。

注:评分均为模拟数据,测试不涉及真实资金。
"""

import datetime
import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import app
from app.models import League, Team, TeamMatch, TeamProfile, TeamRating
from app.services import elo
from app.services.team_rating import recompute_team_ratings

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}


# ---------- 环境与数据预置 ----------

@pytest.fixture
async def env(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    """返回测试客户端与会话工厂。"""
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


async def _seed_teams(
    session_factory: async_sessionmaker,
    *,
    with_away_profile: bool = True,
) -> tuple[int, int]:
    """预置联赛 + 主客两队(可选客队 profile),返回 (home_id, away_id)。"""
    async with session_factory() as session:
        league = League(league_name="英格兰超级联赛", country="英格兰", tier=1, season="2026-2027")
        session.add(league)
        await session.flush()
        home = Team(team_name="阿森纳", league_id=league.league_id)
        away = Team(team_name="切尔西", league_id=league.league_id)
        session.add_all([home, away])
        await session.flush()
        session.add(
            TeamProfile(
                team_id=home.team_id, uniform_team_id=9001, abbrev_name="阿森纳"
            )
        )
        if with_away_profile:
            session.add(
                TeamProfile(
                    team_id=away.team_id, uniform_team_id=9002, abbrev_name="切尔西"
                )
            )
        await session.commit()
        return home.team_id, away.team_id


def _dashboard_row(
    team_id: int,
    uniform_match_id: int,
    *,
    is_home: bool,
    home_team_name: str,
    away_team_name: str,
    uniform_home: int | None,
    uniform_away: int | None,
    home_goals: int,
    away_goals: int,
    match_time: datetime.datetime,
) -> TeamMatch:
    """构造一条看板赛果行。"""
    result = None
    own = home_goals if is_home else away_goals
    opp = away_goals if is_home else home_goals
    if own > opp:
        result = "W"
    elif own < opp:
        result = "L"
    else:
        result = "D"
    return TeamMatch(
        team_id=team_id,
        uniform_match_id=uniform_match_id,
        match_time=match_time,
        home_team_name=home_team_name,
        away_team_name=away_team_name,
        uniform_home_team_id=uniform_home,
        uniform_away_team_id=uniform_away,
        is_home=is_home,
        full_home_score=home_goals,
        full_away_score=away_goals,
        team_result=result,
    )


# ---------- 服务层 ----------

class TestRecomputeTeamRatings:

    async def test_single_match_hand_computed(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """两队各 1500,一场主胜 2-1 -> E_home=0.6401,评分 +/-K*残差。"""
        _, session_factory = env
        home_id, away_id = await _seed_teams(session_factory)
        match_time = datetime.datetime(2026, 9, 19, 19, 0)
        async with session_factory() as session:
            session.add_all(
                [
                    _dashboard_row(
                        home_id, 101, is_home=True, home_team_name="阿森纳",
                        away_team_name="切尔西", uniform_home=9001,
                        uniform_away=9002, home_goals=2, away_goals=1,
                        match_time=match_time,
                    ),
                    _dashboard_row(
                        away_id, 101, is_home=False, home_team_name="阿森纳",
                        away_team_name="切尔西", uniform_home=9001,
                        uniform_away=9002, home_goals=2, away_goals=1,
                        match_time=match_time,
                    ),
                ]
            )
            await session.commit()

            result = await recompute_team_ratings(session)
            await session.commit()
            assert result.matches_replayed == 1
            assert result.teams_rated == 2
            assert result.matches_skipped == 0

            ratings = {
                row.team_id: row
                for row in await session.scalars(select(TeamRating))
            }
            expected_home = elo.update_ratings(1500.0, 1500.0, 2, 1)
            assert ratings[home_id].rating == pytest.approx(expected_home.home_rating_new, abs=0.01)
            assert ratings[away_id].rating == pytest.approx(expected_home.away_rating_new, abs=0.01)
            assert ratings[home_id].matches_played == 1
            assert ratings[home_id].last_match_time == match_time

    async def test_zero_sum_across_league(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """回放后全部评分之和 = 1500 × 球队数(每场更新零和)。"""
        _, session_factory = env
        home_id, away_id = await _seed_teams(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    _dashboard_row(
                        home_id, 201, is_home=True, home_team_name="阿森纳",
                        away_team_name="切尔西", uniform_home=9001,
                        uniform_away=9002, home_goals=1, away_goals=1,
                        match_time=datetime.datetime(2026, 8, 1),
                    ),
                    _dashboard_row(
                        away_id, 202, is_home=True, home_team_name="切尔西",
                        away_team_name="阿森纳", uniform_home=9002,
                        uniform_away=9001, home_goals=0, away_goals=3,
                        match_time=datetime.datetime(2026, 8, 8),
                    ),
                ]
            )
            await session.commit()
            await recompute_team_ratings(session)
            await session.commit()
            ratings = list(await session.scalars(select(TeamRating)))
            assert len(ratings) == 2
            total = sum(row.rating for row in ratings)
            assert total == pytest.approx(1500.0 * 2, abs=0.01)

    async def test_idempotent_recompute(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """连续两次重算,评分完全一致(全量重建幂等)。"""
        _, session_factory = env
        home_id, away_id = await _seed_teams(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    _dashboard_row(
                        home_id, 301, is_home=True, home_team_name="阿森纳",
                        away_team_name="切尔西", uniform_home=9001,
                        uniform_away=9002, home_goals=3, away_goals=0,
                        match_time=datetime.datetime(2026, 8, 1),
                    ),
                    _dashboard_row(
                        away_id, 302, is_home=True, home_team_name="切尔西",
                        away_team_name="阿森纳", uniform_home=9002,
                        uniform_away=9001, home_goals=1, away_goals=1,
                        match_time=datetime.datetime(2026, 8, 8),
                    ),
                ]
            )
            await session.commit()

            first = await recompute_team_ratings(session)
            await session.commit()
            first_ratings = sorted(
                (row.team_id, row.rating)
                for row in await session.scalars(select(TeamRating))
            )
            second = await recompute_team_ratings(session)
            await session.commit()
            second_ratings = sorted(
                (row.team_id, row.rating)
                for row in await session.scalars(select(TeamRating))
            )
            assert first.matches_replayed == second.matches_replayed == 2
            assert first_ratings == second_ratings

    async def test_single_side_dashboard_resolves_opponent(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """仅主队看板有该场行 -> 经 profile 映射解析客队后仍计入。"""
        _, session_factory = env
        home_id, away_id = await _seed_teams(session_factory)
        async with session_factory() as session:
            session.add(
                _dashboard_row(
                    home_id, 401, is_home=True, home_team_name="阿森纳",
                    away_team_name="切尔西", uniform_home=9001,
                    uniform_away=9002, home_goals=2, away_goals=2,
                    match_time=datetime.datetime(2026, 8, 1),
                )
            )
            await session.commit()
            result = await recompute_team_ratings(session)
            await session.commit()
            assert result.matches_replayed == 1
            assert result.matches_skipped == 0
            ratings = {
                row.team_id: row for row in await session.scalars(select(TeamRating))
            }
            assert ratings[home_id].matches_played == 1
            assert ratings[away_id].matches_played == 1

    async def test_opponent_without_profile_is_skipped(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """对手无 profile 映射 -> 该场跳过并计入 matches_skipped。"""
        _, session_factory = env
        home_id, _away_id = await _seed_teams(session_factory, with_away_profile=False)
        async with session_factory() as session:
            session.add(
                _dashboard_row(
                    home_id, 501, is_home=True, home_team_name="阿森纳",
                    away_team_name="切尔西", uniform_home=9001,
                    uniform_away=9002, home_goals=1, away_goals=0,
                    match_time=datetime.datetime(2026, 8, 1),
                )
            )
            await session.commit()
            result = await recompute_team_ratings(session)
            await session.commit()
            assert result.matches_replayed == 0
            assert result.matches_skipped == 1
            assert result.teams_rated == 0

    async def test_inconsistent_group_scores_are_skipped(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """同场两队看板比分不一致(脏数据)-> 跳过该场并计数。"""
        _, session_factory = env
        home_id, away_id = await _seed_teams(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    _dashboard_row(
                        home_id, 511, is_home=True, home_team_name="阿森纳",
                        away_team_name="切尔西", uniform_home=9001,
                        uniform_away=9002, home_goals=2, away_goals=1,
                        match_time=datetime.datetime(2026, 8, 1),
                    ),
                    # 同 uniform_match_id 但比分与主队看板不一致
                    _dashboard_row(
                        away_id, 511, is_home=False, home_team_name="阿森纳",
                        away_team_name="切尔西", uniform_home=9001,
                        uniform_away=9002, home_goals=1, away_goals=1,
                        match_time=datetime.datetime(2026, 8, 1),
                    ),
                ]
            )
            await session.commit()
            result = await recompute_team_ratings(session)
            await session.commit()
            assert result.matches_replayed == 0
            assert result.matches_skipped == 1
            assert result.teams_rated == 0


# ---------- 接口层 ----------

class TestRecomputeEndpoint:

    async def test_recompute_endpoint_returns_summary(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """POST /analytics/team-ratings/recompute 返回重算摘要。"""
        client, session_factory = env
        home_id, away_id = await _seed_teams(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    _dashboard_row(
                        home_id, 601, is_home=True, home_team_name="阿森纳",
                        away_team_name="切尔西", uniform_home=9001,
                        uniform_away=9002, home_goals=2, away_goals=0,
                        match_time=datetime.datetime(2026, 8, 1),
                    ),
                ]
            )
            await session.commit()

        response = await client.post("/api/v1/analytics/team-ratings/recompute")
        assert response.status_code == 200
        body = response.json()
        assert body == {"matches_replayed": 1, "teams_rated": 2, "matches_skipped": 0}

        # 幂等:再次调用结果一致
        response_again = await client.post("/api/v1/analytics/team-ratings/recompute")
        assert response_again.status_code == 200
        assert response_again.json() == body


class TestGetTeamRatingEndpoint:

    async def test_get_rating_before_recompute_returns_404(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """未重算过 -> GET /analytics/team-ratings/{id} 返回 404。"""
        client, session_factory = env
        home_id, _away_id = await _seed_teams(session_factory)

        response = await client.get(f"/api/v1/analytics/team-ratings/{home_id}")
        assert response.status_code == 404

    async def test_get_rating_after_recompute_returns_rating(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """重算后 -> GET 返回该队当前评分,与库中值一致。"""
        client, session_factory = env
        home_id, away_id = await _seed_teams(session_factory)
        async with session_factory() as session:
            session.add(
                _dashboard_row(
                    home_id, 701, is_home=True, home_team_name="阿森纳",
                    away_team_name="切尔西", uniform_home=9001,
                    uniform_away=9002, home_goals=2, away_goals=0,
                    match_time=datetime.datetime(2026, 8, 1),
                )
            )
            await session.commit()

        recompute = await client.post("/api/v1/analytics/team-ratings/recompute")
        assert recompute.status_code == 200

        response = await client.get(f"/api/v1/analytics/team-ratings/{home_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["team_id"] == home_id
        assert body["matches_played"] == 1
        # 主胜 2-0,两队同起点 -> 主队评分高于 1500
        assert body["rating"] > 1500.0

        away_response = await client.get(f"/api/v1/analytics/team-ratings/{away_id}")
        assert away_response.status_code == 200
        assert away_response.json()["rating"] < 1500.0
