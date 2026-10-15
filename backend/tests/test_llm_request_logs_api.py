"""比赛模块接口测试:大模型调用日志(/api/v1/match/games/{id}/llm-request-logs)。

SQLite 内存库 + FastAPI 依赖覆盖,覆盖:
- 日志按调用时间倒序返回,含完整请求参数与响应结果;
- analysis_type 从 request_params 派生(缺省回退为 analysis);
- FAILED 日志保留错误信息;球队维度日志(team: 前缀)不串入;
- limit 参数;比赛不存在 404;无日志返回空列表。
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
from app.models import League, LlmRequestLog, MatchGame, Team

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

BASE_TIME = datetime.datetime(2026, 10, 1, 21, 0)

LOGS_URL = "/api/v1/match/games/m-1/llm-request-logs"


@pytest.fixture
async def env() -> typing.AsyncGenerator[
    tuple[AsyncClient, async_sessionmaker], None
]:
    """返回测试客户端与会话工厂(会话用于预置比赛与日志)。"""
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
    """预置一场比赛(m-1)与 4 条调用日志(含失败与他场/球队维度干扰)。"""
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

        messages = [{"role": "system", "content": "你是分析师"}, {"role": "user", "content": "请分析"}]
        session.add_all(
            [
                # m-1:早期综合分析日志(无 analysis_type 键,应回退为 analysis)
                LlmRequestLog(
                    match_id="m-1",
                    provider="qwen",
                    model="qwen-max",
                    base_url="https://example.com/v1",
                    request_messages=messages,
                    request_params={"temperature": 0.3, "max_tokens": 2048},
                    response_content='{"summary": "ok"}',
                    status="SUCCESS",
                    http_status=200,
                    prompt_tokens=1000,
                    completion_tokens=200,
                    total_tokens=1200,
                    duration_ms=8000,
                    created_at=BASE_TIME,
                ),
                # m-1:基本面分析日志(带 analysis_type)
                LlmRequestLog(
                    match_id="m-1",
                    provider="qwen",
                    model="qwen-max",
                    base_url="https://example.com/v1",
                    request_messages=messages,
                    request_params={
                        "temperature": 0.3,
                        "max_tokens": 2048,
                        "analysis_type": "fundamental",
                    },
                    response_content='{"summary": "ok"}',
                    status="SUCCESS",
                    http_status=200,
                    prompt_tokens=900,
                    completion_tokens=300,
                    total_tokens=1200,
                    duration_ms=9000,
                    created_at=BASE_TIME + datetime.timedelta(hours=1),
                ),
                # m-1:失败的赔率走势日志(保留错误信息)
                LlmRequestLog(
                    match_id="m-1",
                    provider="ark",
                    model="doubao-pro",
                    base_url="https://example.com/v1",
                    request_messages=messages,
                    request_params={
                        "temperature": 0.3,
                        "analysis_type": "odds_trend",
                    },
                    response_content=None,
                    status="FAILED",
                    http_status=None,
                    duration_ms=1200,
                    error_message="大模型服务调用失败(网络错误)",
                    error_detail="ConnectError: timeout",
                    created_at=BASE_TIME + datetime.timedelta(hours=2),
                ),
                # 球队维度日志:match_id 存 "team:{id}" 标识,不应串入比赛日志
                LlmRequestLog(
                    match_id=f"team:{home.team_id}",
                    provider="qwen",
                    model="qwen-max",
                    base_url="https://example.com/v1",
                    request_messages=messages,
                    request_params={"analysis_type": "team"},
                    response_content="{}",
                    status="SUCCESS",
                    duration_ms=500,
                ),
            ]
        )
        await session.commit()


class TestLlmRequestLogsEndpoint:
    """GET /api/v1/match/games/{match_id}/llm-request-logs 测试。"""

    async def test_returns_logs_desc_with_full_payload(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        client, _ = env
        await _seed(env)

        # Act
        response = await client.get(LOGS_URL)

        # Assert:按时间倒序(失败日志最新);球队维度日志不串入
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 3
        assert [row["status"] for row in body] == ["FAILED", "SUCCESS", "SUCCESS"]

        latest = body[0]
        assert latest["analysis_type"] == "odds_trend"
        assert latest["provider"] == "ark"
        assert latest["model"] == "doubao-pro"
        assert latest["response_content"] is None
        assert latest["error_message"] == "大模型服务调用失败(网络错误)"
        assert latest["error_detail"] == "ConnectError: timeout"
        assert latest["duration_ms"] == 1200

        # 完整请求与响应载荷
        middle = body[1]
        assert middle["analysis_type"] == "fundamental"
        assert middle["request_messages"][0]["role"] == "system"
        assert middle["request_params"]["temperature"] == 0.3
        assert middle["response_content"] == '{"summary": "ok"}'
        assert middle["prompt_tokens"] == 900
        assert middle["total_tokens"] == 1200

        # 早期综合分析日志无 analysis_type 键,回退为 analysis
        oldest = body[2]
        assert oldest["analysis_type"] == "analysis"

    async def test_respects_limit_param(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        client, _ = env
        await _seed(env)

        # Act
        response = await client.get(LOGS_URL, params={"limit": 2})

        # Assert:只返回最近 2 条
        assert response.status_code == 200
        assert len(response.json()) == 2
        assert response.json()[0]["status"] == "FAILED"

    async def test_returns_404_for_unknown_match(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange / Act
        client, _ = env
        response = await client.get("/api/v1/match/games/unknown/llm-request-logs")

        # Assert
        assert response.status_code == 404

    async def test_returns_empty_list_when_no_logs(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:预置比赛但不写日志
        client, _ = env
        _, session_factory = env
        async with session_factory() as session:
            liga = League(league_name="联赛", country="西班牙", tier=1)
            session.add(liga)
            await session.flush()
            home = Team(team_name="主队", league_id=liga.league_id)
            away = Team(team_name="客队", league_id=liga.league_id)
            session.add_all([home, away])
            await session.flush()
            session.add(
                MatchGame(
                    match_id="m-2",
                    league_id=liga.league_id,
                    home_team_id=home.team_id,
                    away_team_id=away.team_id,
                    match_time=BASE_TIME,
                    match_status="PENDING",
                )
            )
            await session.commit()

        # Act
        response = await client.get("/api/v1/match/games/m-2/llm-request-logs")

        # Assert
        assert response.status_code == 200
        assert response.json() == []
