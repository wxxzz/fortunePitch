"""用户自选模拟决策服务:赛事中心自选玩法 -> 推荐记录 + 模拟决策。

用户在赛事中心勾选的玩法选项没有 AI 推荐记录可挂靠,而
fp_strategy_user_decisions.recommend_id 为非空外键,故为每条自选
先落一条 confidence_score=0 的“用户自选”推荐记录(logic_tags
标注 ``USER_PICK_TAG`` 以便与 AI 推荐区分),再创建对应的模拟决策。

注额为模拟数据,仅用于复盘与战绩统计,不涉及真实资金。
"""

import typing

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DataValidationError
from app.models import MatchGame, Recommendation, UserDecision
from app.services import crud

# 竞彩玩法编码 -> 推荐记录策略类型
POOL_TO_STRATEGY: dict[str, str] = {
    "HAD": "WIN_DRAW_LOSS",
    "HHAD": "HANDICAP",
    "CRS": "SCORE",
    "TTG": "TOTAL_GOALS",
    "HAFU": "HALF_FULL",
}

# 用户自选推荐记录的固定标注(与 AI 推荐区分)
USER_PICK_TAG = "用户自选"

# 单次批量自选的条数上限(与接口 Schema 的 max_length 一致)
MAX_SELECTIONS = 20


class UserPick(typing.NamedTuple):
    """一条用户自选(玩法选项)。"""

    match_id: str
    pool_code: str
    option_code: str
    option_label: str


async def create_user_picks(
    session: AsyncSession,
    user_id: int,
    stake_amount: float,
    picks: list[UserPick],
) -> list[UserDecision]:
    """批量创建用户自选模拟决策。

    Args:
        session: 异步数据库会话。
        user_id: 用户编号(文档未定义用户表,暂存外部编号)。
        stake_amount: 每条自选的模拟注额。
        picks: 自选列表(已通过接口层校验)。

    Returns:
        创建的模拟决策列表(与 picks 顺序一致)。

    Raises:
        ResourceNotFoundError: 比赛不存在。
        DataValidationError: 玩法编码非法。
    """
    decisions: list[UserDecision] = []
    for pick in picks:
        strategy_type = POOL_TO_STRATEGY.get(pick.pool_code)
        if strategy_type is None:
            raise DataValidationError(
                f"玩法编码必须是 {sorted(POOL_TO_STRATEGY)} 之一: {pick.pool_code}"
            )
        await crud.get_entity(session, MatchGame, pick.match_id)
        recommendation = await crud.create_entity(
            session,
            Recommendation,
            {
                "match_id": pick.match_id,
                "strategy_type": strategy_type,
                "predicted_outcome": pick.option_label,
                "confidence_score": 0.0,
                "logic_tags": [USER_PICK_TAG],
            },
        )
        decisions.append(
            await crud.create_entity(
                session,
                UserDecision,
                {
                    "user_id": user_id,
                    "recommend_id": recommendation.recommend_id,
                    "user_bet_type": f"{pick.pool_code}:{pick.option_code}",
                    "stake_amount": stake_amount,
                },
            )
        )
    return decisions
