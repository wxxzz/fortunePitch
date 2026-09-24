"""复盘结算引擎与统计聚合测试。

覆盖:
1. 单元:选项编码->展示名映射、命中判定(含 TTG 7+ 边界/HHAD 让球前缀)、
   结算赔率解析(SP 优先);
2. 服务:settle_user_decisions(赢/输/未开奖保持 PUSH/无赔率跳过/幂等/按用户)、
   settle_bet_schemes(全中 WIN/部分 LOSS/复式含中奖注/缺赛果保持 PENDING);
3. 接口:POST /settlement、GET /review/stats(KPI/曲线/维度手算比对)、
   GET /review/decisions(富明细/状态过滤/排序)、GET /bet-schemes(逐腿命中
   与实时盈亏)。

注额均为模拟数据,测试不涉及真实资金。
"""

import datetime
import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import app
from app.models import (
    BetScheme,
    DecisionStatus,
    League,
    MatchGame,
    MatchOdds,
    MatchResult,
    Team,
    UserDecision,
)
from app.services.settlement import (
    PLAY_NAMES,
    compute_scheme_payout,
    resolve_option_hit,
    resolve_option_label,
    resolve_payout_odds,
    run_settlement,
    settle_bet_schemes,
    settle_user_decisions,
)
from app.services.user_picks import UserPick, create_user_picks

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}


# ---------- 单元:选项编码与命中判定 ----------

class TestResolveOptionLabel:
    """resolve_option_label:编码 -> 展示名静态映射。"""

    @pytest.mark.parametrize(
        ("play_code", "option_code", "expected"),
        [
            ("HAD", "h", "主胜"),
            ("HAD", "d", "平"),
            ("HAD", "a", "客胜"),
            ("HHAD", "a", "客胜"),
            ("TTG", "s0", "0"),
            ("TTG", "s6", "6"),
            ("TTG", "s7", "7+"),
            ("CRS", "s01s02", "1:2"),
            ("CRS", "s10s00", "10:0"),
            ("CRS", "s1sh", "胜其他"),
            ("HAFU", "hh", "胜胜"),
            ("HAFU", "ha", "胜负"),
            ("HAFU", "aa", "负负"),
        ],
    )
    def test_maps_code_to_label(
        self, play_code: str, option_code: str, expected: str
    ) -> None:
        assert resolve_option_label(play_code, option_code) == expected

    @pytest.mark.parametrize(
        ("play_code", "option_code"),
        [("HAD", "x"), ("TTG", "x8"), ("CRS", "x1y2"), ("XXX", "h")],
    )
    def test_returns_none_for_unknown_code(
        self, play_code: str, option_code: str
    ) -> None:
        assert resolve_option_label(play_code, option_code) is None


class TestResolveOptionHit:
    """resolve_option_hit:选项与赛果比对(归一化 + TTG 7+ 边界)。"""

    @pytest.mark.parametrize(
        ("play_code", "option_label", "result", "expected"),
        [
            ("HAD", "主胜", "主胜", True),
            ("HAD", "主胜", "客胜", False),
            # HHAD 选项文案不带前缀,开奖带"让球"前缀
            ("HHAD", "主胜", "让球主胜", True),
            ("HHAD", "主胜", "让球客胜", False),
            # TTG 边界:7+ 命中一切 >=7 的总进球
            ("TTG", "7+", "7", True),
            ("TTG", "7+", "8", True),
            ("TTG", "7+", "6", False),
            ("TTG", "3", "3球", True),
            ("CRS", "1:2", "1:2", True),
            ("CRS", "胜其他", "胜其他", True),
            ("HAFU", "负负", "负负", True),
        ],
    )
    def test_hit_resolution(
        self, play_code: str, option_label: str, result: str, expected: bool
    ) -> None:
        assert (
            resolve_option_hit(play_code, option_label, result) is expected
        )

    def test_returns_none_when_no_result(self) -> None:
        assert resolve_option_hit("HAD", "主胜", None) is None
        assert resolve_option_hit("HAD", "主胜", "") is None


