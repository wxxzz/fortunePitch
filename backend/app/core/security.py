"""FortunePitch 安全认证模块(API Key 校验)。"""

from fastapi import Depends
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_401_UNAUTHORIZED

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError

# 请求头名称:X-API-Key
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    provided_key: str | None = Depends(api_key_header),
) -> str:
    """FastAPI 依赖:校验请求头中的 API Key。

    Args:
        provided_key: 从 `X-API-Key` 请求头提取的凭证。

    Returns:
        校验通过后的 API Key。

    Raises:
        UnauthorizedError: 缺少请求头或 Key 不匹配。
    """
    expected_key: str = get_settings().API_KEY
    if provided_key is None or provided_key != expected_key:
        raise UnauthorizedError()
    return provided_key
