"""中国竞彩网(sporttery.cn)数据源适配器。

对应前端页面 https://www.sporttery.cn/zqlszl/ (足球联赛资料),
实际数据来自 webapi.sporttery.cn 网关,本模块屏蔽其协议细节,
对上层只暴露结构化的联赛列表与联赛详情。
"""

import contextlib
import typing

import httpx

from app.core.exceptions import ExternalSourceError

# 网关基址与接口路径(从 zqlszl 页面脚本 zqIndex.js 提取)
_BASE_URL = "https://webapi.sporttery.cn"
_LEAGUE_LIST_PATH = "/gateway/uniform/football/league/getLeagueListV1.qry"
_LEAGUE_DETAIL_PATH = "/gateway/uniform/football/league/getLeagueV1.qry"
_LEAGUE_TABLES_PATH = "/gateway/uniform/football/league/getTablesV2.qry"
_LEAGUE_MATCHES_PATH = "/gateway/uniform/football/league/getMatchResultV1.qry"
_TEAM_INFO_PATH = "/gateway/uniform/football/team/getTeamInfoV1.qry"
_MATCH_PLAYERS_PATH = "/gateway/uniform/football/getMatchPlayerV1.qry"
_MATCH_DAY_LIST_PATH = "/gateway/uniform/football/getMatchListV1.qry"
# 混合过关计算器接口(全部 5 种玩法赔率;matchId 与在售赛程一致)
_MATCH_ODDS_PATH = "/gateway/jc/football/getMatchCalculatorV1.qry"
_MATCH_ODDS_POOL_CODES = "HAD,HHAD,CRS,TTG,HAFU"
# 赛果开奖接口(足球赛果开奖页数据,matchId 与在售赛程一致)
_MATCH_RESULT_PATH = "/gateway/uniform/football/getUniformMatchResultV1.qry"
# 单页赛果条数(接口默认 30,配合翻页使用)
_MATCH_RESULT_PAGE_SIZE = 30
# 翻页上限(防止源站 total 异常导致死循环)
_MATCH_RESULT_MAX_PAGES = 20

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


@contextlib.asynccontextmanager
async def _client() -> typing.AsyncGenerator[httpx.AsyncClient, None]:
    """统一的网关客户端(携带浏览器请求头与超时)。"""
    async with httpx.AsyncClient(
        base_url=_BASE_URL, headers=_HEADERS, timeout=_REQUEST_TIMEOUT_SECONDS
    ) as async_client:
        yield async_client


