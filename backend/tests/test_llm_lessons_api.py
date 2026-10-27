"""大模型复盘经验总结模块测试(/api/v1/match/llm-lesson-summaries)。

SQLite 内存库 + FastAPI 依赖覆盖,覆盖:
- POST 生成:无复盘 422;成功落库(总结/经验/输入统计/log_id 关联);
- 每场只取最近一次复盘(重新生成过复盘的场次不重复计);
- GET 列表:历史倒序;
- GET 请求日志:回读该次总结的输入(提示词)与输出(analysis_type=lesson_summary);
- 综合分析提示词注入:有总结时含【历史复盘经验总结】段,无总结时不含;
- 解析层:经验条数超上限截断。

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
    MatchLlmRetrospect,
    Team,
)
from app.services import llm, llm_lessons

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

BASE_TIME = datetime.datetime(2026, 10, 1, 21, 0)

LIST_URL = "/api/v1/match/llm-lesson-summaries"
POST_URL = LIST_URL

# 模拟大模型的标准经验总结输出(3 条经验,不超上限)
_STUB_LLM_CONTENT = (
    "```json\n"
    "{\n"
    '  "summary": "输入复盘整体命中 3/5,共性偏差集中在比分与总进球玩法的高估。",\n'
    '  "lessons": [\n'
    '    "盘口深让时,总进球玩法应结合双方攻防强度派生分布而非取均值",\n'
    '    "客队客场失球率高的对阵,比分倾向 2:0/2:1 区间",\n'
    '    "样本量不足时,各玩法置信度应整体下修"\n'
    "  ]\n"
    "}\n"
    "```"
)


@pytest.fixture
async def env(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    """返回测试客户端与会话工厂(会话用于预置联赛/球队/比赛/复盘)。"""
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


async def _seed_retrospects(session_factory: async_sessionmaker) -> None:
    """预置两场比赛及各一场复盘(m-ls-001 命中 2/3,m-ls-002 命中 1/2)。

    复盘只做经验总结的输入,无需比对明细;每场附带一条最小综合分析
    以满足复盘表 analysis_id 外键。
    """
    async with session_factory() as session:
        league = League(
            league_name="英格兰超级联赛", country="英格兰", tier=1, season="2026-2027"
        )
        session.add(league)
        await session.flush()
        teams = {
            name: Team(team_name=name, league_id=league.league_id)
            for name in ("阿森纳", "埃弗顿", "切尔西", "西汉姆")
        }
        session.add_all(teams.values())
        await session.flush()
        for index, (home, away, hit, total, lessons) in enumerate(
            [
                ("阿森纳", "埃弗顿", 2, 3, ["比分玩法应结合攻防强度派生分布", "主客场分化明显时让球须压低置信度"]),
                ("切尔西", "西汉姆", 1, 2, ["强弱分明的对阵总进球倾向 3 球以上"]),
            ],
            start=1,
        ):
            match_id = f"m-ls-{index:03d}"
            session.add(
                MatchGame(
                    match_id=match_id,
                    match_num_str=f"周四{index:03d}",
                    league_id=league.league_id,
                    home_team_id=teams[home].team_id,
                    away_team_id=teams[away].team_id,
                    match_time=BASE_TIME - datetime.timedelta(days=index),
                    match_status="FINISHED",
                )
            )
            analysis = MatchLlmAnalysis(
                match_id=match_id,
                provider="qwen",
                model="qwen-max",
                summary="赛前综合研判。",
                risks=[],
                created_at=BASE_TIME - datetime.timedelta(days=index + 1),
            )
            session.add(analysis)
            await session.flush()
            session.add(
                MatchLlmRetrospect(
                    match_id=match_id,
                    analysis_id=analysis.analysis_id,
                    provider="qwen",
                    model="qwen-max",
                    summary=f"{home} vs {away} 的复盘总结。",
                    lessons=lessons,
                    hit_count=hit,
                    total_count=total,
                    created_at=BASE_TIME + datetime.timedelta(hours=index),
                )
            )
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
            prompt_tokens=500,
            completion_tokens=150,
            total_tokens=650,
            duration_ms=678,
        )

    return fake_call


class TestGenerateLessonSummary:
    """POST /api/v1/match/llm-lesson-summaries 测试。"""

    async def test_rejects_when_no_retrospects(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange:空库,无任何复盘
        client, _ = env
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        # Act
        response = await client.post(POST_URL)

        # Assert
        assert response.status_code == 422
        assert "尚无已生成的 AI 复盘" in response.json()["error"]["message"]

    async def test_generates_and_persists_summary(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange
        client, session_factory = env
        await _seed_retrospects(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        # Act
        response = await client.post(POST_URL)

        # Assert:总结落库,输入统计为两场复盘的聚合
        assert response.status_code == 200
        body = response.json()
        assert body["summary_id"] > 0
        assert body["provider"] == settings.LLM_PROVIDER.strip().lower()
        assert "共性偏差" in body["summary"]
        assert len(body["lessons"]) == 3
        assert "盘口深让" in body["lessons"][0]
        assert body["retrospect_count"] == 2
        assert body["total_hit"] == 3  # 2 + 1
        assert body["total_decided"] == 5  # 3 + 2
        assert body["log_id"] is not None

    async def test_takes_latest_retrospect_per_match(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange:m-ls-001 再生成一次复盘(命中 0/1),应只计最新一次
        client, session_factory = env
        await _seed_retrospects(session_factory)
        async with session_factory() as session:
            analysis_id = (
                await session.execute(
                    select(MatchLlmAnalysis.analysis_id).where(
                        MatchLlmAnalysis.match_id == "m-ls-001"
                    )
                )
            ).scalar_one()
            session.add(
                MatchLlmRetrospect(
                    match_id="m-ls-001",
                    analysis_id=analysis_id,
                    provider="qwen",
                    model="qwen-max",
                    summary="重新复盘后的总结。",
                    lessons=["重新复盘的经验"],
                    hit_count=0,
                    total_count=1,
                    created_at=BASE_TIME + datetime.timedelta(days=1),
                )
            )
            await session.commit()
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        # Act
        response = await client.post(POST_URL)

        # Assert:场次数仍为 2,命中统计取各场最新复盘(0/1 + 1/2)
        assert response.status_code == 200
        body = response.json()
        assert body["retrospect_count"] == 2
        assert body["total_hit"] == 1
        assert body["total_decided"] == 3

    async def test_list_returns_history_newest_first(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange:连续生成两次
        client, _ = env
        await _seed_retrospects(env[1])
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        first = (await client.post(POST_URL)).json()
        second = (await client.post(POST_URL)).json()

        # Act
        response = await client.get(LIST_URL)

        # Assert:倒序,最新在前
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 2
        assert rows[0]["summary_id"] == second["summary_id"]
        assert rows[1]["summary_id"] == first["summary_id"]
        assert rows[0]["retrospect_count"] == 2

    async def test_request_log_endpoint_returns_input_output(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange:生成一次总结
        client, session_factory = env
        await _seed_retrospects(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        generated = (await client.post(POST_URL)).json()

        # Act
        response = await client.get(f"{LIST_URL}/{generated['summary_id']}/request-log")

        # Assert:回读该次总结的完整输入输出
        assert response.status_code == 200
        log = response.json()
        assert log["log_id"] == generated["log_id"]
        assert log["status"] == "SUCCESS"
        assert log["request_params"]["analysis_type"] == "lesson_summary"
        assert log["request_messages"][0]["role"] == "system"
        assert "不得把偶发结果总结为规律" in log["request_messages"][0]["content"]
        user_content = log["request_messages"][1]["content"]
        assert "复盘样本(2 场" in user_content
        assert "阿森纳 vs 埃弗顿" in user_content
        assert "盘口深让" in log["response_content"]
        # 日志行的 match_id 为经验总结专用标识(非比赛 ID)
        async with session_factory() as session:
            log_row = await session.get(LlmRequestLog, generated["log_id"])
            assert log_row is not None
            assert log_row.match_id == llm_lessons.LOG_MATCH_ID

    async def test_request_log_404_for_unknown_summary(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange / Act
        client, _ = env
        response = await client.get(f"{LIST_URL}/999/request-log")

        # Assert
        assert response.status_code == 404

    async def test_request_log_404_when_log_missing(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange:日志写入失败(返回 None),总结正常落库
        client, session_factory = env
        await _seed_retrospects(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())

        async def fake_write_log(**_kwargs: object) -> None:
            return None

        monkeypatch.setattr(llm, "_write_request_log", fake_write_log)
        generated = (await client.post(POST_URL)).json()
        assert generated["log_id"] is None

        # Act
        response = await client.get(f"{LIST_URL}/{generated['summary_id']}/request-log")

        # Assert:无关联日志时 404
        assert response.status_code == 404


class TestLessonInjection:
    """经验总结注入综合分析提示词的服务层测试。"""

    async def test_analysis_messages_include_latest_lessons(
        self,
        env: tuple[AsyncClient, async_sessionmaker],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange:先生成一次经验总结
        client, session_factory = env
        await _seed_retrospects(session_factory)
        monkeypatch.setattr(llm, "_call_chat", _stub_chat())
        assert (await client.post(POST_URL)).status_code == 200

        # Act:构造综合分析上下文与提示词
        async with session_factory() as session:
            context = await llm.build_match_analysis_context(session, "m-ls-001")
        messages = llm.build_analysis_messages(context)

        # Assert:user 段含经验总结段与条目,system 段含校准参考规则
        user_content = messages[1]["content"]
        assert "【历史复盘经验总结(基于既往复盘归纳,供分析方法参考)】" in user_content
        assert "1. 盘口深让" in user_content
        system_content = messages[0]["content"]
        assert "历史复盘经验总结" in system_content
        assert "不得机械套用历史经验" in system_content

    async def test_analysis_messages_exclude_lessons_when_absent(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:预置比赛但从未生成经验总结
        _, session_factory = env
        await _seed_retrospects(session_factory)

        # Act
        async with session_factory() as session:
            context = await llm.build_match_analysis_context(session, "m-ls-001")
        messages = llm.build_analysis_messages(context)

        # Assert:提示词不含经验总结段
        assert "【历史复盘经验总结" not in messages[1]["content"]


class TestParseLessonSummary:
    """_parse_lesson_summary 解析层测试。"""

    def test_truncates_lessons_over_limit(self) -> None:
        # Arrange:12 条经验,上限 10
        content = (
            '{"summary": "总结", "lessons": ['
            + ",".join(f'"经验{i}"' for i in range(1, 13))
            + "]}"
        )

        # Act
        _, lessons = llm_lessons._parse_lesson_summary(content)

        # Assert
        assert lessons == [f"经验{i}" for i in range(1, 11)]

    def test_rejects_empty_lessons(self) -> None:
        # Arrange / Act / Assert:无有效经验条目时报错
        with pytest.raises(llm.LlmServiceError):
            llm_lessons._parse_lesson_summary('{"summary": "总结", "lessons": []}')
