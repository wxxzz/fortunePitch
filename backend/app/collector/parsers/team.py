"""球队原始数据解析:积分榜行 + 球队详情 -> fp_base_teams 字段。"""

import typing

from app.core.exceptions import DataValidationError


def build_team_fields(
    standing_row: dict[str, typing.Any], team_info: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """组合积分榜行与球队详情,产出 fp_base_teams 业务字段。

    Args:
        standing_row: 积分榜行(含 abbCnName/uniformTeamId)。
        team_info: ``fetch_team_infos`` 返回的详情(可能为空字典)。

    Returns:
        含 ``team_name`` 的字段字典(联赛归属由同步层补充)。

    Raises:
        DataValidationError: 球队名称缺失。
    """
    team_name = str(
        team_info.get("allCnName") or standing_row.get("abbCnName") or ""
    ).strip()
    if not team_name:
        raise DataValidationError(
            f"球队名称缺失(uniformTeamId={standing_row.get('uniformTeamId')})"
        )
    return {"team_name": team_name}


def uniform_team_ids(rows: list[dict[str, typing.Any]]) -> list[int]:
    """从积分榜行列表提取统一球队 ID。"""
    return [int(row["uniformTeamId"]) for row in rows]
