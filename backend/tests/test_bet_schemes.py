"""串关虚拟投注方案测试。

覆盖两个层次:
1. 组合计算:2串1/3串1/复式注数、单注最高赔率、串关规则校验
   (玩法编码 / 同场多玩法 / 场次不足 / 场次越界 / 注数上限);
2. 接口 POST/GET /api/v1/strategy/bet-schemes:保存落库 / 分页列表 /
   参数校验(422) / 比赛不存在(404)。

注额均为模拟数据,测试不涉及真实资金。
"""

import datetime
import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.core.exceptions import DataValidationError
from app.main import app
from app.models import BetScheme, BetSchemeItem, League, MatchGame, Team
from app.services.parlay import ParlayPick, calculate_parlay

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}


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


# ---------- 组合计算 ----------

class TestCalculateParlay:
    """calculate_parlay:注数、总投入、单注最高赔率与规则校验。"""

    async def test_2x1_single_option_each_match(self) -> None:
        # Arrange: 两场各一注,2串1 应为 1 注
        picks = [_pick("m-001", "h", 2.10), _pick("m-002", "h", 1.85)]

        # Act
        calc = calculate_parlay(picks, parlay_size=2, stake_per_bet=100)

        # Assert
        assert calc.bet_count == 1
        assert calc.max_odds == pytest.approx(round(2.10 * 1.85, 2))
        assert calc.total_stake == pytest.approx(100)

    async def test_3x1_with_four_matches_makes_four_bets(self) -> None:
        # Arrange: 四场各一注,3串1 有 C(4,3)=4 个组合
        picks = [
            _pick("m-001", "h", 2.0),
            _pick("m-002", "h", 3.0),
            _pick("m-003", "h", 4.0),
            _pick("m-004", "h", 5.0),
        ]

        # Act
        calc = calculate_parlay(picks, parlay_size=3, stake_per_bet=10)

        # Assert
        assert calc.bet_count == 4
        # 最高组合 = 3/4/5 号场
        assert calc.max_odds == pytest.approx(3.0 * 4.0 * 5.0)
        assert calc.total_stake == pytest.approx(40)

    async def test_multiple_options_same_match_is_duplex(self) -> None:
        # Arrange: 2串1,一场双选、另一场三选 => 1 x 2 x 3 = 6 注
        picks = [
            _pick("m-001", "h", 2.0),
            _pick("m-001", "d", 3.2),
            _pick("m-002", "h", 1.5),
            _pick("m-002", "d", 3.4),
            _pick("m-002", "a", 5.6),
        ]

        # Act
        calc = calculate_parlay(picks, parlay_size=2, stake_per_bet=2)

        # Assert
        assert calc.bet_count == 6
        # 单注最高赔率取各场最高: 3.2 x 5.6
        assert calc.max_odds == pytest.approx(3.2 * 5.6)
        assert calc.total_stake == pytest.approx(12)

    async def test_3x1_with_duplex_options(self) -> None:
        # Arrange: 三场各双选,3串1 => 1 x 2 x 2 x 2 = 8 注
        picks: list[ParlayPick] = []
        for match_id, odds_pair in {
            "m-001": (2.0, 3.0),
            "m-002": (1.8, 3.3),
            "m-003": (2.6, 2.4),
        }.items():
            picks.append(_pick(match_id, "h", odds_pair[0]))
            picks.append(_pick(match_id, "d", odds_pair[1]))

        # Act
        calc = calculate_parlay(picks, parlay_size=3, stake_per_bet=1)

        # Assert
        assert calc.bet_count == 8
        assert calc.max_odds == pytest.approx(3.0 * 3.3 * 2.6)

    async def test_rejects_unknown_pool_code(self) -> None:
        with pytest.raises(DataValidationError) as exc_info:
            calculate_parlay(
                [_pick("m-001", "h", 2.0, pool_code="XXX"), _pick("m-002", "h", 1.5)],
                parlay_size=2,
                stake_per_bet=10,
            )
        assert "玩法编码" in str(exc_info.value)

    async def test_rejects_multiple_pools_on_same_match(self) -> None:
        picks = [
            _pick("m-001", "h", 2.0, pool_code="HAD", play_name="胜平负"),
            _pick("m-001", "s01s02", 8.5, pool_code="CRS", play_name="比分", option_label="1:2"),
        ]

        with pytest.raises(DataValidationError) as exc_info:
            calculate_parlay(picks, parlay_size=2, stake_per_bet=10)
        assert "一种玩法" in str(exc_info.value)

    async def test_rejects_parlay_size_beyond_match_count(self) -> None:
        picks = [_pick("m-001", "h", 2.0), _pick("m-002", "h", 1.5)]

        with pytest.raises(DataValidationError) as exc_info:
            calculate_parlay(picks, parlay_size=3, stake_per_bet=10)
        assert "不同场次" in str(exc_info.value)

    @pytest.mark.parametrize("parlay_size", [1, 9])
    async def test_rejects_parlay_size_out_of_range(self, parlay_size: int) -> None:
        picks = [_pick("m-001", "h", 2.0), _pick("m-002", "h", 1.5)]

        with pytest.raises(DataValidationError) as exc_info:
            calculate_parlay(picks, parlay_size=parlay_size, stake_per_bet=10)
        assert "串关场次" in str(exc_info.value)

    async def test_rejects_bet_count_over_limit(self) -> None:
        # Arrange: 8串1,每场四选 => 4^8 = 65536 注,超过 10000 上限
        picks: list[ParlayPick] = []
        for i in range(1, 9):
            for code, odds in [("h", 2.0), ("d", 3.0), ("a", 3.5), ("x", 4.0)]:
                picks.append(_pick(f"m-{i:03d}", code, odds))

        # Act / Assert
        with pytest.raises(DataValidationError) as exc_info:
            calculate_parlay(picks, parlay_size=8, stake_per_bet=1)
        assert "上限" in str(exc_info.value)


