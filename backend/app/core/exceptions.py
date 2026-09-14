"""FortunePitch 自定义异常与统一异常处理。

禁止在业务逻辑中使用裸 `except:`,
所有可预期错误必须抛出本模块定义的自定义异常类。
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


class FortunePitchError(Exception):
    """业务异常基类,携带 HTTP 状态码与用户可读的错误信息。"""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        detail: str | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.detail = detail or message
        super().__init__(message)


class ResourceNotFoundError(FortunePitchError):
    """请求的资源不存在(如比赛 ID 无效)。"""

    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(
            message=f"{resource} 不存在: {resource_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class DataValidationError(FortunePitchError):
    """输入数据在业务层校验失败(如赔率为负、进球数为非整数)。"""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


class ExternalSourceError(FortunePitchError):
    """外部数据源访问失败(网络超时、接口报错、响应结构异常)。"""

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        )


class LlmNotConfiguredError(FortunePitchError):
    """大模型服务未配置(缺少 API Key 或服务商名非法)。"""

    def __init__(self, message: str = "大模型服务未配置,请在 .env 中填写 LLM API Key") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class LlmServiceError(FortunePitchError):
    """大模型调用失败(网络超时、接口报错、输出无法解析)。"""

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        )


class UnauthorizedError(FortunePitchError):
    """API Key 校验失败。"""

    def __init__(self, message: str = "无效的 API Key") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


async def fortune_pitch_exception_handler(
    request: Request, exc: FortunePitchError
) -> JSONResponse:
    """将 FortunePitchError 统一转换为结构化 JSON 响应。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "data": None,
            "error": {"message": exc.message, "detail": exc.detail},
        },
    )


async def integrity_error_handler(
    request: Request, exc: IntegrityError
) -> JSONResponse:
    """将数据库完整性约束失败(外键/唯一键)转为友好的 422 响应。"""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "data": None,
            "error": {
                "message": "数据完整性约束失败:关联记录不存在或字段重复",
                "detail": str(exc.orig),
            },
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI 应用上注册统一异常处理器。"""
    app.add_exception_handler(FortunePitchError, fortune_pitch_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(IntegrityError, integrity_error_handler)  # type: ignore[arg-type]
