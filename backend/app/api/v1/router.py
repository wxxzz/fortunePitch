"""API v1 总路由:按四大业务模块聚合。"""

from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.base import router as base_router
from app.api.v1.collector import router as collector_router
from app.api.v1.match import router as match_router
from app.api.v1.strategy import router as strategy_router

api_router = APIRouter()
api_router.include_router(base_router.router)
api_router.include_router(match_router.router)
api_router.include_router(analytics_router.router)
api_router.include_router(strategy_router.router)
api_router.include_router(collector_router.router)
