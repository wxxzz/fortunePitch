"""FortunePitch 核心配置模块。

基于 Pydantic Settings 的统一配置管理,
支持通过环境变量与 `.env` 文件覆盖默认值。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置项。

    所有配置均可通过同名环境变量(大小写不敏感)覆盖,
    例如 `DATABASE_URL=sqlite+aiosqlite:///./fortune_pitch.db`。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 对外正式工程名,UI 与日志中一律使用该名称
    PROJECT_NAME: str = "FortunePitch"
    PROJECT_DESCRIPTION: str = "智能足彩数据分析与辅助决策工具(财富绿茵)"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # 异步数据库连接串,默认回退 SQLite(单测/离线开发用);
    # MySQL 生产连接统一通过 backend/.env 的 DATABASE_URL 注入,避免硬编码凭证
    DATABASE_URL: str = "sqlite+aiosqlite:///./fortune_pitch.db"

    # 接口访问凭证,生产环境必须通过环境变量注入
    API_KEY: str = "change-me-in-production"

    # CORS 允许的前端来源,逗号分隔
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    """返回单例 Settings 实例(带缓存,避免重复解析环境变量)。"""
    return Settings()
