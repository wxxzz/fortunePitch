"""竞彩赛果解析:赛果开奖原始响应 -> fp_match_results 结构。

职责:
- 解析全场/半场比分(sectionsNo999/sectionsNo1)与胜平负开奖 SP
- 由比分 + 让球盘口推导 5 种玩法的开奖结果(胜平负/让球胜平负/
  比分/总进球/半全场),与赛果开奖页的口径一致
- 组合出可直接入库的 MatchResult 字段字典
"""

import typing

from app.core.exceptions import DataValidationError

# 胜平负结果编码 -> 展示标签
_WDL_LABEL = {"H": "主胜", "D": "平", "A": "客胜"}

# 半全场结果用的单字标签(半场结果 + 全场结果,如“负负”)
_WDL_SHORT = {"H": "胜", "D": "平", "A": "负"}

# 赛果比分字段中,取消/无效场次的取值
_INVALID_SCORE_TEXTS = ("", "无效场次", "取消")


def _parse_score(raw: typing.Any) -> tuple[int, int] | None:
    """比分字符串转元组:``"1:2"`` -> ``(1, 2)``;无效返回 None。"""
    text = str(raw or "").strip()
    if text in _INVALID_SCORE_TEXTS:
        return None
    parts = text.split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _wdl_code(home: int, away: int) -> str:
    """由比分判定胜平负编码(H/D/A)。"""
    if home > away:
        return "H"
    if home < away:
        return "A"
    return "D"


def _parse_sp(raw: typing.Any) -> float | None:
    """开奖 SP 值转浮点,无效返回 None。"""
    try:
        sp = float(raw)
    except (TypeError, ValueError):
        return None
    return sp if sp > 0 else None


def derive_play_results(
    full_home: int,
    full_away: int,
    half_home: int,
    half_away: int,
    goal_line: int,
) -> dict[str, str]:
    """由比分与让球盘口推导各玩法开奖结果。

    Args:
        full_home/full_away: 全场比分。
        half_home/half_away: 半场比分。
        goal_line: 让球盘口(主队让球数,如 "-1")。

    Returns:
        玩法结果标签字典:``had``/``hhad``/``crs``/``ttg``/``hafu``,
        如 ``{"had": "客胜", "hhad": "让球客胜", "crs": "1:2",
        "ttg": "3", "hafu": "负负"}``。
    """
    had = _WDL_LABEL[_wdl_code(full_home, full_away)]
    adjusted = full_home + goal_line
    hhad = f"让球{_WDL_LABEL[_wdl_code(adjusted, full_away)]}"
    hafu = _WDL_SHORT[_wdl_code(half_home, half_away)] + _WDL_SHORT[
        _wdl_code(full_home, full_away)
    ]
    return {
        "had": had,
        "hhad": hhad,
        "crs": f"{full_home}:{full_away}",
        "ttg": str(full_home + full_away),
        "hafu": hafu,
    }


def build_result_fields(item: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """将赛果开奖的单条记录解析为 MatchResult 入库字段。

    Args:
        item: ``fetch_match_results`` 返回的原始条目。

    Returns:
        字段字典,取消/无效场次比分为 None、玩法结果为 None,
        仍保留场次信息与状态供开奖页展示。

    Raises:
        DataValidationError: matchId 缺失。
    """
    match_id = item.get("matchId")
    if not match_id:
        raise DataValidationError("赛果记录的比赛 ID(matchId)缺失")

    full = _parse_score(item.get("sectionsNo999"))
    half = _parse_score(item.get("sectionsNo1"))
    goal_line_text = str(item.get("goalLine") or "").strip()
    try:
        goal_line = int(goal_line_text) if goal_line_text else 0
    except ValueError:
        goal_line = 0

    fields: dict[str, typing.Any] = {
        "match_id": str(match_id),
        "match_num_str": str(item.get("matchNumStr") or "").strip(),
        "league_name": str(item.get("leagueName") or "").strip(),
        "home_team_name": str(item.get("allHomeTeam") or item.get("homeTeam") or "").strip(),
        "away_team_name": str(item.get("allAwayTeam") or item.get("awayTeam") or "").strip(),
        "goal_line": goal_line_text or None,
        "half_home_score": half[0] if half else None,
        "half_away_score": half[1] if half else None,
        "full_home_score": full[0] if full else None,
        "full_away_score": full[1] if full else None,
        "sp_h": _parse_sp(item.get("h")),
        "sp_d": _parse_sp(item.get("d")),
        "sp_a": _parse_sp(item.get("a")),
        "pool_status": str(item.get("poolStatus") or "").strip(),
        "had": None,
        "hhad": None,
        "crs": None,
        "ttg": None,
        "hafu": None,
    }
    if full is not None and half is not None:
        fields.update(
            derive_play_results(full[0], full[1], half[0], half[1], goal_line)
        )
    return fields
