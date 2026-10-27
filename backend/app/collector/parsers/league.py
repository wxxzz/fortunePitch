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

# 联赛全称中的常见语义片段 -> 简称片段(“词元压缩”推导简称用)
#
# 已知冲突:“瑞典”与“瑞士”均压缩为“瑞”(竞彩网列表仅有“瑞超”)。
# 候选层按“唯一精确命中”生效,列表同时出现两国联赛时会因歧义回退
# 包含匹配;仅单国入库时存在静默误配风险,新增此类国家时需复核映射。
# 国家/地区
_ABBR_TOKENS: dict[str, str] = {
    "英格兰": "英",
    "德国": "德",
    "西班牙": "西",
    "意大利": "意",
    "法国": "法",
    "韩国": "韩",
    "日本": "日",
    "美国": "美",
    "沙特": "沙",
    "澳大利亚": "澳",
    "挪威": "挪",
    "葡萄牙": "葡",
    "荷兰": "荷",
    "瑞典": "瑞",
    "瑞士": "瑞",
    "芬兰": "芬",
    "中国": "中",
    "亚洲": "亚",
    "欧洲": "欧",
    # 玩法/性质词
    "超级": "超",
    "甲级": "甲",
    "乙级": "乙",
    "丙级": "丙",
    "冠军": "冠",
    "职业": "职",
    "国家": "国",
    "协会": "协",
    "运动会": "运",
    "运会": "运",
}
_ABBR_TOKEN_MAX_LEN = max(len(token) for token in _ABBR_TOKENS)

# 结尾泛称:压缩结果以此结尾时,额外生成“删除”与“取首字”两种候选
_TRAILING_DROPS = ("联赛", "大联盟")


def _token_at(name: str, pos: int) -> tuple[str, str] | None:
    """返回 name 在 pos 处可匹配的最长词元 ``(原文, 简称片段)``。"""
    upper = min(_ABBR_TOKEN_MAX_LEN, len(name) - pos)
    for length in range(upper, 1, -1):
        piece = name[pos : pos + length]
        if piece in _ABBR_TOKENS:
            return piece, _ABBR_TOKENS[piece]
    return None


def derived_league_abbr_candidates(full_name: str) -> list[str]:
    """从联赛全称推导竞彩网简称候选列表。

    库内 ``league_name`` 为竞彩网详情页全称,而联赛列表条目仅含简称,
    两者既不相等也不互为子串(如“德国乙级联赛”vs“德乙”、
    “亚洲冠军精英联赛”vs“亚冠精英”)。采用“词元压缩”:国家/地区与
    性质词按映射取短写,其余片段原样保留;结尾泛称(“联赛”“大联盟”)
    额外生成删除/取首字变体。一个全称可对应多个候选
    (如“欧洲国家联赛”->“欧国联赛”/“欧国”/“欧国联”),由调用方
    逐个与列表简称精确比对,唯一命中才生效。
    """
    if not full_name.strip():
        return []
    parts: list[str] = []
    i = 0
    while i < len(full_name):
        token = _token_at(full_name, i)
        if token is not None:
            parts.append(token[1])
            i += len(token[0])
            continue
        # 无词元起点:原样透传,直到下一个词元起点或串尾
        j = i + 1
        while j < len(full_name) and _token_at(full_name, j) is None:
            j += 1
        parts.append(full_name[i:j])
        i = j
    compressed = "".join(parts)

    candidates = [compressed]
    for drop in _TRAILING_DROPS:
        if compressed.endswith(drop) and len(compressed) > len(drop):
            stripped = compressed[: -len(drop)]
            candidates.append(stripped)
            candidates.append(stripped + drop[0])
    return list(dict.fromkeys(candidates))


def find_league_item(
    items: list[dict[str, typing.Any]], league_name: str
) -> dict[str, typing.Any]:
    """按名称从展平后的联赛列表中定位唯一条目。

    匹配优先级:简称精确相等 > 全称词元压缩推导简称精确相等
    (如“德国乙级联赛”->“德乙”、“亚洲冠军精英联赛”->“亚冠精英”)
    > 简称互相包含(如“甲”匹配“西甲”)。同一联赛可能出现在多个分组
    (hot/normal 各一条,uniformLeagueId 相同),按 uniformLeagueId
    去重后才判歧义。

    Args:
        items: ``fetch_league_list`` 返回的展平列表。
        league_name: 用户输入的联赛名称(如“西甲”或库内全称“西班牙甲级联赛”)。

    Returns:
        唯一匹配的联赛条目。

    Raises:
        DataValidationError: 无匹配或匹配到多个联赛。
    """
    name = league_name.strip()
    if not name:
        raise DataValidationError("联赛名称不能为空")

    exact = _dedupe(
        it for it in items if it.get("leagueAbbCnName") == name
    )
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise DataValidationError(
            f"联赛名称“{name}”匹配到多个条目,请使用更精确的名称"
        )

    # 全称按“词元压缩”推导简称候选后逐个精确匹配;候选无果或匹配
    # 不唯一时继续走包含匹配,维持原有歧义/未找到报错口径
    candidate_matches = _dedupe(
        it
        for candidate in derived_league_abbr_candidates(name)
        for it in items
        if it.get("leagueAbbCnName") == candidate
    )
    if len(candidate_matches) == 1:
        return candidate_matches[0]

    partial = _dedupe(
        it
        for it in items
        if (abbr := str(it.get("leagueAbbCnName") or ""))
        and (name in abbr or abbr in name)
    )
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        candidates = "、".join(str(it.get("leagueAbbCnName")) for it in partial)
        raise DataValidationError(
            f"联赛名称“{name}”存在歧义,可选:{candidates}"
        )
    raise DataValidationError(f"未在竞彩网联赛资料中找到联赛“{name}”")


def _dedupe(
    items: typing.Iterable[dict[str, typing.Any]],
) -> list[dict[str, typing.Any]]:
    """按 uniformLeagueId 去重(无 ID 的条目按名称去重,均无则保留)。

    竞彩网列表中同一联赛可能同时出现在 hot 与 normal 分组,
    属同一实体,不应判为歧义。
    """
    seen_ids: set[int] = set()
    seen_names: set[str] = set()
    unique: list[dict[str, typing.Any]] = []
    for item in items:
        league_id = item.get("uniformLeagueId")
        name = str(item.get("leagueAbbCnName") or "")
        if league_id is not None:
            if league_id in seen_ids:
                continue
            seen_ids.add(league_id)
        elif name:
            if name in seen_names:
                continue
            seen_names.add(name)
        unique.append(item)
    return unique


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
