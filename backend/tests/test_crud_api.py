"""四大业务模块 CRUD 接口集成测试。

使用 SQLite 内存库 + FastAPI 依赖覆盖,隔离真实 MySQL,
覆盖 基础档案 -> 比赛与赛果 -> 高阶数据分析 -> 策略与赔率 的完整链路。
"""

import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import app

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# 统一的测试时间基准
TEST_TIME = datetime.datetime(2026, 8, 17, 20, 0, 0)


@pytest.fixture
async def client() -> AsyncClient:
    """创建内存 SQLite 库并覆盖数据库会话依赖。"""
    engine = create_async_engine("sqlite+aiosqlite://")

    from sqlalchemy import event

    # SQLite 默认不启用外键约束,与 MySQL 行为对齐
    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> object:
        """与生产 get_db_session 行为一致:请求成功提交、异常回滚。"""
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
            yield async_client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


class TestBaseModule:
    """基础档案模块(/api/v1/base)测试。"""

    async def test_league_crud_flow(self, client: AsyncClient) -> None:
        created = await client.post(
            "/api/v1/base/leagues",
            json={"league_name": "英超", "country": "英格兰", "tier": 1, "season": "2026-2027"},
        )
        assert created.status_code == 201
        league_id = created.json()["league_id"]

        fetched = await client.get(f"/api/v1/base/leagues/{league_id}")
        assert fetched.status_code == 200
        assert fetched.json()["league_name"] == "英超"

        listed = await client.get("/api/v1/base/leagues")
        assert listed.status_code == 200
        assert len(listed.json()) >= 1

        deleted = await client.delete(f"/api/v1/base/leagues/{league_id}")
        assert deleted.status_code == 204
        missing = await client.get(f"/api/v1/base/leagues/{league_id}")
        assert missing.status_code == 404

    async def test_team_requires_valid_league(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/base/teams",
            json={"team_name": "阿森纳", "league_id": 9999},
        )
        # 联赛不存在时触发外键约束错误,统一映射为 422
        assert response.status_code == 422

    async def test_player_create_with_optional_fields(self, client: AsyncClient) -> None:
        league = await client.post(
            "/api/v1/base/leagues", json={"league_name": "西甲", "country": "西班牙"}
        )
        team = await client.post(
            "/api/v1/base/teams",
            json={"team_name": "皇马", "league_id": league.json()["league_id"]},
        )
        player = await client.post(
            "/api/v1/base/players",
            json={
                "player_name": "贝林厄姆",
                "team_id": team.json()["team_id"],
                "position": "CAM",
                "market_value": 180000000,
            },
        )
        assert player.status_code == 201
        assert player.json()["position"] == "CAM"

    async def test_list_filters_by_parent(self, client: AsyncClient) -> None:
        """球队列表按联赛过滤、球员列表按球队过滤。"""
        league_a = (
            await client.post(
                "/api/v1/base/leagues", json={"league_name": "西甲", "country": "西班牙"}
            )
        ).json()
        league_b = (
            await client.post(
                "/api/v1/base/leagues", json={"league_name": "英超", "country": "英格兰"}
            )
        ).json()
        team_a = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "皇马", "league_id": league_a["league_id"]},
            )
        ).json()
        team_b = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "阿森纳", "league_id": league_b["league_id"]},
            )
        ).json()
        await client.post(
            "/api/v1/base/players",
            json={"player_name": "贝林厄姆", "team_id": team_a["team_id"]},
        )
        await client.post(
            "/api/v1/base/players",
            json={"player_name": "萨卡", "team_id": team_b["team_id"]},
        )

        teams_in_a = await client.get(
            "/api/v1/base/teams", params={"league_id": league_a["league_id"]}
        )
        assert teams_in_a.status_code == 200
        assert [t["team_name"] for t in teams_in_a.json()] == ["皇马"]

        players_in_a = await client.get(
            "/api/v1/base/players", params={"team_id": team_a["team_id"]}
        )
        assert players_in_a.status_code == 200
        assert [p["player_name"] for p in players_in_a.json()] == ["贝林厄姆"]

        all_teams = await client.get("/api/v1/base/teams")
        assert len(all_teams.json()) == 2


