"""比赛模块接口测试:补充信息(/api/v1/match/games/{id}/extra-info)与 AI 上下文注入。

SQLite 内存库 + FastAPI 依赖覆盖,覆盖:
- GET 未录入返回空记录 / 比赛不存在 404;
- PUT 保存与整体覆盖(重复保存为更新,空文本清空);
- 保存后注入 AI 综合分析(llm)与基本面分析(llm_fundamental)的上下文与提示词;
- 未录入时不注入补充信息段。
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
from app.models import League, MatchExtraInfo, MatchGame, Team
from app.services import llm, llm_fundamental

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# 测试基准时间
BASE_TIME = datetime.datetime(2026, 10, 1, 21, 0)

EXTRA_URL = "/api/v1/match/games/m-1/extra-info"


@pytest.fixture
async def env() -> typing.AsyncGenerator[
    tuple[AsyncClient, async_sessionmaker], None
]:
    """返回测试客户端与会话工厂(会话用于预置比赛与直查上下文)。"""
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


async def _seed(env: tuple[AsyncClient, async_sessionmaker]) -> None:
    """预置一场比赛(m-1,未开赛)。"""
    _, session_factory = env
    async with session_factory() as session:
        liga = League(league_name="西班牙甲级联赛", country="西班牙", tier=1)
        session.add(liga)
        await session.flush()
        home = Team(team_name="皇家马德里", league_id=liga.league_id)
        away = Team(team_name="巴塞罗那", league_id=liga.league_id)
        session.add_all([home, away])
        await session.flush()
        session.add(
            MatchGame(
                match_id="m-1",
                match_num_str="周三001",
                league_id=liga.league_id,
                home_team_id=home.team_id,
                away_team_id=away.team_id,
                match_time=BASE_TIME + datetime.timedelta(days=1),
                match_status="PENDING",
            )
        )
        await session.commit()


class TestExtraInfoEndpoint:
    """GET / PUT /api/v1/match/games/{match_id}/extra-info 测试。"""

    async def test_get_returns_empty_record_when_not_saved(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        client, _ = env
        await _seed(env)

        # Act
        response = await client.get(EXTRA_URL)

        # Assert:未录入返回空记录,不报 404
        assert response.status_code == 200
        body = response.json()
        assert body["match_id"] == "m-1"
        assert body["injuries"] is None
        assert body["formations"] is None
        assert body["other_notes"] is None
        assert body["updated_at"] is None

    async def test_get_returns_404_for_unknown_match(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange / Act
        client, _ = env
        response = await client.get("/api/v1/match/games/unknown/extra-info")

        # Assert
        assert response.status_code == 404

    async def test_put_saves_then_roundtrip(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        client, _ = env
        await _seed(env)

        # Act:首次保存
        response = await client.put(
            EXTRA_URL,
            json={
                "injuries": "主队中场核心停赛",
                "formations": "主队 4-3-3,客队 4-2-3-1",
                "other_notes": "赛前有雨",
            },
        )

        # Assert:保存成功且落库为单行
        assert response.status_code == 200
        body = response.json()
        assert body["injuries"] == "主队中场核心停赛"
        assert body["updated_at"] is not None

        _, session_factory = env
        async with session_factory() as session:
            rows = list(
                (
                    await session.execute(select(MatchExtraInfo))
                ).scalars().all()
            )
            assert len(rows) == 1
            assert rows[0].match_id == "m-1"

        # Act:再次保存(整体覆盖:更新伤停,清空其他补充)
        response = await client.put(
            EXTRA_URL,
            json={"injuries": "客队主力中卫伤缺", "formations": "", "other_notes": ""},
        )

        # Assert:仍是单行,字段按整体覆盖语义更新/清空
        assert response.status_code == 200
        assert response.json()["injuries"] == "客队主力中卫伤缺"
        assert response.json()["formations"] is None
        assert response.json()["other_notes"] is None
        async with session_factory() as session:
            rows = list(
                (
                    await session.execute(select(MatchExtraInfo))
                ).scalars().all()
            )
            assert len(rows) == 1

    async def test_put_returns_404_for_unknown_match(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange / Act
        client, _ = env
        response = await client.put(
            "/api/v1/match/games/unknown/extra-info", json={"injuries": "x"}
        )

        # Assert
        assert response.status_code == 404

    async def test_put_rejects_oversized_field(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        client, _ = env
        await _seed(env)

        # Act:单字段超过 5000 字上限
        response = await client.put(
            EXTRA_URL, json={"injuries": "伤" * 5001}
        )

        # Assert
        assert response.status_code == 422


class TestExtraInfoLlmInjection:
    """补充信息注入 AI 分析上下文与提示词测试。"""

    async def test_extra_info_injected_into_llm_context_and_prompt(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:未录入时上下文无补充信息段
        client, session_factory = env
        await _seed(env)
        async with session_factory() as session:
            context = await llm.build_match_analysis_context(session, "m-1")
            assert context.extra_info_text is None
            messages = llm.build_analysis_messages(context)
            assert "人工录入补充信息" not in messages[1]["content"]

        # Act:录入后重建上下文
        await client.put(
            EXTRA_URL,
            json={
                "injuries": "主队中场核心停赛",
                "formations": "主队 4-3-3",
                "other_notes": "",
            },
        )
        async with session_factory() as session:
            context = await llm.build_match_analysis_context(session, "m-1")
            messages = llm.build_analysis_messages(context)

        # Assert:文本块含伤停/阵型,空字段不注入;提示词含补充信息段
        assert context.extra_info_text is not None
        assert "主队中场核心停赛" in context.extra_info_text
        assert "主队 4-3-3" in context.extra_info_text
        assert "其他补充" not in context.extra_info_text
        assert "人工录入补充信息" in messages[1]["content"]
        assert "主队中场核心停赛" in messages[1]["content"]

    async def test_extra_info_injected_into_fundamental_context(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange / Act:录入后重建基本面上下文
        client, session_factory = env
        await _seed(env)
        await client.put(
            EXTRA_URL,
            json={"injuries": "客队主力中卫伤缺", "formations": "", "other_notes": ""},
        )
        async with session_factory() as session:
            context = await llm_fundamental.build_fundamental_context(session, "m-1")
            messages = llm_fundamental.build_fundamental_messages(context)

        # Assert:基本面提示词同样注入补充信息段
        assert context.extra_info_text is not None
        assert "客队主力中卫伤缺" in context.extra_info_text
        assert "人工录入补充信息" in messages[1]["content"]
        assert "客队主力中卫伤缺" in messages[1]["content"]