class TestResolvePayoutOdds:
    """resolve_payout_odds:SP 优先,否则当前在售赔率池。"""

    def _result(self, **kwargs: float | None) -> MatchResult:
        return MatchResult(match_id="m-odds", **kwargs)

    def test_had_prefers_sp(self) -> None:
        result = self._result(sp_h=2.5)
        pools = [{"poolCode": "HAD", "options": [{"code": "h", "odds": 2.15}]}]
        assert resolve_payout_odds("HAD", "h", result, pools) == 2.5

    def test_had_falls_back_to_pools_without_sp(self) -> None:
        result = self._result()
        pools = [{"poolCode": "HAD", "options": [{"code": "h", "odds": 2.15}]}]
        assert resolve_payout_odds("HAD", "h", result, pools) == 2.15

    def test_non_had_uses_pools(self) -> None:
        pools = [
            {
                "poolCode": "HHAD",
                "options": [{"code": "a", "label": "客胜", "odds": 1.9}],
            }
        ]
        assert resolve_payout_odds("HHAD", "a", self._result(), pools) == 1.9

    def test_returns_none_without_any_source(self) -> None:
        # 无 SP 时 pools=None -> 无赔率来源
        assert resolve_payout_odds("HAD", "h", self._result(), None) is None
        assert resolve_payout_odds("HAD", "h", None, None) is None
        pools = [{"poolCode": "HAD", "options": [{"code": "h", "odds": 0}]}]
        assert resolve_payout_odds("HAD", "h", None, pools) is None


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


def _had_pools(
    h: float = 2.15, d: float = 3.20, a: float = 3.05
) -> list[dict[str, typing.Any]]:
    """构造胜平负在售赔率池。"""
    return [
        {
            "poolCode": "HAD",
            "playName": "胜平负",
            "options": [
                {"code": "h", "label": "主胜", "odds": h},
                {"code": "d", "label": "平", "odds": d},
                {"code": "a", "label": "客胜", "odds": a},
            ],
        }
    ]


async def _seed_matches(
    session_factory: async_sessionmaker, count: int
) -> list[str]:
    """预置 N 场比赛(同一联赛同一对球队),返回 match_id 列表。"""
    match_ids = [f"m-set-{i:03d}" for i in range(1, count + 1)]
    async with session_factory() as session:
        league = League(league_name="英格兰超级联赛", country="英格兰", tier=1, season="2026-2027")
        session.add(league)
        await session.flush()
        home = Team(team_name="阿森纳", league_id=league.league_id)
        away = Team(team_name="切尔西", league_id=league.league_id)
        session.add_all([home, away])
        await session.flush()
        for index, match_id in enumerate(match_ids):
            session.add(
                MatchGame(
                    match_id=match_id,
                    league_id=league.league_id,
                    home_team_id=home.team_id,
                    away_team_id=away.team_id,
                    match_time=datetime.datetime(2026, 9, 19 + index, 21, 0),
                )
            )
        await session.commit()
    return match_ids


async def _add_result(
    session_factory: async_sessionmaker,
    match_id: str,
    *,
    had: str | None = None,
    hhad: str | None = None,
    crs: str | None = None,
    ttg: str | None = None,
    hafu: str | None = None,
    sp_h: float | None = None,
    sp_d: float | None = None,
    sp_a: float | None = None,
) -> None:
    """为一场比赛补录赛果。"""
    async with session_factory() as session:
        session.add(
            MatchResult(
                match_id=match_id,
                had=had,
                hhad=hhad,
                crs=crs,
                ttg=ttg,
                hafu=hafu,
                sp_h=sp_h,
                sp_d=sp_d,
                sp_a=sp_a,
                pool_status="Payout",
            )
        )
        await session.commit()


async def _add_odds(
    session_factory: async_sessionmaker, match_id: str, pools: list[dict]
) -> None:
    """为一场比赛补录当前在售赔率。"""
    async with session_factory() as session:
        session.add(MatchOdds(match_id=match_id, pools=pools))
        await session.commit()


async def _add_decisions(
    session_factory: async_sessionmaker,
    user_id: int,
    stake: float,
    picks: list[tuple[str, str, str, str]],
) -> list[int]:
    """批量创建用户模拟决策,返回 decision_id 列表。"""
    async with session_factory() as session:
        decisions = await create_user_picks(
            session,
            user_id=user_id,
            stake_amount=stake,
            picks=[
                UserPick(
                    match_id=match_id,
                    pool_code=pool_code,
                    option_code=option_code,
                    option_label=option_label,
                )
                for match_id, pool_code, option_code, option_label in picks
            ],
        )
        await session.commit()
        return [d.decision_id for d in decisions]


async def _fetch_decisions(
    session_factory: async_sessionmaker,
) -> dict[int, UserDecision]:
    """读取全部决策,返回 decision_id -> UserDecision。"""
    async with session_factory() as session:
        rows = (await session.execute(select(UserDecision))).scalars().all()
        return {d.decision_id: d for d in rows}


