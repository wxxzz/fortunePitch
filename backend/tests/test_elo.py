"""Elo 评分服务单元测试。"""

import pytest

from app.core.exceptions import DataValidationError
from app.services.elo import (
    DEFAULT_HOME_FIELD_ADVANTAGE,
    actual_score,
    expected_score,
    update_ratings,
)


class TestActualScore:
    """actual_score 行为测试。"""

    def test_home_win_returns_one_zero(self) -> None:
        assert actual_score(2, 1) == (1.0, 0.0)

    def test_away_win_returns_zero_one(self) -> None:
        assert actual_score(0, 3) == (0.0, 1.0)

    def test_draw_returns_half_half(self) -> None:
        assert actual_score(1, 1) == (0.5, 0.5)

    def test_negative_goals_raise_validation_error(self) -> None:
        with pytest.raises(DataValidationError):
            actual_score(-1, 0)


class TestExpectedScore:
    """expected_score 行为测试。"""

    def test_equal_ratings_with_hfa_above_half(self) -> None:
        expected = expected_score(1500.0, 1500.0)
        assert expected > 0.5
        assert expected < 1.0

    def test_sum_of_both_sides_equals_one(self) -> None:
        e_home = expected_score(1600.0, 1400.0)
        e_away = 1.0 - e_home
        assert e_home + e_away == pytest.approx(1.0)

    def test_stronger_home_team_has_higher_expectation(self) -> None:
        assert expected_score(1700.0, 1300.0) > expected_score(1500.0, 1500.0)

    def test_zero_hfa_equal_ratings_gives_half(self) -> None:
        assert expected_score(1500.0, 1500.0, home_field_advantage=0.0) == pytest.approx(0.5)


class TestUpdateRatings:
    """update_ratings 行为测试。"""

    def test_conservation_of_total_points(self) -> None:
        """零和性:双方评分之和在更新后保持不变。"""
        result = update_ratings(1500.0, 1500.0, home_goals=1, away_goals=0)
        total_before = 1500.0 + 1500.0
        total_after = result.home_rating_new + result.away_rating_new
        assert total_after == pytest.approx(total_before)

    def test_home_win_raises_home_rating(self) -> None:
        result = update_ratings(1500.0, 1500.0, home_goals=2, away_goals=0)
        assert result.home_rating_new > 1500.0
        assert result.away_rating_new < 1500.0

    def test_draw_between_equal_teams_keeps_ratings(self) -> None:
        result = update_ratings(1500.0, 1500.0, home_goals=1, away_goals=1)
        # 平局时主队因主场优势未达预期,评分略降
        assert result.home_rating_new < 1500.0

    def test_invalid_k_factor_raises(self) -> None:
        with pytest.raises(DataValidationError):
            update_ratings(1500.0, 1500.0, home_goals=1, away_goals=1, k_factor=0.0)

    def test_update_uses_default_hfa(self) -> None:
        result = update_ratings(1500.0, 1500.0, home_goals=0, away_goals=0)
        manual_expected = 1.0 / (
            1.0 + 10.0 ** ((1500.0 - 1500.0 - DEFAULT_HOME_FIELD_ADVANTAGE) / 400.0)
        )
        assert result.home_expected == pytest.approx(manual_expected)
