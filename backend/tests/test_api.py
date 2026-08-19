"""API 接口集成测试(基于 httpx ASGI 传输,无需真实启动服务)。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app

settings = get_settings()

HEADERS = {"X-API-Key": settings.API_KEY}


@pytest.fixture
async def client() -> AsyncClient:
    """提供指向 FastAPI 应用的异步测试客户端。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


class TestHealthEndpoint:
    """GET /health 行为测试。"""

    async def test_health_returns_ok(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["project"] == "FortunePitch"


class TestAnalyticsPoissonEndpoint:
    """POST /api/v1/analytics/poisson 行为测试。"""

    async def test_poisson_prediction_valid(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/analytics/poisson",
            json={"home_xg": 1.6, "away_xg": 1.1},
            headers=HEADERS,
        )
        assert response.status_code == 200
        body = response.json()
        probs = body["probabilities"]
        total = probs["home_win"] + probs["draw"] + probs["away_win"]
        assert total == pytest.approx(1.0)
        assert len(body["top_scores"]) == 5

    async def test_poisson_rejects_non_positive_xg(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/analytics/poisson",
            json={"home_xg": 0, "away_xg": 1.1},
            headers=HEADERS,
        )
        assert response.status_code == 422


class TestStrategyKellyEndpoint:
    """POST /api/v1/strategy/kelly 行为测试。"""

    async def test_kelly_positive_edge(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/strategy/kelly",
            json={"model_prob": 0.6, "decimal_odds": 2.0},
            headers=HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["kelly_fraction"] == pytest.approx(0.2)


class TestAuth:
    """API Key 校验测试。"""

    async def test_missing_api_key_returns_401(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/analytics/poisson",
            json={"home_xg": 1.6, "away_xg": 1.1},
        )
        assert response.status_code in (401, 403)
