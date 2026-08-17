"""xG(Expected Goals,预期进球)计算服务。

xG 衡量一次射门机会的质量:给定射门位置与类型,
估计该次射门转化为进球的概率。

数学模型(基于距离与角度的 Logistic 回归):

    d     = sqrt((x - L)^2 + y^2)                    # 射门点到球门中心的距离(米)
    theta = atan2(hw - y, dx) - atan2(-hw - y, dx)   # 射门点对两根门柱的张角(弧度)
    z     = b0 + b1 * d + b2 * theta + b3 * is_header
    xG    = 1 / (1 + e ** (-z))                      # Sigmoid 映射到 (0, 1)

其中 L 为球场长度的一半(球门线 x 坐标),系数 b0..b3 需由
历史射门数据拟合得到;此处的默认值仅用于演示计算流程。
"""

import math
from dataclasses import dataclass

from app.core.exceptions import DataValidationError

# 球门线 x 坐标(标准球场长 105 米,半场 52.5,此处取球门线位置)
GOAL_LINE_X: float = 52.5
# 球门宽度的一半(标准球门宽 7.32 米)
GOAL_HALF_WIDTH: float = 3.66

# Logistic 回归系数(默认演示值,生产环境应由拟合管道写回)
_COEF_INTERCEPT: float = 1.20
_COEF_DISTANCE: float = -0.11
_COEF_ANGLE: float = 1.10
_COEF_HEADER: float = -0.45


@dataclass(frozen=True)
class ShotEvent:
    """一次射门事件(不可变对象)。

    Attributes:
        x: 射门点 x 坐标(米),坐标系以球场中心为原点,主攻方向为正。
        y: 射门点 y 坐标(米),垂直于进攻方向。
        is_header: 是否为头球射门。
    """

    x: float
    y: float
    is_header: bool = False


def distance_to_goal(shot: ShotEvent) -> float:
    """计算射门点到球门中心的欧氏距离(米)。

    公式: d = sqrt((x - L)^2 + y^2)
    """
    return math.hypot(shot.x - GOAL_LINE_X, shot.y)


def angle_to_goal(shot: ShotEvent) -> float:
    """计算射门点对球门(两根门柱)的张角(弧度)。

    张角越大说明射门正对球门、机会越好。计算射门点分别指向
    上下两根门柱的向量之间的夹角:

        angle = atan2(hw - y, dx) - atan2(-hw - y, dx)

    其中 dx = L - x > 0,hw 为球门半宽。

    越过球门线(x > L)的非法位置会抛出异常。

    Raises:
        DataValidationError: 射门点位于球门线之后。
    """
    dx = GOAL_LINE_X - shot.x
    if dx <= 0:
        raise DataValidationError(f"射门点不能位于球门线之后: x={shot.x}")
    return math.atan2(GOAL_HALF_WIDTH - shot.y, dx) - math.atan2(
        -GOAL_HALF_WIDTH - shot.y, dx
    )


def calculate_xg(shot: ShotEvent) -> float:
    """计算单次射门的预期进球概率 xG。

    Args:
        shot: 射门事件,包含位置坐标与是否头球。

    Returns:
        xG 值,范围 (0, 1)。

    Raises:
        DataValidationError: 射门位置非法(越过球门线或距离为零)。
    """
    d = distance_to_goal(shot)
    theta = angle_to_goal(shot)

    z = (
        _COEF_INTERCEPT
        + _COEF_DISTANCE * d
        + _COEF_ANGLE * theta
        + _COEF_HEADER * (1.0 if shot.is_header else 0.0)
    )
    xg = 1.0 / (1.0 + math.exp(-z))
    return min(max(xg, 0.0), 1.0)


def calculate_team_xg(shots: list[ShotEvent]) -> float:
    """计算一支球队整场比赛的总 xG(各次射门 xG 之和)。

    总 xG 可视为该队进球数的期望值,是评估进攻质量的核心指标。
    """
    return sum(calculate_xg(shot) for shot in shots)
