"""Dixon-Coles 泊松比分预测服务。

核心思路:将足球比分建模为两个独立泊松分布,
并用 Dixon-Coles 低比分相关性修正项 `tau` 校正
泊松独立假设在 0-0 / 1-0 / 0-1 / 1-1 上的系统性偏差。

数学模型:

    P(home=i, away=j) = tau(i, j; lambda, mu, rho) * Pois(i; lambda) * Pois(j; mu)

    Pois(k; lambda) = lambda^k * e^(-lambda) / k!

    tau 修正项:
        i=0, j=0 : 1 - lambda * mu * rho
        i=0, j=1 : 1 + lambda * rho
        i=1, j=0 : 1 + mu * rho
        i=1, j=1 : 1 - rho
        其他     : 1

其中 lambda / mu 分别为主/客队期望进球(可由 xG 或 Elo 差换算),
rho 为相关性参数(通常取 -0.1 附近)。
"""

import math
from dataclasses import dataclass

from app.core.exceptions import DataValidationError

# 最大比分迭代上限(单队进球数 0..MAX_GOALS)
MAX_GOALS: int = 10
# 默认 Dixon-Coles 相关系数
DEFAULT_RHO: float = -0.10


@dataclass(frozen=True)
class ScoreGrid:
    """比分概率矩阵与衍生盘口概率(不可变对象)。"""

    # grid[i][j] = P(主队进 i 球, 客队进 j 球)
    grid: list[list[float]]
    home_win_prob: float
    draw_prob: float
    away_win_prob: float
    total_goals_expected: float


def poisson_pmf(k: int, lam: float) -> float:
    """泊松分布概率质量函数。

    公式: P(X=k) = lambda^k * e^(-lambda) / k!

    Args:
        k: 进球数(非负整数)。
        lam: 期望进球 lambda(> 0)。

    Returns:
        P(X = k)。

    Raises:
        DataValidationError: 参数非法(k 为负或 lam 非正)。
    """
    if k < 0:
        raise DataValidationError(f"进球数 k 不能为负: {k}")
    if lam <= 0:
        raise DataValidationError(f"期望进球 lambda 必须为正: {lam}")
    return (lam**k) * math.exp(-lam) / math.factorial(k)


def dixon_coles_tau(i: int, j: int, lam: float, mu: float, rho: float) -> float:
    """Dixon-Coles 低比分修正因子 tau。

    仅对比分 (0,0) (0,1) (1,0) (1,1) 生效,其余比分返回 1。
    """
    if i == 0 and j == 0:
        return 1.0 - lam * mu * rho
    if i == 0 and j == 1:
        return 1.0 + lam * rho
    if i == 1 and j == 0:
        return 1.0 + mu * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


def predict_score_grid(
    lam: float,
    mu: float,
    rho: float = DEFAULT_RHO,
    max_goals: int = MAX_GOALS,
) -> ScoreGrid:
    """基于 Dixon-Coles 模型生成比分概率矩阵与胜平负概率。

    Args:
        lam: 主队期望进球(通常来自 xG 或 Elo 换算)。
        mu: 客队期望进球。
        rho: Dixon-Coles 相关系数。
        max_goals: 单队进球数枚举上限。

    Returns:
        归一化后的 `ScoreGrid`,包含比分矩阵、胜/平/负概率
        与总进球期望。

    Raises:
        DataValidationError: 输入参数非法。
    """
    if lam <= 0 or mu <= 0:
        raise DataValidationError(f"期望进球必须为正: lambda={lam}, mu={mu}")
    if max_goals < 1:
        raise DataValidationError(f"进球枚举上限必须 >= 1: {max_goals}")

    grid: list[list[float]] = []
    for i in range(max_goals + 1):
        row: list[float] = []
        for j in range(max_goals + 1):
            tau = dixon_coles_tau(i, j, lam, mu, rho)
            prob = tau * poisson_pmf(i, lam) * poisson_pmf(j, mu)
            row.append(prob)
        grid.append(row)

    # 截断枚举会导致总概率略小于 1,重新归一化
    total = sum(cell for row in grid for cell in row)
    if total <= 0:
        raise DataValidationError("比分矩阵总概率非正,无法归一化,请检查输入参数")
    grid = [[cell / total for cell in row] for row in grid]

    home_win_prob = sum(
        grid[i][j] for i in range(max_goals + 1) for j in range(max_goals + 1) if i > j
    )
    draw_prob = sum(grid[k][k] for k in range(max_goals + 1))
    away_win_prob = sum(
        grid[i][j] for i in range(max_goals + 1) for j in range(max_goals + 1) if i < j
    )

    return ScoreGrid(
        grid=grid,
        home_win_prob=home_win_prob,
        draw_prob=draw_prob,
        away_win_prob=away_win_prob,
        total_goals_expected=lam + mu,
    )


def kelly_fraction(model_prob: float, decimal_odds: float) -> float:
    """计算 Kelly Criterion(凯利公式)资金比例。

    公式: f* = (b * p - q) / b = (p * (odds - 1) - (1 - p)) / (odds - 1)

    其中 p 为模型估计概率,q = 1 - p,b = odds - 1 为净赔率。
    结果为负说明市场赔率低于模型价值,不应投入(返回 0 表示无价值)。

    Args:
        model_prob: 模型预测该结果发生的概率,(0, 1)。
        decimal_odds: 欧洲十进制赔率(> 1)。

    Returns:
        建议投入的资金比例 f*;无正期望时返回 0。

    Raises:
        DataValidationError: 参数超出定义域。
    """
    if not 0.0 < model_prob < 1.0:
        raise DataValidationError(f"模型概率必须在 (0, 1) 内: {model_prob}")
    if decimal_odds <= 1.0:
        raise DataValidationError(f"十进制赔率必须大于 1: {decimal_odds}")

    b = decimal_odds - 1.0
    f_star = (model_prob * decimal_odds - 1.0) / b
    return max(f_star, 0.0)
