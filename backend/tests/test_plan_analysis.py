"""投注方案分析测试(中奖概率与期望值)。

覆盖两个层次:
1. 服务计算:隐含概率去水归一、单关/串关的中奖概率与期望值手算比对、
   复式选项、库中无赔率的兜底口径、参数与串关规则校验;
2. 接口 POST /api/v1/strategy/plan-analysis:纯计算不落库、
   请求参数校验(422)。

概率口径为赔率隐含概率(去水),期望值如实反映返还率折扣为负。
注额均为模拟数据,测试不涉及真实资金。
"""

import datetime
import itertools
import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.core.exceptions import DataValidationError
from app.main import app
from app.models import League, MatchGame, MatchOdds, Team
from app.services.parlay import ParlayPick
from app.services.plan_analysis import (
    analyze_plan,
    implied_probabilities,
)

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# 测试用胜平负赔率(返还率约 90.5%,含明显折扣)
HAD_OPTIONS = [("h", 2.15), ("d", 3.20), ("a", 3.05)]


def _had_pools() -> list[dict[str, typing.Any]]:
    """构造 HAD 玩法赔率 JSON(与 fp_match_odds.pools 同构)。"""
    return [
        {
            "poolCode": "HAD",
            "playName": "胜平负",
            "goalLine": None,
            "options": [
                {"code": code, "label": label, "odds": odds}
                for code, odds, label in [
                    ("h", HAD_OPTIONS[0][1], "主胜"),
                    ("d", HAD_OPTIONS[1][1], "平"),
                    ("a", HAD_OPTIONS[2][1], "客胜"),
                ]
            ],
        }
    ]


def _expected_probs(options: list[tuple[str, float]]) -> dict[str, float]:
    """测试内独立实现的去水归一(与服务实现口径一致)。"""
    inversions = {code: 1.0 / odds for code, odds in options}
    total = sum(inversions.values())
    return {code: inv / total for code, inv in inversions.items()}


def _pick(
    match_id: str,
    option_code: str,
    odds: float,
    *,
    pool_code: str = "HAD",
    play_name: str = "胜平负",
    option_label: str = "主胜",
) -> ParlayPick:
    """构造一条选注(默认胜平负玩法)。"""
    return ParlayPick(
        match_id=match_id,
        match_name=f"主队{match_id[-1:]} vs 客队{match_id[-1:]}",
        pool_code=pool_code,
        play_name=play_name,
        option_code=option_code,
        option_label=option_label,
        odds=odds,
    )


# ---------- 隐含概率 ----------

class TestImpliedProbabilities:
    """implied_probabilities:去水归一。"""

    def test_normalizes_to_one(self) -> None:
        # Arrange / Act
        probs = implied_probabilities([("h", 2.0), ("d", 4.0)])

        # Assert
        assert sum(probs.values()) == pytest.approx(1.0)
        assert probs["h"] == pytest.approx(2.0 / 3.0)
        assert probs["d"] == pytest.approx(1.0 / 3.0)

    def test_higher_odds_lower_probability(self) -> None:
        probs = implied_probabilities(HAD_OPTIONS)
        assert probs["h"] > probs["a"] > probs["d"]

    def test_empty_or_invalid_options(self) -> None:
        assert implied_probabilities([]) == {}
        assert implied_probabilities([("h", 0.0)]) == {}


# ---------- 服务计算 ----------