async def _get_json(
    client: httpx.AsyncClient, path: str, params: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """GET 并解析 JSON,网络/解析失败统一转 ExternalSourceError。"""
    try:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ExternalSourceError(f"接口请求失败:{path}", detail=str(exc)) from exc


async def fetch_league_list() -> list[dict[str, typing.Any]]:
    """拉取全部联赛列表,hot/normal/other 三组展平。

    hot 分组条目为平铺联赛;normal 等分组的条目为洲包装
    (``countryList`` -> 国家 -> ``leagueList``),展平时下钻两层。

    Returns:
        展平后的联赛条目列表,每条在原始字段外附加:
        - ``group``: 所属分组(hot/normal/other)
        - ``tier``: 由分组推导的联赛级别
        - ``countryCnName``: 所属国家/地区名(仅嵌套条目携带)

    Raises:
        ExternalSourceError: 网络失败或响应结构不符合预期。
    """
    try:
        async with _client() as client:
            payload = await _get_json(client, _LEAGUE_LIST_PATH, {})
    except ExternalSourceError as exc:
        raise ExternalSourceError("联赛列表拉取失败,请稍后重试", detail=exc.detail) from exc

    groups = _extract_value(payload, "联赛列表")
    flattened: list[dict[str, typing.Any]] = []

    def _append(
        group_name: str,
        league: dict[str, typing.Any],
        country: str | None = None,
    ) -> None:
        flattened.append(
            {
                "group": group_name,
                "tier": _GROUP_TIER.get(group_name, 2),
                **({"countryCnName": country} if country else {}),
                **league,
            }
        )

    for group_name, items in groups.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("leagueAbbCnName"):
                # 平铺条目(hot 分组常见)
                _append(group_name, item)
                continue
            # 洲/地区包装条目:countryList -> 国家 -> leagueList
            for country_item in item.get("countryList") or []:
                if not isinstance(country_item, dict):
                    continue
                country_name = country_item.get("countryCnName")
                for league in country_item.get("leagueList") or []:
                    if isinstance(league, dict):
                        _append(group_name, league, country_name)
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
        async with _client() as client:
            payload = await _get_json(
                client, _LEAGUE_DETAIL_PATH, {"uniformLeagueId": uniform_league_id}
            )
    except ExternalSourceError as exc:
        raise ExternalSourceError(
            f"联赛详情拉取失败(leagueId={uniform_league_id})", detail=exc.detail
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


async def fetch_league_standings(season_id: int) -> list[dict[str, typing.Any]]:
    """按赛季 ID 拉取联赛积分榜(总榜),作为球队清单来源。

    赛季尚未开赛时总榜为空,返回空列表,由调用方回溯历史赛季;
    杯赛可能包含多个阶段/小组(如欧冠),全部展平并按
    ``uniformTeamId`` 去重。

    Args:
        season_id: 赛季 ID(联赛列表接口 seasonList 中的 seasonId)。

    Returns:
        总积分榜的球队行列表(含 abbCnName/uniformTeamId/ranking 等),
        无积分榜数据时为空列表。

    Raises:
        ExternalSourceError: 网络失败或结构异常。
    """
    async with _client() as client:
        payload = await _get_json(
            client, _LEAGUE_TABLES_PATH, {"seasonId": season_id}
        )
    tables = _extract_value(payload, "联赛积分榜")
    if not isinstance(tables, dict):
        raise ExternalSourceError("联赛积分榜结构异常", detail="value 不是对象")
    rows: list[dict[str, typing.Any]] = []
    seen: set[int] = set()
    for phase in tables.get("totalTables") or []:
        for group in phase.get("groups") or []:
            for row in group.get("tables") or []:
                team_id = row.get("uniformTeamId")
                if team_id is not None and team_id in seen:
                    continue
                if team_id is not None:
                    seen.add(team_id)
                rows.append(row)
    return rows


async def fetch_team_infos(
    uniform_team_ids: list[int],
) -> list[dict[str, typing.Any]]:
    """批量拉取球队详情(全称、所属国家等),复用同一 HTTP 连接。

    Args:
        uniform_team_ids: 竞彩网统一球队 ID 列表。

    Returns:
        与入参顺序一致的球队详情列表;单个球队拉取失败时对应位置为空字典。

    Raises:
        ExternalSourceError: 网络失败(整体)。
    """
    results: list[dict[str, typing.Any]] = []
    async with _client() as client:
        for team_id in uniform_team_ids:
            payload = await _get_json(
                client, _TEAM_INFO_PATH, {"uniformTeamId": team_id}
            )
            value = payload.get("value")
            results.append(value if isinstance(value, dict) else {})
    return results


async def fetch_season_matches(
    season_id: int, uniform_league_id: int
) -> list[dict[str, typing.Any]]:
    """拉取赛季全部赛程赛果,展平为单场列表。

    Returns:
        按比赛日期降序排列的比赛列表(含 gmMatchId/uniformHomeTeamId/
        uniformAwayTeamId/matchDate/wbsjMatchScDesc 等)。

    Raises:
        ExternalSourceError: 网络失败或结构异常。
    """
    async with _client() as client:
        payload = await _get_json(
            client,
            _LEAGUE_MATCHES_PATH,
            {"seasonId": season_id, "uniformLeagueId": uniform_league_id},
        )
    value = _extract_value(payload, "赛季赛程赛果")
    match_list = value.get("matchList") or []
    matches = [sub for day in match_list for sub in day.get("subMatchList", [])]
    matches.sort(key=lambda m: str(m.get("matchDate", "")), reverse=True)
    return matches


async def fetch_match_players(
    gm_match_id: int, term_limits: int = 50
) -> dict[str, typing.Any] | None:
    """按场次拉取双方球员名单(含位置与出场数据)。

    Args:
        gm_match_id: 竞彩网比赛 ID(赛果接口的 gmMatchId)。
        term_limits: 返回球员数量上限,默认取满名单。

    Returns:
        接口 value:含 home/away 两侧,每侧有 uniformTeamId 与 playerList;
        未开赛场次无球员数据时返回 None。

    Raises:
        ExternalSourceError: 网络失败或结构异常。
    """
    async with _client() as client:
        payload = await _get_json(
            client,
            _MATCH_PLAYERS_PATH,
            {"sportteryMatchId": gm_match_id, "termLimits": term_limits},
        )
    error_code = str(payload.get("errorCode", ""))
    if error_code != "0":
        raise ExternalSourceError(
            "球员名单接口返回错误",
            detail=f"errorCode={error_code}, message={payload.get('errorMessage')}",
        )
    value = payload.get("value")
    if not isinstance(value, dict) or not value:
        return None
    return value


async def fetch_match_day_list() -> list[dict[str, typing.Any]]:
    """拉取竞彩在售赛程列表(足球赛程赛果页数据),展平为单场列表。

    对应页面 https://www.sporttery.cn/jc/zqszsc/ ,接口按售卖日
    (businessDate)分组返回 matchInfoList,每场含 matchDate/matchTime/
    联赛与球队全称等;此处展平并按开赛时间升序排列。

    Returns:
        在售比赛列表(原始 subMatch 字典,含 businessDate/matchDate/
        matchTime/leagueAllName/homeTeamAllName/awayTeamAllName 等)。

    Raises:
        ExternalSourceError: 网络失败或结构异常。
    """
    try:
        async with _client() as client:
            payload = await _get_json(
                client, _MATCH_DAY_LIST_PATH, {"clientCode": "3001"}
            )
    except ExternalSourceError as exc:
        raise ExternalSourceError("竞彩赛程拉取失败,请稍后重试", detail=exc.detail) from exc

    value = _extract_value(payload, "竞彩赛程")
    match_info_list = value.get("matchInfoList") or []
    matches: list[dict[str, typing.Any]] = []
    for day in match_info_list:
        if not isinstance(day, dict):
            continue
        for sub in day.get("subMatchList") or []:
            if isinstance(sub, dict):
                matches.append(sub)
    matches.sort(key=lambda m: (str(m.get("matchDate", "")), str(m.get("matchTime", ""))))
    return matches


async def fetch_match_odds() -> list[dict[str, typing.Any]]:
    """拉取竞彩全部在售场次的 5 种玩法赔率(混合过关计算器)。

    接口的 ``matchId`` 与在售赛程列表一致,可按 matchId 关联已入库场次。
    返回各玩法的原始赔率字典(had/hhad/crs/ttg/hafu),未开售的玩法
    在对应场次上缺失。

    Returns:
        在售场次赔率列表,每条含 ``matchId`` / 各玩法原始赔率字典 /
        ``updateTime``(取各玩法中最新的更新时间)。

    Raises:
        ExternalSourceError: 网络失败或结构异常。
    """
    try:
        async with _client() as client:
            payload = await _get_json(
                client,
                _MATCH_ODDS_PATH,
                {"poolCode": _MATCH_ODDS_POOL_CODES, "channel": "c"},
            )
    except ExternalSourceError as exc:
        raise ExternalSourceError("竞彩赔率拉取失败,请稍后重试", detail=exc.detail) from exc

    value = _extract_value(payload, "竞彩赔率")
    odds_list: list[dict[str, typing.Any]] = []
    for day in value.get("matchInfoList") or []:
        if not isinstance(day, dict):
            continue
        for sub in day.get("subMatchList") or []:
            if not isinstance(sub, dict) or not sub.get("matchId"):
                continue
            pools = {
                code: sub[code]
                for code in ("had", "hhad", "crs", "ttg", "hafu")
                if isinstance(sub.get(code), dict)
            }
            if not pools:
                continue
            update_times = [
                f"{pool.get('updateDate', '')} {pool.get('updateTime', '')}".strip()
                for pool in pools.values()
            ]
            odds_list.append(
                {
                    "matchId": sub["matchId"],
                    "pools": pools,
                    "updateTime": max(update_times) if update_times else "",
                }
            )
    return odds_list


async def fetch_match_results(date: str) -> list[dict[str, typing.Any]]:
    """拉取指定比赛日的竞彩赛果开奖数据(足球赛果开奖页数据)。

    对应页面 https://www.sporttery.cn/jc/zqsgkj/ ,接口按比赛日区间返回
    已开奖场次,每场含全场/半场比分、胜平负结果(winFlag)、让球盘口与
    胜平负开奖 SP;``matchId`` 与赛程列表一致。此处翻页聚合全部结果,
    未开奖的日期返回空列表。

    Args:
        date: 比赛日,格式 ``YYYY-MM-DD``。

    Returns:
        赛果条目列表(原始字段,含 matchId/matchNumStr/leagueName/
        sectionsNo1/sectionsNo999/winFlag/goalLine/h/d/a/poolStatus)。

    Raises:
        ExternalSourceError: 网络失败或结构异常。
    """
    results: list[dict[str, typing.Any]] = []
    page_no = 1
    try:
        async with _client() as client:
            for _ in range(_MATCH_RESULT_MAX_PAGES):
                payload = await _get_json(
                    client,
                    _MATCH_RESULT_PATH,
                    {
                        "matchBeginDate": date,
                        "matchEndDate": date,
                        "leagueId": "",
                        "pageSize": str(_MATCH_RESULT_PAGE_SIZE),
                        "pageNo": str(page_no),
                        "isFix": "0",
                        "matchPage": "1",
                        "pcOrWap": "1",
                    },
                )
                value = _extract_value(payload, "竞彩赛果")
                page_items = [
                    item
                    for item in value.get("matchResult") or []
                    if isinstance(item, dict) and item.get("matchId")
                ]
                results.extend(page_items)
                total = value.get("total") or 0
                if len(results) >= int(total) or len(page_items) < _MATCH_RESULT_PAGE_SIZE:
                    break
                page_no += 1
    except ExternalSourceError as exc:
        raise ExternalSourceError("竞彩赛果拉取失败,请稍后重试", detail=exc.detail) from exc
    return results
