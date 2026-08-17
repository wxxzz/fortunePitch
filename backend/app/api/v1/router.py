"""API v1 总路由注册。"""

from fastapi import APIRouter

from app.api.v1 import analysis

api_router = APIRouter()
api_router.include_router(analysis.router)