async def _fetch_schemes(session_factory: async_sessionmaker) -> list[BetScheme]:
    """读取全部串关方案。"""
    async with session_factory() as session:
        from sqlalchemy.orm import selectinload

        rows = (
            await session.execute(
                select(BetScheme).options(selectinload(BetScheme.items))
            )
        ).scalars().all()
        return list(rows)


# ---------- 服务:单关决策结算 ----------

class TestSettleUserDecisions:
    """settle_user_decisions:输赢判定与盈亏回写。"""

    async def test_settles_win_with_sp(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:主胜赛果 + SP 2.5,押主胜 100
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 1)
        await _add_result(session_factory, match_ids[0], had="主胜", sp_h=2.5)
        (decision_id,) = await _add_decisions(
            session_factory, 1, 100.0, [(match_ids[0], "HAD", "h", "主胜")]
        )

        # Act
        async with session_factory() as session:
            wins, losses = await settle_user_decisions(session)
            await session.commit()

        # Assert:WIN,profit = 100 x (2.5 - 1)
        assert (wins, losses) == (1, 0)
        decisions = await _fetch_decisions(session_factory)
        decision = decisions[decision_id]
        assert decision.result_status == DecisionStatus.WIN
        assert float(decision.profit_loss) == pytest.approx(150.0)

    async def test_settles_loss(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:主胜赛果,押客胜
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 1)
        await _add_result(
            session_factory, match_ids[0], had="主胜", sp_h=2.5, sp_a=3.1
        )
        (decision_id,) = await _add_decisions(
            session_factory, 1, 80.0, [(match_ids[0], "HAD", "a", "客胜")]
        )

        # Act
        async with session_factory() as session:
            wins, losses = await settle_user_decisions(session)
            await session.commit()

        # Assert:LOSS,profit = -stake(输不需要赔率)
        assert (wins, losses) == (0, 1)
        decisions = await _fetch_decisions(session_factory)
        assert decisions[decision_id].result_status == DecisionStatus.LOSS
        assert float(decisions[decision_id].profit_loss) == pytest.approx(-80.0)

    async def test_hhad_resolves_prefix_and_uses_pools(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:HHAD 押"主胜",开奖"让球主胜";无 SP,用池中赔率 1.9
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 1)
        await _add_odds(
            session_factory,
            match_ids[0],
            [
                {
                    "poolCode": "HHAD",
                    "playName": "让球胜平负",
                    "goalLine": "-1",
                    "options": [
                        {"code": "h", "label": "主胜", "odds": 1.9},
                        {"code": "d", "label": "平", "odds": 3.4},
                        {"code": "a", "label": "客胜", "odds": 4.0},
                    ],
                }
            ],
        )
        await _add_result(session_factory, match_ids[0], hhad="让球主胜")
        (decision_id,) = await _add_decisions(
            session_factory, 1, 100.0, [(match_ids[0], "HHAD", "h", "主胜")]
        )

        # Act
        async with session_factory() as session:
            wins, losses = await settle_user_decisions(session)
            await session.commit()

        # Assert
        decisions = await _fetch_decisions(session_factory)
        assert decisions[decision_id].result_status == DecisionStatus.WIN
        assert float(decisions[decision_id].profit_loss) == pytest.approx(90.0)

    async def test_no_result_stays_push(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 1)
        (decision_id,) = await _add_decisions(
            session_factory, 1, 100.0, [(match_ids[0], "HAD", "h", "主胜")]
        )

        async with session_factory() as session:
            wins, losses = await settle_user_decisions(session)
            await session.commit()

        assert (wins, losses) == (0, 0)
        decisions = await _fetch_decisions(session_factory)
        assert decisions[decision_id].result_status == DecisionStatus.PUSH
        assert decisions[decision_id].profit_loss is None

    async def test_win_without_resolvable_odds_stays_push(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:赛果主胜但无 SP 也无在售赔率 -> 跳过,保持 PUSH
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 1)
        await _add_result(session_factory, match_ids[0], had="主胜")
        (decision_id,) = await _add_decisions(
            session_factory, 1, 100.0, [(match_ids[0], "HAD", "h", "主胜")]
        )

        async with session_factory() as session:
            wins, losses = await settle_user_decisions(session)
            await session.commit()

        assert (wins, losses) == (0, 0)
        decisions = await _fetch_decisions(session_factory)
        assert decisions[decision_id].result_status == DecisionStatus.PUSH

    async def test_sp_preferred_over_current_pools(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:池中 h=2.0 但 SP=2.5,应以 SP 结算
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 1)
        await _add_odds(session_factory, match_ids[0], _had_pools(h=2.0))
        await _add_result(session_factory, match_ids[0], had="主胜", sp_h=2.5)
        (decision_id,) = await _add_decisions(
            session_factory, 1, 100.0, [(match_ids[0], "HAD", "h", "主胜")]
        )

        async with session_factory() as session:
            await settle_user_decisions(session)
            await session.commit()

        decisions = await _fetch_decisions(session_factory)
        assert float(decisions[decision_id].profit_loss) == pytest.approx(150.0)

    async def test_ttg_7plus_boundary(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:总进球 8,押"7+"(s7)
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 1)
        await _add_odds(
            session_factory,
            match_ids[0],
            [
                {
                    "poolCode": "TTG",
                    "playName": "总进球",
                    "options": [{"code": "s7", "label": "7+", "odds": 30.0}],
                }
            ],
        )
        await _add_result(session_factory, match_ids[0], ttg="8")
        (decision_id,) = await _add_decisions(
            session_factory, 1, 10.0, [(match_ids[0], "TTG", "s7", "7+")]
        )

        async with session_factory() as session:
            wins, _ = await settle_user_decisions(session)
            await session.commit()

        decisions = await _fetch_decisions(session_factory)
        assert wins == 1
        assert decisions[decision_id].result_status == DecisionStatus.WIN
        assert float(decisions[decision_id].profit_loss) == pytest.approx(290.0)

    async def test_crs_and_hafu_hits(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:比分 1:2 + 半全场 负负
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 1)
        await _add_odds(
            session_factory,
            match_ids[0],
            [
                {
                    "poolCode": "CRS",
                    "playName": "比分",
                    "options": [{"code": "s01s02", "label": "1:2", "odds": 8.5}],
                },
                {
                    "poolCode": "HAFU",
                    "playName": "半全场",
                    "options": [{"code": "aa", "label": "负负", "odds": 6.0}],
                },
            ],
        )
        await _add_result(
            session_factory, match_ids[0], crs="1:2", hafu="负负"
        )
        decision_ids = await _add_decisions(
            session_factory,
            1,
            10.0,
            [
                (match_ids[0], "CRS", "s01s02", "1:2"),
                (match_ids[0], "HAFU", "aa", "负负"),
            ],
        )

        async with session_factory() as session:
            wins, _ = await settle_user_decisions(session)
            await session.commit()

        decisions = await _fetch_decisions(session_factory)
        assert wins == 2
        assert float(decisions[decision_ids[0]].profit_loss) == pytest.approx(75.0)
        assert float(decisions[decision_ids[1]].profit_loss) == pytest.approx(50.0)

    async def test_filters_by_user(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 1)
        await _add_result(session_factory, match_ids[0], had="主胜", sp_h=2.5)
        await _add_decisions(
            session_factory, 1, 100.0, [(match_ids[0], "HAD", "h", "主胜")]
        )
        await _add_decisions(
            session_factory, 2, 100.0, [(match_ids[0], "HAD", "h", "主胜")]
        )

        # Act:只结算用户 1
        async with session_factory() as session:
            wins, _ = await settle_user_decisions(session, user_id=1)
            await session.commit()

        # Assert:用户 2 保持 PUSH
        decisions = await _fetch_decisions(session_factory)
        statuses = {d.user_id: d.result_status for d in decisions.values()}
        assert statuses[1] == DecisionStatus.WIN
        assert statuses[2] == DecisionStatus.PUSH

    async def test_idempotent_rerun(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 1)
        await _add_result(session_factory, match_ids[0], had="主胜", sp_h=2.5)
        await _add_decisions(
            session_factory, 1, 100.0, [(match_ids[0], "HAD", "h", "主胜")]
        )

        async with session_factory() as session:
            first = await settle_user_decisions(session)
            await session.commit()
        async with session_factory() as session:
            second = await settle_user_decisions(session)
            await session.commit()

        assert first == (1, 0)
        assert second == (0, 0)


