"""大模型模块(fp_llm_ 前缀):请求日志。"""

import datetime
import typing

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, BigIntPK


class LlmRequestLog(Base):
    """大模型请求日志表(fp_llm_request_logs):记录每次 LLM 调用的参数与结果。

    供调用排障、耗时与 token 用量统计;日志不与业务表建外键,
    比赛数据删除不影响日志保留。由 services/llm.py 用独立会话写入,
    即使业务请求失败回滚,日志也已提交留存。
    """

    __tablename__ = "fp_llm_request_logs"

    log_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    # 完整提示词(system + user),JSON 数组原样保存
    request_messages: Mapped[list[dict[str, typing.Any]]] = mapped_column(
        JSON, nullable=False
    )
    # 调用参数:temperature / max_tokens / timeout_seconds
    request_params: Mapped[dict[str, typing.Any]] = mapped_column(JSON, nullable=False)
    # 模型原始输出(解析前);失败时也可能保留用于排障
    response_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SUCCESS / FAILED(网络错误、接口报错、输出解析失败)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )
