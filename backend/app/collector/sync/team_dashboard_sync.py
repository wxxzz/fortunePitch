"""球队看板同步:按竞彩网球队专栏拉取未来赛事与赛程赛果。

流程:解析看板球队(本地球队 ID 或竞彩网统一球队 ID,后者依赖
球队档案映射)-> 拉取球队详情并 upsert 档案映射 -> 拉取未来赛事
upsert 并修剪已失效的未开赛行 -> 拉取参赛联赛 ID 后抓取近期赛果
upsert(未开赛行补上比分与结果)。

数据来源:https://www.sporttery.cn/zqlszl/qdzl/ (tid=竞彩网统一球队 ID)。
"""

import datetime
import logging
import typing

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.parsers import team_dashboard as dashboard_parser
from app.collector.sources import sporttery
from app.core.exceptions import DataValidationError, ResourceNotFoundError
from app.models import Team, TeamMatch, TeamProfile

logger = logging.getLogger(__name__)

# logo 允许的 URL 形态:竞彩网返回 http(s) 或协议相对地址
_LOGO_SCHEME_PREFIXES = ("http://", "https://", "//")


class TeamDashboardSyncResult(typing.NamedTuple):
    """一次球队看板同步的结果。"""

    team: Team
    uniform_team_id: int
    profile_created: bool
    future_count: int
    result_count: int
    created_count: int
    updated_count: int
    pruned_count: int


def build_profile_fields(
    info: dict[str, typing.Any], fallback_name: str
) -> dict[str, typing.Any]:
    """从球队详情提取 fp_base_team_profiles 字段。"""
    logo_url = str(info.get("logoUrl") or "").strip() or None
    if logo_url and not logo_url.startswith(_LOGO_SCHEME_PREFIXES):
        # 非白名单 scheme 的 logo 一律丢弃,防止注入异常 URL
        logger.warning("丢弃非法 logo_url: %r", logo_url)
        logo_url = None
    return {
        "uniform_team_id": int(info["uniformTeamId"]),
        "gm_team_id": int(info["gmTeamId"]) if info.get("gmTeamId") else None,
        "wbsj_team_id": int(info["wbsjTeamId"]) if info.get("wbsjTeamId") else None,
        "abbrev_name": str(info.get("abbCnName") or fallback_name).strip(),
        "full_name": str(info.get("allCnName") or "").strip() or None,
        "country_name": str(info.get("countryCnName") or "").strip() or None,
        "logo_url": logo_url,
    }


async def upsert_team_profile(
    session: AsyncSession, team: Team, info: dict[str, typing.Any]
) -> bool | None:
    """按球队详情 upsert 档案映射,返回是否新建(None=信息不足跳过)。

    同一 uniform_team_id 已挂在其他球队下时跳过(球队更换联赛等场景),
    避免唯一键冲突。
    """
    if not info or info.get("uniformTeamId") is None:
        return None
    fields = build_profile_fields(info, team.team_name)
    conflict = await session.scalar(
        select(TeamProfile).where(
            TeamProfile.uniform_team_id == fields["uniform_team_id"]
        )
    )
    if conflict is not None and conflict.team_id != team.team_id:
        logger.warning(
            "uniform_team_id=%s 已属于球队 %s,跳过球队 %s 的档案写入",
            fields["uniform_team_id"],
            conflict.team_id,
            team.team_id,
        )
        return None
    profile = await session.get(TeamProfile, team.team_id)
    if profile is None:
        profile = TeamProfile(team_id=team.team_id, **fields)
        profile.update_time = datetime.datetime.now()
        session.add(profile)
        await session.flush()
        return True
    for key, value in fields.items():
        setattr(profile, key, value)
    profile.update_time = datetime.datetime.now()
    await session.flush()
    return False


async def _find_same_name_profile(
    session: AsyncSession, team: Team
) -> TeamProfile | None:
    """查找同名球队(任意联赛)持有的档案映射。

    杯赛联赛下的球队行因 uniform_team_id 唯一约束拿不到自己的档案时,
    借用同名俱乐部在国内联赛行下的映射。
    """
    return await session.scalar(
        select(TeamProfile)
        .join(Team, Team.team_id == TeamProfile.team_id)
        .where(Team.team_name == team.team_name, Team.team_id != team.team_id)
        .limit(1)
    )