# ---------- 接口 ----------

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


async def _seed_matches(session_factory: async_sessionmaker, count: int) -> list[str]:
    """预置 N 场比赛,返回 match_id 列表。"""
    match_ids = [f"m-sch-{i:03d}" for i in range(1, count + 1)]
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
        await session.commit()
    return match_ids


def _payload(
    match_ids: list[str],
    *,
    user_id: int = 1,
    parlay_size: int = 2,
    stake_per_bet: float = 100.0,
    options_per_match: int = 1,
) -> dict:
    """构造创建方案的请求体。"""
    items = []
    for match_id in match_ids:
        items.append(
            {
                "match_id": match_id,
                "match_name": "阿森纳 vs 切尔西",
                "pool_code": "HAD",
                "play_name": "胜平负",
                "option_code": "h",
                "option_label": "主胜",
                "odds": 2.10,
            }
        )
        if options_per_match > 1:
            items.append(
                {
                    "match_id": match_id,
                    "match_name": "阿森纳 vs 切尔西",
                    "pool_code": "HAD",
                    "play_name": "胜平负",
                    "option_code": "d",
                    "option_label": "平",
                    "odds": 3.30,
                }
            )
    return {
        "user_id": user_id,
        "parlay_size": parlay_size,
        "stake_per_bet": stake_per_bet,
        "items": items,
    }


class TestCreateBetScheme:
    """POST /api/v1/strategy/bet-schemes"""

    async def test_persists_scheme_with_items(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        match_ids = await _seed_matches(session_factory, 3)

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/bet-schemes", json=_payload(match_ids, parlay_size=3)
        )

        # Assert
        assert resp.status_code == 201
        body = resp.json()
        assert body["parlay_size"] == 3
        assert body["bet_count"] == 1
        assert body["total_stake"] == pytest.approx(100.0)
        assert body["max_odds"] == pytest.approx(round(2.10**3, 2))
        assert body["status"] == "PENDING"
        assert len(body["items"]) == 3

        async with session_factory() as session:
            schemes = (await session.execute(select(BetScheme))).scalars().all()
            assert len(schemes) == 1
            assert schemes[0].bet_count == 1
            items = (
                await session.execute(select(BetSchemeItem))
            ).scalars().all()
            assert len(items) == 3
            assert {i.match_id for i in items} == set(match_ids)

    async def test_duplex_options_compute_bet_count(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange: 两场各双选 => 2串1 为 4 注
        async_client, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/bet-schemes",
            json=_payload(match_ids, parlay_size=2, options_per_match=2, stake_per_bet=50),
        )

        # Assert
        assert resp.status_code == 201
        body = resp.json()
        assert body["bet_count"] == 4
        assert body["total_stake"] == pytest.approx(200.0)
        # 单注最高赔率 = 各场最高赔率乘积
        assert body["max_odds"] == pytest.approx(3.30**2)

    async def test_returns_422_for_same_match_multiple_pools(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange: 同一场比赛勾选两种玩法
        async_client, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)
        payload = _payload([match_ids[0], match_ids[0]], parlay_size=2)
        payload["items"][1]["pool_code"] = "CRS"
        payload["items"][1]["play_name"] = "比分"

        # Act
        resp = await async_client.post("/api/v1/strategy/bet-schemes", json=payload)

        # Assert
        assert resp.status_code == 422
        assert "一种玩法" in resp.text

    async def test_returns_422_for_insufficient_matches(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange: 3串1 只有 2 场
        async_client, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/bet-schemes",
            json=_payload(match_ids, parlay_size=3),
        )

        # Assert
        assert resp.status_code == 422
        assert "不同场次" in resp.text

    async def test_returns_422_for_schema_violation(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange: parlay_size=1 违反 ge=2
        async_client, _ = env

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/bet-schemes", json=_payload(["m-x", "m-y"], parlay_size=1)
        )

        # Assert
        assert resp.status_code == 422

    async def test_returns_404_for_unknown_match(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, _ = env

        # Act
        resp = await async_client.post(
            "/api/v1/strategy/bet-schemes",
            json=_payload(["m-missing-1", "m-missing-2"]),
        )

        # Assert
        assert resp.status_code == 404


class TestListBetSchemes:
    """GET /api/v1/strategy/bet-schemes"""

    async def test_lists_schemes_desc_with_user_filter(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange: 两个用户各保存一个方案
        async_client, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)
        for user_id in (1, 2):
            resp = await async_client.post(
                "/api/v1/strategy/bet-schemes",
                json=_payload(match_ids, user_id=user_id, parlay_size=2),
            )
            assert resp.status_code == 201

        # Act
        resp = await async_client.get("/api/v1/strategy/bet-schemes", params={"user_id": 1})

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["user_id"] == 1
        assert len(body[0]["items"]) == 2

        # 全量(不分用户)应有两条
        resp_all = await async_client.get("/api/v1/strategy/bet-schemes")
        assert resp_all.status_code == 200
        assert len(resp_all.json()) == 2

    async def test_supports_pagination(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange: 同一用户保存两个方案
        async_client, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)
        for _ in range(2):
            resp = await async_client.post(
                "/api/v1/strategy/bet-schemes",
                json=_payload(match_ids, user_id=1, parlay_size=2),
            )
            assert resp.status_code == 201

        # Act
        resp = await async_client.get(
            "/api/v1/strategy/bet-schemes", params={"user_id": 1, "offset": 1, "limit": 1}
        )

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1

        async with session_factory() as session:
            total = (
                await session.execute(select(func.count()).select_from(BetScheme))
            ).scalar_one()
            assert total == 2
