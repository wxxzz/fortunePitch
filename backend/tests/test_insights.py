"""赛事高阶数据派生计算服务与接口测试。

覆盖:
1. 近况:近 6 场手算比对(计数/场均进失球/结果串/状态标签);
2. 历史交锋:双向过滤 + uniform_match_id 去重 + 视角反转映射回本场视角;
3. 攻防强度:seed 使联赛均值 LGH=2.0 / LGA=1.0,手算 A/D/λ/μ;
4. 泊松:胜平负和 ≈ 1、大小球和 ≈ 1、Top 比分概率降序;
5. Elo 快照:落库评分读出与期望得分;
6. 数据缺口:全库无积分榜 -> strength/poisson 为 None,接口仍 200;
7. 近况样本 < 3 场时强度退化纯赛季值;
8. 接口:GET /match/games/{id}/insights 404 与字段组装。

注:均为模拟数据,测试不涉及真实资金。
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
    Team,
    TeamFundamentals,
    TeamMatch,
    TeamProfile,
    TeamRating,
)
from app.services import insights as insights_service

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

LEAGUE_NAME = "英格兰超级联赛"
HOME_NAME = "阿森纳"
AWAY_NAME = "切尔西"


# ---------- 环境与数据预置 ----------

@pytest.fixture
async def env(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    """返回测试客户端与会话工厂。"""
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


async def _seed_fixture(
    session_factory: async_sessionmaker,
    *,
    with_fundamentals: bool = True,
) -> tuple[str, int, int]:
    """预置联赛 + 主客队 + profiles + 一场比赛,返回 (match_id, home_id, away_id)。

    with_fundamentals=True 时预置积分榜:
    - 联赛 4 队 home_goals_for 合计 16 / home_played 合计 8 -> LGH=2.0;
    - away_goals_for 合计 8 / away_played 合计 8 -> LGA=1.0;
    - 主队 home 进球 6(速率 3.0)、失 2(速率 1.0);
      客队 away 进球 2(速率 1.0)、失 4(速率 2.0)。
    """
    async with session_factory() as session:
        league = League(league_name=LEAGUE_NAME, country="英格兰", tier=1, season="2026-2027")
        session.add(league)
        await session.flush()
        home = Team(team_name=HOME_NAME, league_id=league.league_id)
        away = Team(team_name=AWAY_NAME, league_id=league.league_id)
        extra1 = Team(team_name="曼联", league_id=league.league_id)
        extra2 = Team(team_name="热刺", league_id=league.league_id)
        session.add_all([home, away, extra1, extra2])
        await session.flush()
        session.add_all(
            [
                TeamProfile(team_id=home.team_id, uniform_team_id=9001, abbrev_name=HOME_NAME),
                TeamProfile(team_id=away.team_id, uniform_team_id=9002, abbrev_name=AWAY_NAME),
            ]
        )
        game = MatchGame(
            match_id="m-ins",
            match_num_str="周六001",
            league_id=league.league_id,
            home_team_id=home.team_id,
            away_team_id=away.team_id,
            match_time=datetime.datetime(2026, 9, 26, 22, 0),
            business_date=datetime.date(2026, 9, 26),
        )
        session.add(game)
        if with_fundamentals:
            session.add_all(
                [
                    TeamFundamentals(
                        team_id=home.team_id,
                        season="2026-2027",
                        home_played=2, home_goals_for=6, home_goals_against=2,
                        away_played=2, away_goals_for=2, away_goals_against=4,
                    ),
                    TeamFundamentals(
                        team_id=away.team_id,
                        season="2026-2027",
                        home_played=2, home_goals_for=4, home_goals_against=3,
                        away_played=2, away_goals_for=2, away_goals_against=4,
                    ),
                    TeamFundamentals(
                        team_id=extra1.team_id,
                        season="2026-2027",
                        home_played=2, home_goals_for=4, home_goals_against=2,
                        away_played=2, away_goals_for=2, away_goals_against=4,
                    ),
                    TeamFundamentals(
                        team_id=extra2.team_id,
                        season="2026-2027",
                        home_played=2, home_goals_for=2, home_goals_against=2,
                        away_played=2, away_goals_for=2, away_goals_against=4,
                    ),
                ]
            )
        await session.commit()
        return game.match_id, home.team_id, away.team_id


def _row(
    team_id: int,
    uniform_match_id: int,
    *,
    is_home: bool,
    home_team_name: str,
    away_team_name: str,
    uniform_home: int | None,
    uniform_away: int | None,
    home_goals: int,
    away_goals: int,
    match_time: datetime.datetime,
) -> TeamMatch:
    """构造一条已完赛看板行(自动推导看板队视角结果)。"""
    own = home_goals if is_home else away_goals
    opp = away_goals if is_home else home_goals
    result = "W" if own > opp else ("L" if own < opp else "D")
    return TeamMatch(
        team_id=team_id,
        uniform_match_id=uniform_match_id,
        match_time=match_time,
        home_team_name=home_team_name,
        away_team_name=away_team_name,
        uniform_home_team_id=uniform_home,
        uniform_away_team_id=uniform_away,
        is_home=is_home,
        full_home_score=home_goals,
        full_away_score=away_goals,
        team_result=result,
    )


# ---------- 服务层:近况 ----------

class TestTeamForm:

    async def test_form_hand_computed(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """主队近 6 场 4胜1平1负,进 11 失 7 -> 场均 1.83 / 1.17,连胜 2 场。"""
        _, session_factory = env
        match_id, home_id, _away_id = await _seed_fixture(session_factory)
        # (比分, 时间序号):时间越晚越新;结果串按时间倒序
        scores = [(3, 1), (2, 0), (1, 1), (0, 2), (2, 1), (3, 2)]
        async with session_factory() as session:
            for index, (home_goals, away_goals) in enumerate(scores):
                session.add(
                    _row(
                        home_id,
                        800 + index,
                        is_home=True,
                        home_team_name=HOME_NAME,
                        away_team_name=f"对手{index}队",
                        uniform_home=9001,
                        uniform_away=9100 + index,
                        home_goals=home_goals,
                        away_goals=away_goals,
                        match_time=datetime.datetime(2026, 8, 1 + index),
                    )
                )
            await session.commit()

            data = await insights_service.get_match_insights(session, match_id)
            form = data.home_form
            # 时间倒序:最新 8-06 胜 -> 8-04 负 -> 8-03 平 -> 8-01 胜
            assert form.results == "WWLDWW"
            assert (form.wins, form.draws, form.losses) == (4, 1, 1)
            assert form.goals_for_avg == pytest.approx(11 / 6, abs=0.01)
            assert form.goals_against_avg == pytest.approx(7 / 6, abs=0.01)
            assert form.streak_label == "连胜 2 场"
            assert len(form.entries) == 6
            assert form.entries[0].home_goals == 3
            assert form.entries[0].away_goals == 2
            assert form.entries[0].opponent_name == "对手5队"
            # 客队无看板数据
            assert data.away_form.results == ""
            assert data.away_form.streak_label == "无近期比赛"

    async def test_form_respects_limit(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """form_limit 截取样本次数。"""
        _, session_factory = env
        match_id, home_id, _away_id = await _seed_fixture(session_factory)
        async with session_factory() as session:
            for index in range(8):
                session.add(
                    _row(
                        home_id, 900 + index, is_home=True,
                        home_team_name=HOME_NAME, away_team_name=f"对手{index}队",
                        uniform_home=9001, uniform_away=9200 + index,
                        home_goals=1, away_goals=0,
                        match_time=datetime.datetime(2026, 8, 1 + index),
                    )
                )
            await session.commit()
            data = await insights_service.get_match_insights(
                session, match_id, form_limit=3
            )
            assert len(data.home_form.entries) == 3
            assert data.home_form.results == "WWW"


# ---------- 服务层:历史交锋 ----------

class TestH2H:

    async def test_h2h_dedup_and_perspective_mapping(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """3 次交锋(含视角反转行与双侧看板重复行)去重后计数正确。"""
        _, session_factory = env
        match_id, home_id, away_id = await _seed_fixture(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    # 交锋1:主队看板,阿森纳 2:1 切尔西 -> 本场主队胜
                    _row(
                        home_id, 701, is_home=True, home_team_name=HOME_NAME,
                        away_team_name=AWAY_NAME, uniform_home=9001,
                        uniform_away=9002, home_goals=2, away_goals=1,
                        match_time=datetime.datetime(2026, 5, 1),
                    ),
                    # 交锋2:客队看板且客队曾为主场(视角反转),切尔西 1:1 阿森纳
                    _row(
                        away_id, 702, is_home=True, home_team_name=AWAY_NAME,
                        away_team_name=HOME_NAME, uniform_home=9002,
                        uniform_away=9001, home_goals=1, away_goals=1,
                        match_time=datetime.datetime(2026, 3, 1),
                    ),
                    # 交锋3:双侧看板各一行(同 uniform_match_id,去重),阿森纳 0:2 切尔西
                    _row(
                        home_id, 703, is_home=True, home_team_name=HOME_NAME,
                        away_team_name=AWAY_NAME, uniform_home=9001,
                        uniform_away=9002, home_goals=0, away_goals=2,
                        match_time=datetime.datetime(2026, 1, 1),
                    ),
                    _row(
                        away_id, 703, is_home=False, home_team_name=HOME_NAME,
                        away_team_name=AWAY_NAME, uniform_home=9001,
                        uniform_away=9002, home_goals=0, away_goals=2,
                        match_time=datetime.datetime(2026, 1, 1),
                    ),
                    # 干扰行:对手不是交锋对象,不应计入
                    _row(
                        home_id, 704, is_home=True, home_team_name=HOME_NAME,
                        away_team_name="曼城", uniform_home=9001,
                        uniform_away=9999, home_goals=1, away_goals=0,
                        match_time=datetime.datetime(2026, 6, 1),
                    ),
                ]
            )
            await session.commit()

            data = await insights_service.get_match_insights(session, match_id)
            h2h = data.h2h
            assert len(h2h.entries) == 3
            # 视角反转行(交锋2)按本场主队视角计平
            assert (h2h.home_wins, h2h.draws, h2h.away_wins) == (1, 1, 1)
            # 场均总进球 (3 + 2 + 2) / 3
            assert h2h.avg_total_goals == pytest.approx(7 / 3, abs=0.01)
            # 时间倒序:最新交锋 5 月在前
            assert h2h.entries[0].home_goals == 2
            assert h2h.entries[0].home_result == "W"
            # 视角反转行按行自身主队(切尔西)视角计平
            reversed_entry = h2h.entries[1]
            assert reversed_entry.home_team_name == AWAY_NAME
            assert reversed_entry.home_result == "D"

    async def test_h2h_name_variant_maps_exact_perspective(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """看板行队名与档案队名存在变体(如简称/译名差异)时,视角仍精确判定。

        视角由"行所属看板 team_id + is_home"推导,不依赖队名字符串匹配,
        否则该行(主队看板、主队为主、1:0 胜)会被错误计为客队胜。
        """
        _, session_factory = env
        match_id, home_id, _away_id = await _seed_fixture(session_factory)
        async with session_factory() as session:
            session.add(
                _row(
                    # 队名使用变体写法,与 Team 表的队名不一致
                    home_id, 711, is_home=True, home_team_name="阿仙奴",
                    away_team_name="车路士", uniform_home=9001,
                    uniform_away=9002, home_goals=1, away_goals=0,
                    match_time=datetime.datetime(2026, 5, 1),
                )
            )
            await session.commit()
            data = await insights_service.get_match_insights(session, match_id)
            h2h = data.h2h
            assert len(h2h.entries) == 1
            assert (h2h.home_wins, h2h.draws, h2h.away_wins) == (1, 0, 0)
            assert h2h.entries[0].home_result == "W"


# ---------- 服务层:攻防强度与泊松 ----------

class TestStrengthAndPoisson:

    async def test_strength_hand_computed(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """LGH=2.0 / LGA=1.0:主攻 1.5 主防 1.0,客攻 1.0 客防 1.0 -> λ=3.0 μ=1.0。"""
        _, session_factory = env
        match_id, _home_id, _away_id = await _seed_fixture(session_factory)
        async with session_factory() as session:
            data = await insights_service.get_match_insights(session, match_id)
            strength = data.strength
            assert strength.league_avg_home_goals == pytest.approx(2.0, abs=0.001)
            assert strength.league_avg_away_goals == pytest.approx(1.0, abs=0.001)
            assert strength.home_attack == pytest.approx(1.5, abs=0.001)
            assert strength.home_defense == pytest.approx(1.0, abs=0.001)
            assert strength.away_attack == pytest.approx(1.0, abs=0.001)
            assert strength.away_defense == pytest.approx(2.0 / 2.0, abs=0.001)
            assert strength.lam == pytest.approx(3.0, abs=0.01)
            assert strength.mu == pytest.approx(1.0, abs=0.01)

    async def test_poisson_probabilities(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """胜平负和 ≈ 1,大小球和 ≈ 1,Top 比分概率降序。"""
        _, session_factory = env
        match_id, _home_id, _away_id = await _seed_fixture(session_factory)
        async with session_factory() as session:
            data = await insights_service.get_match_insights(session, match_id)
            assert data.poisson is not None
            forecast = data.poisson
            assert forecast.home_win + forecast.draw + forecast.away_win == pytest.approx(
                1.0, abs=0.01
            )
            assert forecast.over_2_5 + forecast.under_2_5 == pytest.approx(1.0, abs=0.01)
            probs = [prob for _h, _a, prob in forecast.top_scores]
            assert probs == sorted(probs, reverse=True)
            assert len(forecast.top_scores) == 5
            # λ=3.0 > μ=1.0,主胜概率应显著高于客胜
            assert forecast.home_win > forecast.away_win
            # 总进球分布桶 0..6 与 7+
            assert [goals for goals, _prob in forecast.total_goals_dist] == list(range(7)) + [7]
            assert forecast.total_goals_expected == pytest.approx(4.0, abs=0.01)

    async def test_recent_form_blends_into_strength(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """近况 ≥ 3 场时以 0.7/0.3 混合:主队近 3 场场均进 0.67 -> 速率 2.3。"""
        _, session_factory = env
        match_id, home_id, _away_id = await _seed_fixture(session_factory)
        async with session_factory() as session:
            # 主队近 3 场全负 0:1(场均进 0 失 1)
            for index in range(3):
                session.add(
                    _row(
                        home_id, 1000 + index, is_home=True,
                        home_team_name=HOME_NAME, away_team_name=f"对手{index}队",
                        uniform_home=9001, uniform_away=9300 + index,
                        home_goals=0, away_goals=1,
                        match_time=datetime.datetime(2026, 8, 10 + index),
                    )
                )
            await session.commit()
            data = await insights_service.get_match_insights(session, match_id)
            strength = data.strength
            # home_scored = 0.7 × 3.0 + 0.3 × 0.0 = 2.1 -> A_h = 1.05
            assert strength.home_attack == pytest.approx(1.05, abs=0.001)
            # home_conceded = 0.7 × 1.0 + 0.3 × 1.0 = 1.0 -> D_h = 1.0
            assert strength.home_defense == pytest.approx(1.0, abs=0.001)

    async def test_small_recent_sample_degrades_to_season(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """近况 < 3 场时强度等于纯赛季值(不引入小样本噪声)。"""
        _, session_factory = env
        match_id, home_id, _away_id = await _seed_fixture(session_factory)
        async with session_factory() as session:
            # 主队仅 2 场近况,场均进 0(若混合会使速率 = 2.1)
            for index in range(2):
                session.add(
                    _row(
                        home_id, 1100 + index, is_home=True,
                        home_team_name=HOME_NAME, away_team_name=f"对手{index}队",
                        uniform_home=9001, uniform_away=9400 + index,
                        home_goals=0, away_goals=1,
                        match_time=datetime.datetime(2026, 8, 10 + index),
                    )
                )
            await session.commit()
            data = await insights_service.get_match_insights(session, match_id)
            # 退化为纯赛季值:home_scored = 3.0 -> A_h = 1.5
            assert data.strength.home_attack == pytest.approx(1.5, abs=0.001)

    async def test_no_fundamentals_returns_none(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """全库无积分榜 -> strength 各值 None 且 poisson None。"""
        _, session_factory = env
        match_id, _home_id, _away_id = await _seed_fixture(
            session_factory, with_fundamentals=False
        )
        async with session_factory() as session:
            data = await insights_service.get_match_insights(session, match_id)
            assert data.strength.lam is None
            assert data.strength.home_attack is None
            assert data.poisson is None


# ---------- 服务层:Elo 快照 ----------

class TestEloSnapshot:

    async def test_elo_snapshot_from_ratings(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """落库评分读出快照,含差值与期望得分。"""
        _, session_factory = env
        match_id, home_id, away_id = await _seed_fixture(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    TeamRating(
                        team_id=home_id, rating=1560.0, matches_played=10,
                        last_match_time=datetime.datetime(2026, 8, 20),
                    ),
                    TeamRating(
                        team_id=away_id, rating=1480.0, matches_played=10,
                        last_match_time=datetime.datetime(2026, 8, 20),
                    ),
                ]
            )
            await session.commit()
            data = await insights_service.get_match_insights(session, match_id)
            elo = data.elo
            assert elo.home_rating == pytest.approx(1560.0)
            assert elo.away_rating == pytest.approx(1480.0)
            assert elo.rating_diff == pytest.approx(80.0)
            # E = 1 / (1 + 10^((1480 - 1560 - 100)/400)) = 1/(1+10^-0.45)
            expected = 1.0 / (1.0 + 10 ** (-0.45))
            assert elo.home_expected_score == pytest.approx(expected, abs=0.001)
            assert (elo.home_matches_played, elo.away_matches_played) == (10, 10)

    async def test_elo_missing_returns_none(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """未重算评分 -> Elo 快照 rating 各值为 None。"""
        _, session_factory = env
        match_id, _home_id, _away_id = await _seed_fixture(session_factory)
        async with session_factory() as session:
            data = await insights_service.get_match_insights(session, match_id)
            assert data.elo.home_rating is None
            assert data.elo.away_rating is None
            assert data.elo.home_expected_score is None


# ---------- AI 摘要 ----------

class TestFormatInsightsSummary:

    async def test_summary_contains_key_sections(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """摘要含近况/交锋/Elo/强度/模型预测各段。"""
        _, session_factory = env
        match_id, home_id, away_id = await _seed_fixture(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    TeamRating(team_id=home_id, rating=1510.0, matches_played=5),
                    TeamRating(team_id=away_id, rating=1490.0, matches_played=5),
                    _row(
                        home_id, 1201, is_home=True, home_team_name=HOME_NAME,
                        away_team_name=AWAY_NAME, uniform_home=9001,
                        uniform_away=9002, home_goals=1, away_goals=0,
                        match_time=datetime.datetime(2026, 5, 1),
                    ),
                ]
            )
            await session.commit()
            data = await insights_service.get_match_insights(session, match_id)
            summary = insights_service.format_insights_summary(data)
            assert "近况" in summary
            assert "历史交锋" in summary
            assert "Elo" in summary
            assert "攻防强度" in summary
            assert "模型预测" in summary
            assert "λ=3.0" in summary

    async def test_summary_with_gaps_outputs_insufficient(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """数据缺口时各段输出"数据不足"。"""
        _, session_factory = env
        match_id, _home_id, _away_id = await _seed_fixture(
            session_factory, with_fundamentals=False
        )
        async with session_factory() as session:
            data = await insights_service.get_match_insights(session, match_id)
            summary = insights_service.format_insights_summary(data)
            assert "Elo 评分:数据不足" in summary
            assert "攻防强度:数据不足" in summary
            assert "模型预测:数据不足" in summary
            assert "历史交锋:数据不足" in summary


# ---------- 接口层 ----------

class TestInsightsEndpoint:

    async def test_endpoint_returns_full_payload(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """GET /match/games/{id}/insights 返回完整聚合结构。"""
        client, session_factory = env
        match_id, home_id, _away_id = await _seed_fixture(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    TeamRating(team_id=home_id, rating=1510.0, matches_played=5),
                    _row(
                        home_id, 1301, is_home=True, home_team_name=HOME_NAME,
                        away_team_name=AWAY_NAME, uniform_home=9001,
                        uniform_away=9002, home_goals=2, away_goals=1,
                        match_time=datetime.datetime(2026, 5, 1),
                    ),
                ]
            )
            await session.commit()

        response = await client.get(f"/api/v1/match/games/{match_id}/insights")
        assert response.status_code == 200
        body = response.json()
        assert body["match_id"] == match_id
        assert body["home_team_name"] == HOME_NAME
        assert body["elo"]["home_rating"] == pytest.approx(1510.0)
        assert body["home_form"]["results"] == "W"
        assert body["h2h"]["entries"][0]["score"] == "2:1"
        assert body["strength"]["lam"] == pytest.approx(3.0, abs=0.01)
        assert body["poisson"]["home_win"] > 0.5

    async def test_endpoint_unknown_match_returns_404(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """未知 match_id -> 404。"""
        client, _session_factory = env
        response = await client.get("/api/v1/match/games/m-unknown/insights")
        assert response.status_code == 404

    async def test_endpoint_without_fundamentals_still_200(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        """数据缺口时接口仍 200,poisson 为 null。"""
        client, session_factory = env
        match_id, _home_id, _away_id = await _seed_fixture(
            session_factory, with_fundamentals=False
        )
        response = await client.get(f"/api/v1/match/games/{match_id}/insights")
        assert response.status_code == 200
        body = response.json()
        assert body["poisson"] is None
        assert body["strength"]["lam"] is None
