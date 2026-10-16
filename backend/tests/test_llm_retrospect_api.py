"""大模型赛事复盘模块接口测试(/api/v1/match/games/{id}/llm-retrospect)。

SQLite 内存库 + FastAPI 依赖覆盖,覆盖:
- GET 视图:比对预览实时计算 / 赛果与分析缺失标记 / 最近一次复盘回读;
- POST 生成:前置校验 422(无赛果 / 无分析 / 无已开奖玩法);
- POST 成功:落库快照(推荐/开奖/命中/归因)、命中统计、经验教训;
- 命中口径归一化("3球" vs 开奖"3"、"让球主胜" vs "主胜");
- 请求日志以 analysis_type=retrospect 留痕;比赛不存在 404。

网络层(llm._call_chat)全部打桩,测试不发起真实请求。
"""

import datetime
import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.database import Base, get_db_session
from app.main import app
from app.models import (
    League,
    LlmRequestLog,
    MatchGame,
    MatchLlmAnalysis,
    MatchLlmPlayRec,
    MatchResult,
    Team,
)
from app.services import llm

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

BASE_TIME = datetime.datetime(2026, 10, 1, 21, 0)

VIEW_URL = "/api/v1/match/games/m-retro-001/llm-retrospect"
POST_URL = VIEW_URL

# 模拟大模型的标准复盘输出:HAD 命中归因 + CRS 未中归因,
# 含一条非法玩法编码(应被过滤)与 4 条经验(不超上限)
_STUB_LLM_CONTENT = (
    "```json\n"
    "{\n"
    '  "summary": "AI 对主队基本面占优的判断成立,胜平负命中;'
    '比分玩法低估了客队反击效率导致未中,整体 1/2 命中。",\n'
    '  "playReviews": [\n'
    '    {"playCode": "HAD", "review": "推理链成立:主队主场胜率与积分优势均指向主胜,属正常命中。"},\n'
    '    {"playCode": "CRS", "review": "推理断裂:仅用攻防均值推比分,忽略客队客场反击效率。"},\n'
    '    {"playCode": "FAKE", "review": "非法玩法编码,应被过滤。"}\n'
    "  ],\n"
    '  "lessons": [\n'
    '    "比分玩法应结合双方攻防强度派生分布,而非直接取常见比分",\n'
    '    "主客场战绩分化明显的球队,让球玩法须谨慎压低置信度"\n'
    "  ]\n"
    "}\n"
    "```"
)


