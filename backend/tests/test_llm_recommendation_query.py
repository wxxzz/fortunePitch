"""AI 分析结果查询测试。

覆盖 GET /api/v1/match/llm-recommendations:
- 每场仅取最近一次分析(历史多份时旧分析不出现);
- 售卖日过滤(其他日期的比赛不出现);
- 置信度下限过滤(含边界);
- 玩法编码过滤与非法编码(422);
- 排序(置信度倒序)与比赛上下文(联赛/主客队)输出。
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
from app.models import (
    League,
    MatchGame,
    MatchLlmAnalysis,
    MatchLlmPlayRec,
    Team,
)

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# 测试售卖日与其他日期
QUERY_DATE = datetime.date(2026, 9, 17)
OTHER_DATE = datetime.date(2026, 9, 18)


@pytest.fixture
async def env(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    """返回测试客户端与会话工厂(会话用于预置联赛/球队/比赛/分析)。"""
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


async def _add_analysis(
    session: object,
    match_id: str,
    plays: list[dict],
    *,
    summary: str = "整体研判",
) -> None:
    """挂一条分析 + 分玩法推荐明细。"""
    analysis = MatchLlmAnalysis(
        match_id=match_id,
        provider="qwen",
        model="qwen3.7-plus",
        summary=summary,
        risks=[],
    )
    session.add(analysis)
    await session.flush()
    for play in plays:
        session.add(
            MatchLlmPlayRec(
                analysis_id=analysis.analysis_id,
                play_code=play["code"],
                play_name=play["name"],
                recommendation=play["recommendation"],
                confidence=play["confidence"],
                reasoning=play["reasoning"],
                alternatives=play.get("alternatives", []),
            )
        )


async def _seed(session_factory: async_sessionmaker) -> None:
    """预置三场比赛(两场在查询售卖日,一场在其他日期)与分析历史。

    - m-q1:两次分析(旧分析的推荐不应出现在查询结果中);
    - m-q2:一次分析,胜平负置信度 0.5、让球 0.8;
    - m-q3:其他售卖日,不应出现。
    """
    async with session_factory() as session:
        league = League(league_name="西班牙甲级联赛", country="西班牙", tier=1, season="2026-2027")
        session.add(league)
        await session.flush()
        home = Team(team_name="巴塞罗那", league_id=league.league_id)
        away = Team(team_name="皇家马德里", league_id=league.league_id)
        session.add_all([home, away])
        await session.flush()
        for match_id, business_date in (
            ("m-q1", QUERY_DATE),
            ("m-q2", QUERY_DATE),
            ("m-q3", OTHER_DATE),
        ):
            session.add(
                MatchGame(
                    match_id=match_id,
                    league_id=league.league_id,
                    home_team_id=home.team_id,
                    away_team_id=away.team_id,
                    match_time=datetime.datetime(2026, 9, 17, 21, 0),
                    business_date=business_date,
                )
            )
        await session.flush()

        # m-q1 旧分析(高置信度,但应被最新分析覆盖)
        await _add_analysis(
            session,
            "m-q1",
            [
                {
                    "code": "HAD",
                    "name": "胜平负",
                    "recommendation": "旧推荐-主胜",
                    "confidence": 0.9,
                    "reasoning": "旧分析依据",
                }
            ],
            summary="旧分析",
        )
        # m-q1 最新分析(查询应以此为准)
        await _add_analysis(
            session,
            "m-q1",
            [
                {
                    "code": "HAD",
                    "name": "胜平负",
                    "recommendation": "主胜",
                    "confidence": 0.7,
                    "reasoning": "主队主场强势,近 5 场 4 胜",
                    "alternatives": ["平"],
                },
                {
                    "code": "TTG",
                    "name": "总进球",
                    "recommendation": "3球",
                    "confidence": 0.3,
                    "reasoning": "两队攻强守弱",
                },
            ],
        )
        # m-q2 一次分析
        await _add_analysis(
            session,
            "m-q2",
            [
                {
                    "code": "HAD",
                    "name": "胜平负",
                    "recommendation": "客胜",
                    "confidence": 0.5,
                    "reasoning": "客队近期状态更稳",
                },
                {
                    "code": "HHAD",
                    "name": "让球胜平负",
                    "recommendation": "让球主胜",
                    "confidence": 0.8,
                    "reasoning": "让球后主队仍有优势",
                    "alternatives": ["让球平"],
                },
            ],
        )
        # m-q3 其他售卖日
        await _add_analysis(
            session,
            "m-q3",
            [
                {
                    "code": "HAD",
                    "name": "胜平负",
                    "recommendation": "平",
                    "confidence": 0.85,
                    "reasoning": "其他日期,不应出现",
                }
            ],
        )
        await session.commit()


class TestLlmRecommendations:
    """GET /api/v1/match/llm-recommendations"""

    async def test_returns_latest_analysis_and_match_context(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        await _seed(session_factory)

        # Act
        resp = await async_client.get(
            "/api/v1/match/llm-recommendations",
            params={"business_date": "2026-09-17"},
        )

        # Assert
        assert resp.status_code == 200
        rows = resp.json()
        # m-q1(2 玩法) + m-q2(2 玩法) = 4 行,m-q3 不出现
        assert len(rows) == 4
        q1_had = next(
            r for r in rows if r["match_id"] == "m-q1" and r["play_code"] == "HAD"
        )
        # 取最新分析,不是旧的高置信度分析
        assert q1_had["recommendation"] == "主胜"
        assert q1_had["confidence"] == pytest.approx(0.7)
        assert q1_had["reasoning"] == "主队主场强势,近 5 场 4 胜"
        assert q1_had["alternatives"] == ["平"]
        # 比赛上下文
        assert q1_had["league_name"] == "西班牙甲级联赛"
        assert q1_had["home_team_name"] == "巴塞罗那"
        assert q1_had["away_team_name"] == "皇家马德里"
        assert q1_had["match_time"].startswith("2026-09-17")

    async def test_filters_by_min_confidence(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange: 置信度 >= 0.7 时剩 m-q2 HHAD 0.8 与 m-q1 HAD 0.7(边界含)
        async_client, session_factory = env
        await _seed(session_factory)

        # Act
        resp = await async_client.get(
            "/api/v1/match/llm-recommendations",
            params={"business_date": "2026-09-17", "min_confidence": 0.7},
        )

        # Assert: 0.5 与 0.3 的推荐被过滤
        assert resp.status_code == 200
        rows = resp.json()
        assert {r["play_code"] for r in rows} == {"HAD", "HHAD"}
        assert all(r["confidence"] >= 0.7 for r in rows)

    async def test_filters_by_play_code(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        await _seed(session_factory)

        # Act
        resp = await async_client.get(
            "/api/v1/match/llm-recommendations",
            params={"business_date": "2026-09-17", "play_code": "HHAD"},
        )

        # Assert
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["play_code"] == "HHAD"
        assert rows[0]["match_id"] == "m-q2"

    async def test_orders_by_confidence_desc(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        await _seed(session_factory)

        # Act
        resp = await async_client.get(
            "/api/v1/match/llm-recommendations",
            params={"business_date": "2026-09-17"},
        )

        # Assert: 0.8 / 0.7 / 0.5 / 0.3
        confidences = [r["confidence"] for r in resp.json()]
        assert confidences == sorted(confidences, reverse=True)

    async def test_returns_empty_for_date_without_analyses(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, _ = env

        # Act
        resp = await async_client.get(
            "/api/v1/match/llm-recommendations",
            params={"business_date": "2025-01-01"},
        )

        # Assert
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_422_for_invalid_play_code(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, _ = env

        # Act
        resp = await async_client.get(
            "/api/v1/match/llm-recommendations",
            params={"business_date": "2026-09-17", "play_code": "XXX"},
        )

        # Assert
        assert resp.status_code == 422
        assert "玩法编码" in resp.text

    async def test_business_date_defaults_to_today(
        self, env: tuple[AsyncClient, async_sessionmaker], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange:把"今天"固定到测试售卖日,验证缺省日期取当天
        async_client, session_factory = env
        from app.services import llm_query

        monkeypatch.setattr(llm_query, "current_business_date", lambda: QUERY_DATE)
        await _seed(session_factory)

        # Act: 不传 business_date
        resp = await async_client.get("/api/v1/match/llm-recommendations")

        # Assert: 等同于按查询售卖日过滤
        assert resp.status_code == 200
        assert len(resp.json()) == 4