class TestAnalyzePlanSingle:
    """analyze_plan 单关口径。"""

    async def test_single_two_bets_probability_and_ev(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange: 两场各选主胜,库中 HAD 赔率一致
        picks = [
            _pick("m-an-001", "h", 2.15),
            _pick("m-an-002", "h", 2.15),
        ]

        # Act
        async with session_factory() as session:
            result = await analyze_plan(session, picks, "single", None, 100.0)

        # Assert: 去水概率与手算一致
        p = _expected_probs(HAD_OPTIONS)["h"]
        assert result.selections[0].implied_prob == pytest.approx(p, abs=1e-4)
        assert result.bet_count == 2
        assert result.total_stake == pytest.approx(200.0)
        assert result.max_odds == pytest.approx(2.15)
        # 期望回报 = 100 x (p x 2.15) x 2
        assert result.expected_return == pytest.approx(100.0 * p * 2.15 * 2, abs=0.01)
        # 中奖概率 = 1 - (1-p)^2
        assert result.win_prob == pytest.approx(1.0 - (1.0 - p) ** 2, abs=1e-4)
        # 去水后 EV 为负(返还率折扣)
        assert result.expected_value < 0
        assert result.ev_pct < 0
        # 负期望时凯利为 0
        assert all(a.kelly_fraction == 0 for a in result.selections)

    async def test_single_duplex_same_match_groups_by_pool(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange: 同一场勾选 主胜+平(复式单关)
        picks = [
            _pick("m-an-001", "h", 2.15, option_label="主胜"),
            _pick("m-an-001", "d", 3.20, option_label="平"),
        ]

        # Act
        async with session_factory() as session:
            result = await analyze_plan(session, picks, "single", None, 10.0)

        # Assert: 中奖概率 = 同组互斥求和 q = p_h + p_d
        probs = _expected_probs(HAD_OPTIONS)
        q = probs["h"] + probs["d"]
        assert result.win_prob == pytest.approx(q, abs=1e-4)
        assert result.bet_count == 2

    async def test_single_uses_current_db_odds_over_snapshot(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange: 勾选时点赔率 1.5,库中当前 2.15,应以库中为准
        picks = [_pick("m-an-001", "h", 1.5)]

        # Act
        async with session_factory() as session:
            result = await analyze_plan(session, picks, "single", None, 100.0)

        # Assert
        assert result.selections[0].odds == pytest.approx(2.15)
        assert result.selections[0].implied_prob == pytest.approx(
            _expected_probs(HAD_OPTIONS)["h"], abs=1e-4
        )


class TestAnalyzePlanParlay:
    """analyze_plan 串关口径。"""

    async def test_2x1_win_prob_and_expected_return(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange: 两场各选主胜,2串1
        picks = [
            _pick("m-an-001", "h", 2.15),
            _pick("m-an-002", "h", 2.15),
        ]

        # Act
        async with session_factory() as session:
            result = await analyze_plan(session, picks, "parlay", 2, 100.0)

        # Assert: 注数/总投入来自 calculate_parlay 口径
        p = _expected_probs(HAD_OPTIONS)["h"]
        s = p * 2.15
        assert result.bet_count == 1
        assert result.total_stake == pytest.approx(100.0)
        # 中奖概率 = p1 x p2
        assert result.win_prob == pytest.approx(p * p, abs=1e-4)
        # 期望回报 = 100 x S1 x S2
        assert result.expected_return == pytest.approx(100.0 * s * s, abs=0.01)
        assert result.expected_value < 0

    async def test_3_matches_2x1_combinatorics(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange: 三场各选主胜,2串1 => C(3,2)=3 注
        picks = [_pick(f"m-an-{i:03d}", "h", 2.15) for i in range(1, 4)]

        # Act
        async with session_factory() as session:
            result = await analyze_plan(session, picks, "parlay", 2, 10.0)

        # Assert: 期望回报 = 10 x (S1S2 + S1S3 + S2S3)
        p = _expected_probs(HAD_OPTIONS)["h"]
        s = p * 2.15
        assert result.bet_count == 3
        assert result.expected_return == pytest.approx(
            10.0 * (s * s + s * s + s * s), abs=0.01
        )
        # 中奖概率 = 至少 2 场被覆盖(独立伯努利闭式穷举)
        q = p
        at_least_2 = 0.0
        for wins in itertools.product([True, False], repeat=3):
            prob = 1.0
            for w in wins:
                prob *= q if w else 1.0 - q
            if sum(wins) >= 2:
                at_least_2 += prob
        assert result.win_prob == pytest.approx(at_least_2, abs=1e-4)

    async def test_2x1_with_duplex_expected_return(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange: 一场双选(主胜+平)、一场单选 => 2 注
        picks = [
            _pick("m-an-001", "h", 2.15, option_label="主胜"),
            _pick("m-an-001", "d", 3.20, option_label="平"),
            _pick("m-an-002", "h", 2.15),
        ]

        # Act
        async with session_factory() as session:
            result = await analyze_plan(session, picks, "parlay", 2, 50.0)

        # Assert: 期望回报 = 50 x (p_h x 2.15 + p_d x 3.20) x (p_h x 2.15)
        probs = _expected_probs(HAD_OPTIONS)
        s1 = probs["h"] * 2.15 + probs["d"] * 3.20
        s2 = probs["h"] * 2.15
        assert result.bet_count == 2
        assert result.expected_return == pytest.approx(50.0 * s1 * s2, abs=0.01)
        # 中奖概率 = q1 x q2(复式覆盖)
        assert result.win_prob == pytest.approx(
            (probs["h"] + probs["d"]) * probs["h"], abs=1e-4
        )

    async def test_mixed_mode_follows_parlay_semantics(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange: 混合模式与串关同口径
        picks = [
            _pick("m-an-001", "h", 2.15),
            _pick("m-an-002", "h", 2.15),
        ]

        # Act
        async with session_factory() as session:
            mixed = await analyze_plan(session, picks, "mixed", 2, 100.0)
            parlay = await analyze_plan(session, picks, "parlay", 2, 100.0)

        # Assert: 与 parlay 模式结果一致
        assert mixed.win_prob == pytest.approx(parlay.win_prob)
        assert mixed.expected_return == pytest.approx(parlay.expected_return)


class TestAnalyzePlanFallbackAndValidation:
    """analyze_plan 兜底口径与参数校验。"""

    async def test_fallback_without_db_odds(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange: m-an-099 无 MatchOdds 记录,用勾选时点赔率
        picks = [_pick("m-an-099", "h", 2.0)]

        # Act
        async with session_factory() as session:
            result = await analyze_plan(session, picks, "single", None, 100.0)

        # Assert: 不归一直接取隐含概率,公平赔率还原勾选赔率
        assert result.selections[0].implied_prob == pytest.approx(0.5)
        assert result.selections[0].fair_odds == pytest.approx(2.0)
        # EV = 100 x 0.5 x 2.0 - 100 = 0(无折扣信息时中性)
        assert result.expected_value == pytest.approx(0.0, abs=0.01)

    async def test_parlay_requires_parlay_size(self) -> None:
        picks = [_pick("m-an-001", "h", 2.0), _pick("m-an-002", "h", 2.0)]
        with pytest.raises(DataValidationError) as exc_info:
            await analyze_plan(None, picks, "parlay", None, 100.0)  # type: ignore[arg-type]
        assert "parlay_size" in str(exc_info.value)

    async def test_rejects_empty_picks(self) -> None:
        with pytest.raises(DataValidationError):
            await analyze_plan(None, [], "single", None, 100.0)  # type: ignore[arg-type]

    async def test_rejects_non_positive_stake(self) -> None:
        picks = [_pick("m-an-001", "h", 2.0)]
        with pytest.raises(DataValidationError):
            await analyze_plan(None, picks, "single", None, 0.0)  # type: ignore[arg-type]

    async def test_rejects_odds_not_greater_than_one(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange: 无库中赔率兜底时,勾选赔率 1.0 应被拒绝
        picks = [_pick("m-an-099", "h", 1.0)]
        with pytest.raises(DataValidationError) as exc_info:
            async with session_factory() as session:
                await analyze_plan(session, picks, "single", None, 100.0)
        assert "大于 1" in str(exc_info.value)

    async def test_rejects_multiple_pools_on_same_match(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange: 串关口径不允许同场多玩法(由 calculate_parlay 校验)
        picks = [
            _pick("m-an-001", "h", 2.0, pool_code="HAD", play_name="胜平负"),
            _pick(
                "m-an-001",
                "s01s02",
                8.5,
                pool_code="CRS",
                play_name="比分",
                option_label="1:2",
            ),
            _pick("m-an-002", "h", 1.5),
        ]
        with pytest.raises(DataValidationError) as exc_info:
            async with session_factory() as session:
                await analyze_plan(session, picks, "parlay", 2, 100.0)
        assert "一种玩法" in str(exc_info.value)


# ---------- 接口 ----------

class TestPlanAnalysisEndpoint:
    """POST /api/v1/strategy/plan-analysis"""

    async def test_returns_analysis_without_persisting(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        match_ids = await _seed_matches_with_odds(session_factory, 2)

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/plan-analysis",
            json={
                "mode": "parlay",
                "stake_per_bet": 100.0,
                "parlay_size": 2,
                "selections": [
                    {
                        "match_id": match_id,
                        "match_name": "阿森纳 vs 切尔西",
                        "pool_code": "HAD",
                        "play_name": "胜平负",
                        "option_code": "h",
                        "option_label": "主胜",
                        "odds": 2.15,
                    }
                    for match_id in match_ids
                ],
            },
        )

        # Assert: 纯计算返回,不落库
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "parlay"
        assert body["probability_source"] == "implied"
        assert body["bet_count"] == 1
        assert len(body["selections"]) == 2
        assert 0 < body["win_prob"] < 1
        assert body["expected_value"] < 0
        assert body["ev_pct"] < 0
        selection = body["selections"][0]
        assert selection["implied_prob"] == pytest.approx(
            _expected_probs(HAD_OPTIONS)["h"], abs=1e-4
        )
        assert selection["kelly_fraction"] == 0

    async def test_single_mode_payload(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        match_ids = await _seed_matches_with_odds(session_factory, 1)

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/plan-analysis",
            json={
                "mode": "single",
                "stake_per_bet": 50.0,
                "selections": [
                    {
                        "match_id": match_ids[0],
                        "match_name": "阿森纳 vs 切尔西",
                        "pool_code": "HAD",
                        "play_name": "胜平负",
                        "option_code": "h",
                        "option_label": "主胜",
                        "odds": 2.15,
                    }
                ],
            },
        )

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert body["bet_count"] == 1
        assert body["total_stake"] == pytest.approx(50.0)
        assert body["max_odds"] == pytest.approx(2.15)

    async def test_parlay_mode_requires_parlay_size(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        match_ids = await _seed_matches_with_odds(session_factory, 2)

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/plan-analysis",
            json={
                "mode": "parlay",
                "stake_per_bet": 100.0,
                "selections": [
                    {
                        "match_id": match_id,
                        "pool_code": "HAD",
                        "option_code": "h",
                        "odds": 2.15,
                    }
                    for match_id in match_ids
                ],
            },
        )

        # Assert: 业务校验 422
        assert resp.status_code == 422

    async def test_rejects_invalid_payloads(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, _ = env

        # Act / Assert: 空选注
        resp = await async_client.post(
            "/api/v1/strategy/plan-analysis",
            json={"mode": "single", "stake_per_bet": 100.0, "selections": []},
        )
        assert resp.status_code == 422

        # 非法模式
        resp = await async_client.post(
            "/api/v1/strategy/plan-analysis",
            json={
                "mode": "whatever",
                "stake_per_bet": 100.0,
                "selections": [
                    {"match_id": "m-1", "pool_code": "HAD", "option_code": "h", "odds": 2.0}
                ],
            },
        )
        assert resp.status_code == 422

        # 注额为 0
        resp = await async_client.post(
            "/api/v1/strategy/plan-analysis",
            json={
                "mode": "single",
                "stake_per_bet": 0,
                "selections": [
                    {"match_id": "m-1", "pool_code": "HAD", "option_code": "h", "odds": 2.0}
                ],
            },
        )
        assert resp.status_code == 422

        # 赔率不大于 1
        resp = await async_client.post(
            "/api/v1/strategy/plan-analysis",
            json={
                "mode": "single",
                "stake_per_bet": 100.0,
                "selections": [
                    {"match_id": "m-1", "pool_code": "HAD", "option_code": "h", "odds": 1.0}
                ],
            },
        )
        assert resp.status_code == 422

    async def test_rejects_unknown_pool_code(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange: 串关模式经 calculate_parlay 校验玩法编码
        async_client, _ = env

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/plan-analysis",
            json={
                "mode": "parlay",
                "stake_per_bet": 100.0,
                "parlay_size": 2,
                "selections": [
                    {"match_id": "m-1", "pool_code": "XXX", "option_code": "h", "odds": 2.0},
                    {"match_id": "m-2", "pool_code": "XXX", "option_code": "h", "odds": 2.0},
                ],
            },
        )

        # Assert
        assert resp.status_code == 422


# ---------- fixtures ----------

@pytest.fixture
async def env(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    """返回测试客户端与会话工厂(会话用于预置联赛/球队/比赛)。"""
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


@pytest.fixture
async def session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncGenerator[async_sessionmaker, None]:
    """预置三场比赛(含 HAD 当前赔率),返回会话工厂。

    服务层测试直接持有会话工厂,不经过 HTTP 层;
    m-an-099 等未预置的编号用于验证无库中赔率的兜底口径。
    """
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _seed_matches_with_odds(factory, 3)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_matches_with_odds(
    session_factory: async_sessionmaker, count: int
) -> list[str]:
    """预置 N 场比赛并写入 HAD 当前赔率,返回 match_id 列表。"""
    match_ids = [f"m-an-{i:03d}" for i in range(1, count + 1)]
    async with session_factory() as session:
        league = League(league_name="英格兰超级联赛", country="英格兰", tier=1, season="2026-2027")
        session.add(league)
        await session.flush()
        home = Team(team_name="阿森纳", league_id=league.league_id)
        away = Team(team_name="切尔西", league_id=league.league_id)
        session.add_all([home, away])
        await session.flush()
        for match_id in match_ids:
            session.add(
                MatchGame(
                    match_id=match_id,
                    league_id=league.league_id,
                    home_team_id=home.team_id,
                    away_team_id=away.team_id,
                    match_time=datetime.datetime(2026, 9, 20, 21, 0),
                )
            )
            session.add(
                MatchOdds(
                    match_id=match_id,
                    pools=_had_pools(),
                    update_time=datetime.datetime(2026, 9, 20, 12, 0),
                )
            )
        await session.commit()
    return match_ids
