"""xG(Expected Goals)计算服务单元测试。"""

import math

import pytest

from app.core.exceptions import DataValidationError
from app.services.xg import (
    GOAL_LINE_X,
    ShotEvent,
    angle_to_goal,
    calculate_team_xg,
    calculate_xg,
    distance_to_goal,
)


class TestDistanceToGoal:
    """distance_to_goal 行为测试。"""

    def test_goal_line_center_is_half_width_zero(self) -> None:
        # 球门中心点距离应为 0
        assert distance_to_goal(ShotEvent(x=GOAL_LINE_X, y=0.0)) == pytest.approx(0.0)

    def test_penalty_spot_distance(self) -> None:
        # 点球点距球门线 11 米
        d = distance_to_goal(ShotEvent(x=GOAL_LINE_X - 11.0, y=0.0))
        assert d == pytest.approx(11.0)

    def test_wide_shot_has_larger_distance(self) -> None:
        near = distance_to_goal(ShotEvent(x=GOAL_LINE_X - 10.0, y=0.0))
        wide = distance_to_goal(ShotEvent(x=GOAL_LINE_X - 10.0, y=15.0))
        assert wide > near


class TestAngleToGoal:
    """angle_to_goal 行为测试。"""

    def test_invalid_position_behind_goal_line_raises(self) -> None:
        with pytest.raises(DataValidationError):
            angle_to_goal(ShotEvent(x=GOAL_LINE_X + 1.0, y=0.0))

    def test_central_shot_has_max_angle(self) -> None:
        central = angle_to_goal(ShotEvent(x=GOAL_LINE_X - 10.0, y=0.0))
        wide = angle_to_goal(ShotEvent(x=GOAL_LINE_X - 10.0, y=10.0))
        assert central > wide

    def test_angle_in_valid_range(self) -> None:
        angle = angle_to_goal(ShotEvent(x=30.0, y=-5.0))
        assert 0.0 < angle < math.pi


class TestCalculateXg:
    """calculate_xg 行为测试。"""

    def test_xg_between_zero_and_one(self) -> None:
        shot = ShotEvent(x=GOAL_LINE_X - 15.0, y=3.0)
        assert 0.0 <= calculate_xg(shot) <= 1.0

    def test_closer_shot_has_higher_xg(self) -> None:
        close = calculate_xg(ShotEvent(x=GOAL_LINE_X - 6.0, y=0.0))
        far = calculate_xg(ShotEvent(x=GOAL_LINE_X - 30.0, y=0.0))
        assert close > far

    def test_header_has_lower_xg_than_foot_shot(self) -> None:
        foot = calculate_xg(ShotEvent(x=GOAL_LINE_X - 8.0, y=0.0, is_header=False))
        header = calculate_xg(ShotEvent(x=GOAL_LINE_X - 8.0, y=0.0, is_header=True))
        assert header < foot

    def test_shot_behind_goal_line_raises(self) -> None:
        with pytest.raises(DataValidationError):
            calculate_xg(ShotEvent(x=GOAL_LINE_X + 2.0, y=0.0))


class TestCalculateTeamXg:
    """calculate_team_xg 行为测试。"""

    def test_empty_shot_list_returns_zero(self) -> None:
        assert calculate_team_xg([]) == pytest.approx(0.0)

    def test_total_is_sum_of_individual_shots(self) -> None:
        shots = [
            ShotEvent(x=GOAL_LINE_X - 6.0, y=0.0),
            ShotEvent(x=GOAL_LINE_X - 20.0, y=5.0),
            ShotEvent(x=GOAL_LINE_X - 11.0, y=-2.0, is_header=True),
        ]
        expected_total = sum(calculate_xg(s) for s in shots)
        assert calculate_team_xg(shots) == pytest.approx(expected_total)