class TestMatchModule:
    """比赛与赛果模块(/api/v1/match)测试。"""

    async def _create_fixture(self, client: AsyncClient) -> dict[str, int]:
        league = (
            await client.post(
                "/api/v1/base/leagues",
                json={"league_name": "意甲", "country": "意大利"},
            )
        ).json()
        home = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "国米", "league_id": league["league_id"]},
            )
        ).json()
        away = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "米兰", "league_id": league["league_id"]},
            )
        ).json()
        return {
            "league_id": league["league_id"],
            "home_team_id": home["team_id"],
            "away_team_id": away["team_id"],
        }

    async def test_game_create_and_score_update(self, client: AsyncClient) -> None:
        fixture = await self._create_fixture(client)
        game = await client.post(
            "/api/v1/match/games",
            json={
                "match_id": "m-20260817-01",
                "match_time": TEST_TIME.isoformat(),
                **fixture,
            },
        )
        assert game.status_code == 201
        assert game.json()["match_status"] == "PENDING"

        scored = await client.patch(
            "/api/v1/match/games/m-20260817-01/score",
            json={"home_score": 2, "away_score": 1},
        )
        assert scored.status_code == 200
        assert scored.json()["home_score"] == 2
        assert scored.json()["match_status"] == "FINISHED"

    async def test_game_rejects_same_teams(self, client: AsyncClient) -> None:
        fixture = await self._create_fixture(client)
        response = await client.post(
            "/api/v1/match/games",
            json={
                "match_id": "m-dup",
                "match_time": TEST_TIME.isoformat(),
                "home_team_id": fixture["home_team_id"],
                "away_team_id": fixture["home_team_id"],
                "league_id": fixture["league_id"],
            },
        )
        # DataValidationError 统一映射为 422
        assert response.status_code == 422

    async def test_event_create_and_list(self, client: AsyncClient) -> None:
        fixture = await self._create_fixture(client)
        await client.post(
            "/api/v1/match/games",
            json={
                "match_id": "m-evt",
                "match_time": TEST_TIME.isoformat(),
                **fixture,
            },
        )
        event = await client.post(
            "/api/v1/match/events",
            json={"match_id": "m-evt", "event_type": "GOAL", "event_minute": 34},
        )
        assert event.status_code == 201

        listed = await client.get("/api/v1/match/events", params={"match_id": "m-evt"})
        assert listed.status_code == 200
        assert listed.json()[0]["event_type"] == "GOAL"

    async def test_event_requires_existing_match(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/match/events",
            json={"match_id": "not-exist", "event_type": "GOAL", "event_minute": 1},
        )
        assert response.status_code == 404


