"""中国竞彩网(sporttery.cn)数据源适配器。

对应前端页面 https://www.sporttery.cn/zqlszl/ (足球联赛资料),
实际数据来自 webapi.sporttery.cn 网关,本模块屏蔽其协议细节,
对上层只暴露结构化的联赛列表与联赛详情。
"""

import typing

import httpx

from app.core.exceptions import ExternalSourceError

# 网关基址与接口路径(从 zqlszl 页面脚本 zqIndex.js 提取)
_BASE_URL = "https://webapi.sporttery.cn"
_LEAGUE_LIST_PATH = "/gateway/uniform/football/league/getLeagueListV1.qry"
_LEAGUE_DETAIL_PATH = "/gateway/uniform/football/league/getLeagueV1.qry"

_REQUEST_TIMEOUT_SECONDS = 15.0

# 竞彩网接口对无浏览器特征的请求可能拒绝,携带常用请求头
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://www.sporttery.cn/zqlszl/",
}

# 联赛列表分组 -> 联赛级别(1=顶级,2=次级)
_GROUP_TIER = {"hot": 1, "normal": 1, "other": 2}


async def fetch_league_list() -> list[dict[str, typing.Any]]:
    """拉取全部联赛列表,hot/normal/other 三组展平。

    Returns:
        展平后的联赛条目列表,每条在原始字段外附加:
        - ``group``: 所属分组(hot/normal/other)
        - ``tier``: 由分组推导的联赛级别

    Raises:
        ExternalSourceError: 网络失败或响应结构不符合预期。
    """
    try:
        async with httpx.AsyncClient(
            base_url=_BASE_URL,
            headers=_HEADERS,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(_LEAGUE_LIST_PATH)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ExternalSourceError(
            "联赛列表拉取失败,请稍后重试", detail=str(exc)
        ) from exc

    groups = _extract_value(payload, "联赛列表")
    flattened: list[dict[str, typing.Any]] = []
    for group_name, items in groups.items():
        if not isinstance(items, list):
            continue
        for item in items:
            flattened.append(
                {"group": group_name, "tier": _GROUP_TIER.get(group_name, 2), **item}
            )
    return flattened


async def fetch_league_detail(uniform_league_id: int) -> dict[str, typing.Any]:
    """按统一联赛 ID 拉取单个联赛详情(全称、英文名、是否热门等)。

    Args:
        uniform_league_id: 竞彩网统一联赛 ID(列表接口的 uniformLeagueId)。

    Returns:
        联赛详情字典(接口 value 字段)。

    Raises:
        ExternalSourceError: 网络失败、接口报错或详情为空。
    """
    try:
        async with httpx.AsyncClient(
            base_url=_BASE_URL,
            headers=_HEADERS,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(
                _LEAGUE_DETAIL_PATH, params={"uniformLeagueId": uniform_league_id}
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ExternalSourceError(
            f"联赛详情拉取失败(leagueId={uniform_league_id})", detail=str(exc)
        ) from exc

    detail = _extract_value(payload, "联赛详情")
    if not detail:
        raise ExternalSourceError(
            f"联赛详情为空(leagueId={uniform_league_id})",
            detail="接口返回空 value,该联赛可能已下线",
        )
    return detail


def _extract_value(payload: dict[str, typing.Any], api_name: str) -> typing.Any:
    """校验网关响应结构并提取 value 字段。

    Raises:
        ExternalSourceError: errorCode 非 0 或结构缺失。
    """
    if not isinstance(payload, dict):
        raise ExternalSourceError(f"{api_name}响应结构异常", detail="顶层不是对象")
    error_code = str(payload.get("errorCode", ""))
    if error_code != "0":
        raise ExternalSourceError(
            f"{api_name}接口返回错误",
            detail=f"errorCode={error_code}, message={payload.get('errorMessage')}",
        )
    value = payload.get("value")
    if value in (None, {}, []):
        raise ExternalSourceError(f"{api_name}接口返回空数据")
    return value