async def _resolve_dashboard_team(
    session: AsyncSession,
    team_id: int | None,
    uniform_team_id: int | None,
) -> tuple[Team, int]:
    """解析看板球队,返回 (本地球队, 竞彩网统一球队 ID)。

    本地球队按 (联赛, 球队名) 建档,同一俱乐部征战杯赛时会在杯赛联赛下
    另建一行;而档案映射的 uniform_team_id 唯一,只能挂在其中一个球队行下
    (通常是国内联赛行)。因此球队行缺档案时,回退查同名球队(其他联赛)
    的档案,复用其 uniform_team_id。

    Raises:
        DataValidationError: 两个 ID 同时提供/均未提供,或映射缺失。
        ResourceNotFoundError: 本地球队不存在。
    """
    if (team_id is None) == (uniform_team_id is None):
        raise DataValidationError("team_id 与 uniform_team_id 必须二选一")
    if team_id is not None:
        team = await session.get(Team, team_id)
        if team is None:
            raise ResourceNotFoundError("球队", str(team_id))
        profile = await session.get(TeamProfile, team_id)
        if profile is None:
            profile = await _find_same_name_profile(session, team)
        if profile is None:
            raise DataValidationError(
                "该球队尚未同步竞彩网档案(uniform_team_id 缺失),"
                "请先在数据采集页同步对应联赛(或其他同名球队所在联赛)"
                "的球队清单"
            )
        return team, int(profile.uniform_team_id)
    profile = await session.scalar(
        select(TeamProfile).where(TeamProfile.uniform_team_id == uniform_team_id)
    )
    if profile is None:
        raise DataValidationError(
            f"竞彩网球队(uniformTeamId={uniform_team_id})未入库,"
            "请先在数据采集页同步对应联赛的球队清单"
        )
    team = await session.get(Team, profile.team_id)
    if team is None:
        raise ResourceNotFoundError("球队", str(profile.team_id))
    return team, int(uniform_team_id)


async def _upsert_match(
    session: AsyncSession, team_id: int, fields: dict[str, typing.Any]
) -> bool:
    """按 (team_id, uniform_match_id) upsert 看板比赛行,返回是否新建。"""
    match = await session.get(TeamMatch, (team_id, fields["uniform_match_id"]))
    if match is None:
        session.add(TeamMatch(team_id=team_id, **fields))
        return True
    for key, value in fields.items():
        # 赛果接口不提供轮次/阶段,更新时保留未来赛事带来的旧值
        if key in ("gameweek", "phase_name") and value is None:
            continue
        setattr(match, key, value)
    match.update_time = datetime.datetime.now()
    return False


async def sync_team_dashboard(
    session: AsyncSession,
    *,
    team_id: int | None = None,
    uniform_team_id: int | None = None,
    term_limits: int = 20,
) -> TeamDashboardSyncResult:
    """同步球队看板:球队档案 + 未来赛事 + 赛程赛果。

    Args:
        session: 异步数据库会话。
        team_id: 本地球队 ID(需已同步球队档案映射)。
        uniform_team_id: 竞彩网统一球队 ID(球队专栏页 URL 的 tid)。
        term_limits: 赛程赛果拉取的近期完赛条数上限(1-100)。

    Returns:
        同步结果,含新建/更新/修剪计数。

    Raises:
        DataValidationError: ID 参数不合法或映射缺失。
        ResourceNotFoundError: 本地球队不存在。
        ExternalSourceError: 竞彩网接口失败。
    """
    team, uniform_id = await _resolve_dashboard_team(session, team_id, uniform_team_id)

    # 球队档案:刷新名称/国家/队徽等映射信息
    infos = await sporttery.fetch_team_infos([uniform_id])
    profile_created = await upsert_team_profile(
        session, team, infos[0] if infos else {}
    )
    profile_created = bool(profile_created)

    # 未来赛事:upsert 本期抓到的未开赛行
    created_count = 0
    updated_count = 0
    future_rows = await sporttery.fetch_team_future_matches(uniform_id)
    future_ids: set[int] = set()
    for item in future_rows:
        fields = dashboard_parser.build_future_match_fields(uniform_id, item)
        future_ids.add(fields["uniform_match_id"])
        if await _upsert_match(session, team.team_id, fields):
            created_count += 1
        else:
            updated_count += 1

    # 赛程赛果:先取参赛联赛 ID,再按全部联赛拉取近期赛果;
    # 已完赛的原未来赛事行会被补上比分与结果
    league_rows = await sporttery.fetch_team_league_list(uniform_id)
    league_ids = [
        int(row["uniformLeagueId"])
        for row in league_rows
        if row.get("uniformLeagueId")
    ]
    result_value = await sporttery.fetch_team_match_results(
        uniform_id, uniform_league_ids=league_ids, term_limits=term_limits
    )
    result_rows = [
        item for item in result_value.get("matchList") or [] if isinstance(item, dict)
    ]
    for item in result_rows:
        fields = dashboard_parser.build_result_match_fields(uniform_id, item)
        if await _upsert_match(session, team.team_id, fields):
            created_count += 1
        else:
            updated_count += 1

    # 修剪:删除本次未抓到的未开赛行(赛程改期/推迟产生的脏数据)。
    # 在赛果 upsert 之后执行,刚完赛的行已有比分,不会被误删;
    # 未来赛事为空时同样修剪(本期无未来赛程 => 库存未开赛行均为脏数据)
    pruned = await session.execute(
        delete(TeamMatch).where(
            TeamMatch.team_id == team.team_id,
            TeamMatch.full_home_score.is_(None),
            TeamMatch.uniform_match_id.not_in(future_ids),
        )
    )
    pruned_count = int(pruned.rowcount or 0)

    await session.flush()
    return TeamDashboardSyncResult(
        team=team,
        uniform_team_id=uniform_id,
        profile_created=profile_created,
        future_count=len(future_rows),
        result_count=len(result_rows),
        created_count=created_count,
        updated_count=updated_count,
        pruned_count=pruned_count,
    )