# ---------- 服务:串关方案结算 ----------

async def _seed_scheme(
    session_factory: async_sessionmaker,
    *,
    user_id: int = 1,
    parlay_size: int = 2,
    stake_per_bet: float = 100.0,
    legs: list[tuple[str, str, str, str, float]],
) -> int:
    """直接落库一个串关方案(含赔率快照),返回 scheme_id。"""
    from app.services.parlay import ParlayPick, save_bet_scheme

    async with session_factory() as session:
        scheme = await save_bet_scheme(
            session,
            user_id=user_id,
            parlay_size=parlay_size,
            stake_per_bet=stake_per_bet,
            picks=[
                ParlayPick(
                    match_id=match_id,
                    match_name="阿森纳 vs 切尔西",
                    pool_code=pool_code,
                    play_name=PLAY_NAMES[pool_code],
                    option_code=option_code,
                    option_label=option_label,
                    odds=odds,
                )
                for match_id, pool_code, option_code, option_label, odds in legs
            ],
        )
        await session.commit()
        return scheme.scheme_id


class TestSettleBetSchemes:
    """settle_bet_schemes:方案级输赢判定。"""

    async def test_scheme_full_win(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:两场全主胜,2串1 押 h(2.10 / 3.00)
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)
        for match_id in match_ids:
            await _add_result(session_factory, match_id, had="主胜")
        scheme_id = await _seed_scheme(
            session_factory,
            legs=[
                (match_ids[0], "HAD", "h", "主胜", 2.10),
                (match_ids[1], "HAD", "h", "主胜", 3.00),
            ],
        )

        # Act
        async with session_factory() as session:
            wins, losses = await settle_bet_schemes(session)
            await session.commit()

        # Assert
        assert (wins, losses) == (1, 0)
        schemes = await _fetch_schemes(session_factory)
        assert schemes[0].scheme_id == scheme_id
        assert schemes[0].status == "WIN"

    async def test_scheme_partial_loss(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:一场客胜 -> 无中奖注
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)
        await _add_result(session_factory, match_ids[0], had="主胜")
        await _add_result(session_factory, match_ids[1], had="客胜")
        await _seed_scheme(
            session_factory,
            legs=[
                (match_ids[0], "HAD", "h", "主胜", 2.10),
                (match_ids[1], "HAD", "h", "主胜", 3.00),
            ],
        )

        async with session_factory() as session:
            wins, losses = await settle_bet_schemes(session)
            await session.commit()

        assert (wins, losses) == (0, 1)
        schemes = await _fetch_schemes(session_factory)
        assert schemes[0].status == "LOSS"

    async def test_scheme_pending_when_result_missing(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)
        await _add_result(session_factory, match_ids[0], had="主胜")
        await _seed_scheme(
            session_factory,
            legs=[
                (match_ids[0], "HAD", "h", "主胜", 2.10),
                (match_ids[1], "HAD", "h", "主胜", 3.00),
            ],
        )

        async with session_factory() as session:
            wins, losses = await settle_bet_schemes(session)
            await session.commit()

        assert (wins, losses) == (0, 0)
        schemes = await _fetch_schemes(session_factory)
        assert schemes[0].status == "PENDING"

    async def test_scheme_3x1_partial_coverage_wins(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:3串1 四场(A/B/C 命中,D 未中)-> C(4,3) 组合中
        # 仅 {A,B,C} 一注中奖
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 4)
        for match_id in match_ids[:3]:
            await _add_result(session_factory, match_id, had="主胜")
        await _add_result(session_factory, match_ids[3], had="客胜")
        await _seed_scheme(
            session_factory,
            parlay_size=3,
            legs=[
                (match_ids[0], "HAD", "h", "主胜", 2.0),
                (match_ids[1], "HAD", "h", "主胜", 3.0),
                (match_ids[2], "HAD", "h", "主胜", 4.0),
                (match_ids[3], "HAD", "h", "主胜", 5.0),
            ],
        )

        async with session_factory() as session:
            wins, losses = await settle_bet_schemes(session)
            await session.commit()

        assert (wins, losses) == (1, 0)
        schemes = await _fetch_schemes(session_factory)
        assert schemes[0].status == "WIN"


