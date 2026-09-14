"""大模型分析模块测试。

覆盖三个层次:
1. 提示词构造:关键上下文(球队/基本面/赔率/玩法)必须进入提示词;
2. 输出解析:裸 JSON / 代码块围栏 / 前后缀噪声 / 非法输出的鲁棒处理;
3. 接口 POST /api/v1/match/games/{id}/llm-analysis:成功 / 未配置 / 比赛不存在 / 服务故障。

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
from app.core.exceptions import LlmServiceError
from app.main import app
from app.models import (
    League,
    MatchGame,
    MatchLlmAnalysis,
    MatchLlmPlayRec,
    MatchOdds,
    MatchStatus,
    Team,
    TeamFundamentals,
)
from app.services import llm

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# 模拟大模型的标准输出(带代码块围栏 + 前后缀噪声,验证解析鲁棒性)
_STUB_LLM_CONTENT = (
    "好的,以下是分析结果:\n"
    "```json\n"
    "{\n"
    '  "summary": "主队主场强势,客队客场疲软,整体看好主队方向。",\n'
    '  "plays": [\n'
    "    {\n"
    '      "playCode": "HAD", "recommendation": "主胜", "confidence": 0.6,\n'
    '      "reasoning": "主队主场胜率 80%,客队客场仅 1 胜", "alternatives": ["平"]\n'
    "    },\n"
    "    {\n"
    '      "playCode": "TTG", "recommendation": "3球", "confidence": 0.4,\n'
    '      "reasoning": "两队攻强守弱", "alternatives": []\n'
    "    },\n"
    "    {\n"
    '      "playCode": "FAKE", "recommendation": "无效玩法", "confidence": 0.9,\n'
    '      "reasoning": "应被过滤", "alternatives": []\n'
    "    }\n"
    "  ],\n"
    '  "risks": ["客队近期状态回暖", "盘口存在异动"]\n'
    "}\n"
    "```\n"
    "以上仅供参考。"
)

_STUB_POOLS = [
    {
        "poolCode": "HAD",
        "playName": "胜平负",
        "options": [
            {"code": "h", "label": "主胜", "odds": 2.15},
            {"code": "d", "label": "平", "odds": 3.30},
            {"code": "a", "label": "客胜", "odds": 3.05},
        ],
    },
    {
        "poolCode": "TTG",
        "playName": "总进球",
        "options": [
            {"code": "s2", "label": "2球", "odds": 3.40},
            {"code": "s3", "label": "3球", "odds": 4.10},
        ],
    },
]


@pytest.fixture
async def env() -> typing.AsyncGenerator[
    tuple[AsyncClient, async_sessionmaker], None
]:
    """返回测试客户端与会话工厂(会话用于预置联赛/球队/比赛/基本面/赔率)。"""
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


async def _seed_match(session_factory: async_sessionmaker) -> str:
    """预置一场完整上下文的比赛(联赛/两队/基本面/赔率),返回 match_id。"""
    async with session_factory() as session:
        league = League(league_name="西班牙甲级联赛", country="西班牙", tier=1, season="2026-2027")
        session.add(league)
        await session.flush()
        home = Team(team_name="巴塞罗那", league_id=league.league_id)
        away = Team(team_name="皇家马德里", league_id=league.league_id)
        session.add_all([home, away])
        await session.flush()
        session.add(
            TeamFundamentals(
                team_id=home.team_id,
                season="2026-2027",
                ranking=1,
                played=4,
                wins=3,
                draws=1,
                losses=0,
                goals_for=12,
                goals_against=3,
                goal_diff=9,
                points=10,
                win_rate=75.0,
                home_wins=2,
                away_wins=1,
            )
        )
        session.add(
            TeamFundamentals(
                team_id=away.team_id,
                season="2026-2027",
                ranking=5,
                played=4,
                wins=2,
                draws=1,
                losses=1,
                goals_for=7,
                goals_against=5,
                goal_diff=2,
                points=7,
                win_rate=50.0,
                away_wins=1,
            )
        )
        game = MatchGame(
            match_id="m-llm-001",
            league_id=league.league_id,
            home_team_id=home.team_id,
            away_team_id=away.team_id,
            match_time=datetime.datetime(2026, 9, 15, 21, 0),
        )
        session.add(game)
        await session.flush()
        session.add(MatchOdds(match_id="m-llm-001", pools=_STUB_POOLS))
        await session.commit()
    return "m-llm-001"


def _stub_chat(
    content: str = _STUB_LLM_CONTENT,
) -> typing.Callable[..., typing.Awaitable[str]]:
    """构造 _call_chat 测试桩:忽略入参,返回固定输出。"""

    async def fake_call(
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        settings: Settings,
    ) -> str:
        return content

    return fake_call


# ---------- 提示词构造 ----------


class TestBuildAnalysisMessages:
    """build_analysis_messages:上下文完整性测试。"""

    def _context(self) -> llm.MatchAnalysisContext:
        # 直接构造 frozen dataclass,不依赖数据库
        return llm.MatchAnalysisContext(
            match_id="m-1",
            league_name="西班牙甲级联赛",
            season="2026-2027",
            match_time=datetime.datetime(2026, 9, 15, 21, 0),
            match_status=MatchStatus.PENDING,
            home_team_name="巴塞罗那",
            away_team_name="皇家马德里",
            home_fundamentals=None,
            away_fundamentals=None,
            pools=_STUB_POOLS,
        )

    def test_messages_contain_match_and_odds_context(self) -> None:
        messages = llm.build_analysis_messages(self._context())
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        user_text = messages[1]["content"]
        assert "巴塞罗那" in user_text
        assert "皇家马德里" in user_text
        assert "西班牙甲级联赛" in user_text
        assert "胜平负" in user_text
        assert "2.15" in user_text
        assert "3.4" in user_text

    def test_missing_fundamentals_are_flagged(self) -> None:
        user_text = llm.build_analysis_messages(self._context())[1]["content"]
        assert "未同步基本面数据" in user_text

    def test_system_prompt_requires_json_only(self) -> None:
        system_text = llm.build_analysis_messages(self._context())[0]["content"]
        assert "只输出一个 JSON 对象" in system_text
        assert "playCode" in system_text


# ---------- 输出解析 ----------


class TestParseAnalysis:
    """_parse_analysis:模型输出鲁棒解析测试。"""

    def test_parses_fenced_json_with_noise(self) -> None:
        context = typing.cast(llm.MatchAnalysisContext, None)  # 解析不读上下文字段
        summary, plays, risks = llm._parse_analysis(_STUB_LLM_CONTENT, context)
        assert "主队" in summary
        assert [p.play_code for p in plays] == ["HAD", "TTG"]
        assert plays[0].recommendation == "主胜"
        assert plays[0].confidence == pytest.approx(0.6)
        assert risks == ["客队近期状态回暖", "盘口存在异动"]

    def test_unknown_play_code_is_filtered(self) -> None:
        context = typing.cast(llm.MatchAnalysisContext, None)
        _, plays, _ = llm._parse_analysis(_STUB_LLM_CONTENT, context)
        assert all(p.play_code in llm.PLAY_NAMES for p in plays)

    def test_raises_on_plain_text_output(self) -> None:
        context = typing.cast(llm.MatchAnalysisContext, None)
        with pytest.raises(LlmServiceError):
            llm._parse_analysis("抱歉,我无法完成该分析。", context)

    def test_raises_when_no_valid_plays(self) -> None:
        context = typing.cast(llm.MatchAnalysisContext, None)
        with pytest.raises(LlmServiceError):
            llm._parse_analysis('{"summary": "ok", "plays": []}', context)


# ---------- 接口 ----------


class TestLlmAnalysisEndpoint:
    """POST /api/v1/match/games/{match_id}/llm-analysis 测试。"""

    async def test_returns_analysis_with_plays(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-analysis")
        assert response.status_code == 200
        body = response.json()
        assert body["match_id"] == match_id
        assert body["analysis_id"] > 0
        assert body["created_at"]
        assert body["provider"] in ("qwen", "ark")
        assert len(body["plays"]) == 2
        had = next(p for p in body["plays"] if p["play_code"] == "HAD")
        assert had["recommendation"] == "主胜"
        assert 0.0 <= had["confidence"] <= 1.0
        assert body["risks"]

    async def test_post_persists_analysis_rows(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-analysis")
        analysis_id = response.json()["analysis_id"]

        async with session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(MatchLlmAnalysis).where(MatchLlmAnalysis.match_id == match_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].analysis_id == analysis_id
            assert rows[0].summary
            recs = list(
                (
                    await session.execute(
                        select(MatchLlmPlayRec).where(MatchLlmPlayRec.analysis_id == analysis_id)
                    )
                )
                .scalars()
                .all()
            )
            assert {r.play_code for r in recs} == {"HAD", "TTG"}
            assert all(0.0 <= float(r.confidence) <= 1.0 for r in recs)

    async def test_get_latest_returns_most_recent(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)

        # 未生成过 -> 404
        empty = await client.get(f"/api/v1/match/games/{match_id}/llm-analysis")
        assert empty.status_code == 404

        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        first = (await client.post(f"/api/v1/match/games/{match_id}/llm-analysis")).json()
        second = (await client.post(f"/api/v1/match/games/{match_id}/llm-analysis")).json()

        latest = await client.get(f"/api/v1/match/games/{match_id}/llm-analysis")
        assert latest.status_code == 200
        assert latest.json()["analysis_id"] == second["analysis_id"] > first["analysis_id"]

    async def test_list_returns_history_desc(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        ids = [
            (await client.post(f"/api/v1/match/games/{match_id}/llm-analysis")).json()["analysis_id"]
            for _ in range(3)
        ]

        response = await client.get(f"/api/v1/match/games/{match_id}/llm-analyses")
        assert response.status_code == 200
        body = response.json()
        assert [a["analysis_id"] for a in body] == sorted(ids, reverse=True)
        assert all(a["plays"] for a in body)

    async def test_returns_404_for_unknown_match(
        self, env: tuple[AsyncClient, async_sessionmaker], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, _ = env
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        response = await client.post("/api/v1/match/games/unknown/llm-analysis")
        assert response.status_code == 404

    async def test_returns_503_when_api_key_missing(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        empty_key_settings = Settings(LLM_PROVIDER="qwen", LLM_QWEN_API_KEY="")
        monkeypatch.setattr(llm, "get_settings", lambda: empty_key_settings)

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-analysis")
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
        ) -> str:
            raise LlmServiceError("大模型服务调用失败(网络错误)")

        monkeypatch.setattr(llm, "_call_chat", failing_call)
        response = await client.post(f"/api/v1/match/games/{match_id}/llm-analysis")
        assert response.status_code == 502
