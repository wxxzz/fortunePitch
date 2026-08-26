"""球员同步:按联赛名称从竞彩网比赛球员数据中收集名单并入库。

竞彩网没有独立的球队名单接口,球员数据挂在比赛维度的
“比赛数据射手信息”接口上(termLimits 放宽后返回双方完整出场名单)。

策略:先同步联赛与球队(保证外键可用),再从旧到新扫描赛季的
已完成比赛,收集双方球员;同一球队保留人数最多的名单,直到覆盖
联赛全部球队或达到调用上限。升班马在当前赛季尚未完赛时,
会在 skipped_teams 中如实上报。
"""

import typing

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.parsers import player as player_parser
from app.collector.sources import sporttery
from app.collector.sync import league_sync, team_sync
from app.models import League, Player, Team

# 单次球员同步最多请求的比赛场次数(防止长尾联赛拖垮同步)
MAX_MATCH_CALLS = 60
# 最多回溯的赛季数(当前赛季 + 上一赛季)
MAX_SEASONS = 2
# 已完成比赛的状态描述
_PLAYED_FLAG = "已完成"


class PlayerSyncResult(typing.NamedTuple):
    """一次球员同步的结果。"""

    league: League
    created_count: int
    updated_count: int
    # 各队入库球员数(按球队名)
    team_player_counts: list[tuple[str, int]]
    # 未能取得球员数据的球队名(如刚升级、赛季初尚未完赛)
    skipped_team_names: list[str]
    matches_scanned: int


async def sync_league_players(
    session: AsyncSession, league_name: str
) -> PlayerSyncResult:
    """按联赛名称同步球员名单(自动先同步联赛与球队)。

    Args:
        session: 异步数据库会话。
        league_name: 联赛名称,如“西甲”。

    Returns:
        同步结果,包含各队球员计数与未覆盖球队名单。
    """
    item, detail = await league_sync.resolve_league(league_name)
    league_result = await league_sync.upsert_league(session, item, detail)
    team_result = await team_sync.sync_teams_for_league(session, item, league_result)

    collected, skipped_team_names, matches_scanned = await _collect_players(
        item, team_result
    )
    created_count, updated_count = await _upsert_players(
        session, collected, team_result.uniform_team_map
    )
    team_player_counts = [
        (team.team_name, len(players))
        for team_id, players in collected.items()
        if (team := team_result.uniform_team_map.get(team_id)) is not None
    ]
    return PlayerSyncResult(
        league=league_result.league,
        created_count=created_count,
        updated_count=updated_count,
        team_player_counts=team_player_counts,
        skipped_team_names=skipped_team_names,
        matches_scanned=matches_scanned,
    )


async def _collect_players(
    item: dict[str, typing.Any], team_result: team_sync.TeamSyncResult
) -> tuple[
    dict[int, dict[str, dict[str, typing.Any]]],
    list[str],
    int,
]:
    """从旧到新扫描赛季比赛,收集各队球员。

    扫描顺序为旧赛季 -> 当前赛季:先以上一赛季补齐存量球队,
    再以当前赛季补齐升班马并刷新名单;同一球队保留人数更多的名单,
    避免赛季初仅踢一场的球队被稀疏数据覆盖完整名单。

    Returns:
        (uniform_team_id -> {player_name: 字段}, 未覆盖球队名列表, 扫描场次数)
    """
    target_teams = dict(team_result.uniform_team_map)
    remaining = set(target_teams)
    collected: dict[int, dict[str, dict[str, typing.Any]]] = {}
    matches_scanned = 0

    season_ids = [int(s["seasonId"]) for s in item.get("seasonList", [])]
    for season_id in reversed(season_ids[:MAX_SEASONS]):
        if not remaining or matches_scanned >= MAX_MATCH_CALLS:
            break
        matches = await sporttery.fetch_season_matches(
            season_id, team_result.uniform_league_id
        )
        for match in matches:
            if not remaining or matches_scanned >= MAX_MATCH_CALLS:
                break
            if match.get("wbsjMatchScDesc") != _PLAYED_FLAG:
                continue
            value = await sporttery.fetch_match_players(int(match["gmMatchId"]))
            matches_scanned += 1
            if value is None:
                continue
            for team_id, players in player_parser.parse_match_players(value).items():
                if team_id not in target_teams:
                    continue
                merged = {p["player_name"]: p for p in players}
                if not merged:
                    continue
                if team_id not in collected or len(merged) > len(collected[team_id]):
                    collected[team_id] = merged
                remaining.discard(team_id)

    skipped = [
        target_teams[team_id].team_name
        for team_id in sorted(remaining)
        if team_id in target_teams
    ]
    return collected, skipped, matches_scanned


async def _upsert_players(
    session: AsyncSession,
    collected: dict[int, dict[str, dict[str, typing.Any]]],
    uniform_team_map: dict[int, Team],
) -> tuple[int, int]:
    """将收集到的球员按 (team_id, player_name) 幂等写入 fp_base_players。

    Args:
        session: 异步数据库会话。
        collected: uniform_team_id -> {player_name: 字段}。
        uniform_team_map: uniform_team_id -> 已入库 Team 实体。

    Returns:
        (新建数, 更新数)。
    """
    created_count = 0
    updated_count = 0
    for uniform_team_id, players in collected.items():
        team = uniform_team_map.get(uniform_team_id)
        if team is None:
            continue
        existing = {
            p.player_name: p
            for p in (
                await session.scalars(
                    select(Player).where(Player.team_id == team.team_id)
                )
            ).all()
        }
        for name, fields in players.items():
            player = existing.get(name)
            if player is None:
                session.add(Player(team_id=team.team_id, **fields))
                created_count += 1
            else:
                player.position = fields["position"]
                updated_count += 1
    await session.flush()
    return created_count, updated_count
