"""Elo 评分服务:基于比赛结果动态更新球队实力评分。

数学模型(Elo 标准公式):

    E_home = 1 / (1 + 10 ** ((R_away - R_home + HFA) / 400))
    E_away = 1 - E_home

    R_home' = R_home + K * (S_home - E_home)
    R_away' = R_away + K * (S_away - E_away)

其中:
- R_home / R_away  : 主/客队当前 Elo 评分
- HFA              : 主场优势(Home Field Advantage),以 Elo 分表示
- S                : 实际得分,胜 = 1,平 = 0.5,负 = 0
- K                : 更新系数,K 越大单场比赛对评分的影响越强
- E                : 以当前评分计算的期望得分(即胜率估计)
"""

from dataclasses import dataclass

from app.core.exceptions import DataValidationError

DEFAULT_ELO: float = 1500.0
DEFAULT_K_FACTOR: float = 20.0
DEFAULT_HOME_FIELD_ADVANTAGE: float = 100.0

# 比赛实际得分常量
SCORE_WIN: float = 1.0
SCORE_DRAW: float = 0.5
SCORE_LOSS: float = 0.0


@dataclass(frozen=True)
class EloUpdate:
    """一次比赛后的 Elo 更新结果(不可变对象)。"""

    home_rating_new: float
    away_rating_new: float
    home_expected: float
    away_expected: float


def actual_score(home_goals: int, away_goals: int) -> tuple[float, float]:
    """根据比分计算主/客队实际得分 S。

    Args:
        home_goals: 主队进球数(>= 0)。
        away_goals: 客队进球数(>= 0)。

    Returns:
        (S_home, S_away) 二元组,取值属于 {1.0, 0.5, 0.0}。

    Raises:
        DataValidationError: 进球数为负。
    """
    if home_goals < 0 or away_goals < 0:
        raise DataValidationError(f"进球数不能为负: {home_goals}-{away_goals}")
    if home_goals > away_goals:
        return SCORE_WIN, SCORE_LOSS
    if home_goals < away_goals:
        return SCORE_LOSS, SCORE_WIN
    return SCORE_DRAW, SCORE_DRAW


def expected_score(
    home_rating: float,
    away_rating: float,
    home_field_advantage: float = DEFAULT_HOME_FIELD_ADVANTAGE,
) -> float:
    """计算主队期望得分(胜率估计)。

    公式: E_home = 1 / (1 + 10 ** ((R_away - R_home - HFA) / 400))

    Args:
        home_rating: 主队 Elo 评分。
        away_rating: 客队 Elo 评分。
        home_field_advantage: 主场优势(Elo 分),主场优势加在主队一侧。

    Returns:
        主队期望得分,取值 (0, 1);客队期望为 1 - E_home。
    """
    exponent = (away_rating - home_rating - home_field_advantage) / 400.0
    return 1.0 / (1.0 + 10.0**exponent)


def update_ratings(
    home_rating: float,
    away_rating: float,
    home_goals: int,
    away_goals: int,
    k_factor: float = DEFAULT_K_FACTOR,
    home_field_advantage: float = DEFAULT_HOME_FIELD_ADVANTAGE,
) -> EloUpdate:
    """根据一场比赛结果更新双方 Elo 评分。

    Args:
        home_rating: 赛前主队 Elo 评分。
        away_rating: 赛前客队 Elo 评分。
        home_goals: 主队实际进球数。
        away_goals: 客队实际进球数。
        k_factor: 更新系数 K。
        home_field_advantage: 主场优势(Elo 分)。

    Returns:
        包含赛后双方新评分与赛前期望得分的 `EloUpdate`。

    Raises:
        DataValidationError: K 系数非正或进球数为负。
    """
    if k_factor <= 0:
        raise DataValidationError(f"K 系数必须为正数: {k_factor}")

    s_home, s_away = actual_score(home_goals, away_goals)
    e_home = expected_score(home_rating, away_rating, home_field_advantage)
    e_away = 1.0 - e_home

    return EloUpdate(
        home_rating_new=home_rating + k_factor * (s_home - e_home),
        away_rating_new=away_rating + k_factor * (s_away - e_away),
        home_expected=e_home,
        away_expected=e_away,
    )
