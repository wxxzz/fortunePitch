"""球队基本面解析:积分榜总/主/客三榜行 -> fp_base_team_fundamentals 字段。

职责:
- 将三榜原始行(字符串计数)归一化为强类型字段字典
- 单榜或个别字段缺失时容错降级(保留 None)
- 赛季名归一化与联赛档案一致(如 "2026/2027" -> "2026-2027")
"""

import typing

from app.collector.parsers import league as league_parser

# 总榜行字段 -> 基本面字段(ranking/胜平负/进失球/积分/胜率)
_TOTAL_FIELDS = (
    ("ranking", "ranking"),
    ("totalLegCnt", "played"),
    ("winGoalMatchCnt", "wins"),
    ("drawMatchCnt", "draws"),
    ("lossGoalMatchCnt", "losses"),
    ("goalCnt", "goals_for"),
    ("lossGoalCnt", "goals_against"),
    ("netGoal", "goal_diff"),
    ("points", "points"),
    ("winProbability", "win_rate"),
)


def _to_int(value: typing.Any) -> int | None:
    """字符串计数转整数,无法解析时返回 None。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_percent(value: typing.Any) -> float | None:
    """胜率字符串("100%")转百分数值(100.0),无法解析时返回 None。"""
    if not isinstance(value, str):
        return None
    try:
        return round(float(value.rstrip("%")), 2)
    except ValueError:
        return None


def _view_fields(
    row: dict[str, typing.Any] | None, prefix: str = ""
) -> dict[str, typing.Any]:
    """单榜行转字段;row 缺失时返回空字典(调用方保留 NULL)。"""
    if not isinstance(row, dict):
        return {}
    fields: dict[str, typing.Any] = {}
    for source_key, target_key in _TOTAL_FIELDS:
        raw = row.get(source_key)
        if source_key == "winProbability":
            value = _to_percent(raw)
        else:
            value = _to_int(raw)
        if value is not None:
            fields[f"{prefix}{target_key}"] = value
    return fields


def build_fundamental_fields(
    season_name: str,
    total_row: dict[str, typing.Any],
    home_row: dict[str, typing.Any] | None = None,
    away_row: dict[str, typing.Any] | None = None,
) -> dict[str, typing.Any]:
    """组合总/主/客三榜行,产出 fp_base_team_fundamentals 字段。

    Args:
        season_name: 赛季名(积分榜所属赛季,如 "2026/2027")。
        total_row: 总榜行(必有,作为基准)。
        home_row: 主场榜行(可能缺失,如赛季初仅踢过客场的球队)。
        away_row: 客场榜行(可能缺失)。

    Returns:
        除 ``team_id``/``update_time`` 外的字段字典
        (同步层补充主键与时间戳)。
    """
    fields: dict[str, typing.Any] = _view_fields(total_row)
    fields.update(_view_fields(home_row, prefix="home_"))
    fields.update(_view_fields(away_row, prefix="away_"))
    fields["season"] = league_parser.normalize_season(season_name)
    return fields