@pytest.fixture
async def env(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    """返回测试客户端与会话工厂(会话用于预置联赛/球队/比赛/赛果/分析)。"""
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    # 请求日志通过独立会话工厂写入,测试指向 SQLite 测试库(默认指向生产 MySQL)
    monkeypatch.setattr(llm, "_log_session_factory", session_factory)

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


async def _seed_match(
    session_factory: async_sessionmaker,
    *,
    with_result: bool = True,
    with_analysis: bool = True,
) -> None:
    """预置比赛 m-retro-001(可选赛果与 AI 综合分析)。

    赛果:全场 2:1(半场 1:0),胜平负=主胜、让球(盘口 -1)=平、
    比分=2:1、总进球=3、半全场=胜胜。
    分析:HAD 推荐"主胜"(命中)、TTG 推荐"3球"(归一化后命中开奖"3")、
    CRS 推荐"1:1"(未中,开奖 2:1)。
    """
    async with session_factory() as session:
        league = League(
            league_name="英格兰超级联赛", country="英格兰", tier=1, season="2026-2027"
        )
        session.add(league)
        await session.flush()
        home = Team(team_name="阿森纳", league_id=league.league_id)
        away = Team(team_name="埃弗顿", league_id=league.league_id)
        session.add_all([home, away])
        await session.flush()
        session.add(
            MatchGame(
                match_id="m-retro-001",
                match_num_str="周四001",
                league_id=league.league_id,
                home_team_id=home.team_id,
                away_team_id=away.team_id,
                match_time=BASE_TIME,
                match_status="FINISHED",
            )
        )
        if with_result:
            session.add(
                MatchResult(
                    match_id="m-retro-001",
                    match_num_str="周四001",
                    goal_line="-1",
                    half_home_score=1,
                    half_away_score=0,
                    full_home_score=2,
                    full_away_score=1,
                    had="主胜",
                    hhad="让球平",
                    crs="2:1",
                    ttg="3",
                    hafu="胜胜",
                    sp_h=1.85,
                    sp_d=3.40,
                    sp_a=4.20,
                )
            )
        if with_analysis:
            analysis = MatchLlmAnalysis(
                match_id="m-retro-001",
                provider="qwen",
                model="qwen-max",
                summary="主队主场强势且积分占优,整体倾向主胜。",
                risks=["客队近期状态回暖"],
                created_at=BASE_TIME - datetime.timedelta(days=1),
            )
            analysis.plays = [
                MatchLlmPlayRec(
                    play_code="HAD",
                    play_name="胜平负",
                    recommendation="主胜",
                    confidence=0.62,
                    reasoning="主队主场胜率 75%,积分榜领先 6 分。",
                    alternatives=["平"],
                ),
                MatchLlmPlayRec(
                    play_code="TTG",
                    play_name="总进球",
                    recommendation="3球",
                    confidence=0.40,
                    reasoning="双方攻防均值指向 3 球上下。",
                    alternatives=["2球"],
                ),
                MatchLlmPlayRec(
                    play_code="CRS",
                    play_name="比分",
                    recommendation="1:1",
                    confidence=0.18,
                    reasoning="平局比分兼顾攻防均衡的判断。",
                    alternatives=["2:1"],
                ),
            ]
            session.add(analysis)
        await session.commit()


def _stub_chat(
    content: str = _STUB_LLM_CONTENT,
) -> typing.Callable[..., typing.Awaitable[llm.LlmCallResult]]:
    """构造 _call_chat 测试桩:忽略入参,返回固定输出(带计量信息)。"""

    async def fake_call(
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        settings: Settings,
    ) -> llm.LlmCallResult:
        return llm.LlmCallResult(
            content=content,
            http_status=200,
            prompt_tokens=300,
            completion_tokens=120,
            total_tokens=420,
            duration_ms=567,
        )

    return fake_call


class TestGetRetrospectView:
    """GET /api/v1/match/games/{match_id}/llm-retrospect 测试。"""

    async def test_returns_404_for_unknown_match(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange / Act
        client, _ = env
        response = await client.get("/api/v1/match/games/unknown/llm-retrospect")

        # Assert
        assert response.status_code == 404

    async def test_view_without_result_and_analysis(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:只有比赛,无赛果无分析
        client, session_factory = env
        await _seed_match(session_factory, with_result=False, with_analysis=False)

        # Act
        response = await client.get(VIEW_URL)

        # Assert:缺失标记明确,比对为空,无已保存复盘
        assert response.status_code == 200
        body = response.json()
        assert body["match_id"] == "m-retro-001"
        assert body["result_available"] is False
        assert body["analysis_available"] is False
        assert body["comparison"] == []
        assert body["retrospect"] is None

    async def test_view_comparison_computed_live(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:赛果 + 分析齐备,尚未生成复盘
        client, session_factory = env
        await _seed_match(session_factory)

        # Act
        response = await client.get(VIEW_URL)

        # Assert:比对预览实时计算,命中口径归一化
        assert response.status_code == 200
        body = response.json()
        assert body["result_available"] is True
        assert body["analysis_available"] is True
        assert body["retrospect"] is None
        by_code = {row["play_code"]: row for row in body["comparison"]}
        assert by_code["HAD"]["is_hit"] is True  # 主胜 vs 主胜
        assert by_code["TTG"]["is_hit"] is True  # "3球"归一化为"3" vs 开奖"3"
        assert by_code["CRS"]["is_hit"] is False  # 1:1 vs 2:1
        assert by_code["HAD"]["result"] == "主胜"
        assert by_code["HAD"]["confidence"] == pytest.approx(0.62)
        assert by_code["HAD"]["alternatives"] == ["平"]


class TestGenerateRetrospect:
    """POST /api/v1/match/games/{match_id}/llm-retrospect 测试。"""

    async def test_rejects_when_result_missing(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange:无赛果(有分析)
        client, session_factory = env
        await _seed_match(session_factory, with_result=False)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        # Act
        response = await client.post(POST_URL)

        # Assert
        assert response.status_code == 422
        assert "赛果未同步" in response.json()["error"]["message"]

    async def test_rejects_when_analysis_missing(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange:有赛果,无分析
        client, session_factory = env
        await _seed_match(session_factory, with_analysis=False)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        # Act
        response = await client.post(POST_URL)

        # Assert
        assert response.status_code == 422
        assert "尚未生成 AI 综合分析" in response.json()["error"]["message"]

    async def test_rejects_when_no_decided_plays(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange:赛果有开奖字段(让球平),但分析覆盖的玩法
        # (HAD/TTG/CRS)对应开奖字段全为空 -> 无可比对玩法
        client, session_factory = env
        await _seed_match(session_factory)
        async with session_factory() as session:
            row = (
                await session.execute(
                    select(MatchResult).where(MatchResult.match_id == "m-retro-001")
                )
            ).scalar_one()
            row.had = None
            row.crs = None
            row.ttg = None
            row.hafu = None
            await session.commit()
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        # Act
        response = await client.post(POST_URL)

        # Assert
        assert response.status_code == 422
        assert "没有已开奖玩法" in response.json()["error"]["message"]

    async def test_generates_and_persists_snapshot(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange
        client, session_factory = env
        await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        # Act
        response = await client.post(POST_URL)

        # Assert:返回完整复盘载荷
        assert response.status_code == 200
        body = response.json()
        assert body["match_id"] == "m-retro-001"
        assert body["analysis_id"] > 0
        assert body["provider"] == settings.LLM_PROVIDER.strip().lower()
        assert "胜平负命中" in body["summary"]
        assert len(body["lessons"]) == 2
        assert "比分玩法" in body["lessons"][0]
        # 命中统计:HAD 命中、TTG 命中(归一化)、CRS 未中 -> 2/3
        assert body["hit_count"] == 2
        assert body["total_count"] == 3
        items = {row["play_code"]: row for row in body["items"]}
        assert items["HAD"]["is_hit"] is True
        assert items["HAD"]["review"] is not None
        assert "推理链成立" in items["HAD"]["review"]
        assert items["CRS"]["is_hit"] is False
        assert "推理断裂" in items["CRS"]["review"]
        # 模型未覆盖的玩法(TTG)归因为 None;非法玩法编码(FAKE)不入明细
        assert items["TTG"]["review"] is None
        assert "FAKE" not in items
        assert items["HAD"]["recommendation"] == "主胜"
        assert items["HAD"]["result"] == "主胜"
        assert items["HAD"]["reasoning"].startswith("主队主场胜率")

    async def test_view_returns_saved_retrospect_after_generation(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange:生成一次复盘
        client, session_factory = env
        await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        generate_response = await client.post(POST_URL)
        assert generate_response.status_code == 200
        generated = generate_response.json()

        # Act:GET 视图应带回已保存复盘
        response = await client.get(VIEW_URL)

        # Assert
        assert response.status_code == 200
        body = response.json()
        assert body["retrospect"] is not None
        assert body["retrospect"]["retrospect_id"] == generated["retrospect_id"]
        assert body["retrospect"]["hit_count"] == 2
        assert len(body["retrospect"]["items"]) == 3

    async def test_writes_request_log_with_retrospect_type(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange
        client, session_factory = env
        await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        # Act
        response = await client.post(POST_URL)
        assert response.status_code == 200

        # Assert:请求日志以 analysis_type=retrospect 留痕
        async with session_factory() as session:
            logs = (
                (
                    await session.execute(
                        select(LlmRequestLog).where(
                            LlmRequestLog.match_id == "m-retro-001"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(logs) == 1
            assert logs[0].status == "SUCCESS"
            assert logs[0].request_params["analysis_type"] == "retrospect"
            assert logs[0].request_messages[0]["role"] == "system"
            assert "事后复盘" in logs[0].request_messages[0]["content"]
