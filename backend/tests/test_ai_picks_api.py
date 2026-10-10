"""AI 策略推荐 API 端点测试。

覆盖 POST /strategy/ai-recommendations/generate、GET /ai-picks、
GET /ai-parlay-plans、两个 convert 端点的成功/幂等/错误分支,
以及完整闭环集成:推荐生成 -> 转决策/方案 -> 结算 -> 复盘统计
(AI 来源记录进入与自选流同构的结算/复盘统计)。
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
from app.models import (
    League,
    MatchGame,
    MatchLlmAnalysis,
    MatchLlmPlayRec,
    MatchOdds,
    MatchResult,
    Team,
)

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# 测试售卖日
BATCH_DATE = datetime.date(2026, 9, 17)


@pytest.fixture
async def env(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    """返回测试客户端与会话工厂(会话用于预置联赛/球队/比赛/分析/赛果)。"""
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


async def _seed(factory: async_sessionmaker) -> None:
    """预置两场可完整闭环的比赛:在售 HAD 赔率、AI 分析与赛果开奖。

    - m1:分析主胜 0.80,赛果 2:1 主胜(SP 主胜赔 2.20,高于在售 2.0,
      验证结算优先用 SP 赔率);
    - m2:分析主胜 0.70,赛果 0:0 平(主胜未中)。
    """
    async with factory() as session:
        league = League(league_name="西班牙甲级联赛", country="西班牙", tier=1, season="2026-2027")
        session.add(league)
        await session.flush()
        home = Team(team_name="巴塞罗那", league_id=league.league_id)
        away = Team(team_name="皇家马德里", league_id=league.league_id)
        session.add_all([home, away])
        await session.flush()
        for idx, match_id in enumerate(("m-1", "m-2")):
            session.add(
                MatchGame(
                    match_id=match_id,
                    match_num_str=f"周四{idx + 1:03d}",
                    league_id=league.league_id,
                    home_team_id=home.team_id,
                    away_team_id=away.team_id,
                    match_time=datetime.datetime(2026, 9, 17, 21, 0),
                    business_date=BATCH_DATE,
                )
            )
        await session.flush()
        for match_id in ("m-1", "m-2"):
            session.add(
                MatchOdds(
                    match_id=match_id,
                    pools=[
                        {
                            "poolCode": "HAD",
                            "playName": "胜平负",
                            "options": [
                                {"code": "h", "label": "主胜", "odds": 2.0},
                                {"code": "d", "label": "平", "odds": 4.0},
                                {"code": "a", "label": "客胜", "odds": 4.0},
                            ],
                        }
                    ],
                    update_time=datetime.datetime(2026, 9, 16, 10, 0),
                )
            )
        await session.flush()

        for match_id, confidence in (("m-1", 0.80), ("m-2", 0.70)):
            analysis = MatchLlmAnalysis(
                match_id=match_id,
                provider="qwen",
                model="qwen3.7-plus",
                summary="整体研判",
                risks=[],
            )
            session.add(analysis)
            await session.flush()
            session.add(
                MatchLlmPlayRec(
                    analysis_id=analysis.analysis_id,
                    play_code="HAD",
                    play_name="胜平负",
                    recommendation="主胜",
                    confidence=confidence,
                    reasoning="主队占优",
                    alternatives=[],
                )
            )
        await session.flush()

        # 赛果开奖:m1 主胜(SP 主胜 2.20),m2 平局
        session.add(
            MatchResult(
                match_id="m-1",
                match_num_str="周四001",
                goal_line=None,
                half_home_score=1,
                half_away_score=0,
                full_home_score=2,
                full_away_score=1,
                had="主胜",
                crs="2:1",
                ttg="3",
                hafu="胜胜",
                sp_h=2.20,
                sp_d=4.10,
                sp_a=3.40,
                pool_status="Payout",
            )
        )
        session.add(
            MatchResult(
                match_id="m-2",
                match_num_str="周四002",
                goal_line=None,
                half_home_score=0,
                half_away_score=0,
                full_home_score=0,
                full_away_score=0,
                had="平",
                crs="0:0",
                ttg="0",
                hafu="平平",
                sp_h=2.50,
                sp_d=3.30,
                sp_a=3.10,
                pool_status="Payout",
            )
        )
        await session.commit()


class TestAiGenerate:
    """POST /api/v1/strategy/ai-recommendations/generate"""

    async def test_generate_returns_batch_summary(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        await _seed(session_factory)

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/ai-recommendations/generate",
            json={"business_date": "2026-09-17"},
        )

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert body["pick_count"] == 2
        assert body["skipped_count"] == 0
        # 两条顺向腿 -> 仅稳胆 2串1
        assert body["plan_count"] == 1
        assert body["superseded_batch_ids"] == []
        assert body["business_date"] == "2026-09-17"

    async def test_generate_defaults_to_today(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange:把"今天"固定到测试售卖日
        async_client, session_factory = env
        from app.services import llm_query

        monkeypatch.setattr(llm_query, "current_business_date", lambda: BATCH_DATE)
        await _seed(session_factory)

        # Act:不传 business_date
        resp = await async_client.post(
            "/api/v1/strategy/ai-recommendations/generate", json={}
        )

        # Assert
        assert resp.status_code == 200
        assert resp.json()["pick_count"] == 2

    async def test_generate_recalculation_supersedes(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        await _seed(session_factory)
        first = (
            await async_client.post(
                "/api/v1/strategy/ai-recommendations/generate",
                json={"business_date": "2026-09-17"},
            )
        ).json()

        # Act:同售卖日重算
        resp = await async_client.post(
            "/api/v1/strategy/ai-recommendations/generate",
            json={"business_date": "2026-09-17"},
        )

        # Assert
        assert resp.status_code == 200
        assert resp.json()["superseded_batch_ids"] == [first["batch_id"]]

    async def test_generate_rejects_invalid_min_confidence(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, _ = env

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/ai-recommendations/generate",
            json={"business_date": "2026-09-17", "min_confidence": 1.5},
        )

        # Assert
        assert resp.status_code == 422


class TestAiPicksListing:
    """GET /api/v1/strategy/ai-picks 与 /ai-parlay-plans"""

    async def test_lists_picks_with_rich_fields(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        await _seed(session_factory)
        await async_client.post(
            "/api/v1/strategy/ai-recommendations/generate",
            json={"business_date": "2026-09-17"},
        )

        # Act
        resp = await async_client.get(
            "/api/v1/strategy/ai-picks", params={"business_date": "2026-09-17"}
        )

        # Assert:按 EV 倒序(m1 0.6 > m2 0.4),含富字段与量化指标
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 2
        first = rows[0]
        assert first["match_id"] == "m-1"
        assert first["match_num_str"] == "周四001"
        assert first["league_name"] == "西班牙甲级联赛"
        assert first["home_team_name"] == "巴塞罗那"
        assert first["away_team_name"] == "皇家马德里"
        assert first["option_code"] == "h"
        assert first["option_label"] == "主胜"
        assert first["odds"] == pytest.approx(2.0)
        assert first["confidence"] == pytest.approx(0.80)
        assert first["implied_prob"] == pytest.approx(0.5)
        assert first["ev"] == pytest.approx(0.6)
        assert first["kelly"] == pytest.approx(0.6)
        assert first["is_contrarian"] is False
        assert first["decision_id"] is None

    async def test_lists_parlay_plans(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        await _seed(session_factory)
        await async_client.post(
            "/api/v1/strategy/ai-recommendations/generate",
            json={"business_date": "2026-09-17"},
        )

        # Act
        resp = await async_client.get(
            "/api/v1/strategy/ai-parlay-plans", params={"business_date": "2026-09-17"}
        )

        # Assert
        assert resp.status_code == 200
        plans = resp.json()
        assert len(plans) == 1
        plan = plans[0]
        assert plan["plan_name"] == "稳胆 2串1"
        assert plan["parlay_size"] == 2
        assert [leg["match_id"] for leg in plan["legs"]] == ["m-1", "m-2"]
        assert plan["combined_odds"] == pytest.approx(4.0)
        assert plan["contrarian_count"] == 0
        assert plan["scheme_id"] is None

    async def test_empty_when_no_active_batch(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:未生成过推荐
        async_client, _ = env

        # Act / Assert
        resp = await async_client.get("/api/v1/strategy/ai-picks")
        assert resp.status_code == 200
        assert resp.json() == []
        resp = await async_client.get("/api/v1/strategy/ai-parlay-plans")
        assert resp.status_code == 200
        assert resp.json() == []


class TestAiConvert:
    """POST /ai-picks/{id}/convert 与 /ai-parlay-plans/{id}/convert"""

    async def test_convert_pick_and_idempotency(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        await _seed(session_factory)
        await async_client.post(
            "/api/v1/strategy/ai-recommendations/generate",
            json={"business_date": "2026-09-17"},
        )
        picks = (
            await async_client.get(
                "/api/v1/strategy/ai-picks", params={"business_date": "2026-09-17"}
            )
        ).json()
        pick_id = picks[0]["pick_id"]

        # Act
        first = await async_client.post(
            f"/api/v1/strategy/ai-picks/{pick_id}/convert",
            json={"user_id": 1, "stake_amount": 100},
        )
        second = await async_client.post(
            f"/api/v1/strategy/ai-picks/{pick_id}/convert",
            json={"user_id": 1, "stake_amount": 100},
        )

        # Assert:首次新建,重复转换返回既有决策
        assert first.status_code == 200
        assert first.json()["created"] is True
        assert first.json()["decision"]["user_bet_type"] == "HAD:h"
        assert second.status_code == 200
        assert second.json()["created"] is False
        assert (
            second.json()["decision"]["decision_id"]
            == first.json()["decision"]["decision_id"]
        )
        # 转换状态回填到清单
        picks = (
            await async_client.get(
                "/api/v1/strategy/ai-picks", params={"business_date": "2026-09-17"}
            )
        ).json()
        assert picks[0]["decision_id"] == first.json()["decision"]["decision_id"]

    async def test_convert_pick_not_found(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, _ = env

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/ai-picks/9999/convert",
            json={"user_id": 1, "stake_amount": 100},
        )

        # Assert
        assert resp.status_code == 404

    async def test_convert_plan_and_idempotency(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        await _seed(session_factory)
        await async_client.post(
            "/api/v1/strategy/ai-recommendations/generate",
            json={"business_date": "2026-09-17"},
        )
        plans = (
            await async_client.get(
                "/api/v1/strategy/ai-parlay-plans",
                params={"business_date": "2026-09-17"},
            )
        ).json()
        plan_id = plans[0]["plan_id"]

        # Act
        first = await async_client.post(
            f"/api/v1/strategy/ai-parlay-plans/{plan_id}/convert",
            json={"user_id": 1, "stake_per_bet": 100},
        )
        second = await async_client.post(
            f"/api/v1/strategy/ai-parlay-plans/{plan_id}/convert",
            json={"user_id": 1, "stake_per_bet": 100},
        )

        # Assert
        assert first.status_code == 200
        assert first.json()["created"] is True
        scheme = first.json()["scheme"]
        assert scheme["parlay_size"] == 2
        assert scheme["bet_count"] == 1
        assert {item["match_id"] for item in scheme["items"]} == {"m-1", "m-2"}
        assert second.status_code == 200
        assert second.json()["created"] is False
        assert (
            second.json()["scheme"]["scheme_id"] == scheme["scheme_id"]
        )
        # 保存状态回填到候选清单
        plans = (
            await async_client.get(
                "/api/v1/strategy/ai-parlay-plans",
                params={"business_date": "2026-09-17"},
            )
        ).json()
        assert plans[0]["scheme_id"] == scheme["scheme_id"]

    async def test_convert_plan_not_found(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, _ = env

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/ai-parlay-plans/9999/convert",
            json={"user_id": 1, "stake_per_bet": 100},
        )

        # Assert
        assert resp.status_code == 404


class TestAiClosedLoop:
    """闭环集成:生成 -> 转换 -> 结算 -> 复盘统计。"""

    async def test_converted_records_settle_and_enter_review(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:生成推荐,两条单场转决策,串关候选转方案
        async_client, session_factory = env
        await _seed(session_factory)
        await async_client.post(
            "/api/v1/strategy/ai-recommendations/generate",
            json={"business_date": "2026-09-17"},
        )
        picks = (
            await async_client.get(
                "/api/v1/strategy/ai-picks", params={"business_date": "2026-09-17"}
            )
        ).json()
        for pick in picks:
            resp = await async_client.post(
                f"/api/v1/strategy/ai-picks/{pick['pick_id']}/convert",
                json={"user_id": 1, "stake_amount": 100},
            )
            assert resp.status_code == 200
        plans = (
            await async_client.get(
                "/api/v1/strategy/ai-parlay-plans",
                params={"business_date": "2026-09-17"},
            )
        ).json()
        scheme_resp = await async_client.post(
            f"/api/v1/strategy/ai-parlay-plans/{plans[0]['plan_id']}/convert",
            json={"user_id": 1, "stake_per_bet": 100},
        )
        assert scheme_resp.status_code == 200

        # Act:结算
        settle_resp = await async_client.post(
            "/api/v1/strategy/settlement", json={"user_id": 1}
        )

        # Assert:m1 主胜命中(SP 赔率 2.20 优先于在售 2.0),
        # m2 主胜未中,串关方案(m2 腿未中)整体 LOSS
        assert settle_resp.status_code == 200
        settled = settle_resp.json()
        assert settled["decision_wins"] == 1
        assert settled["decision_losses"] == 1
        assert settled["scheme_wins"] == 0
        assert settled["scheme_losses"] == 1

        # Assert:复盘统计纳入 AI 来源记录
        stats_resp = await async_client.get(
            "/api/v1/strategy/review/stats", params={"user_id": 1}
        )
        assert stats_resp.status_code == 200
        kpi = stats_resp.json()["kpi"]
        assert kpi["total_bets"] == 3  # 2 决策 + 1 方案
        assert kpi["settled"] == 3
        assert kpi["win_count"] == 1
        # hit_rate 落库口径 4 位小数
        assert kpi["hit_rate"] == pytest.approx(1 / 3, abs=1e-4)
        assert kpi["total_stake"] == pytest.approx(300)
        # 120(SP 2.20 命中)- 100 - 100(串关败)
        assert kpi["total_profit"] == pytest.approx(-80)

        # Assert:单关决策明细可见 AI 来源(玩法为胜平负)
        decisions_resp = await async_client.get(
            "/api/v1/strategy/review/decisions", params={"user_id": 1}
        )
        assert decisions_resp.status_code == 200
        rows = decisions_resp.json()
        assert len(rows) == 2
        win_row = next(r for r in rows if r["result_status"] == "WIN")
        assert win_row["match_id"] == "m-1"
        assert win_row["profit_loss"] == pytest.approx(120.0)
        assert win_row["option_code"] == "h"
