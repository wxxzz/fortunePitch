"""AI 策略推荐引擎服务层测试(recommendation_engine)。

覆盖:
- generate_batch:每场仅取最新分析、置信度阈值过滤、非 PENDING 与
  不可解析条目计入 skipped、EV/隐含概率/凯利/逆向标记数值断言、
  重算 SUPERSEDED 幂等(旧批次历史保留,查询只看 ACTIVE);
- _build_parlay_plans:每场仅取一条代表腿、组合乘积口径、
  腿不足的档位不硬凑、逆向腿数硬约束、
  复合档位(6 场 3/4 串、5 场 3 串)的平均单注指标口径;
- convert_pick_to_decision:桥接 Recommendation 落库口径、幂等、
  批次失效/比赛开赛 422、不存在 404;
- convert_plan_to_scheme:经 save_bet_scheme 物化、幂等、批次失效 422、
  复合方案按 C(腿数, N) 组合口径计算注数。
"""

import datetime
import itertools
import math
import typing

import pytest
from sqlalchemy import select
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import DataValidationError, ResourceNotFoundError
from app.core.database import Base
from app.models import (
    AiParlayPlan,
    AiPick,
    AiPickBatch,
    League,
    MatchGame,
    MatchLlmAnalysis,
    MatchLlmPlayRec,
    MatchOdds,
    Team,
    UserDecision,
)
from app.services import recommendation_engine

# 测试售卖日
BATCH_DATE = datetime.date(2026, 9, 17)


@pytest.fixture
async def session_factory() -> typing.AsyncGenerator[async_sessionmaker, None]:
    """内存 SQLite 会话工厂(外键约束开启,对齐生产提交口径)。"""
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _add_analysis(
    session: object, match_id: str, plays: list[dict]
) -> None:
    """挂一条分析 + 分玩法推荐明细。"""
    analysis = MatchLlmAnalysis(
        match_id=match_id,
        provider="qwen",
        model="qwen3.7-plus",
        summary="整体研判",
        risks=[],
    )
    session.add(analysis)
    await session.flush()
    for play in plays:
        session.add(
            MatchLlmPlayRec(
                analysis_id=analysis.analysis_id,
                play_code=play["code"],
                play_name=play["name"],
                recommendation=play["recommendation"],
                confidence=play["confidence"],
                reasoning=play["reasoning"],
                alternatives=[],
            )
        )


def _had_pool(odds: list[float]) -> list[dict]:
    """构造 HAD 赔率池(主/平/客三选项)。"""
    return [
        {
            "poolCode": "HAD",
            "playName": "胜平负",
            "options": [
                {"code": "h", "label": "主胜", "odds": odds[0]},
                {"code": "d", "label": "平", "odds": odds[1]},
                {"code": "a", "label": "客胜", "odds": odds[2]},
            ],
        }
    ]


async def _seed_pending_matches(
    factory: async_sessionmaker, count: int
) -> None:
    """预置 count 场 PENDING 比赛(在售 HAD 2.0/4.0/4.0),各挂主胜分析。

    供复合串关档位(需 ≥5 场代表腿)的数据库级测试使用。
    """
    async with factory() as session:
        league = League(
            league_name="意大利甲级联赛", country="意大利", tier=1, season="2026-2027"
        )
        session.add(league)
        await session.flush()
        home = Team(team_name="国际米兰", league_id=league.league_id)
        away = Team(team_name="AC米兰", league_id=league.league_id)
        session.add_all([home, away])
        await session.flush()
        for idx in range(count):
            session.add(
                MatchGame(
                    match_id=f"c-{idx + 1}",
                    match_num_str=f"周六{idx + 1:03d}",
                    league_id=league.league_id,
                    home_team_id=home.team_id,
                    away_team_id=away.team_id,
                    match_time=datetime.datetime(2026, 9, 17, 21, 0),
                    business_date=BATCH_DATE,
                    match_status="PENDING",
                )
            )
        await session.flush()
        for idx in range(count):
            session.add(
                MatchOdds(
                    match_id=f"c-{idx + 1}",
                    pools=_had_pool([2.0, 4.0, 4.0]),
                    update_time=datetime.datetime(2026, 9, 16, 10, 0),
                )
            )
        await session.flush()
        for idx in range(count):
            await _add_analysis(
                session,
                f"c-{idx + 1}",
                [
                    {
                        "code": "HAD",
                        "name": "胜平负",
                        "recommendation": "主胜",
                        "confidence": 0.80,
                        "reasoning": "复合串关测试",
                    }
                ],
            )
        await session.commit()


