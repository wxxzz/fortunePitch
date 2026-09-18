"""FortunePitch 核心配置模块。

基于 Pydantic Settings 的统一配置管理,
支持通过环境变量与 `.env` 文件覆盖默认值。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录(app/core/config.py 向上两级),.env 解析的固定锚点
_BACKEND_DIR = Path(__file__).resolve().parents[2]

# 候选 .env 位置:backend/.env(README 约定)优先,兼容 backend/app/.env。
# 相对 cwd 解析 .env 会导致"启动目录不同、配置不同",故统一锚定到包位置。
_ENV_FILE = next(
    (p for p in (_BACKEND_DIR / ".env", _BACKEND_DIR / "app" / ".env") if p.is_file()),
    ".env",
)


class Settings(BaseSettings):
    """全局配置项。

    所有配置均可通过同名环境变量(大小写不敏感)覆盖,
    例如 `DATABASE_URL=sqlite+aiosqlite:///./fortune_pitch.db`。
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
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

    # 大模型分析:服务商切换(qwen=阿里云百炼千问 / ark=火山方舟)
    LLM_PROVIDER: str = "qwen"
    # 千问(默认服务商),OpenAI 兼容协议
    LLM_QWEN_BASE_URL: str = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    LLM_QWEN_API_KEY: str = ""
    LLM_QWEN_MODEL: str = "qwen3.8-max"
    # 火山引擎方舟,OpenAI 兼容协议(模型 glm-5.2 在方舟侧的 ID)
    LLM_ARK_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/coding/v3"
    LLM_ARK_API_KEY: str = ""
    LLM_ARK_MODEL: str = "glm-5-2-260617"
    # 单次生成超时与输出上限。注意:GLM 等推理模型的思考过程也计入
    # max_tokens(实测一场分析约消耗 7k),上限不足会导致 content 为空
    LLM_TIMEOUT_SECONDS: float = 180.0
    LLM_MAX_TOKENS: int = 16000

    # CORS 允许的前端来源,逗号分隔
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    """返回单例 Settings 实例(带缓存,避免重复解析环境变量)。"""
    return Settings()
