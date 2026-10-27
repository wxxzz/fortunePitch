"""数据采集模块测试:联赛解析、同步入库与同步接口。

外部 sporttery 接口通过 monkeypatch 替换为离线样本,
不产生真实网络请求;数据库使用 SQLite 内存库。
"""

import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.collector.parsers import league as league_parser
from app.collector.sync import league_sync
from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.main import app
from app.models import League

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# 离线样本:模拟竞彩网联赛列表(hot/normal/other 展平后)与西甲详情
SAMPLE_LIST: list[dict[str, typing.Any]] = [
    {
        "group": "hot",
        "tier": 1,
        "leagueAbbCnName": "英超",
        "uniformLeagueId": 72,
        "seasonList": [{"seasonId": 13343, "seasonName": "2025/2026"}],
    },
    {
        "group": "hot",
        "tier": 1,
        "leagueAbbCnName": "西甲",
        "uniformLeagueId": 24,
        "seasonList": [{"seasonId": 15485, "seasonName": "2026/2027"}],
    },
    {
        "group": "other",
        "tier": 2,
        "leagueAbbCnName": "西甲杯",
        "uniformLeagueId": 999,
        "seasonList": [{"seasonId": 1, "seasonName": "2026/2027"}],
    },
    {
        "group": "normal",
        "tier": 2,
        "leagueAbbCnName": "亚冠精英",
        "uniformLeagueId": 41,
        "seasonList": [{"seasonId": 10, "seasonName": "2026/2027"}],
    },
    {
        "group": "normal",
        "tier": 2,
        "leagueAbbCnName": "欧国联",
        "uniformLeagueId": 60,
        "seasonList": [{"seasonId": 11, "seasonName": "2026/2027"}],
    },
    {
        "group": "normal",
        "tier": 2,
        "leagueAbbCnName": "韩职",
        "uniformLeagueId": 50,
        "seasonList": [{"seasonId": 12, "seasonName": "2026/2027"}],
    },
]
SAMPLE_DETAIL_XIJIA = {
    "cnName": "西班牙甲级联赛",
    "enName": "Spanish Division 1",
    "isHot": 1,
    "uniformLeagueId": 24,
}


# ---------- 解析层(纯函数) ----------


