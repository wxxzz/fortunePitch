"""球员原始数据解析:按场次球员名单 -> fp_base_players 字段。

竞彩网只提供宽泛位置(前锋/中场/后卫/门将),映射为
库内约定的短码:ST/MF/DF/GK。
"""

import typing

# sporttery playerPositionCode -> fp_base_players.position 短码
_POSITION_CODE_MAP = {
    "Forward": "ST",
    "Midfielder": "MF",
    "Defender": "DF",
    "Goalkeeper": "GK",
}


def map_position(position_code: typing.Any) -> str | None:
    """将竞彩网位置编码映射为库内短码,未知编码返回 None。"""
    return _POSITION_CODE_MAP.get(str(position_code or ""))


def parse_match_players(
    value: dict[str, typing.Any],
) -> dict[int, list[dict[str, typing.Any]]]:
    """解析按场次球员名单接口的 value。

    Args:
        value: ``fetch_match_players`` 返回的 value(含 home/away)。

    Returns:
        统一球队 ID -> 球员字段列表(``player_name``/``position``)。

    Raises:
        ValueError: 响应结构异常(缺球队 ID)。
    """
    teams: dict[int, list[dict[str, typing.Any]]] = {}
    for side in ("home", "away"):
        team = value.get(side)
        if not isinstance(team, dict):
            continue
        team_id = team.get("uniformTeamId")
        if not isinstance(team_id, int):
            raise ValueError("球员名单缺少 uniformTeamId")
        players: list[dict[str, typing.Any]] = []
        for player in team.get("playerList") or []:
            name = str(player.get("personName") or "").strip()
            if not name:
                continue
            players.append(
                {"player_name": name, "position": map_position(player.get("playerPositionCode"))}
            )
        teams[team_id] = players
    return teams
