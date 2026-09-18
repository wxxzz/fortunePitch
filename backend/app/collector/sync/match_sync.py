"""赛事同步:按售卖日拉取竞彩在售赛程并写入 fp_match_games。

流程:拉取在售赛程 -> 按售卖日过滤 -> 逐场解析 ->
联赛/球队须已在基础档案中(联赛或球队缺失的场次跳过并在结果中
说明,需先在数据采集页同步对应联赛)-> 按 match_id 幂等 upsert ->
拉取 5 种玩法赔率并幂等写入 fp_match_odds(仅覆盖已入库场次),
赔率发生变化时另追加一条快照到 fp_match_odds_snapshots(未变不落,
避免走势出现重复噪音点)。

已入库场次只刷新开赛时间,不改写状态与比分,避免赛果数据被
未开赛状态覆盖。
"""

import datetime
import typing

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.parsers import match as match_parser
from app.collector.parsers import odds as odds_parser
from app.collector.sources import sporttery
from app.core.exceptions import ExternalSourceError
from app.models import (
    League,
    MatchGame,
    MatchOdds,
    MatchOddsSnapshot,
    MatchStatus,
    Team,
)


class MatchSyncResult(typing.NamedTuple):
    """一次赛事同步的结果。"""

    date: str
    # 售卖日当天竞彩网在售场次总数
    day_match_count: int
    created_count: int
    updated_count: int
    # 本次写入/刷新玩法赔率的场次数
    odds_count: int
    # 本次因赔率变化而新增的赔率快照条数
    odds_snapshot_count: int
    # 联赛未入库而被跳过的联赛名称(去重)
    skipped_league_names: list[str]
    # 球队未入库等原因被跳过的场次描述,如“周一004 奥萨苏纳 vs 莱万特”
    skipped_matches: list[str]


async def sync_matches_by_date(session: AsyncSession, date: str) -> MatchSyncResult:
    """按售卖日同步竞彩在售赛程,并刷新已入库场次的玩法赔率。

    Args:
        session: 异步数据库会话。
        date: 售卖日,格式 ``YYYY-MM-DD``。

    Returns:
        同步结果,含新建/更新计数、赔率刷新场次数与被跳过的联赛、场次说明。
    """
    all_matches = await sporttery.fetch_match_day_list()
    day_matches = match_parser.filter_matches_by_date(all_matches, date)

    league_map = await _load_league_map(session)
    skipped_league_names: list[str] = []
    skipped_matches: list[str] = []
    created_count = 0
    updated_count = 0
    for sub in day_matches:
        fields = match_parser.build_match_fields(sub)
        league = league_map.get(fields["league_name"])
        if league is None:
            _append_unique(skipped_league_names, fields["league_name"])
            continue

        home_team = await session.scalar(
            select(Team).where(
                Team.league_id == league.league_id,
                Team.team_name == fields["home_team_name"],
            )
        )
        away_team = await session.scalar(
            select(Team).where(
                Team.league_id == league.league_id,
                Team.team_name == fields["away_team_name"],
            )
        )
        if home_team is None or away_team is None:
            missing = [
                name
                for name, team in (
                    (fields["home_team_name"], home_team),
                    (fields["away_team_name"], away_team),
                )
                if team is None
            ]
            skipped_matches.append(
                f"{sub.get('matchNumStr', '')} "
                f"{fields['home_team_name']} vs {fields['away_team_name']}"
                f"(球队未入库:{'、'.join(missing)})"
            )
            continue

        game = await session.get(MatchGame, fields["match_id"])
        if game is None:
            game = MatchGame(
                match_id=fields["match_id"],
                match_num_str=fields["match_num_str"],
                league_id=league.league_id,
                home_team_id=home_team.team_id,
                away_team_id=away_team.team_id,
                match_time=fields["match_time"],
                business_date=fields["business_date"],
                match_status=MatchStatus.PENDING,
            )
            session.add(game)
            created_count += 1
        else:
            # 只刷新场次编号/开赛时间/售卖日;状态与比分由赛果数据维护,不做降级
            game.match_num_str = fields["match_num_str"]
            game.match_time = fields["match_time"]
            game.business_date = fields["business_date"]
            updated_count += 1

    odds_count, snapshot_count = await _sync_match_odds(session)

    await session.flush()
    return MatchSyncResult(
        date=date,
        day_match_count=len(day_matches),
        created_count=created_count,
        updated_count=updated_count,
        odds_count=odds_count,
        odds_snapshot_count=snapshot_count,
        skipped_league_names=skipped_league_names,
        skipped_matches=skipped_matches,
    )


async def _sync_match_odds(session: AsyncSession) -> tuple[int, int]:
    """拉取全部在售玩法赔率,幂等写入已入库场次的 fp_match_odds。

    计算器接口覆盖全部在售日,未入库场次跳过(避免外键错误);
    已有赔率记录时原地刷新玩法与更新时间。首次写入或赔率相对上次
    发生变化时,另向 fp_match_odds_snapshots 追加一条完整快照
    (赔率未变不落快照,避免走势出现重复点)。

    Returns:
        (写入/刷新赔率的场次数, 新增快照条数)。
        外部接口失败时为 (0, 0),不影响赛程同步。
    """
    try:
        odds_items = await sporttery.fetch_match_odds()
    except ExternalSourceError:
        # 赔率拉取失败不阻断赛程同步(结果中 odds_count=0),
        # 下次同步自动补齐
        return 0, 0

    # 会话 autoflush=False,本同步新建的场次仍在 pending 状态,
    # 不 flush 的话下面 existing_ids 查不到它们,当次赛程将永远错过赔率
    await session.flush()
    existing_ids = set(
        await session.scalars(select(MatchGame.match_id))
    )
    odds_count = 0
    snapshot_count = 0
    for item in odds_items:
        fields = odds_parser.build_odds_record(item)
        if fields is None or fields["match_id"] not in existing_ids:
            continue
        record = await session.get(MatchOdds, fields["match_id"])
        if record is None:
            session.add(MatchOdds(**fields))
            session.add(MatchOddsSnapshot(match_id=fields["match_id"], pools=fields["pools"]))
            snapshot_count += 1
        elif record.pools != fields["pools"]:
            record.pools = fields["pools"]
            # default 仅在插入时生效,更新时须显式刷新(与模型 default 同口径)
            record.update_time = datetime.datetime.now()
            session.add(MatchOddsSnapshot(match_id=fields["match_id"], pools=fields["pools"]))
            snapshot_count += 1
        odds_count += 1
    return odds_count, snapshot_count


async def _load_league_map(session: AsyncSession) -> dict[str, League]:
    """加载全量联赛档案,按联赛全称索引。"""
    leagues = (await session.scalars(select(League))).all()
    return {league.league_name: league for league in leagues}


def _append_unique(target: list[str], value: str) -> None:
    """向列表追加去重后的值(保持首次出现顺序)。"""
    if value not in target:
        target.append(value)