class TestLeagueParser:
    """parsers/league.py 单元测试。"""

    def test_find_league_by_exact_name(self) -> None:
        item = league_parser.find_league_item(SAMPLE_LIST, "西甲")
        assert item["uniformLeagueId"] == 24

    def test_find_league_by_partial_name(self) -> None:
        item = league_parser.find_league_item(SAMPLE_LIST, "国联")
        assert item["leagueAbbCnName"] == "欧国联"

    def test_find_league_partial_ambiguous_across_cups(self) -> None:
        # “英”同时命中“英超”与“亚冠精英”(精英含“英”),判歧义
        with pytest.raises(Exception, match="歧义"):
            league_parser.find_league_item(SAMPLE_LIST, "英")

    def test_find_league_ambiguous(self) -> None:
        with pytest.raises(Exception, match="歧义"):
            league_parser.find_league_item(SAMPLE_LIST, "甲")

    def test_find_league_not_found(self) -> None:
        with pytest.raises(Exception, match="未在竞彩网联赛资料中找到"):
            league_parser.find_league_item(SAMPLE_LIST, "中超")

    def test_find_league_by_compressed_abbr(self) -> None:
        # 库内 league_name 为竞彩网详情全称,与列表简称既不相等也不互为子串,
        # 经“词元压缩”推导简称候选后精确匹配
        item = league_parser.find_league_item(SAMPLE_LIST, "英格兰超级联赛")
        assert item["leagueAbbCnName"] == "英超"
        item = league_parser.find_league_item(SAMPLE_LIST, "亚洲冠军精英联赛")
        assert item["leagueAbbCnName"] == "亚冠精英"
        item = league_parser.find_league_item(SAMPLE_LIST, "欧洲国家联赛")
        assert item["leagueAbbCnName"] == "欧国联"
        item = league_parser.find_league_item(SAMPLE_LIST, "韩国职业联赛")
        assert item["leagueAbbCnName"] == "韩职"

    def test_find_league_compressed_abbr_falls_through(self) -> None:
        # 推导出的候选简称在列表中均不存在时,维持“未找到”报错口径
        with pytest.raises(Exception, match="未在竞彩网联赛资料中找到"):
            league_parser.find_league_item(SAMPLE_LIST, "德国乙级联赛")

    def test_derived_league_abbr_candidates(self) -> None:
        # “国家/地区 + 级别联赛”式:压缩 + 结尾泛称变体(删除/取首字)
        assert league_parser.derived_league_abbr_candidates("德国乙级联赛") == [
            "德乙联赛",
            "德乙",
            "德乙联",
        ]
        # 结尾“联赛”取首字保留(欧洲国家联赛 -> 欧国联)
        assert league_parser.derived_league_abbr_candidates("欧洲国家联赛") == [
            "欧国联赛",
            "欧国",
            "欧国联",
        ]
        # 非词元片段原样透传(亚洲冠军精英联赛 -> 亚冠精英)
        assert league_parser.derived_league_abbr_candidates("亚洲冠军精英联赛") == [
            "亚冠精英联赛",
            "亚冠精英",
            "亚冠精英联",
        ]
        # 结尾“大联盟”删除(美国职业大联盟 -> 美职)
        assert league_parser.derived_league_abbr_candidates("美国职业大联盟") == [
            "美职大联盟",
            "美职",
            "美职大",
        ]
        # 无结尾泛称时仅有压缩结果本身
        assert league_parser.derived_league_abbr_candidates("英格兰联赛杯") == ["英联赛杯"]
        assert league_parser.derived_league_abbr_candidates("亚运会男足") == ["亚运男足"]
        # 已是简称/无词元的名称原样返回
        assert league_parser.derived_league_abbr_candidates("德乙") == ["德乙"]
        assert league_parser.derived_league_abbr_candidates("欧冠") == ["欧冠"]

    def test_derived_league_abbr_candidates_edge_cases(self) -> None:
        # 空串/纯空白无候选
        assert league_parser.derived_league_abbr_candidates("") == []
        assert league_parser.derived_league_abbr_candidates("   ") == []
        # 单字与结尾泛称整词:仅原样返回,不生成删除/取首字变体
        assert league_parser.derived_league_abbr_candidates("甲") == ["甲"]
        assert league_parser.derived_league_abbr_candidates("联赛") == ["联赛"]
        assert league_parser.derived_league_abbr_candidates("大联盟") == ["大联盟"]
        # 最长词元优先:“英格兰”作为三字词元整体压缩
        assert league_parser.derived_league_abbr_candidates("英格兰足总杯") == [
            "英足总杯"
        ]

    def test_normalize_season(self) -> None:
        assert league_parser.normalize_season("2026/2027") == "2026-2027"
        assert league_parser.normalize_season("2026-2027") == "2026-2027"

    def test_derive_country(self) -> None:
        assert league_parser.derive_country("西班牙甲级联赛") == "西班牙"
        assert league_parser.derive_country("英格兰超级联赛") == "英格兰"
        # 无法从名称推导国家/地区(如洲际赛事)时返回“其他”
        assert league_parser.derive_country("欧冠") == "其他"

    def test_build_league_fields(self) -> None:
        item = league_parser.find_league_item(SAMPLE_LIST, "西甲")
        fields = league_parser.build_league_fields(item, SAMPLE_DETAIL_XIJIA)
        assert fields == {
            "league_name": "西班牙甲级联赛",
            "country": "西班牙",
            "tier": 1,
            "season": "2026-2027",
        }

    def test_build_league_fields_tier_fallback_to_group(self) -> None:
        # 详情缺少 isHot 时回退到列表分组推导的级别
        item = dict(SAMPLE_LIST[2])
        fields = league_parser.build_league_fields(item, {"cnName": "西甲杯赛"})
        assert fields["tier"] == 2


