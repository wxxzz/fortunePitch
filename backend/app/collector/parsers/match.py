"""比赛原始数据解析:竞彩网在售赛程 -> 赛事同步中间结构。

职责:
- 按售卖日(businessDate)过滤当日比赛,与竞彩赛程赛果页的日期选择一致
- 校验单场比赛的必备字段(场次号/时间/联赛与球队名称)
- 组合出可直接定位档案的字段字典(match_id/match_time/联赛与球队名称)
"""

import datetime
import typing

from app.core.exceptions import DataValidationError
from app.models import MatchStatus


def filter_matches_by_date(
    matches: list[dict[str, typing.Any]], date: str
) -> list[dict[str, typing.Any]]:
    """按售卖日(businessDate)过滤比赛列表。

    竞彩以售卖日组织场次:次日凌晨开赛的比赛归属前一个售卖日,
    与 https://www.sporttery.cn/jc/zqszsc/ 页面按日期查看的行为一致。

    Args:
        matches: ``fetch_match_day_list`` 返回的展平列表。
        date: 售卖日,格式 ``YYYY-MM-DD``。

    Returns:
        该售卖日的比赛列表(保持原顺序)。

    Raises:
        DataValidationError: 日期格式非法。
    """
    target = _parse_date(date)
    return [m for m in matches if str(m.get("businessDate", "")) == target]


def _parse_date(date: str) -> str:
    try:
        return datetime.date.fromisoformat(date).isoformat()
    except ValueError as exc:
        raise DataValidationError(f"日期格式非法:{date}(应为 YYYY-MM-DD)") from exc


def build_match_fields(sub: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """将单场 subMatch 解析为赛事同步所需字段。

    Returns:
        字段字典:
        - ``match_id``: 竞彩网比赛 ID(字符串,作 fp_match_games 主键)
        - ``match_time``: 开赛时间(matchDate + matchTime 组合,本地时区)
        - ``league_name`` / ``home_team_name`` / ``away_team_name``: 全称,
          与基础档案的 league_name / team_name 对齐
        - ``match_status``: Selling/Define 均为未开赛(PENDING)

    Raises:
        DataValidationError: 必备字段缺失或时间格式非法。
    """
    match_id = sub.get("matchId")
    if not match_id:
        raise DataValidationError("比赛 ID(matchId)缺失")
    league_name = str(sub.get("leagueAllName") or "").strip()
    home_name = str(sub.get("homeTeamAllName") or "").strip()
    away_name = str(sub.get("awayTeamAllName") or "").strip()
    if not (league_name and home_name and away_name):
        raise DataValidationError(
            f"比赛 {match_id} 的联赛或球队名称缺失"
        )
    return {
        "match_id": str(match_id),
        "match_time": build_match_time(sub),
        "business_date": build_business_date(sub),
        "league_name": league_name,
        "home_team_name": home_name,
        "away_team_name": away_name,
        "match_status": map_match_status(sub.get("matchStatus")),
    }


def build_business_date(sub: dict[str, typing.Any]) -> datetime.date | None:
    """提取售卖日(businessDate),次日凌晨开赛的比赛归属前一售卖日。

    Raises:
        DataValidationError: 字段存在但格式非法。
    """
    value = str(sub.get("businessDate") or "").strip()
    if not value:
        return None
    return _parse_date(value)


def build_match_time(sub: dict[str, typing.Any]) -> datetime.datetime:
    """组合 matchDate + matchTime 为开赛时间。

    Raises:
        DataValidationError: 日期或时间字段缺失/格式非法。
    """
    match_date = str(sub.get("matchDate") or "").strip()
    match_time = str(sub.get("matchTime") or "").strip()
    if not (match_date and match_time):
        raise DataValidationError(f"比赛 {sub.get('matchId')} 的开赛时间缺失")
    try:
        return datetime.datetime.fromisoformat(f"{match_date}T{match_time}")
    except ValueError as exc:
        raise DataValidationError(
            f"比赛 {sub.get('matchId')} 的开赛时间格式非法:"
            f"{match_date} {match_time}"
        ) from exc


def map_match_status(raw_status: typing.Any) -> MatchStatus:
    """竞彩赛程状态 -> 库内比赛状态。

    在售赛程只包含未开赛场次(Selling/Define),统一映射为 PENDING;
    完赛状态与比分由赛果数据另行回填,此处不做降级。
    """
    return MatchStatus.PENDING