class TestComputeSchemePayout:
    """compute_scheme_payout:中奖注枚举分解。"""

    async def test_duplex_with_winning_combo(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:2串1,A 场双选 h(2.0)+d(3.0) 开平,B 场 h(1.5) 开主胜
        # 中奖注 = d x h => 回报 = 100 x (3.0 x 1.5) = 450
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)
        await _add_result(session_factory, match_ids[0], had="平")
        await _add_result(session_factory, match_ids[1], had="主胜")
        scheme_id = await _seed_scheme(
            session_factory,
            legs=[
                (match_ids[0], "HAD", "h", "主胜", 2.0),
                (match_ids[0], "HAD", "d", "平", 3.0),
                (match_ids[1], "HAD", "h", "主胜", 1.5),
            ],
        )
        schemes = await _fetch_schemes(session_factory)
        scheme = next(s for s in schemes if s.scheme_id == scheme_id)

        results = {
            match_ids[0]: MatchResult(match_id=match_ids[0], had="平"),
            match_ids[1]: MatchResult(match_id=match_ids[1], had="主胜"),
        }

        # Act
        payout = compute_scheme_payout(
            list(scheme.items), results, parlay_size=2, stake_per_bet=100.0
        )

        # Assert:Σ_{中奖注} Π odds = 3.0 x 1.5(每场命中选项赔率和之积)
        assert payout == pytest.approx(450.0)

    async def test_returns_none_when_result_missing(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)
        scheme_id = await _seed_scheme(
            session_factory,
            legs=[
                (match_ids[0], "HAD", "h", "主胜", 2.0),
                (match_ids[1], "HAD", "h", "主胜", 3.0),
            ],
        )
        schemes = await _fetch_schemes(session_factory)
        scheme = next(s for s in schemes if s.scheme_id == scheme_id)

        payout = compute_scheme_payout(
            list(scheme.items), {match_ids[0]: MatchResult(match_id=match_ids[0], had="主胜")},
            parlay_size=2,
            stake_per_bet=100.0,
        )
        assert payout is None

    async def test_mixed_hits_duplex_sums_per_match(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:A 场双选 d(3.0)+a(4.0) 开平,B 场开客胜押 h
        # -> A 场命中和 = 3.0,B 场 = 0 => 回报 0
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)
        scheme_id = await _seed_scheme(
            session_factory,
            legs=[
                (match_ids[0], "HAD", "d", "平", 3.0),
                (match_ids[0], "HAD", "a", "客胜", 4.0),
                (match_ids[1], "HAD", "h", "主胜", 1.5),
            ],
        )
        schemes = await _fetch_schemes(session_factory)
        scheme = next(s for s in schemes if s.scheme_id == scheme_id)
        results = {
            match_ids[0]: MatchResult(match_id=match_ids[0], had="平"),
            match_ids[1]: MatchResult(match_id=match_ids[1], had="客胜"),
        }

        payout = compute_scheme_payout(
            list(scheme.items), results, parlay_size=2, stake_per_bet=50.0
        )
        assert payout == pytest.approx(0.0)