# ---------- 同步层(数据库 + 打桩数据源) ----------


@pytest.fixture
async def session_factory() -> async_sessionmaker:  # type: ignore[type-args]
    """创建内存 SQLite 库(启用外键),返回会话工厂。"""
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


@pytest.fixture
def stub_sporttery(monkeypatch: pytest.MonkeyPatch) -> None:
    """将 sporttery 数据源替换为离线样本。"""
    monkeypatch.setattr(league_sync.sporttery, "fetch_league_list", SAMPLE_LIST_FN)
    monkeypatch.setattr(
        league_sync.sporttery, "fetch_league_detail", SAMPLE_DETAIL_FN
    )


async def _sample_list() -> list[dict[str, typing.Any]]:
    return SAMPLE_LIST


async def _sample_detail(uniform_league_id: int) -> dict[str, typing.Any]:
    if uniform_league_id == 24:
        return SAMPLE_DETAIL_XIJIA
    raise AssertionError(f"未预期的 leagueId: {uniform_league_id}")


SAMPLE_LIST_FN = _sample_list
SAMPLE_DETAIL_FN = _sample_detail


class TestLeagueSync:
    """sync/league_sync.py 集成测试(SQLite 内存库)。"""

    async def test_sync_creates_new_league(
        self, session_factory: async_sessionmaker, stub_sporttery: None
    ) -> None:
        async with session_factory() as session:
            result = await league_sync.sync_league_by_name(session, "西甲")
            await session.commit()

        assert result.action == "created"
        assert result.uniform_league_id == 24
        assert result.league.league_name == "西班牙甲级联赛"
        assert result.league.country == "西班牙"
        assert result.league.season == "2026-2027"

        async with session_factory() as session:
            saved = await session.scalar(select(League))
            assert saved is not None
            assert saved.league_name == "西班牙甲级联赛"

    async def test_sync_is_idempotent(
        self, session_factory: async_sessionmaker, stub_sporttery: None
    ) -> None:
        async with session_factory() as session:
            first = await league_sync.sync_league_by_name(session, "西甲")
            await session.commit()
        async with session_factory() as session:
            second = await league_sync.sync_league_by_name(session, "西甲")
            await session.commit()

        assert first.action == "created"
        assert second.action == "updated"
        assert second.league.league_id == first.league.league_id

        async with session_factory() as session:
            count = len((await session.execute(select(League))).scalars().all())
            assert count == 1


# ---------- 接口层(ASGI + 依赖覆盖) ----------


@pytest.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncGenerator[AsyncClient, None]:
    """内存 SQLite + 打桩数据源的测试客户端。"""
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> object:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setattr(league_sync.sporttery, "fetch_league_list", SAMPLE_LIST_FN)
    monkeypatch.setattr(league_sync.sporttery, "fetch_league_detail", SAMPLE_DETAIL_FN)
    app.dependency_overrides[get_db_session] = override_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=HEADERS
        ) as async_client:
            yield async_client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


class TestLeagueSyncApi:
    """/api/v1/collector/leagues/sync 接口测试。"""

    async def test_sync_league_endpoint(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/leagues/sync", json={"league_name": "西甲"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "created"
        assert body["uniform_league_id"] == 24
        assert body["league"]["league_name"] == "西班牙甲级联赛"
        assert body["source"] == "sporttery"

    async def test_sync_league_unknown_name(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/leagues/sync", json={"league_name": "中超"}
        )
        assert response.status_code == 422
        assert "未在竞彩网联赛资料中找到" in response.json()["error"]["message"]

    async def test_sync_league_requires_api_key(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/collector/leagues/sync",
            json={"league_name": "西甲"},
            headers={"X-API-Key": "wrong"},
        )
        assert response.status_code == 401