class TestAnalyticsModule:
    """高阶数据分析模块(/api/v1/analytics)测试。"""

    async def test_team_stats_create_and_filter(self, client: AsyncClient) -> None:
        league = (
            await client.post(
                "/api/v1/base/leagues", json={"league_name": "德甲", "country": "德国"}
            )
        ).json()
        home = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "拜仁", "league_id": league["league_id"]},
            )
        ).json()
        away = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "多特", "league_id": league["league_id"]},
            )
        ).json()
        await client.post(
            "/api/v1/match/games",
            json={
                "match_id": "m-xg",
                "match_time": TEST_TIME.isoformat(),
                "league_id": league["league_id"],
                "home_team_id": home["team_id"],
                "away_team_id": away["team_id"],
            },
        )

        stat = await client.post(
            "/api/v1/analytics/team-stats",
            json={
                "match_id": "m-xg",
                "team_id": home["team_id"],
                "xg": 2.31,
                "xga": 0.87,
                "possession": 61.4,
                "shot_accuracy": 44.0,
                "ppda": 8.2,
            },
        )
        assert stat.status_code == 201
        assert stat.json()["xg"] == pytest.approx(2.31)

        listed = await client.get(
            "/api/v1/analytics/team-stats", params={"match_id": "m-xg"}
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1


class TestStrategyModule:
    """策略与赔率模块(/api/v1/strategy)测试。"""

    async def test_recommendation_and_decision_flow(self, client: AsyncClient) -> None:
        league = (
            await client.post(
                "/api/v1/base/leagues", json={"league_name": "法甲", "country": "法国"}
            )
        ).json()
        home = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "巴黎", "league_id": league["league_id"]},
            )
        ).json()
        away = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "马赛", "league_id": league["league_id"]},
            )
        ).json()
        await client.post(
            "/api/v1/match/games",
            json={
                "match_id": "m-str",
                "match_time": TEST_TIME.isoformat(),
                "league_id": league["league_id"],
                "home_team_id": home["team_id"],
                "away_team_id": away["team_id"],
            },
        )

        rec = await client.post(
            "/api/v1/strategy/recommendations",
            json={
                "match_id": "m-str",
                "strategy_type": "WIN_DRAW_LOSS",
                "predicted_outcome": "HOME_WIN",
                "confidence_score": 0.62,
                "logic_tags": ["核心缺阵", "盘口浅开"],
            },
        )
        assert rec.status_code == 201
        assert rec.json()["logic_tags"] == ["核心缺阵", "盘口浅开"]

        decision = await client.post(
            "/api/v1/strategy/user-decisions",
            json={
                "user_id": 1,
                "recommend_id": rec.json()["recommend_id"],
                "user_bet_type": "WIN_DRAW_LOSS",
                "stake_amount": 100.0,
            },
        )
        assert decision.status_code == 201
        assert decision.json()["result_status"] == "PUSH"

    async def test_user_decisions_batch_creates_picks(self, client: AsyncClient) -> None:
        """POST /user-decisions/batch:自选玩法 -> 用户自选推荐 + 模拟决策。"""
        league = (
            await client.post(
                "/api/v1/base/leagues", json={"league_name": "英超", "country": "英格兰"}
            )
        ).json()
        home = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "阿森纳", "league_id": league["league_id"]},
            )
        ).json()
        away = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "热刺", "league_id": league["league_id"]},
            )
        ).json()
        await client.post(
            "/api/v1/match/games",
            json={
                "match_id": "m-pick",
                "match_time": TEST_TIME.isoformat(),
                "league_id": league["league_id"],
                "home_team_id": home["team_id"],
                "away_team_id": away["team_id"],
            },
        )

        response = await client.post(
            "/api/v1/strategy/user-decisions/batch",
            json={
                "user_id": 1,
                "stake_amount": 50.0,
                "selections": [
                    {
                        "match_id": "m-pick",
                        "pool_code": "HAD",
                        "option_code": "h",
                        "option_label": "主胜",
                    },
                    {
                        "match_id": "m-pick",
                        "pool_code": "TTG",
                        "option_code": "s2",
                        "option_label": "2",
                    },
                ],
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["decision_count"] == 2
        assert [d["user_bet_type"] for d in body["decisions"]] == ["HAD:h", "TTG:s2"]
        assert all(d["stake_amount"] == 50.0 for d in body["decisions"])

        # 每条决策挂靠一条“用户自选”推荐记录
        recs = (
            await client.get(
                "/api/v1/strategy/recommendations", params={"match_id": "m-pick"}
            )
        ).json()
        assert len(recs) == 2
        assert all(r["logic_tags"] == ["用户自选"] for r in recs)
        assert all(r["confidence_score"] == 0.0 for r in recs)
        assert {r["predicted_outcome"] for r in recs} == {"主胜", "2"}
        assert {r["strategy_type"] for r in recs} == {"WIN_DRAW_LOSS", "TOTAL_GOALS"}

    async def test_user_decisions_batch_rejects_bad_pool(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/strategy/user-decisions/batch",
            json={
                "user_id": 1,
                "stake_amount": 50.0,
                "selections": [
                    {
                        "match_id": "no-such-match",
                        "pool_code": "XX",
                        "option_code": "h",
                        "option_label": "主胜",
                    },
                ],
            },
        )
        assert response.status_code == 422

    async def test_recommendation_rejects_unknown_strategy_type(
        self, client: AsyncClient
    ) -> None:
        league = (
            await client.post(
                "/api/v1/base/leagues", json={"league_name": "荷甲", "country": "荷兰"}
            )
        ).json()
        home = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "阿贾克斯", "league_id": league["league_id"]},
            )
        ).json()
        away = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "埃因霍温", "league_id": league["league_id"]},
            )
        ).json()
        await client.post(
            "/api/v1/match/games",
            json={
                "match_id": "m-str2",
                "match_time": TEST_TIME.isoformat(),
                "league_id": league["league_id"],
                "home_team_id": home["team_id"],
                "away_team_id": away["team_id"],
            },
        )
        response = await client.post(
            "/api/v1/strategy/recommendations",
            json={
                "match_id": "m-str2",
                "strategy_type": "UNKNOWN_TYPE",
                "predicted_outcome": "X",
                "confidence_score": 0.5,
            },
        )
        assert response.status_code == 422

    async def test_odds_history_create_and_order(self, client: AsyncClient) -> None:
        league = (
            await client.post(
                "/api/v1/base/leagues", json={"league_name": "葡超", "country": "葡萄牙"}
            )
        ).json()
        home = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "本菲卡", "league_id": league["league_id"]},
            )
        ).json()
        away = (
            await client.post(
                "/api/v1/base/teams",
                json={"team_name": "波尔图", "league_id": league["league_id"]},
            )
        ).json()
        await client.post(
            "/api/v1/match/games",
            json={
                "match_id": "m-odds",
                "match_time": TEST_TIME.isoformat(),
                "league_id": league["league_id"],
                "home_team_id": home["team_id"],
                "away_team_id": away["team_id"],
            },
        )
        for i, value in enumerate([2.10, 1.95, 1.88]):
            created = await client.post(
                "/api/v1/strategy/odds-history",
                json={
                    "match_id": "m-odds",
                    "bookmaker": "Bet365",
                    "market_type": "EURO_ODDS",
                    "initial_value": 2.10,
                    "current_value": value,
                    "update_time": (
                        TEST_TIME + datetime.timedelta(hours=i)
                    ).isoformat(),
                },
            )
            assert created.status_code == 201

        listed = await client.get(
            "/api/v1/strategy/odds-history", params={"match_id": "m-odds"}
        )
        values = [r["current_value"] for r in listed.json()]
        assert values == [2.10, 1.95, 1.88]
