"""Dixon-Coles 泊松预测与凯利指数单元测试。"""

import math

import pytest

from app.core.exceptions import DataValidationError
from app.services.poisson import (
    MAX_GOALS,
    dixon_coles_tau,
    kelly_fraction,
    poisson_pmf,
    predict_score_grid,
)


class TestPoissonPmf:
    """poisson_pmf 行为测试。"""

    def test_known_value_lambda_one_k_zero(self) -> None:
        assert poisson_pmf(0, 1.0) == pytest.approx(math.exp(-1.0))

    def test_probabilities_sum_to_one(self) -> None:
        lam = 1.5
        total = sum(poisson_pmf(k, lam) for k in range(50))
        assert total == pytest.approx(1.0)

    def test_negative_k_raises(self) -> None:
        with pytest.raises(DataValidationError):
            poisson_pmf(-1, 1.0)

    def test_non_positive_lambda_raises(self) -> None:
        with pytest.raises(DataValidationError):
            poisson_pmf(1, 0.0)


class TestDixonColesTau:
    """dixon_coles_tau 行为测试。"""

    def test_low_scores_are_adjusted(self) -> None:
        lam, mu, rho = 1.3, 1.1, -0.1
        assert dixon_coles_tau(0, 0, lam, mu, rho) == pytest.approx(1.0 - lam * mu * rho)
        assert dixon_coles_tau(0, 1, lam, mu, rho) == pytest.approx(1.0 + lam * rho)
        assert dixon_coles_tau(1, 0, lam, mu, rho) == pytest.approx(1.0 + mu * rho)
        assert dixon_coles_tau(1, 1, lam, mu, rho) == pytest.approx(1.0 - rho)

    def test_other_scores_unadjusted(self) -> None:
        assert dixon_coles_tau(2, 1, 1.3, 1.1, -0.1) == pytest.approx(1.0)
        assert dixon_coles_tau(3, 0, 1.3, 1.1, -0.1) == pytest.approx(1.0)


class TestPredictScoreGrid:
    """predict_score_grid 行为测试。"""

    def test_probabilities_sum_to_one(self) -> None:
        result = predict_score_grid(1.5, 1.2)
        total = sum(cell for row in result.grid for cell in row)
        assert total == pytest.approx(1.0)

    def test_wdl_probs_sum_to_one(self) -> None:
        result = predict_score_grid(1.8, 0.9)
        wdl_sum = result.home_win_prob + result.draw_prob + result.away_win_prob
        assert wdl_sum == pytest.approx(1.0)

    def test_stronger_home_team_favored(self) -> None:
        result = predict_score_grid(2.2, 0.6)
        assert result.home_win_prob > result.away_win_prob

    def test_equal_strength_draw_prob_reasonable(self) -> None:
        result = predict_score_grid(1.2, 1.2)
        # 足球平局概率典型区间 0.20 ~ 0.35
        assert 0.20 < result.draw_prob < 0.35

    def test_grid_dimensions_match_max_goals(self) -> None:
        result = predict_score_grid(1.0, 1.0)
        assert len(result.grid) == MAX_GOALS + 1
        assert all(len(row) == MAX_GOALS + 1 for row in result.grid)

    def test_total_goals_expected_is_lambda_plus_mu(self) -> None:
        result = predict_score_grid(1.7, 1.1)
        assert result.total_goals_expected == pytest.approx(2.8)

    def test_invalid_lambda_raises(self) -> None:
        with pytest.raises(DataValidationError):
            predict_score_grid(0.0, 1.0)


class TestKellyFraction:
    """kelly_fraction 行为测试。"""

    def test_positive_edge_gives_positive_fraction(self) -> None:
        # p=0.6, odds=2.0: f* = (0.6*2 - 1) / 1 = 0.2
        assert kelly_fraction(0.6, 2.0) == pytest.approx(0.2)

    def test_no_edge_returns_zero(self) -> None:
        # 公平赔率下 f* = 0
        assert kelly_fraction(0.5, 2.0) == pytest.approx(0.0)

    def test_negative_edge_returns_zero(self) -> None:
        assert kelly_fraction(0.4, 2.0) == 0.0

    def test_invalid_prob_raises(self) -> None:
        with pytest.raises(DataValidationError):
            kelly_fraction(1.5, 2.0)

    def test_invalid_odds_raises(self) -> None:
        with pytest.raises(DataValidationError):
            kelly_fraction(0.5, 1.0)
