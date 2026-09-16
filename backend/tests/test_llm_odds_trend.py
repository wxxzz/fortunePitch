"""大模型赔率走势分析模块测试。

覆盖三个层次:
1. 上下文聚合与提示词构造:快照时间与各玩法赔率必须进入提示词;
2. 输出解析:玩法过滤 / 非法输出抛错 / 缺走势结论抛错;
3. 接口 POST /api/v1/match/games/{id}/llm-odds-trend:成功 / 无快照 422 /
   未配置 503 / 比赛不存在 404 / 服务故障 502 / 日志落库 / 结果落库。

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
from app.core.exceptions import DataValidationError, LlmServiceError
from app.main import app
from app.models import (
    League,
    LlmRequestLog,
    MatchGame,
    MatchLlmAnalysis,
    MatchLlmFundAnalysis,
    MatchLlmTrendAnalysis,
    MatchLlmTrendPlay,
    MatchOddsSnapshot,
    Team,
)
from app.services import llm, llm_odds_trend

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# 模拟大模型的标准输出:2 个有效玩法 + 1 个非法编码 + 非法 confidence
_STUB_LLM_CONTENT = (
    "好的,以下是赔率走势分析:\n"
    "```json\n"
    "{\n"
    '  "summary": "主胜赔率持续走低,市场资金明显倾向主队。",\n'
    '  "plays": [\n'
    '    {"playCode": "HAD", "signal": "主胜走强", "confidence": 0.62,'
    '    "reasoning": "主胜由2.15降至1.95,隐含概率抬升约5个百分点"},\n'
    '    {"playCode": "TTG", "signal": "进球数中低位", "confidence": 0.41,'
    '    "reasoning": "总进球水位整体小幅下移,方向不明"},\n'
    '    {"playCode": "FAKE", "signal": "无效玩法", "confidence": 0.9,'
    '    "reasoning": "应被过滤"},\n'
    '    {"playCode": "HHAD", "signal": "让球主胜", "confidence": "高",'
    '    "reasoning": "非法置信度应被跳过"}\n'
    "  ],\n"
    '  "risks": ["快照条数较少,走势可能不连续", "临场赔率或有突变"]\n'
    "}\n"
    "```\n"
    "以上仅供参考。"
)

# 预置的 3 条快照:主胜 2.15 -> 2.05 -> 1.95,平 / 客胜同步微调
_SEED_ODDS = [
    (2.15, 3.20, 3.10),
    (2.05, 3.25, 3.20),
    (1.95, 3.30, 3.35),
]


def _pools(home: float, draw: float, away: float) -> list[dict[str, typing.Any]]:
    """构造单条快照的玩法数据(胜平负 + 让球胜平负)。"""
    return [
        {
            "poolCode": "HAD",
            "playName": "胜平负",
            "options": [
                {"code": "h", "label": "主胜", "odds": home},
                {"code": "d", "label": "平", "odds": draw},
                {"code": "a", "label": "客胜", "odds": away},
            ],
        },
        {
            "poolCode": "HHAD",
            "playName": "让球胜平负",
            "goalLine": "-1",
            "options": [
                {"code": "hh", "label": "让球主胜", "odds": round(home * 1.8, 2)},
                {"code": "hd", "label": "让球平", "odds": round(draw * 1.1, 2)},
                {"code": "ha", "label": "让球客胜", "odds": round(away * 1.2, 2)},
            ],
        },
    ]


@pytest.fixture
async def env(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    """返回测试客户端与会话工厂(会话用于预置联赛/球队/比赛/快照)。"""
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    # 请求日志通过独立会话工厂写入,测试指向 SQLite 测试库(默认指向生产库)
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
    session_factory: async_sessionmaker, *, snapshot_count: int = 3
) -> str:
    """预置一场带赔率快照的比赛,返回 match_id。"""
    async with session_factory() as session:
        league = League(league_name="英格兰超级联赛", country="英格兰", tier=1, season="2026-2027")
        session.add(league)
        await session.flush()
        home = Team(team_name="阿森纳", league_id=league.league_id)
        away = Team(team_name="埃弗顿", league_id=league.league_id)
        session.add_all([home, away])
        await session.flush()

        session.add(
            MatchGame(
                match_id="m-trend-001",
                league_id=league.league_id,
                home_team_id=home.team_id,
                away_team_id=away.team_id,
                match_time=datetime.datetime(2026, 9, 18, 22, 0),
            )
        )
        for idx in range(snapshot_count):
            home_odds, draw_odds, away_odds = _SEED_ODDS[idx]
            session.add(
                MatchOddsSnapshot(
                    match_id="m-trend-001",
                    pools=_pools(home_odds, draw_odds, away_odds),
                    snapshot_time=datetime.datetime(2026, 9, 15, 10 + idx, 0),
                )
            )
        await session.commit()
    return "m-trend-001"


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
            completion_tokens=90,
            total_tokens=390,
            duration_ms=512,
        )

    return fake_call


# ---------- 提示词构造 ----------


class TestBuildTrendMessages:
    """build_trend_messages:上下文完整性测试。"""

    def _context(self, snapshot_count: int) -> llm_odds_trend.TrendAnalysisContext:
        snapshots = tuple(
            MatchOddsSnapshot(
                snapshot_id=idx + 1,
                match_id="m-trend-001",
                pools=_pools(*_SEED_ODDS[idx]),
                snapshot_time=datetime.datetime(2026, 9, 15, 10 + idx, 0),
            )
            for idx in range(snapshot_count)
        )
        return llm_odds_trend.TrendAnalysisContext(
            match_id="m-trend-001",
            league_name="英格兰超级联赛",
            season="2026-2027",
            match_time=datetime.datetime(2026, 9, 18, 22, 0),
            home_team_name="阿森纳",
            away_team_name="埃弗顿",
            snapshots=snapshots,
        )

    def test_messages_contain_system_spec_and_snapshot_odds(self) -> None:
        messages = llm_odds_trend.build_trend_messages(self._context(3))
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "只输出一个 JSON 对象" in messages[0]["content"]
        assert "赔率下降" in messages[0]["content"]

        user_text = messages[1]["content"]
        # 快照时间与各时点赔率进入提示词
        assert "共 3 条" in user_text
        assert "胜平负:主胜2.15/平3.2/客胜3.1" in user_text
        assert "胜平负:主胜1.95/平3.3/客胜3.35" in user_text
        assert "让球胜平负(-1)" in user_text

    def test_single_snapshot_flags_insufficient_trend(self) -> None:
        user_text = llm_odds_trend.build_trend_messages(self._context(1))[1]["content"]
        assert "仅有 1 条快照" in user_text


# ---------- 输出解析 ----------


class TestParseTrend:
    """_parse_trend:模型输出鲁棒解析测试。"""

    def test_parses_fenced_json_and_filters_plays(self) -> None:
        summary, plays, risks = llm_odds_trend._parse_trend(_STUB_LLM_CONTENT)
        assert "主胜" in summary
        assert risks == ["快照条数较少,走势可能不连续", "临场赔率或有突变"]
        # 非法 playCode 与非法 confidence 的条目被过滤,仅保留 2 条有效结论
        assert [p.play_code for p in plays] == ["HAD", "TTG"]
        assert plays[0].signal == "主胜走强"
        assert plays[0].confidence == 0.62

    def test_raises_on_plain_text_output(self) -> None:
        with pytest.raises(LlmServiceError):
            llm_odds_trend._parse_trend("抱歉,我无法完成该分析。")

    def test_raises_when_no_valid_plays(self) -> None:
        with pytest.raises(LlmServiceError):
            llm_odds_trend._parse_trend('{"summary": "ok", "plays": []}')

    def test_raises_when_summary_missing(self) -> None:
        with pytest.raises(LlmServiceError):
            llm_odds_trend._parse_trend('{"plays": []}')

    def test_overlong_fields_truncated_to_column_width(self) -> None:
        content = (
            '{"summary": "ok", "plays": [{'
            '"playCode": "HAD", "signal": "' + "长" * 40 + '", '
            '"confidence": 0.5, "reasoning": "' + "析" * 600 + '"}], '
            '"risks": []}'
        )
        _, plays, _ = llm_odds_trend._parse_trend(content)
        assert len(plays[0].signal) == 32
        assert len(plays[0].reasoning) == 500


# ---------- 上下文聚合 ----------


class TestBuildTrendContext:
    """build_trend_context:快照聚合测试。"""

    async def test_aggregates_snapshots_ascending(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        match_id = await _seed_match(session_factory)
        async with session_factory() as session:
            context = await llm_odds_trend.build_trend_context(session, match_id)
        assert context.match_id == match_id
        assert context.home_team_name == "阿森纳"
        assert len(context.snapshots) == 3
        # 时间正序,首条为主胜 2.15 的最早快照
        assert context.snapshots[0].snapshot_time < context.snapshots[-1].snapshot_time

    async def test_raises_422_when_no_snapshots(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        # snapshot_count=0:预置比赛但不落快照
        match_id = await _seed_match(session_factory, snapshot_count=0)
        async with session_factory() as session:
            with pytest.raises(DataValidationError):
                await llm_odds_trend.build_trend_context(session, match_id)

    async def test_raises_404_for_unknown_match(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        async with session_factory() as session:
            with pytest.raises(Exception):
                await llm_odds_trend.build_trend_context(session, "unknown")


# ---------- 接口 ----------


class TestLlmOddsTrendEndpoint:
    """POST /api/v1/match/games/{match_id}/llm-odds-trend 测试。"""

    async def test_returns_plays_and_summary(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-odds-trend")
        assert response.status_code == 200
        body = response.json()
        assert body["match_id"] == match_id
        assert body["analysis_id"] > 0
        assert body["created_at"]
        assert body["provider"] in ("qwen", "ark")
        assert body["model"]
        assert "主胜" in body["summary"]
        assert [p["play_code"] for p in body["plays"]] == ["HAD", "TTG"]
        assert body["plays"][0]["signal"] == "主胜走强"
        assert body["risks"]

    async def test_post_persists_analysis_rows(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-odds-trend")
        analysis_id = response.json()["analysis_id"]

        async with session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(MatchLlmTrendAnalysis).where(
                            MatchLlmTrendAnalysis.match_id == match_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].analysis_id == analysis_id
            assert rows[0].summary
            plays = list(
                (
                    await session.execute(
                        select(MatchLlmTrendPlay).where(
                            MatchLlmTrendPlay.analysis_id == analysis_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            # 过滤后的有效玩法结论各一条落库
            assert [p.play_code for p in plays] == ["HAD", "TTG"]
            assert plays[0].signal == "主胜走强"

    async def test_get_latest_returns_most_recent(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)

        # 未生成过 -> 404
        empty = await client.get(f"/api/v1/match/games/{match_id}/llm-odds-trend")
        assert empty.status_code == 404

        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        first = (
            await client.post(f"/api/v1/match/games/{match_id}/llm-odds-trend")
        ).json()
        second = (
            await client.post(f"/api/v1/match/games/{match_id}/llm-odds-trend")
        ).json()

        latest = await client.get(f"/api/v1/match/games/{match_id}/llm-odds-trend")
        assert latest.status_code == 200
        body = latest.json()
        assert body["analysis_id"] == second["analysis_id"] > first["analysis_id"]
        assert len(body["plays"]) == 2

    async def test_list_returns_history_desc(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        ids = [
            (
                await client.post(f"/api/v1/match/games/{match_id}/llm-odds-trend")
            ).json()["analysis_id"]
            for _ in range(3)
        ]

        response = await client.get(
            f"/api/v1/match/games/{match_id}/llm-odds-trend-analyses"
        )
        assert response.status_code == 200
        body = response.json()
        assert [a["analysis_id"] for a in body] == sorted(ids, reverse=True)
        assert all(a["plays"] for a in body)

    async def test_post_does_not_touch_other_llm_tables(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-odds-trend")
        assert response.status_code == 200
        # 走势分析与分玩法推荐 / 基本面分析各自落表,互不影响
        async with session_factory() as session:
            for model in (MatchLlmAnalysis, MatchLlmFundAnalysis):
                rows = list(
                    (
                        await session.execute(
                            select(model).where(model.match_id == match_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert rows == []

    async def test_post_writes_success_request_log(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-odds-trend")
        assert response.status_code == 200

        async with session_factory() as session:
            logs = list((await session.execute(select(LlmRequestLog))).scalars().all())
            assert len(logs) == 1
            log = logs[0]
            assert log.status == "SUCCESS"
            assert log.match_id == match_id
            assert log.http_status == 200
            assert log.prompt_tokens == 300
            assert log.duration_ms == 512
            assert log.error_message is None
            # 走势快照数据进入日志留存的提示词
            assert any("阿森纳" in m["content"] for m in log.request_messages)
            assert "赔率走势快照" in log.request_messages[1]["content"]
            assert "主胜2.15" in log.request_messages[1]["content"]
            assert log.request_params["max_tokens"] > 0
            assert log.request_params["analysis_type"] == "odds_trend"
            assert "主胜走强" in (log.response_content or "")

    async def test_returns_422_when_no_snapshots(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory, snapshot_count=0)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-odds-trend")
        assert response.status_code == 422
        assert "赔率走势" in response.json()["error"]["message"]
        # 未调用大模型,不产生请求日志
        async with session_factory() as session:
            logs = list((await session.execute(select(LlmRequestLog))).scalars().all())
            assert logs == []

    async def test_returns_404_for_unknown_match(
        self, env: tuple[AsyncClient, async_sessionmaker], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, _ = env
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        response = await client.post("/api/v1/match/games/unknown/llm-odds-trend")
        assert response.status_code == 404

    async def test_returns_503_when_api_key_missing(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        empty_key_settings = Settings(LLM_PROVIDER="qwen", LLM_QWEN_API_KEY="")
        monkeypatch.setattr(llm_odds_trend, "get_settings", lambda: empty_key_settings)

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-odds-trend")
        assert response.status_code == 503
        assert "LLM_QWEN_API_KEY" in response.json()["error"]["message"]

    async def test_returns_502_when_provider_fails(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)

        async def failing_call(
            base_url: str,
            api_key: str,
            model: str,
            messages: list[dict[str, str]],
            settings: Settings,
        ) -> llm.LlmCallResult:
            raise LlmServiceError(
                "大模型服务返回错误(HTTP 500)", detail="upstream error", http_status=500
            )

        monkeypatch.setattr(llm, "_call_chat", failing_call)
        response = await client.post(f"/api/v1/match/games/{match_id}/llm-odds-trend")
        assert response.status_code == 502

        async with session_factory() as session:
            logs = list((await session.execute(select(LlmRequestLog))).scalars().all())
            assert len(logs) == 1
            assert logs[0].status == "FAILED"
            assert logs[0].http_status == 500

    async def test_parse_failure_writes_log_with_response(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(
            llm, "_call_chat", _stub_chat(content="抱歉,我无法完成该分析。")
        )

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-odds-trend")
        assert response.status_code == 502

        async with session_factory() as session:
            logs = list((await session.execute(select(LlmRequestLog))).scalars().all())
            assert len(logs) == 1
            log = logs[0]
            assert log.status == "FAILED"
            # 调用成功但输出无法解析:响应原文保留,便于排障
            assert log.response_content == "抱歉,我无法完成该分析。"
            assert log.error_message is not None
