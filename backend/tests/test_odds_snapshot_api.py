"""比赛赔率快照 API 测试:GET /api/v1/match/games/{match_id}/odds-snapshots。

覆盖 升序返回 / 不存在比赛 404 / 无快照空列表 三类场景。
"""

import typing

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.collector.sources import sporttery
from app.core.config import get_settings
from app.core.database import Base, get_db_session
from app.core.exceptions import ExternalSourceError
from app.main import app
from app.models import League, Team

settings = get_settings()
HEADERS = {"X-API-Key": settings.API_KEY}

# ---------- 离线样本(仅含已入库联赛/球队的最小集) ----------

SAMPLE_MATCHES: list[dict[str, typing.Any]] = [
    {
        "businessDate": "2026-08-24",
        "matchId": 2041028,
        "matchNumStr": "周一001",
        "matchDate": "2026-08-24",
        "matchTime": "20:00",
        "leagueAllName": "西班牙甲级联赛",
        "homeTeamAllName": "巴塞罗那",
        "awayTeamAllName": "皇家马德里",
        "matchStatus": "Selling",
    },
]


async def _fetch_match_day_list() -> list[dict[str, typing.Any]]:
    return SAMPLE_MATCHES


def _odds_item(home_odds: str) -> dict[str, typing.Any]:
    """构造指定主胜赔率的赔率样本。"""

    return {
        "matchId": 2041028,
        "pools": {
            "had": {"h": home_odds, "d": "3.40", "a": "3.20"},
            "hhad": {"h": "1.55", "d": "3.80", "a": "5.50", "goalLine": "-1"},
        },
        "updateTime": "2026-08-24 10:00:00",
    }


@pytest.fixture(autouse=True)
def stub_sporttery(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认打桩为首次赔率,个别测试按需覆写。"""

    async def fetch_odds() -> list[dict[str, typing.Any]]:
        return [_odds_item("2.15")]

    monkeypatch.setattr(sporttery, "fetch_match_day_list", _fetch_match_day_list)
    monkeypatch.setattr(sporttery, "fetch_match_odds", fetch_odds)


# ---------- 数据库与会话 ----------


@pytest.fixture
async def session_factory() -> typing.AsyncGenerator[async_sessionmaker, None]:  # type: ignore[type-args]
    """内存 SQLite 库(启用外键),预置西甲联赛与两支球队。"""
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        league = League(
            league_name="西班牙甲级联赛", country="西班牙", tier=1, season="2026-2027"
        )
        session.add(league)
        await session.flush()
        for name in ("巴塞罗那", "皇家马德里"):
            session.add(Team(league_id=league.league_id, team_name=name))
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.fixture
async def client(session_factory: async_sessionmaker) -> typing.AsyncGenerator[AsyncClient, None]:  # type: ignore[type-args]
    """将应用数据库会话替换为内存库。"""

    async def override_session() -> typing.AsyncGenerator[None, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()


async def _sync_with_odds(monkeypatch: pytest.MonkeyPatch, home_odds: str) -> None:
    """以指定主胜赔率执行一次赛事同步(无既有会话,直接走接口链路)。"""

    async def fetch_odds() -> list[dict[str, typing.Any]]:
        return [_odds_item(home_odds)]

    monkeypatch.setattr(sporttery, "fetch_match_odds", fetch_odds)


class TestOddsSnapshotsAPI:
    """赔率快照查询接口测试。"""

    async def test_returns_snapshots_ordered_by_time(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 两次同步、赔率变化 -> 两条快照
        await _sync_with_odds(monkeypatch, "2.15")
        await client.post(
            "/api/v1/collector/matches/sync",
            json={"date": "2026-08-24"},
            headers=HEADERS,
        )
        await _sync_with_odds(monkeypatch, "2.05")
        await client.post(
            "/api/v1/collector/matches/sync",
            json={"date": "2026-08-24"},
            headers=HEADERS,
        )

        response = await client.get(
            "/api/v1/match/games/2041028/odds-snapshots",
            headers=HEADERS,
        )
        assert response.status_code == 200
        snapshots = response.json()
        assert len(snapshots) == 2
        # 主胜赔率先 2.15 后 2.05(升序时间轴)
        home_odds = [
            next(
                o["odds"]
                for p in s["pools"]
                if p["poolCode"] == "HAD"
                for o in p["options"]
                if o["code"] == "h"
            )
            for s in snapshots
        ]
        assert home_odds == [2.15, 2.05]
        assert snapshots[0]["snapshot_id"] < snapshots[1]["snapshot_id"]

    async def test_returns_404_for_unknown_match(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/match/games/not-exists/odds-snapshots",
            headers=HEADERS,
        )
        assert response.status_code == 404

    async def test_returns_empty_list_without_snapshots(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 同步赛程但赔率接口失败 -> 比赛存在、无快照
        async def broken_odds() -> list[dict[str, typing.Any]]:
            raise ExternalSourceError("竞彩赔率拉取失败")

        monkeypatch.setattr(sporttery, "fetch_match_odds", broken_odds)
        await client.post(
            "/api/v1/collector/matches/sync",
            json={"date": "2026-08-24"},
            headers=HEADERS,
        )
        # 比赛已入库,直接落一条以确认 200 空列表
        response = await client.get(
            "/api/v1/match/games/2041028/odds-snapshots",
            headers=HEADERS,
        )
        assert response.status_code == 200
        assert response.json() == []
