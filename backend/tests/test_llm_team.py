"""大模型球队维度分析模块测试。

覆盖三个层次:
1. 上下文聚合与提示词构造:积分榜三维拆分 / 近期赛果 / 后续赛程 / Elo 必须进入提示词;
2. 输出解析:维度过滤 / 非法 rating 归一 / 缺失维度补位 / 非法输出的鲁棒处理;
3. 接口 POST /api/v1/base/teams/{id}/llm-analysis:成功落库 + 日志(match_id=team:{id})/
   未生成 404 / 球队不存在 404 / 服务故障 502 且日志 FAILED / 解析失败日志保留原文。

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
    Team,
    TeamFundamentals,
    TeamLlmAnalysis,
    TeamLlmAnalysisDim,
    TeamMatch,
    TeamProfile,
    TeamRating,
)
from app.services import llm, llm_team

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# 模拟大模型的标准输出:6 个维度中给出 4 个有效 + 1 个非法编码 + 缺 RECENT_FORM/OTHER,
# 且 DEFENSE 的 rating 为非法值(应归一为 average)
_STUB_LLM_CONTENT = (
    "好的,以下是球队维度分析:\n"
    "```json\n"
    "{\n"
    '  "summary": "该队进攻火力突出且主场强势,整体处于联赛上游。",\n'
    '  "dimensions": [\n'
    '    {"code": "ATTACK", "title": "进攻能力", "rating": "strong", "content": "场均进球2.4,火力联赛前列"},\n'
    '    {"code": "DEFENSE", "title": "防守能力", "rating": "SIDE", "content": "场均失球1.1,防线中规中矩"},\n'
    '    {"code": "HOME_FORM", "title": "主场表现", "rating": "strong", "content": "主场4胜1平保持不败"},\n'
    '    {"code": "AWAY_FORM", "title": "客场表现", "rating": "weak", "content": "客场两连败且一球未进"},\n'
    '    {"code": "FAKE_CODE", "title": "无效维度", "rating": "strong", "content": "应被过滤"}\n'
    "  ],\n"
    '  "risks": ["客场状态波动", "后续赛程密集"]\n'
    "}\n"
    "```\n"
    "以上仅供参考。"
)


@pytest.fixture
async def env(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    """返回测试客户端与会话工厂(会话用于预置联赛/球队/档案/赛程/评分)。"""
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


async def _seed_team(session_factory: async_sessionmaker) -> int:
    """预置一支带完整档案数据的球队,返回 team_id。

    含档案 + 积分榜基本面 + 3 场近期已赛 + 1 场后续赛程 + Elo 评分。
    """
    async with session_factory() as session:
        league = League(league_name="英格兰超级联赛", country="英格兰", tier=1, season="2026-2027")
        session.add(league)
        await session.flush()
        team = Team(team_name="阿森纳", league_id=league.league_id)
        session.add(team)
        await session.flush()

        session.add(
            TeamFundamentals(
                team_id=team.team_id,
                season="2026-2027",
                ranking=2,
                played=6,
                wins=4,
                draws=1,
                losses=1,
                goals_for=15,
                goals_against=6,
                goal_diff=9,
                points=13,
                win_rate=66.7,
                home_wins=3,
                away_wins=1,
            )
        )
        session.add(
            TeamProfile(
                team_id=team.team_id,
                uniform_team_id=9001,
                abbrev_name="阿森纳",
                full_name="阿森纳足球俱乐部",
                country_name="英格兰",
            )
        )
        session.add(
            TeamRating(
                team_id=team.team_id,
                rating=1523.5,
                matches_played=6,
                last_match_time=datetime.datetime(2026, 9, 8, 21, 0),
            )
        )

        # 近期已赛 3 场(时间倒序最后一轮最近)
        for idx, (day, hs, as_, result) in enumerate(
            [(1, 3, 0, "W"), (5, 1, 1, "D"), (8, 0, 2, "L")]
        ):
            session.add(
                TeamMatch(
                    team_id=team.team_id,
                    uniform_match_id=1000 + idx,
                    league_name="英超",
                    gameweek=str(6 - idx),
                    match_time=datetime.datetime(2026, 9, day, 21, 0),
                    home_team_name="阿森纳",
                    away_team_name="对手队",
                    is_home=True,
                    full_home_score=hs,
                    full_away_score=as_,
                    team_result=result,
                )
            )
        # 后续赛程(未开赛,晚于当前时间)
        session.add(
            TeamMatch(
                team_id=team.team_id,
                uniform_match_id=2000,
                league_name="欧冠",
                match_time=datetime.datetime(2026, 10, 15, 21, 0),
                home_team_name="对手队",
                away_team_name="阿森纳",
                is_home=False,
                full_home_score=None,
                full_away_score=None,
                team_result=None,
            )
        )
        await session.commit()
    return team.team_id


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
            prompt_tokens=180,
            completion_tokens=90,
            total_tokens=270,
            duration_ms=432,
        )

    return fake_call


# ---------- 提示词构造 ----------


class TestBuildTeamMessages:
    """build_team_messages:上下文完整性测试。"""

    def _context(self) -> llm_team.TeamAnalysisContext:
        return llm_team.TeamAnalysisContext(
            team_id=1,
            team_name="阿森纳",
            league_name="英格兰超级联赛",
            season="2026-2027",
            profile=None,
            fundamentals=None,
            recent=(),
            upcoming=(),
            elo=None,
        )

    def test_messages_contain_team_and_dimension_spec(self) -> None:
        messages = llm_team.build_team_messages(self._context())
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        system_text = messages[0]["content"]
        assert "只输出一个 JSON 对象" in system_text
        for title in llm_team.DIMENSION_TITLES.values():
            assert title in system_text
        assert '"rating"' in system_text
        assert "strong=强" in system_text

    def test_missing_data_sections_are_flagged(self) -> None:
        user_text = llm_team.build_team_messages(self._context())[1]["content"]
        assert "未同步球队档案" in user_text
        assert "未同步基本面数据" in user_text
        assert "近期赛程赛果未同步" in user_text
        assert "暂无后续赛程数据" in user_text
        assert "Elo 评分未重算" in user_text


# ---------- 输出解析 ----------


class TestParseTeam:
    """_parse_team:模型输出鲁棒解析测试。"""

    def test_parses_fenced_json_with_noise(self) -> None:
        summary, dimensions, risks = llm_team._parse_team(_STUB_LLM_CONTENT)
        assert "进攻" in summary
        assert risks == ["客场状态波动", "后续赛程密集"]

    def test_dimensions_fixed_order_and_completion(self) -> None:
        _, dimensions, _ = llm_team._parse_team(_STUB_LLM_CONTENT)
        assert [d.code for d in dimensions] == list(
            llm_team.DIMENSION_TITLES.keys()
        )
        # 缺失的 RECENT_FORM / OTHER 维度被补位,非法 FAKE_CODE 被过滤
        recent = next(d for d in dimensions if d.code == "RECENT_FORM")
        assert recent.rating == "average"
        assert "未给出" in recent.content

    def test_invalid_rating_normalized_to_average(self) -> None:
        _, dimensions, _ = llm_team._parse_team(_STUB_LLM_CONTENT)
        defense = next(d for d in dimensions if d.code == "DEFENSE")
        assert defense.rating == "average"

    def test_valid_ratings_preserved(self) -> None:
        _, dimensions, _ = llm_team._parse_team(_STUB_LLM_CONTENT)
        by_code = {d.code: d for d in dimensions}
        assert by_code["ATTACK"].rating == "strong"
        assert by_code["AWAY_FORM"].rating == "weak"

    def test_raises_on_plain_text_output(self) -> None:
        with pytest.raises(LlmServiceError):
            llm_team._parse_team("抱歉,我无法完成该分析。")

    def test_raises_when_no_valid_dimensions(self) -> None:
        with pytest.raises(LlmServiceError):
            llm_team._parse_team('{"summary": "ok", "dimensions": []}')


# ---------- 上下文聚合 ----------


class TestBuildTeamContext:
    """build_team_context:球队数据聚合测试。"""

    async def test_aggregates_team_data(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        team_id = await _seed_team(session_factory)
        async with session_factory() as session:
            context = await llm_team.build_team_context(session, team_id)
        assert context.team_id == team_id
        assert context.team_name == "阿森纳"
        assert context.league_name == "英格兰超级联赛"
        assert context.profile is not None
        assert context.fundamentals is not None
        assert context.elo is not None
        assert len(context.recent) == 3
        assert len(context.upcoming) == 1

        messages = llm_team.build_team_messages(context)
        user_text = messages[1]["content"]
        # 积分榜三维拆分 / 近期赛果 / 后续赛程 / Elo 注入提示词
        assert "总战绩:排名 2,6 赛 4 胜 1 平 1 负" in user_text
        assert "主场战绩" in user_text
        assert "客场战绩" in user_text
        assert "2026-09-08 英超(4) 主场 0:2 vs 对手队" in user_text
        assert "2026-10-15 欧冠 客场 vs 对手队(未开赛)" in user_text
        assert "当前评分 1524,参与评分 6 场" in user_text
        assert "全称 阿森纳足球俱乐部" in user_text

    async def test_raises_404_for_unknown_team(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        async with session_factory() as session:
            with pytest.raises(Exception):
                await llm_team.build_team_context(session, 99999)


# ---------- 接口 ----------


class TestLlmTeamEndpoint:
    """POST/GET /api/v1/base/teams/{team_id}/llm-analysis 测试。"""

    async def test_returns_dimensions_and_summary(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        team_id = await _seed_team(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/base/teams/{team_id}/llm-analysis")
        assert response.status_code == 200
        body = response.json()
        assert body["team_id"] == team_id
        assert body["analysis_id"] > 0
        assert body["created_at"]
        assert body["provider"] in ("qwen", "ark")
        assert body["model"]
        assert "进攻" in body["summary"]
        assert [d["code"] for d in body["dimensions"]] == [
            "ATTACK", "DEFENSE", "HOME_FORM", "AWAY_FORM", "RECENT_FORM", "OTHER"
        ]
        assert body["risks"]

    async def test_post_persists_analysis_rows(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        team_id = await _seed_team(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/base/teams/{team_id}/llm-analysis")
        analysis_id = response.json()["analysis_id"]

        async with session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(TeamLlmAnalysis).where(
                            TeamLlmAnalysis.team_id == team_id
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
                        select(TeamLlmAnalysisDim).where(
                            TeamLlmAnalysisDim.analysis_id == analysis_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            # 六维度各一条,按固定顺序写入
            assert [d.code for d in dims] == list(
                llm_team.DIMENSION_TITLES.keys()
            )
            defense = next(d for d in dims if d.code == "DEFENSE")
            assert defense.rating == "average"  # 非法 rating 已在解析层归一
            recent = next(d for d in dims if d.code == "RECENT_FORM")
            assert "未给出" in recent.content  # 缺失维度补位落库

    async def test_get_latest_returns_most_recent(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        team_id = await _seed_team(session_factory)

        # 未生成过 -> 404
        empty = await client.get(f"/api/v1/base/teams/{team_id}/llm-analysis")
        assert empty.status_code == 404

        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        first = (
            await client.post(f"/api/v1/base/teams/{team_id}/llm-analysis")
        ).json()
        second = (
            await client.post(f"/api/v1/base/teams/{team_id}/llm-analysis")
        ).json()

        latest = await client.get(f"/api/v1/base/teams/{team_id}/llm-analysis")
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
        team_id = await _seed_team(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        ids = [
            (
                await client.post(f"/api/v1/base/teams/{team_id}/llm-analysis")
            ).json()["analysis_id"]
            for _ in range(3)
        ]

        response = await client.get(f"/api/v1/base/teams/{team_id}/llm-analyses")
        assert response.status_code == 200
        body = response.json()
        assert [a["analysis_id"] for a in body] == sorted(ids, reverse=True)
        assert all(a["dimensions"] for a in body)

    async def test_post_writes_success_request_log(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        team_id = await _seed_team(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        response = await client.post(f"/api/v1/base/teams/{team_id}/llm-analysis")
        assert response.status_code == 200

        async with session_factory() as session:
            logs = list((await session.execute(select(LlmRequestLog))).scalars().all())
            assert len(logs) == 1
            log = logs[0]
            assert log.status == "SUCCESS"
            # 球队分析以 "team:{team_id}" 标识写入日志,与比赛类分析区分
            assert log.match_id == f"team:{team_id}"
            assert log.http_status == 200
            assert log.prompt_tokens == 180
            assert log.duration_ms == 432
            assert log.error_message is None
            # 球队上下文进入日志留存
            assert any("阿森纳" in m["content"] for m in log.request_messages)
            assert "赛季基本面" in log.request_messages[1]["content"]
            assert log.request_params["max_tokens"] > 0
            assert log.request_params["analysis_type"] == "team"
            assert "ATTACK" in (log.response_content or "")

    async def test_returns_404_for_unknown_team(
        self, env: tuple[AsyncClient, async_sessionmaker], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, _ = env
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        response = await client.post("/api/v1/base/teams/99999/llm-analysis")
        assert response.status_code == 404

    async def test_returns_503_when_api_key_missing(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        team_id = await _seed_team(session_factory)
        empty_key_settings = Settings(LLM_PROVIDER="qwen", LLM_QWEN_API_KEY="")
        monkeypatch.setattr(llm_team, "get_settings", lambda: empty_key_settings)

        response = await client.post(f"/api/v1/base/teams/{team_id}/llm-analysis")
        assert response.status_code == 503
        assert "LLM_QWEN_API_KEY" in response.json()["error"]["message"]

    async def test_returns_502_when_provider_fails(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        team_id = await _seed_team(session_factory)

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
        response = await client.post(f"/api/v1/base/teams/{team_id}/llm-analysis")
        assert response.status_code == 502

        async with session_factory() as session:
            logs = list((await session.execute(select(LlmRequestLog))).scalars().all())
            assert len(logs) == 1
            assert logs[0].status == "FAILED"
            assert logs[0].http_status == 500
            assert logs[0].match_id == f"team:{team_id}"

    async def test_parse_failure_writes_log_with_response(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, session_factory = env
        team_id = await _seed_team(session_factory)
        monkeypatch.setattr(
            llm, "_call_chat", _stub_chat(content="抱歉,我无法完成该分析。")
        )

        response = await client.post(f"/api/v1/base/teams/{team_id}/llm-analysis")
        assert response.status_code == 502

        async with session_factory() as session:
            logs = list((await session.execute(select(LlmRequestLog))).scalars().all())
            assert len(logs) == 1
            log = logs[0]
            assert log.status == "FAILED"
            # 调用成功但输出无法解析:响应原文保留,便于排障
            assert log.response_content == "抱歉,我无法完成该分析。"
            assert log.error_message is not None

            # 解析失败时结果表不落库
            rows = list(
                (
                    await session.execute(
                        select(TeamLlmAnalysis).where(
                            TeamLlmAnalysis.team_id == team_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert rows == []
