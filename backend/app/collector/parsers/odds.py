"""竞彩玩法赔率解析:混合过关计算器原始响应 -> fp_match_odds 结构。

职责:
- 将 5 种玩法(had/hhad/crs/ttg/hafu)的原始赔率字典归一化为
  统一的选项结构(poolCode/playName/goalLine/options)
- 剔除未开售(无赔率值)的玩法
- 组合出可直接入库的 MatchOdds 字段字典
"""

import typing

from app.core.exceptions import DataValidationError

# 玩法编码 -> 展示名(与竞彩官方玩法命名一致)
_PLAY_NAMES = {
    "HAD": "胜平负",
    "HHAD": "让球胜平负",
    "CRS": "比分",
    "TTG": "总进球",
    "HAFU": "半全场",
}

# 胜平负/让球胜平负的三个选项
_WDL_OPTIONS = (
    ("h", "h", "主胜"),
    ("d", "d", "平"),
    ("a", "a", "客胜"),
)

# 半全场 9 个选项:前半场 + 全场结果(胜/平/负 -> 胜/平/负)
_HAFU_OPTIONS = (
    ("hh", "hh", "胜胜"),
    ("hd", "hd", "胜平"),
    ("ha", "ha", "胜负"),
    ("dh", "dh", "平胜"),
    ("dd", "dd", "平平"),
    ("da", "da", "平负"),
    ("ah", "ah", "负胜"),
    ("ad", "ad", "负平"),
    ("aa", "aa", "负负"),
)

# 比分特殊选项(胜/平/负其他),键 -> 展示名
_CRS_SPECIAL = {
    "s1sh": "胜其他",
    "s1sd": "平其他",
    "s1sa": "负其他",
}


def _build_option(
    code: str, label: str, raw_odds: typing.Any
) -> dict[str, typing.Any] | None:
    """把原始赔率值转为选项字典,无值(未开售)返回 None。"""
    try:
        odds = float(raw_odds)
    except (TypeError, ValueError):
        return None
    if odds <= 0:
        return None
    return {"code": code, "label": label, "odds": odds}


def _build_crs_label(key: str) -> str:
    """比分键转展示标签:``s01s02`` -> ``1:2``(s+主队2位+s+客队2位)。"""
    return f"{int(key[1:3])}:{int(key[4:6])}"


def build_odds_pools(
    raw_pools: dict[str, typing.Any],
) -> list[dict[str, typing.Any]]:
    """将单场比赛的原始玩法赔率归一化为统一选项结构。

    Args:
        raw_pools: ``fetch_match_odds`` 返回的原始玩法字典,
            如 ``{"had": {"h": "2.15", ...}, "crs": {...}}``。

    Returns:
        玩法列表,每条含:
        - ``poolCode``: 玩法编码(HAD/HHAD/CRS/TTG/HAFU)
        - ``playName``: 玩法展示名
        - ``goalLine``: 让球盘口(仅 HHAD,如 "-1")
        - ``options``: 选项列表(``code``/``label``/``odds``)

        未开售(无有效赔率)的玩法被剔除;全部为空时返回空列表。
    """
    pools: list[dict[str, typing.Any]] = []

    def _append(
        pool_code: str,
        options: list[dict[str, typing.Any]],
        goal_line: str | None = None,
    ) -> None:
        if options:
            record: dict[str, typing.Any] = {
                "poolCode": pool_code,
                "playName": _PLAY_NAMES[pool_code],
                "options": options,
            }
            if goal_line:
                record["goalLine"] = goal_line
            pools.append(record)

    had = raw_pools.get("had") or {}
    _append(
        "HAD",
        [
            opt
            for key, code, label in _WDL_OPTIONS
            if (opt := _build_option(code, label, had.get(key))) is not None
        ],
    )

    hhad = raw_pools.get("hhad") or {}
    _append(
        "HHAD",
        [
            opt
            for key, code, label in _WDL_OPTIONS
            if (opt := _build_option(code, label, hhad.get(key))) is not None
        ],
        goal_line=str(hhad.get("goalLine") or "").strip() or None,
    )

    crs = raw_pools.get("crs") or {}
    crs_options = []
    for key in sorted(k for k in crs if k.startswith("s") and "s" in k[1:]):
        if key in _CRS_SPECIAL:
            continue
        opt = _build_option(key, _build_crs_label(key), crs.get(key))
        if opt is not None:
            crs_options.append(opt)
    for key, label in _CRS_SPECIAL.items():
        opt = _build_option(key, label, crs.get(key))
        if opt is not None:
            crs_options.append(opt)
    _append("CRS", crs_options)

    ttg = raw_pools.get("ttg") or {}
    ttg_options = []
    for num in range(8):
        label = f"{num}+" if num == 7 else str(num)
        opt = _build_option(f"s{num}", label, ttg.get(f"s{num}"))
        if opt is not None:
            ttg_options.append(opt)
    _append("TTG", ttg_options)

    hafu = raw_pools.get("hafu") or {}
    _append(
        "HAFU",
        [
            opt
            for key, code, label in _HAFU_OPTIONS
            if (opt := _build_option(code, label, hafu.get(key))) is not None
        ],
    )

    return pools


def build_odds_record(
    odds_item: dict[str, typing.Any],
) -> dict[str, typing.Any] | None:
    """将 ``fetch_match_odds`` 的单条记录解析为 MatchOdds 入库字段。

    Returns:
        字段字典(``match_id``/``pools``),全部玩法均未开售时返回 None。

    Raises:
        DataValidationError: matchId 缺失。
    """
    match_id = odds_item.get("matchId")
    if not match_id:
        raise DataValidationError("赔率记录的比赛 ID(matchId)缺失")
    pools = build_odds_pools(odds_item.get("pools") or {})
    if not pools:
        return None
    return {"match_id": str(match_id), "pools": pools}
