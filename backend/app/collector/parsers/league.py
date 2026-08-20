"""联赛原始数据解析:竞彩网响应 -> fp_base_leagues 字段。

职责:
- 按名称从联赛列表中定位目标联赛(支持简称/包含匹配)
- 从联赛全称推导所属国家
- 赛份格式归一(``2026/2027`` -> ``2026-2027``)
- 组合列表条目与详情,产出可直接入库的字段字典
"""

import typing

from app.core.exceptions import DataValidationError

# 联赛全称的常见后缀,去除后剩余部分即国家/地区名
_COUNTRY_SUFFIXES = (
    "甲级联赛",
    "乙级联赛",
    "丙级联赛",
    "超级联赛",
    "甲级",
    "乙级",
    "联赛",
    "杯",
)


def find_league_item(
    items: list[dict[str, typing.Any]], league_name: str
) -> dict[str, typing.Any]:
    """按名称从展平后的联赛列表中定位唯一条目。

    匹配优先级:简称精确相等 > 简称互相包含(如“甲”匹配“西甲”)。

    Args:
        items: ``fetch_league_list`` 返回的展平列表。
        league_name: 用户输入的联赛名称(如“西甲”)。

    Returns:
        唯一匹配的联赛条目。

    Raises:
        DataValidationError: 无匹配或匹配到多个联赛。
    """
    name = league_name.strip()
    if not name:
        raise DataValidationError("联赛名称不能为空")

    exact = [it for it in items if it.get("leagueAbbCnName") == name]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise DataValidationError(
            f"联赛名称“{name}”匹配到多个条目,请使用更精确的名称"
        )

    partial = [
        it
        for it in items
        if (abbr := str(it.get("leagueAbbCnName") or ""))
        and (name in abbr or abbr in name)
    ]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        candidates = "、".join(str(it.get("leagueAbbCnName")) for it in partial)
        raise DataValidationError(
            f"联赛名称“{name}”存在歧义,可选:{candidates}"
        )
    raise DataValidationError(f"未在竞彩网联赛资料中找到联赛“{name}”")


def normalize_season(raw_season: str) -> str:
    """将竞彩网赛季格式归一为库内格式。

    ``2026/2027`` -> ``2026-2027``;已是连字符格式则原样返回。

    Raises:
        DataValidationError: 赛季串为空。
    """
    season = raw_season.strip()
    if not season:
        raise DataValidationError("赛季信息为空")
    return season.replace("/", "-")


def derive_country(full_name: str) -> str:
    """从联赛全称推导所属国家/地区。

    如“西班牙甲级联赛” -> “西班牙”。无法推导时返回“其他”。
    """
    for suffix in _COUNTRY_SUFFIXES:
        if full_name.endswith(suffix) and len(full_name) > len(suffix):
            return full_name[: -len(suffix)]
    return "其他"


def latest_season(item: dict[str, typing.Any]) -> str:
    """提取联赛条目中最新赛季并归一格式。

    竞彩网 seasonList 按新到旧排序,首项即当前赛季。

    Raises:
        DataValidationError: 列表缺失或为空。
    """
    season_list = item.get("seasonList")
    if not isinstance(season_list, list) or not season_list:
        raise DataValidationError("联赛赛季列表为空")
    return normalize_season(str(season_list[0].get("seasonName", "")))


def build_league_fields(
    item: dict[str, typing.Any], detail: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """组合列表条目与详情,产出 fp_base_leagues 字段字典。

    Args:
        item: 列表条目(含 group/tier 与 seasonList)。
        detail: ``fetch_league_detail`` 返回的详情。

    Returns:
        仅含 League 模型业务字段的字典:
        ``league_name`` / ``country`` / ``tier`` / ``season``。
    """
    full_name = str(detail.get("cnName") or item.get("leagueAbbCnName") or "")
    if not full_name:
        raise DataValidationError("联赛名称缺失")
    # 详情接口的 isHot 优先于列表分组推导的级别
    is_hot = detail.get("isHot")
    tier = int(item["tier"])
    if isinstance(is_hot, int):
        tier = 1 if is_hot == 1 else 2
    return {
        "league_name": full_name,
        "country": derive_country(full_name),
        "tier": tier,
        "season": latest_season(item),
    }
