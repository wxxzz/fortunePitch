"""比赛补充信息服务:人工录入的场外情报(伤停/阵型等)读写与提示词渲染。

职责:
1. 读写 fp_match_extra_info(每场一行,UPSERT 语义);
2. 把已录入的补充信息渲染为 AI 分析提示词的"人工录入补充信息"段,
   供综合分析(llm)与基本面分析(llm_fundamental)注入上下文。

录入内容为人工自由文本,可能包含主观判断,提示词渲染时显式标注
数据来源,由模型自行校验与取舍;全部字段为空时不注入该段。
"""

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundError
from app.models import MatchExtraInfo, MatchGame

# 单字段录入上限(与前端 textarea maxlength 对齐,防超大文本拖垮提示词)
MAX_FIELD_LENGTH = 5000


async def load_extra_info(
    session: AsyncSession, match_id: str
) -> MatchExtraInfo | None:
    """查询比赛的补充信息,未录入过返回 None。"""
    return (
        await session.execute(
            select(MatchExtraInfo).where(MatchExtraInfo.match_id == match_id)
        )
    ).scalar_one_or_none()


async def upsert_extra_info(
    session: AsyncSession,
    *,
    match_id: str,
    injuries: str | None,
    formations: str | None,
    other_notes: str | None,
) -> MatchExtraInfo:
    """按场插入或更新补充信息(整体覆盖语义),比赛不存在时抛 404。

    空白文本统一归一为 None,保持"未录入"与"清空"一致;
    通过 merge 按 PK 转为 INSERT 或 UPDATE,避免"先查后插"在
    并发保存(双开页/连点)时撞重复主键;updated_at 显式赋值,
    保证 UPDATE 路径下时间戳刷新。flush 后即可读取,提交由
    请求级会话依赖完成。
    """

    def normalize(text: str | None) -> str | None:
        stripped = (text or "").strip()
        return stripped if stripped else None

    game = await session.get(MatchGame, match_id)
    if game is None:
        raise ResourceNotFoundError(MatchGame.__tablename__, match_id)

    row = await session.merge(
        MatchExtraInfo(
            match_id=match_id,
            injuries=normalize(injuries),
            formations=normalize(formations),
            other_notes=normalize(other_notes),
            updated_at=datetime.datetime.now(),
        )
    )
    await session.flush()
    return row


def format_extra_info_text(row: MatchExtraInfo | None) -> str | None:
    """把补充信息渲染为提示词文本块;未录入或全空时返回 None。

    显式标注"人工录入"来源,提示模型该段可能含主观判断,须与
    积分榜/赔率等系统数据交叉校验后再采信。
    """
    if row is None:
        return None
    sections: list[str] = []
    if row.injuries:
        sections.append(f"- 伤停信息:{row.injuries}")
    if row.formations:
        sections.append(f"- 阵型信息:{row.formations}")
    if row.other_notes:
        sections.append(f"- 其他补充:{row.other_notes}")
    return "\n".join(sections) if sections else None


__all__ = [
    "MAX_FIELD_LENGTH",
    "load_extra_info",
    "upsert_extra_info",
    "format_extra_info_text",
]