async def _seed(factory: async_sessionmaker) -> None:
    """预置五场比赛:

    - m1:在售 HAD 2.0/4.0/4.0(隐含主胜概率恰为 0.5),两次分析
      (旧分析客胜 0.95 应被最新分析主胜 0.80 覆盖);
    - m2:同池,分析主胜 0.70;
    - m3:同池,分析主胜 0.65 + 总进球 3球 0.90(TTG 未开售,应跳过);
    - m4:在售 HAD 1.5/4.0/6.0(隐含主胜概率 8/13≈0.6154),
      分析主胜 0.60 -> 逆向腿(confidence < implied);
    - m5:已完赛(FINISHED),分析主胜 0.90 -> 跳过(非 PENDING)。
    """
    async with factory() as session:
        league = League(league_name="西班牙甲级联赛", country="西班牙", tier=1, season="2026-2027")
        session.add(league)
        await session.flush()
        home = Team(team_name="巴塞罗那", league_id=league.league_id)
        away = Team(team_name="皇家马德里", league_id=league.league_id)
        session.add_all([home, away])
        await session.flush()

        statuses = ("PENDING", "PENDING", "PENDING", "PENDING", "FINISHED")
        for idx, match_id in enumerate(("m-1", "m-2", "m-3", "m-4", "m-5")):
            session.add(
                MatchGame(
                    match_id=match_id,
                    match_num_str=f"周四{idx + 1:03d}",
                    league_id=league.league_id,
                    home_team_id=home.team_id,
                    away_team_id=away.team_id,
                    match_time=datetime.datetime(2026, 9, 17, 21, 0),
                    business_date=BATCH_DATE,
                    match_status=statuses[idx],
                )
            )
        await session.flush()

        for match_id, odds in (
            ("m-1", [2.0, 4.0, 4.0]),
            ("m-2", [2.0, 4.0, 4.0]),
            ("m-3", [2.0, 4.0, 4.0]),
            ("m-4", [1.5, 4.0, 6.0]),
            ("m-5", [2.0, 4.0, 4.0]),
        ):
            session.add(
                MatchOdds(
                    match_id=match_id,
                    pools=_had_pool(odds),
                    update_time=datetime.datetime(2026, 9, 16, 10, 0),
                )
            )
        await session.flush()

        # m1 旧分析(高置信度,但应被最新分析覆盖)
        await _add_analysis(
            session,
            "m-1",
            [
                {
                    "code": "HAD",
                    "name": "胜平负",
                    "recommendation": "客胜",
                    "confidence": 0.95,
                    "reasoning": "旧分析依据",
                }
            ],
        )
        await _add_analysis(
            session,
            "m-1",
            [
                {
                    "code": "HAD",
                    "name": "胜平负",
                    "recommendation": "主胜",
                    "confidence": 0.80,
                    "reasoning": "主队主场强势",
                }
            ],
        )
        await _add_analysis(
            session,
            "m-2",
            [
                {
                    "code": "HAD",
                    "name": "胜平负",
                    "recommendation": "主胜",
                    "confidence": 0.70,
                    "reasoning": "交锋占优",
                }
            ],
        )
        await _add_analysis(
            session,
            "m-3",
            [
                {
                    "code": "HAD",
                    "name": "胜平负",
                    "recommendation": "主胜",
                    "confidence": 0.65,
                    "reasoning": "阵容齐整",
                },
                {
                    "code": "TTG",
                    "name": "总进球",
                    "recommendation": "3球",
                    "confidence": 0.90,
                    "reasoning": "攻强守弱(TTG 未开售,应跳过)",
                },
            ],
        )
        await _add_analysis(
            session,
            "m-4",
            [
                {
                    "code": "HAD",
                    "name": "胜平负",
                    "recommendation": "主胜",
                    "confidence": 0.60,
                    "reasoning": "浅盘,市场隐含概率更高",
                }
            ],
        )
        await _add_analysis(
            session,
            "m-5",
            [
                {
                    "code": "HAD",
                    "name": "胜平负",
                    "recommendation": "主胜",
                    "confidence": 0.90,
                    "reasoning": "已完赛,应跳过",
                }
            ],
        )
        await session.commit()