# ---------- 接口 ----------

async def _seed_review_scenario(
    session_factory: async_sessionmaker,
) -> dict[str, typing.Any]:
    """预置复盘统计场景,返回关键 ID。

    - m1 (09-19):主胜 sp_h 2.5;决策 WIN 150;池 h=2.15/d=3.20/a=3.05
    - m2 (09-20):客胜 sp_a 3.1、sp_h 2.2;决策(押 h)LOSS -100
    - m3 (09-21):平 sp_d 3.3;决策(押 d 50)WIN 115
    - m4 (09-22):无赛果;决策 PUSH(80)
    - 串关 2串1:m1 押 h(2.10) + m2 押 a(3.05),WIN,盈亏 540.5
    """
    match_ids = await _seed_matches(session_factory, 4)
    await _add_odds(session_factory, match_ids[0], _had_pools())
    await _add_odds(session_factory, match_ids[1], _had_pools())
    await _add_odds(session_factory, match_ids[2], _had_pools())
    await _add_result(
        session_factory, match_ids[0], had="主胜", sp_h=2.5, sp_d=3.4, sp_a=3.2
    )
    await _add_result(
        session_factory, match_ids[1], had="客胜", sp_h=2.2, sp_d=3.3, sp_a=3.1
    )
    await _add_result(
        session_factory, match_ids[2], had="平", sp_h=2.6, sp_d=3.3, sp_a=2.9
    )
    decision_ids = await _add_decisions(
        session_factory,
        1,
        100.0,
        [
            (match_ids[0], "HAD", "h", "主胜"),  # WIN 150
            (match_ids[1], "HAD", "h", "主胜"),  # LOSS -100
        ],
    )
    await _add_decisions(
        session_factory,
        1,
        50.0,
        [(match_ids[2], "HAD", "d", "平")],  # WIN 50 x (3.3-1) = 115
    )
    await _add_decisions(
        session_factory,
        1,
        80.0,
        [(match_ids[3], "HAD", "h", "主胜")],  # PUSH
    )
    scheme_id = await _seed_scheme(
        session_factory,
        legs=[
            (match_ids[0], "HAD", "h", "主胜", 2.10),
            (match_ids[1], "HAD", "a", "客胜", 3.05),
        ],
    )
    return {
        "match_ids": match_ids,
        "decision_ids": decision_ids,
        "scheme_id": scheme_id,
    }


