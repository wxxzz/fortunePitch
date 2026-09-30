"""大模型模块(fp_llm_ 前缀):请求日志 + 球队维度分析结果。"""

import datetime
import typing

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, BigIntPK


class LlmRequestLog(Base):
    """大模型请求日志表(fp_llm_request_logs):记录每次 LLM 调用的参数与结果。

    供调用排障、耗时与 token 用量统计;日志不与业务表建外键,
    比赛数据删除不影响日志保留。由 services/llm.py 用独立会话写入,
    即使业务请求失败回滚,日志也已提交留存。

    注:match_id 对比赛类分析存比赛 ID;球队维度分析存 "team:{team_id}"
    标识,并以 request_params.analysis_type 区分调用类型。
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
    # 调用参数:temperature / max_tokens / timeout_seconds / analysis_type
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


class TeamLlmAnalysis(Base):
    """大模型球队维度分析结果表(fp_llm_team_analyses):每次生成一行,保留历史。

    由球队全景档案页(/teams)「生成 AI 分析」触发落库,记录整体研判与
    风险提示;六维度结论明细另由 fp_llm_team_analysis_dims 承载。
    """

    __tablename__ = "fp_llm_team_analyses"

    analysis_id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True
    )
    team_id: Mapped[int] = mapped_column(
        ForeignKey("fp_base_teams.team_id"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    risks: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.datetime.now
    )

    team: Mapped["Team"] = relationship()
    # 级联删除:主表删除时明细随数据库外键 ON DELETE CASCADE 一并清除;
    # 显式按 dim_id 排序,保证六维度按写入顺序(固定维度顺序)返回
    dimensions: Mapped[list["TeamLlmAnalysisDim"]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TeamLlmAnalysisDim.dim_id",
    )


class TeamLlmAnalysisDim(Base):
    """大模型球队维度结论明细表(fp_llm_team_analysis_dims)。

    每个维度一行,挂在某次球队分析下;(analysis_id, dim_code) 唯一,
    即同一次分析内每个维度至多一条结论。
    """

    __tablename__ = "fp_llm_team_analysis_dims"
    __table_args__ = (
        UniqueConstraint("analysis_id", "dim_code", name="uk_llm_team_dim"),
    )

    dim_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("fp_llm_team_analyses.analysis_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 维度编码 ATTACK/DEFENSE/HOME_FORM/AWAY_FORM/RECENT_FORM/OTHER 与展示名
    # (属性名与响应 schema 对齐,数据库列名保持 dim_ 前缀)
    code: Mapped[str] = mapped_column("dim_code", String(32), nullable=False)
    title: Mapped[str] = mapped_column("dim_title", String(32), nullable=False)
    # 维度评级:strong=强 / average=中(或数据不足) / weak=弱
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    content: Mapped[str] = mapped_column(String(1000), nullable=False)

    analysis: Mapped["TeamLlmAnalysis"] = relationship(
        back_populates="dimensions"
    )
