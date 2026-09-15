"""大模型基本面分析模块测试。

覆盖三个层次:
1. 上下文聚合与提示词构造:近期战绩 / 主客场 / 攻防 / 战意 / 历史交锋必须进入提示词;
2. 输出解析:维度过滤 / 非法 edge 归一 / 缺失维度补位 / 非法输出的鲁棒处理;
3. 接口 POST /api/v1/match/games/{id}/llm-fundamentals:成功 / 未配置 / 比赛不存在 / 服务故障 / 日志落库。

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
    LlmRequestLog,
    MatchGame,
    MatchLlmAnalysis,
    MatchLlmFundAnalysis,
    MatchLlmFundDim,
    MatchStatus,
    Team,
    TeamFundamentals,
    TeamMatch,
    TeamProfile,
)
from app.services import llm, llm_fundamental

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# 模拟大模型的标准输出:6 个维度中给出 4 个有效 + 1 个非法编码 + 缺 H2H,
# 且 ATTACK_DEFENSE 的 edge 为非法值(应归一为 even)
_STUB_LLM_CONTENT = (
    "好的,以下是基本面分析:\n"
    "```json\n"
    "{\n"
    '  "summary": "主队近期三连胜且主场强势,整体基本面占优。",\n'
    '  "dimensions": [\n'
    '    {"code": "RECENT_FORM", "title": "近期状态", "edge": "home", "content": "主队近3轮全胜"},\n'
    '    {"code": "HOME_AWAY", "title": "主客场表现", "edge": "home", "content": "主队主场胜率高"},\n'
    '    {"code": "ATTACK_DEFENSE", "title": "攻防效率", "edge": "SIDE", "content": "双方攻强守弱"},\n'
    '    {"code": "MOTIVATION", "title": "战意与动机", "edge": "away", "content": "客队保级压力大"},\n'
    '    {"code": "FAKE_CODE", "title": "无效维度", "edge": "home", "content": "应被过滤"}\n'
    "  ],\n"
    '  "risks": ["客队近期状态回暖", "主队周中有欧战消耗"]\n'
    "}\n"
    "```\n"
    "以上仅供参考。"
)


@pytest.fixture
async def env(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    """返回测试客户端与会话工厂(会话用于预置联赛/球队/比赛/档案/赛程)。"""
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


async def _seed_match(session_factory: async_sessionmaker) -> str:
    """预置一场带完整看板数据的比赛,返回 match_id。

    主队有档案 + 基本面 + 近期战绩 + 后续赛程 + 与客队的历史交锋;
    客队仅有档案(无基本面/近期战绩),用于验证数据缺失路径。
    """
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
            )
        )
        session.add(
            TeamProfile(team_id=home.team_id, uniform_team_id=9001, abbrev_name="巴萨")
        )
        session.add(
            TeamProfile(team_id=away.team_id, uniform_team_id=9002, abbrev_name="皇马")
        )

        game = MatchGame(
            match_id="m-fund-001",
            league_id=league.league_id,
            home_team_id=home.team_id,
            away_team_id=away.team_id,
            match_time=datetime.datetime(2026, 9, 15, 21, 0),
        )
        session.add(game)

        # 主队近期已赛:3 场(倒序最后一轮离比赛日最近)
        for idx, (day, hs, as_, result) in enumerate(
            [(1, 2, 0, "W"), (5, 1, 1, "D"), (8, 0, 2, "L")]
        ):
            session.add(
                TeamMatch(
                    team_id=home.team_id,
                    uniform_match_id=1000 + idx,
                    league_name="西甲",
                    gameweek=str(4 - idx),
                    match_time=datetime.datetime(2026, 9, day, 21, 0),
                    home_team_name="巴萨",
                    away_team_name="对手队",
                    is_home=True,
                    full_home_score=hs,
                    full_away_score=as_,
                    team_result=result,
                )
            )
        # 主队后续赛程(比赛日之后、未开赛)
        session.add(
            TeamMatch(
                team_id=home.team_id,
                uniform_match_id=2000,
                league_name="欧冠",
                match_time=datetime.datetime(2026, 9, 18, 21, 0),
                home_team_name="对手队",
                away_team_name="巴萨",
                is_home=False,
                full_home_score=None,
                full_away_score=None,
                team_result=None,
            )
        )
        # 历史交锋:主队视角与客队(uniform 9002)交手
        session.add(
            TeamMatch(
                team_id=home.team_id,
                uniform_match_id=3000,
                uniform_away_team_id=9002,
                league_name="西甲",
                match_time=datetime.datetime(2026, 3, 1, 21, 0),
                home_team_name="巴萨",
                away_team_name="皇马",
                is_home=True,
                full_home_score=3,
                full_away_score=1,
                half_home_score=1,
                half_away_score=0,
                team_result="W",
            )
        )
        await session.commit()
    return "m-fund-001"


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
            prompt_tokens=200,
            completion_tokens=80,
            total_tokens=280,
            duration_ms=456,
        )

    return fake_call


# ---------- 提示词构造 ----------


class TestBuildFundamentalMessages:
    """build_fundamental_messages:上下文完整性测试。"""

    def _context(self) -> llm_fundamental.FundamentalAnalysisContext:
        return llm_fundamental.FundamentalAnalysisContext(
            match_id="m-fund-001",
            league_name="西班牙甲级联赛",
            season="2026-2027",
            match_time=datetime.datetime(2026, 9, 15, 21, 0),
            match_status=MatchStatus.PENDING,
            home_team_name="巴塞罗那",
            away_team_name="皇家马德里",
            home_profile=None,
            away_profile=None,
            home_fundamentals=None,
            away_fundamentals=None,
            home_recent=(),
            away_recent=(),
            home_upcoming=(),
            away_upcoming=(),
            h2h=(),
        )

    def test_messages_contain_match_and_dimension_spec(self) -> None:
        messages = llm_fundamental.build_fundamental_messages(self._context())
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        system_text = messages[0]["content"]
        assert "只输出一个 JSON 对象" in system_text
        for title in llm_fundamental.DIMENSION_TITLES.values():
            assert title in system_text
        assert '"edge"' in system_text

    def test_missing_data_sections_are_flagged(self) -> None:
        user_text = llm_fundamental.build_fundamental_messages(self._context())[1]["content"]
        assert "未同步球队档案" in user_text
        assert "主队近期赛程赛果未同步" in user_text
        assert "客队近期赛程赛果未同步" in user_text
        assert "暂无双方交锋数据" in user_text


# ---------- 输出解析 ----------


class TestParseFundamental:
    """_parse_fundamental:模型输出鲁棒解析测试。"""

    def test_parses_fenced_json_with_noise(self) -> None:
        summary, dimensions, risks = llm_fundamental._parse_fundamental(_STUB_LLM_CONTENT)
        assert "主队" in summary
        assert risks == ["客队近期状态回暖", "主队周中有欧战消耗"]

    def test_dimensions_fixed_order_and_completion(self) -> None:
        _, dimensions, _ = llm_fundamental._parse_fundamental(_STUB_LLM_CONTENT)
        assert [d.code for d in dimensions] == list(
            llm_fundamental.DIMENSION_TITLES.keys()
        )
        # 缺失的 H2H / OTHER 维度被补位,非法 FAKE_CODE 被过滤
        h2h = next(d for d in dimensions if d.code == "H2H")
        assert h2h.edge == "even"
        assert "未给出" in h2h.content

    def test_invalid_edge_normalized_to_even(self) -> None:
        _, dimensions, _ = llm_fundamental._parse_fundamental(_STUB_LLM_CONTENT)
        attack = next(d for d in dimensions if d.code == "ATTACK_DEFENSE")
        assert attack.edge == "even"

    def test_valid_edges_preserved(self) -> None:
        _, dimensions, _ = llm_fundamental._parse_fundamental(_STUB_LLM_CONTENT)
        by_code = {d.code: d for d in dimensions}
        assert by_code["RECENT_FORM"].edge == "home"
        assert by_code["MOTIVATION"].edge == "away"

    def test_raises_on_plain_text_output(self) -> None:
        with pytest.raises(LlmServiceError):
            llm_fundamental._parse_fundamental("抱歉,我无法完成该分析。")

    def test_raises_when_no_valid_dimensions(self) -> None:
        with pytest.raises(LlmServiceError):
            llm_fundamental._parse_fundamental('{"summary": "ok", "dimensions": []}')


# ---------- 上下文聚合 ----------


class TestBuildFundamentalContext:
    """build_fundamental_context:看板数据聚合测试。"""

    async def test_aggregates_dashboard_data(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        match_id = await _seed_match(session_factory)
        async with session_factory() as session:
            context = await llm_fundamental.build_fundamental_context(session, match_id)
        assert context.match_id == match_id
        assert context.home_fundamentals is not None
        assert context.away_fundamentals is None  # 客队基本面未同步
        assert context.home_profile is not None
        assert len(context.home_recent) == 4  # 3 场近期 + 1 场历史交锋(同为已赛记录)
        assert len(context.home_upcoming) == 1
        assert len(context.h2h) == 1
        assert context.h2h[0].uniform_away_team_id == 9002

        messages = llm_fundamental.build_fundamental_messages(context)
        user_text = messages[1]["content"]
        # 近期战绩 / 后续赛程 / 交锋 / 档案数据注入提示词
        assert "2026-09-08 西甲(2) 主场 0:2 vs 对手队" in user_text
        assert "2026-09-18 欧冠 客场 vs 对手队(未开赛)" in user_text
        assert "2026-03-01 西甲 主场 3:1 vs 皇马,半场 1:0 -> 胜" in user_text
        assert "全称 巴萨" in user_text
        assert "客队近期赛程赛果未同步" in user_text

    async def test_raises_404_for_unknown_match(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        async with session_factory() as session:
            with pytest.raises(Exception):
                await llm_fundamental.build_fundamental_context(session, "unknown")


# ---------- 接口 ----------


class TestLlmFundamentalEndpoint:
    """POST /api/v1/match/games/{match_id}/llm-fundamentals 测试。"""

    async def test_returns_dimensions_and_summary(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-fundamentals")
        assert response.status_code == 200
        body = response.json()
        assert body["match_id"] == match_id
        assert body["analysis_id"] > 0
        assert body["created_at"]
        assert body["provider"] in ("qwen", "ark")
        assert body["model"]
        assert "主队" in body["summary"]
        assert [d["code"] for d in body["dimensions"]] == [
            "RECENT_FORM", "HOME_AWAY", "ATTACK_DEFENSE", "MOTIVATION", "H2H", "OTHER"
        ]
        assert body["risks"]

    async def test_post_persists_analysis_rows(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-fundamentals")
        analysis_id = response.json()["analysis_id"]

        async with session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(MatchLlmFundAnalysis).where(
                            MatchLlmFundAnalysis.match_id == match_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].analysis_id == analysis_id
            assert rows[0].summary
            dims = list(
                (
                    await session.execute(
                        select(MatchLlmFundDim).where(
                            MatchLlmFundDim.analysis_id == analysis_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            # 六维度各一条,按固定顺序写入
            assert [d.code for d in dims] == list(
                llm_fundamental.DIMENSION_TITLES.keys()
            )
            attack = next(d for d in dims if d.code == "ATTACK_DEFENSE")
            assert attack.edge == "even"  # 非法 edge 已在解析层归一
            h2h = next(d for d in dims if d.code == "H2H")
            assert "未给出" in h2h.content  # 缺失维度补位落库

    async def test_get_latest_returns_most_recent(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)

        # 未生成过 -> 404
        empty = await client.get(f"/api/v1/match/games/{match_id}/llm-fundamentals")
        assert empty.status_code == 404

        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        first = (
            await client.post(f"/api/v1/match/games/{match_id}/llm-fundamentals")
        ).json()
        second = (
            await client.post(f"/api/v1/match/games/{match_id}/llm-fundamentals")
        ).json()

        latest = await client.get(f"/api/v1/match/games/{match_id}/llm-fundamentals")
        assert latest.status_code == 200
        body = latest.json()
        assert body["analysis_id"] == second["analysis_id"] > first["analysis_id"]
        assert len(body["dimensions"]) == 6

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
                await client.post(f"/api/v1/match/games/{match_id}/llm-fundamentals")
            ).json()["analysis_id"]
            for _ in range(3)
        ]

        response = await client.get(f"/api/v1/match/games/{match_id}/llm-fund-analyses")
        assert response.status_code == 200
        body = response.json()
        assert [a["analysis_id"] for a in body] == sorted(ids, reverse=True)
        assert all(a["dimensions"] for a in body)

    async def test_post_does_not_touch_play_analysis_table(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-fundamentals")
        assert response.status_code == 200
        # 基本面分析与分玩法推荐各自落表,互不影响
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
            assert rows == []

    async def test_post_writes_success_request_log(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-fundamentals")
        assert response.status_code == 200

        async with session_factory() as session:
            logs = list((await session.execute(select(LlmRequestLog))).scalars().all())
            assert len(logs) == 1
            log = logs[0]
            assert log.status == "SUCCESS"
            assert log.match_id == match_id
            assert log.http_status == 200
            assert log.prompt_tokens == 200
            assert log.duration_ms == 456
            assert log.error_message is None
            # 基本面上下文进入日志留存
            assert any("巴塞罗那" in m["content"] for m in log.request_messages)
            assert "近期比赛" in log.request_messages[1]["content"]
            assert log.request_params["max_tokens"] > 0
            assert log.request_params["analysis_type"] == "fundamental"
            assert "RECENT_FORM" in (log.response_content or "")

    async def test_returns_404_for_unknown_match(
        self, env: tuple[AsyncClient, async_sessionmaker], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, _ = env
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        response = await client.post("/api/v1/match/games/unknown/llm-fundamentals")
        assert response.status_code == 404

    async def test_returns_503_when_api_key_missing(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        match_id = await _seed_match(session_factory)
        empty_key_settings = Settings(LLM_PROVIDER="qwen", LLM_QWEN_API_KEY="")
        monkeypatch.setattr(llm_fundamental, "get_settings", lambda: empty_key_settings)

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-fundamentals")
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
        response = await client.post(f"/api/v1/match/games/{match_id}/llm-fundamentals")
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

        response = await client.post(f"/api/v1/match/games/{match_id}/llm-fundamentals")
        assert response.status_code == 502

        async with session_factory() as session:
            logs = list((await session.execute(select(LlmRequestLog))).scalars().all())
            assert len(logs) == 1
            log = logs[0]
            assert log.status == "FAILED"
            # 调用成功但输出无法解析:响应原文保留,便于排障
            assert log.response_content == "抱歉,我无法完成该分析。"
            assert log.error_message is not None
