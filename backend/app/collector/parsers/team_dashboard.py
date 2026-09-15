"""球队看板原始数据解析:球队专栏接口响应 -> 看板表字段。

对应数据源:竞彩网球队专栏(sporttery.cn/zqlszl/qdzl)的
未来赛事与赛程赛果接口,均为纯函数,便于离线单元测试。
"""

import datetime
import typing

from app.core.exceptions import DataValidationError


def parse_match_time(value: typing.Any) -> datetime.datetime:
    """解析开赛时间,兼容未来赛事的 ``YYYY-MM-DD HH:MM`` 与
    赛程赛果的 ``YYYY-MM-DD`` 两种格式(日期补零点)。

    Raises:
        DataValidationError: 时间为空或格式不合法。
    """
    text = str(value or "").strip()
    if not text:
        raise DataValidationError("比赛时间为空")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise DataValidationError(f"比赛时间格式不合法:{text}")


def split_score(value: typing.Any) -> tuple[int | None, int | None]:
    """解析比分字符串(如 ``3:1``)为 (主, 客) 整数对。

    空值或格式不合法时返回 (None, None),不视为错误
    (未开赛场次与部分历史数据可能缺比分)。
    """
    text = str(value or "").strip()
    if not text:
        return (None, None)
    parts = text.split(":")
    if len(parts) != 2:
        return (None, None)
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return (None, None)


def compute_result(
    full_home: int | None, full_away: int | None, is_home: bool
) -> str | None:
    """按看板球队视角计算比赛结果:W=胜 D=平 L=负。

    比分缺失(未开赛)时返回 None。
    """
    if full_home is None or full_away is None:
        return None
    if full_home == full_away:
        return "D"
    home_won = full_home > full_away
    won = home_won if is_home else not home_won
    return "W" if won else "L"


def _require_fields(
    item: dict[str, typing.Any], keys: tuple[str, ...], api_name: str
) -> None:
    """校验条目必填字段,缺失时抛 DataValidationError。"""
    missing = [key for key in keys if item.get(key) in (None, "")]
    if missing:
        raise DataValidationError(
            f"{api_name}条目缺少必填字段:{','.join(missing)}"
        )


def _build_common_fields(
    uniform_team_id: int,
    item: dict[str, typing.Any],
    api_name: str,
) -> dict[str, typing.Any]:
    """提取未来赛事与赛程赛果共有的看板字段(不含比分)。"""
    _require_fields(
        item,
        ("uniformMatchId", "homeAbbCnName", "awayAbbCnName"),
        api_name,
    )
    home_id = item.get("uniformHomeTeamId")
    away_id = item.get("uniformAwayTeamId")
    return {
        "uniform_match_id": int(item["uniformMatchId"]),
        "uniform_league_id": int(item["uniformLeagueId"])
        if item.get("uniformLeagueId") is not None
        else None,
        "league_name": str(
            item.get("leagueAbbCnName") or item.get("leagueCnName") or ""
        ).strip()
        or None,
        "home_team_name": str(item["homeAbbCnName"]).strip(),
        "away_team_name": str(item["awayAbbCnName"]).strip(),
        "uniform_home_team_id": int(home_id) if home_id is not None else None,
        "uniform_away_team_id": int(away_id) if away_id is not None else None,
        "is_home": home_id is not None and int(home_id) == uniform_team_id,
    }


def build_future_match_fields(
    uniform_team_id: int, item: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """解析未来赛事条目为 fp_base_team_matches 字段(比分为空)。

    Args:
        uniform_team_id: 看板球队的竞彩网统一 ID。
        item: ``fetch_team_future_matches`` 返回的条目。

    Returns:
        含开赛时间/轮次/阶段/联赛与主客队信息的字段字典。

    Raises:
        DataValidationError: 必填字段缺失或时间格式不合法。
    """
    fields = _build_common_fields(uniform_team_id, item, "未来赛事")
    fields.update(
        {
            "match_time": parse_match_time(item.get("matchDateTime")),
            "gameweek": str(item["gameweek"]).strip()
            if item.get("gameweek") not in (None, "")
            else None,
            "phase_name": str(item.get("phaseName") or "").strip() or None,
            "half_home_score": None,
            "half_away_score": None,
            "full_home_score": None,
            "full_away_score": None,
            "team_result": None,
        }
    )
    return fields


def build_result_match_fields(
    uniform_team_id: int, item: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """解析赛程赛果条目为 fp_base_team_matches 字段(含比分与结果)。

    Args:
        uniform_team_id: 看板球队的竞彩网统一 ID。
        item: ``fetch_team_match_results`` 返回 matchList 中的条目。

    Returns:
        含比赛日期/半场与全场比分/看板球队视角结果的字段字典。

    Raises:
        DataValidationError: 必填字段缺失或日期格式不合法。
    """
    fields = _build_common_fields(uniform_team_id, item, "赛程赛果")
    half_home, half_away = split_score(item.get("sectionsNo1"))
    full_home, full_away = split_score(item.get("sectionsNo999"))
    fields.update(
        {
            "match_time": parse_match_time(item.get("matchDate")),
            "gameweek": None,
            "phase_name": None,
            "half_home_score": half_home,
            "half_away_score": half_away,
            "full_home_score": full_home,
            "full_away_score": full_away,
            "team_result": compute_result(full_home, full_away, fields["is_home"]),
        }
    )
    return fields