class TestSettlementEndpoint:
    """POST /api/v1/strategy/settlement"""

    async def test_settles_and_returns_counts(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        await _seed_review_scenario(session_factory)

        # Act
        resp = await async_client.post("/api/v1/strategy/settlement", json={})

        # Assert:2 决策 WIN、1 决策 LOSS;1 方案 WIN
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "decision_wins": 2,
            "decision_losses": 1,
            "scheme_wins": 1,
            "scheme_losses": 0,
        }

        # 幂等:再次触发全为 0
        resp_again = await async_client.post(
            "/api/v1/strategy/settlement", json={}
        )
        assert resp_again.json() == {
            "decision_wins": 0,
            "decision_losses": 0,
            "scheme_wins": 0,
            "scheme_losses": 0,
        }

    async def test_settles_by_user(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        async_client, session_factory = env
        await _seed_review_scenario(session_factory)

        resp = await async_client.post(
            "/api/v1/strategy/settlement", json={"user_id": 1}
        )
        assert resp.status_code == 200
        assert resp.json()["decision_wins"] == 2


class TestReviewStatsEndpoint:
    """GET /api/v1/strategy/review/stats"""

    async def test_aggregates_kpi_curve_and_dimensions(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        await _seed_review_scenario(session_factory)
        settle_resp = await async_client.post(
            "/api/v1/strategy/settlement", json={}
        )
        assert settle_resp.status_code == 200

        # Act
        resp = await async_client.get(
            "/api/v1/strategy/review/stats", params={"user_id": 1}
        )

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        kpi = body["kpi"]
        # 总注数 4 决策 + 1 方案;已结算 4(3 决策 + 1 方案);待结算 1
        assert kpi["total_bets"] == 5
        assert kpi["settled"] == 4
        assert kpi["pending"] == 1
        assert kpi["win_count"] == 3
        assert kpi["hit_rate"] == pytest.approx(0.75)
        # 累计投入 = 100+100+50+80 + 100(方案) = 430
        assert kpi["total_stake"] == pytest.approx(430.0)
        # 累计盈亏 = 150 - 100 + 115 + (100x2.10x3.05 - 100) = 705.5
        assert kpi["total_profit"] == pytest.approx(705.5)
        assert kpi["roi"] == pytest.approx(round(705.5 / 430.0, 4))
        # 事件流:d1 WIN -> (d2 LOSS, 方案 WIN) -> d3 WIN => 最大连红 2
        assert kpi["max_win_streak"] == 2

        # 盈亏曲线:4 个事件点,首点 +150,末点 705.5
        curve = body["profit_curve"]
        assert len(curve) == 4
        assert curve[0]["cumulative_profit"] == pytest.approx(150.0)
        assert curve[-1]["cumulative_profit"] == pytest.approx(705.5)

        # 按玩法:全部 HAD,5 条已结算选注(3 决策 + 2 串关腿)命中 4
        by_play = body["by_play"]
        assert by_play == [
            {"name": "胜平负", "count": 5, "hits": 4, "hit_rate": 0.8}
        ]

        # 按赔率区间:决策 d1 2.5/d2 2.2/d3 3.3 + 腿 2.10/3.05
        by_odds = {d["name"]: d for d in body["by_odds_range"]}
        assert by_odds["高赔 ≥2.50"]["count"] == 3
        assert by_odds["高赔 ≥2.50"]["hits"] == 3
        assert by_odds["中赔 1.80-2.50"]["count"] == 2
        assert by_odds["中赔 1.80-2.50"]["hits"] == 1

        # 按联赛:全部英超
        assert body["by_league"] == [
            {"name": "英格兰超级联赛", "count": 5, "hits": 4, "hit_rate": 0.8}
        ]

    async def test_empty_user_returns_zero_kpi(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        async_client, _ = env
        resp = await async_client.get(
            "/api/v1/strategy/review/stats", params={"user_id": 999}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["kpi"]["total_bets"] == 0
        assert body["kpi"]["hit_rate"] == 0.0
        assert body["profit_curve"] == []
        assert body["by_play"] == []


class TestReviewDecisionsEndpoint:
    """GET /api/v1/strategy/review/decisions"""

    async def test_returns_rich_rows_ordered_desc(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange
        async_client, session_factory = env
        ids = await _seed_review_scenario(session_factory)
        settle_resp = await async_client.post(
            "/api/v1/strategy/settlement", json={}
        )
        assert settle_resp.status_code == 200

        # Act
        resp = await async_client.get(
            "/api/v1/strategy/review/decisions",
            params={"user_id": 1, "limit": 50},
        )

        # Assert:按比赛时间倒序(m4 -> m3 -> m2 -> m1)
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 4
        assert [r["match_id"] for r in rows] == [
            ids["match_ids"][3],
            ids["match_ids"][2],
            ids["match_ids"][1],
            ids["match_ids"][0],
        ]
        first = rows[0]
        assert first["match_name"] == "阿森纳 vs 切尔西"
        assert first["league_name"] == "英格兰超级联赛"
        assert first["play_name"] == "胜平负"
        assert first["option_label"] == "主胜"
        assert first["result_label"] is None
        assert first["odds"] is None
        assert first["result_status"] == "PUSH"
        # 已结算行:赛果/赔率/盈亏齐全
        settled_row = rows[3]
        assert settled_row["result_label"] == "主胜"
        assert settled_row["odds"] == pytest.approx(2.5)
        assert settled_row["result_status"] == "WIN"
        assert settled_row["profit_loss"] == pytest.approx(150.0)

    async def test_filters_by_status(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        async_client, session_factory = env
        await _seed_review_scenario(session_factory)
        await async_client.post("/api/v1/strategy/settlement", json={})

        resp = await async_client.get(
            "/api/v1/strategy/review/decisions",
            params={"user_id": 1, "result_status": "WIN"},
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 2
        assert {r["result_status"] for r in rows} == {"WIN"}


class TestBetSchemesAnnotations:
    """GET /api/v1/strategy/bet-schemes:逐腿赛果/命中与实时盈亏"""

    async def test_annotates_items_and_profit(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:结算后方案 WIN
        async_client, session_factory = env
        ids = await _seed_review_scenario(session_factory)
        settle_resp = await async_client.post(
            "/api/v1/strategy/settlement", json={}
        )
        assert settle_resp.status_code == 200

        # Act
        resp = await async_client.get(
            "/api/v1/strategy/bet-schemes", params={"user_id": 1}
        )

        # Assert
        assert resp.status_code == 200
        schemes = resp.json()
        assert len(schemes) == 1
        scheme = schemes[0]
        assert scheme["scheme_id"] == ids["scheme_id"]
        assert scheme["status"] == "WIN"
        # 盈亏 = 100 x 2.10 x 3.05 - 100 = 540.5
        assert scheme["profit_loss"] == pytest.approx(540.5)
        items = scheme["items"]
        assert [(i["result_label"], i["is_hit"]) for i in items] == [
            ("主胜", True),
            ("客胜", True),
        ]

    async def test_pending_scheme_has_null_profit_and_hits(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        # Arrange:一场无赛果的方案
        async_client, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)
        await _add_result(session_factory, match_ids[0], had="主胜")
        await _seed_scheme(
            session_factory,
            legs=[
                (match_ids[0], "HAD", "h", "主胜", 2.10),
                (match_ids[1], "HAD", "h", "主胜", 3.00),
            ],
        )

        resp = await async_client.get(
            "/api/v1/strategy/bet-schemes", params={"user_id": 1}
        )

        assert resp.status_code == 200
        scheme = resp.json()[0]
        assert scheme["status"] == "PENDING"
        assert scheme["profit_loss"] is None
        items = scheme["items"]
        assert items[0]["result_label"] == "主胜"
        assert items[0]["is_hit"] is True
        assert items[1]["result_label"] is None
        assert items[1]["is_hit"] is None


class TestRunSettlement:
    """run_settlement:决策 + 方案一次结算。"""

    async def test_settles_both(
        self, env: tuple[AsyncClient, async_sessionmaker]
    ) -> None:
        _, session_factory = env
        match_ids = await _seed_matches(session_factory, 2)
        await _add_result(session_factory, match_ids[0], had="主胜", sp_h=2.5)
        await _add_result(session_factory, match_ids[1], had="主胜")
        await _add_decisions(
            session_factory, 1, 100.0, [(match_ids[0], "HAD", "h", "主胜")]
        )
        await _seed_scheme(
            session_factory,
            legs=[
                (match_ids[0], "HAD", "h", "主胜", 2.10),
                (match_ids[1], "HAD", "h", "主胜", 3.00),
            ],
        )

        async with session_factory() as session:
            result = await run_settlement(session)
            await session.commit()

        assert result.decision_wins == 1
        assert result.decision_losses == 0
        assert result.scheme_wins == 1
        assert result.scheme_losses == 0