def _make_pick(
    match_id: str,
    *,
    play_code: str = "HAD",
    play_name: str = "胜平负",
    odds: float = 2.0,
    confidence: float = 0.8,
    implied: float = 0.5,
    ev: float | None = None,
    is_contrarian: bool = False,
) -> AiPick:
    """构造未落库的 AiPick(供 _build_parlay_plans 纯逻辑测试)。"""
    return AiPick(
        batch_id=1,
        match_id=match_id,
        analysis_id=1,
        play_code=play_code,
        play_name=play_name,
        recommendation="主胜",
        option_code="h",
        option_label="主胜",
        odds=odds,
        confidence=confidence,
        implied_prob=implied,
        ev=ev if ev is not None else confidence * odds - 1.0,
        kelly=0.1,
        is_contrarian=is_contrarian,
        reasoning="",
    )


class TestGenerateBatch:
    """recommendation_engine.generate_batch"""

    async def test_generates_picks_with_metrics(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange
        await _seed(session_factory)

        # Act
        async with session_factory() as session:
            summary = await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()

        # Assert:4 条入选(m1/m2/m3 HAD + m4 HAD),
        # 2 条跳过(m3 TTG 未开售 + m5 已完赛)
        batch = summary.batch
        assert batch.pick_count == 4
        assert batch.skipped_count == 2
        assert summary.superseded_batch_ids == []
        assert float(batch.min_confidence) == pytest.approx(0.55)

        async with session_factory() as session:
            picks = {
                p.match_id: p
                for p in (
                    await session.execute(
                        select(AiPick).where(AiPick.batch_id == batch.batch_id)
                    )
                )
                .scalars()
                .all()
            }
        assert set(picks) == {"m-1", "m-2", "m-3", "m-4"}

        # m1 取最新分析(主胜 0.80),不是旧分析客胜 0.95
        m1 = picks["m-1"]
        assert m1.recommendation == "主胜"
        assert float(m1.confidence) == pytest.approx(0.80)
        assert m1.option_code == "h"
        assert float(m1.odds) == pytest.approx(2.0)
        # 去水隐含概率 0.5(1/2 / (1/2+1/4+1/4)),EV = 0.8*2-1
        assert float(m1.implied_prob) == pytest.approx(0.5)
        assert float(m1.ev) == pytest.approx(0.6)
        assert float(m1.kelly) == pytest.approx(0.6)
        assert m1.is_contrarian is False

        # m4 逆向腿:confidence 0.60 < implied 8/13,EV = 0.6*1.5-1 < 0,凯利 0
        m4 = picks["m-4"]
        # 列宽 Numeric(8,4),与 8/13 的差在 4 位小数舍入内
        assert float(m4.implied_prob) == pytest.approx(8.0 / 13.0, abs=1e-4)
        assert m4.is_contrarian is True
        assert float(m4.ev) == pytest.approx(-0.1)
        assert float(m4.kelly) == 0.0

    async def test_min_confidence_filters_at_query_level(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange:阈值 0.7 -> m3 HAD 0.65 与 m4 0.60 在查询层被过滤(不计 skipped)
        await _seed(session_factory)

        # Act
        async with session_factory() as session:
            summary = await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE, min_confidence=0.7
            )
            await session.commit()

        # Assert:入选 m1 0.80 / m2 0.70;跳过仍为 m3 TTG + m5
        assert summary.batch.pick_count == 2
        assert summary.batch.skipped_count == 2

    async def test_regeneration_supersedes_old_batch(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange
        await _seed(session_factory)
        async with session_factory() as session:
            first = await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()
        first_batch_id = first.batch.batch_id

        # Act:同售卖日重算
        async with session_factory() as session:
            second = await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()

        # Assert:旧批次置 SUPERSEDED,新批次 ACTIVE;
        # 旧推荐历史保留,查询只看最新生效批次
        assert second.superseded_batch_ids == [first_batch_id]
        async with session_factory() as session:
            old = await session.get(AiPickBatch, first_batch_id)
            assert old is not None and old.status == "SUPERSEDED"
            total_picks = len(
                (
                    await session.execute(select(AiPick))
                )
                .scalars()
                .all()
            )
            active_picks = await recommendation_engine.list_active_picks(
                session, business_date=BATCH_DATE
            )
        assert total_picks == 8  # 两批各 4 条,历史保留
        assert len(active_picks) == 4
        assert all(p.batch_id == second.batch.batch_id for p in active_picks)

    async def test_empty_date_produces_empty_batch(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange / Act:无分析的售卖日
        async with session_factory() as session:
            summary = await recommendation_engine.generate_batch(
                session, business_date=datetime.date(2025, 1, 1)
            )
            await session.commit()

        # Assert
        assert summary.batch.pick_count == 0
        assert summary.batch.skipped_count == 0
        assert summary.batch.plan_count == 0


class TestParlayPlanBuilding:
    """generate_batch 产出的串关候选与 _build_parlay_plans 纯逻辑。"""

    async def test_generates_four_plans_with_combined_metrics(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange:m1/m2/m3 为顺向腿(0.8/0.7/0.65 > 0.5),m4 为逆向腿
        await _seed(session_factory)

        # Act
        async with session_factory() as session:
            summary = await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()

        # Assert:稳胆 2/3/4串1 + 价值混合 2串1,共 4 档
        async with session_factory() as session:
            plans = await recommendation_engine.list_active_plans(
                session, business_date=BATCH_DATE
            )
        assert summary.batch.plan_count == 4
        by_name = {p.plan_name: p for p in plans}
        assert set(by_name) == {"稳胆 2串1", "稳胆 3串1", "稳胆 4串1", "价值混合 2串1"}

        chalk2 = by_name["稳胆 2串1"]
        assert chalk2.parlay_size == 2
        assert [leg["match_id"] for leg in chalk2.legs] == ["m-1", "m-2"]
        assert float(chalk2.combined_odds) == pytest.approx(4.0)  # 2.0 * 2.0
        assert float(chalk2.combined_confidence) == pytest.approx(0.56)  # 0.8*0.7
        assert float(chalk2.ev) == pytest.approx(0.56 * 4.0 - 1.0)
        assert chalk2.contrarian_count == 0
        # 腿快照含场次编号与对阵
        assert chalk2.legs[0]["match_num_str"] == "周四001"

        chalk4 = by_name["稳胆 4串1"]
        # 3 顺向 + 1 逆向(m4)
        assert [leg["match_id"] for leg in chalk4.legs] == ["m-1", "m-2", "m-3", "m-4"]
        assert chalk4.contrarian_count == 1
        assert float(chalk4.combined_odds) == pytest.approx(12.0)  # 2^3 * 1.5
        assert chalk4.legs[3]["is_contrarian"] is True

        mixed = by_name["价值混合 2串1"]
        assert [leg["match_id"] for leg in mixed.legs] == ["m-1", "m-4"]
        assert mixed.contrarian_count == 1
        # 所有方案逆向腿数均不超上限
        assert all(p.contrarian_count <= 2 for p in plans)

    async def test_underpopulated_tiers_are_skipped(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange:阈值 0.7 后仅 2 条顺向腿 -> 只有稳胆 2串1
        await _seed(session_factory)

        # Act
        async with session_factory() as session:
            summary = await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE, min_confidence=0.7
            )
            await session.commit()

        # Assert
        async with session_factory() as session:
            plans = await recommendation_engine.list_active_plans(
                session, business_date=BATCH_DATE
            )
        assert summary.batch.plan_count == 1
        assert [p.plan_name for p in plans] == ["稳胆 2串1"]

    def test_one_leg_per_match_even_with_multiple_plays(self) -> None:
        # Arrange:同一场比赛两条玩法推荐,EV 高者入选代表腿
        picks = [
            _make_pick("m-1", odds=2.0, confidence=0.8),
            _make_pick(
                "m-1",
                play_code="TTG",
                play_name="总进球",
                odds=3.5,
                confidence=0.6,
                ev=0.6 * 3.5 - 1.0,
            ),
            _make_pick("m-2", odds=1.9, confidence=0.75),
        ]
        match_info = {
            "m-1": ("周四001", "主队A vs 客队B"),
            "m-2": ("周四002", "主队C vs 客队D"),
        }

        # Act
        plans = recommendation_engine._build_parlay_plans(1, picks, match_info)

        # Assert:唯一方案的两条腿分属不同比赛,每场一玩法
        assert len(plans) == 1
        leg_match_ids = {leg["match_id"] for leg in plans[0].legs}
        assert leg_match_ids == {"m-1", "m-2"}

    def test_no_plans_when_no_chalk_legs(self) -> None:
        # Arrange:全部为逆向腿时无稳胆/混合档可组
        picks = [
            _make_pick("m-1", confidence=0.6, implied=0.7, is_contrarian=True),
            _make_pick("m-2", confidence=0.6, implied=0.7, is_contrarian=True),
        ]

        # Act
        plans = recommendation_engine._build_parlay_plans(
            1, picks, {"m-1": ("a", "x"), "m-2": ("b", "y")}
        )

        # Assert
        assert plans == []

    @staticmethod
    def _six_chalk_picks() -> list[AiPick]:
        """六场顺向代表腿(置信度/赔率各异,供复合档位指标断言)。"""
        specs = (
            ("m-1", 2.0, 0.80),
            ("m-2", 1.8, 0.70),
            ("m-3", 2.5, 0.60),
            ("m-4", 1.5, 0.75),
            ("m-5", 3.0, 0.55),
            ("m-6", 2.2, 0.65),
        )
        return [
            _make_pick(match_id, odds=odds, confidence=conf)
            for match_id, odds, conf in specs
        ]

    def test_composite_six_matches_plans_with_average_metrics(self) -> None:
        # Arrange:6 场顺向代表腿 -> 追加 复合 6场3串1 / 复合 6场4串1
        picks = self._six_chalk_picks()
        match_info = {f"m-{i}": (f"周六{i:03d}", f"主{i} vs 客{i}") for i in range(1, 7)}

        # Act
        plans = recommendation_engine._build_parlay_plans(1, picks, match_info)

        # Assert:3 个单式档 + 2 个复合档
        by_name = {p.plan_name: p for p in plans}
        assert set(by_name) == {
            "稳胆 2串1", "稳胆 3串1", "稳胆 4串1",
            "复合 6场3串1", "复合 6场4串1",
        }

        comp3 = by_name["复合 6场3串1"]
        assert comp3.parlay_size == 3
        assert len(comp3.legs) == 6
        assert comp3.contrarian_count == 0
        # 指标口径:组合赔率 = 最高单注赔率;置信度/EV = 平均单注
        combo_odds = [
            math.prod(leg["odds"] for leg in combo)
            for combo in itertools.combinations(comp3.legs, 3)
        ]
        combo_conf = [
            math.prod(leg["confidence"] for leg in combo)
            for combo in itertools.combinations(comp3.legs, 3)
        ]
        assert len(combo_odds) == 20  # C(6,3)
        assert float(comp3.combined_odds) == pytest.approx(max(combo_odds))
        assert float(comp3.combined_confidence) == pytest.approx(
            sum(combo_conf) / len(combo_conf), abs=1e-4
        )
        assert float(comp3.ev) == pytest.approx(
            sum(c * o for c, o in zip(combo_conf, combo_odds)) / len(combo_odds) - 1.0,
            abs=1e-4,
        )

        comp4 = by_name["复合 6场4串1"]
        assert comp4.parlay_size == 4
        assert len(comp4.legs) == 6
        # 说明文案带平均单注口径标注
        assert "平均单注" in comp4.plan_desc

    def test_composite_five_matches_degrades_to_3leg(self) -> None:
        # Arrange:恰 5 场代表腿 -> 复合档降级为 5场3串1(C(5,3)=10 注)
        picks = self._six_chalk_picks()[:5]
        match_info = {f"m-{i}": (f"周六{i:03d}", f"主{i} vs 客{i}") for i in range(1, 6)}

        # Act
        plans = recommendation_engine._build_parlay_plans(1, picks, match_info)

        # Assert:复合档只有 5场3串1,无 6 场档
        by_name = {p.plan_name: p for p in plans}
        assert "复合 5场3串1" in by_name
        assert not any(name.startswith("复合 6场") for name in by_name)
        comp = by_name["复合 5场3串1"]
        assert comp.parlay_size == 3
        assert len(comp.legs) == 5

    def test_composite_legs_fill_value_capped_at_two(self) -> None:
        # Arrange:4 顺向 + 3 逆向 -> 复合 6 场档补 2 条逆向(硬上限)
        picks = self._six_chalk_picks()[:4] + [
            _make_pick("v-1", confidence=0.45, implied=0.6, is_contrarian=True),
            _make_pick("v-2", confidence=0.40, implied=0.6, is_contrarian=True),
            _make_pick("v-3", confidence=0.35, implied=0.6, is_contrarian=True),
        ]
        match_info = {
            **{f"m-{i}": (f"周六{i:03d}", f"主{i} vs 客{i}") for i in range(1, 5)},
            **{f"v-{i}": (f"周日{i:03d}", f"主{i} vs 客{i}") for i in range(1, 4)},
        }

        # Act
        plans = recommendation_engine._build_parlay_plans(1, picks, match_info)

        # Assert:逆向补位恰 2 条(第 3 条逆向不进方案)
        by_name = {p.plan_name: p for p in plans}
        comp3 = by_name["复合 6场3串1"]
        assert len(comp3.legs) == 6
        assert comp3.contrarian_count == 2
        assert all(p.contrarian_count <= 2 for p in plans)


class TestConvertPickToDecision:
    """recommendation_engine.convert_pick_to_decision"""

    @staticmethod
    async def _first_pick_id(
        factory: async_sessionmaker, match_id: str
    ) -> int:
        async with factory() as session:
            pick = (
                await session.execute(
                    select(AiPick).where(AiPick.match_id == match_id)
                )
            ).scalar_one()
            return pick.pick_id

    async def test_creates_bridged_decision(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange
        await _seed(session_factory)
        async with session_factory() as session:
            await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()
        pick_id = await self._first_pick_id(session_factory, "m-1")

        # Act
        async with session_factory() as session:
            decision, created = await recommendation_engine.convert_pick_to_decision(
                session, pick_id=pick_id, user_id=1, stake_amount=100
            )
            await session.commit()

        # Assert:桥接 Recommendation + UserDecision 落库,决策指针回填
        assert created is True
        assert decision.user_bet_type == "HAD:h"
        assert float(decision.stake_amount) == pytest.approx(100)
        async with session_factory() as session:
            pick = await session.get(AiPick, pick_id)
            assert pick is not None and pick.decision_id == decision.decision_id
            from app.models import Recommendation

            recommendation = await session.get(
                Recommendation, decision.recommend_id
            )
            assert recommendation is not None
            assert recommendation.strategy_type == "WIN_DRAW_LOSS"
            assert recommendation.predicted_outcome == "主胜"
            assert float(recommendation.confidence_score) == pytest.approx(0.80)
            assert recommendation.logic_tags == ["AI推荐", "胜平负"]

    async def test_convert_is_idempotent(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange
        await _seed(session_factory)
        async with session_factory() as session:
            await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()
        pick_id = await self._first_pick_id(session_factory, "m-1")

        # Act:重复转换
        async with session_factory() as session:
            first, created_first = (
                await recommendation_engine.convert_pick_to_decision(
                    session, pick_id=pick_id, user_id=1, stake_amount=100
                )
            )
            await session.commit()
        async with session_factory() as session:
            second, created_second = (
                await recommendation_engine.convert_pick_to_decision(
                    session, pick_id=pick_id, user_id=1, stake_amount=100
                )
            )
            await session.commit()

        # Assert:返回既有决策,不新增行
        assert created_first is True
        assert created_second is False
        assert second.decision_id == first.decision_id
        async with session_factory() as session:
            count = len(
                (
                    await session.execute(
                        select(UserDecision).where(
                            UserDecision.recommend_id == first.recommend_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert count == 1

    async def test_rejects_superseded_batch(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange:生成后重算,旧批次推荐不可再转换
        await _seed(session_factory)
        async with session_factory() as session:
            await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()
        pick_id = await self._first_pick_id(session_factory, "m-1")
        async with session_factory() as session:
            await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()

        # Act / Assert
        async with session_factory() as session:
            with pytest.raises(DataValidationError):
                await recommendation_engine.convert_pick_to_decision(
                    session, pick_id=pick_id, user_id=1, stake_amount=100
                )

    async def test_rejects_started_match(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange:生成后比赛开赛(LIVE)
        await _seed(session_factory)
        async with session_factory() as session:
            await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()
        pick_id = await self._first_pick_id(session_factory, "m-2")
        async with session_factory() as session:
            game = await session.get(MatchGame, "m-2")
            game.match_status = "LIVE"
            await session.commit()

        # Act / Assert
        async with session_factory() as session:
            with pytest.raises(DataValidationError):
                await recommendation_engine.convert_pick_to_decision(
                    session, pick_id=pick_id, user_id=1, stake_amount=100
                )

    async def test_raises_for_missing_pick(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Act / Assert
        async with session_factory() as session:
            with pytest.raises(ResourceNotFoundError):
                await recommendation_engine.convert_pick_to_decision(
                    session, pick_id=999, user_id=1, stake_amount=100
                )


class TestConvertPlanToScheme:
    """recommendation_engine.convert_plan_to_scheme"""

    @staticmethod
    async def _plan_id_by_name(
        factory: async_sessionmaker, plan_name: str
    ) -> int:
        async with factory() as session:
            plan = (
                await session.execute(
                    select(AiParlayPlan).where(AiParlayPlan.plan_name == plan_name)
                )
            ).scalar_one()
            return plan.plan_id

    async def test_materializes_scheme_via_parlay_rules(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange
        await _seed(session_factory)
        async with session_factory() as session:
            await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()
        plan_id = await self._plan_id_by_name(session_factory, "稳胆 2串1")

        # Act
        async with session_factory() as session:
            scheme, created = await recommendation_engine.convert_plan_to_scheme(
                session, plan_id=plan_id, user_id=1, stake_per_bet=100
            )
            await session.commit()

        # Assert:物化正式方案,腿快照/注数/注额口径正确,指针回填
        assert created is True
        assert scheme.parlay_size == 2
        assert scheme.bet_count == 1
        assert float(scheme.stake_per_bet) == pytest.approx(100)
        assert {item.match_id for item in scheme.items} == {"m-1", "m-2"}
        assert all(item.pool_code == "HAD" for item in scheme.items)
        async with session_factory() as session:
            plan = await session.get(AiParlayPlan, plan_id)
            assert plan is not None and plan.scheme_id == scheme.scheme_id

    async def test_convert_composite_plan_counts_combination_bets(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange:6 场代表腿 -> 复合 6场3串1 候选
        await _seed_pending_matches(session_factory, 6)
        async with session_factory() as session:
            await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()
        plan_id = await self._plan_id_by_name(
            session_factory, "复合 6场3串1"
        )

        # Act
        async with session_factory() as session:
            scheme, created = await recommendation_engine.convert_plan_to_scheme(
                session, plan_id=plan_id, user_id=1, stake_per_bet=100
            )
            await session.commit()

        # Assert:6 场 3 串 -> C(6,3)=20 注,总投入 20 x 100
        assert created is True
        assert scheme.parlay_size == 3
        assert scheme.bet_count == 20
        assert len(scheme.items) == 6
        assert float(scheme.total_stake) == pytest.approx(2000)
        async with session_factory() as session:
            plan = await session.get(AiParlayPlan, plan_id)
            assert plan is not None and plan.scheme_id == scheme.scheme_id

    async def test_convert_is_idempotent(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange
        await _seed(session_factory)
        async with session_factory() as session:
            await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()
        plan_id = await self._plan_id_by_name(session_factory, "稳胆 2串1")

        # Act
        async with session_factory() as session:
            first, created_first = (
                await recommendation_engine.convert_plan_to_scheme(
                    session, plan_id=plan_id, user_id=1, stake_per_bet=100
                )
            )
            await session.commit()
        async with session_factory() as session:
            second, created_second = (
                await recommendation_engine.convert_plan_to_scheme(
                    session, plan_id=plan_id, user_id=1, stake_per_bet=100
                )
            )
            await session.commit()

        # Assert
        assert created_first is True
        assert created_second is False
        assert second.scheme_id == first.scheme_id

    async def test_rejects_superseded_batch(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Arrange:生成后重算,旧批次候选不可再保存
        await _seed(session_factory)
        async with session_factory() as session:
            await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()
        plan_id = await self._plan_id_by_name(session_factory, "稳胆 2串1")
        async with session_factory() as session:
            await recommendation_engine.generate_batch(
                session, business_date=BATCH_DATE
            )
            await session.commit()

        # Act / Assert
        async with session_factory() as session:
            with pytest.raises(DataValidationError):
                await recommendation_engine.convert_plan_to_scheme(
                    session, plan_id=plan_id, user_id=1, stake_per_bet=100
                )

    async def test_raises_for_missing_plan(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Act / Assert
        async with session_factory() as session:
            with pytest.raises(ResourceNotFoundError):
                await recommendation_engine.convert_plan_to_scheme(
                    session, plan_id=999, user_id=1, stake_per_bet=100
                )
