"""数据采集模块 Pydantic Schema:联赛 / 球队 / 球员 / 赛事同步。"""

import datetime

from pydantic import BaseModel, Field

from app.api.v1.base.schemas import LeagueRead


class LeagueSyncRequest(BaseModel):
    """同步请求体:按名称从竞彩网拉取联赛相关信息。"""

    league_name: str = Field(
        min_length=1, max_length=128, description="联赛名称,如“西甲”", examples=["西甲"]
    )


class LeagueSyncResultRead(BaseModel):
    """联赛同步结果。"""

    league: LeagueRead
    action: str = Field(description="created=新建档案,updated=更新已有档案")
    uniform_league_id: int = Field(description="竞彩网统一联赛 ID")
    source: str = Field(description="数据来源标识", default="sporttery")


class TeamSyncResultRead(BaseModel):
    """球队同步结果。"""

    league: LeagueRead
    team_count: int = Field(description="同步球队总数")
    created_count: int = Field(description="新建球队数")
    updated_count: int = Field(description="更新球队数")
    uniform_league_id: int = Field(description="竞彩网统一联赛 ID")
    source: str = Field(description="数据来源标识", default="sporttery")


class TeamPlayerCountRead(BaseModel):
    """球队维度的球员计数。"""

    team_name: str
    player_count: int


class PlayerSyncResultRead(BaseModel):
    """球员同步结果。"""

    league: LeagueRead
    team_count: int = Field(description="取得球员数据的球队数")
    player_count: int = Field(description="入库球员总数")
    created_count: int = Field(description="新建球员数")
    updated_count: int = Field(description="更新球员数")
    matches_scanned: int = Field(description="扫描的已完成比赛场次")
    team_player_counts: list[TeamPlayerCountRead] = Field(
        description="各队球员数明细"
    )
    skipped_teams: list[str] = Field(
        description="未取得球员数据的球队(如刚升级、赛季初未完赛)"
    )
    source: str = Field(description="数据来源标识", default="sporttery")


class MatchSyncRequest(BaseModel):
    """同步请求体:按售卖日拉取竞彩在售赛程。"""

    date: datetime.date = Field(
        description="竞彩售卖日(YYYY-MM-DD),与赛程赛果页的日期选择一致",
        examples=["2026-08-24"],
    )


class MatchSyncResultRead(BaseModel):
    """赛事同步结果。"""

    date: datetime.date = Field(description="本次同步的售卖日")
    day_match_count: int = Field(description="该售卖日竞彩网在售场次总数")
    created_count: int = Field(description="新建赛事数")
    updated_count: int = Field(description="更新赛事数")
    odds_count: int = Field(
        default=0, description="写入/刷新玩法赔率的场次数(赔率接口失败时为 0)"
    )
    skipped_leagues: list[str] = Field(
        description="联赛档案未入库而被跳过的联赛,请先同步对应联赛"
    )
    skipped_matches: list[str] = Field(
        description="球队档案未入库等原因被跳过的场次说明"
    )
    source: str = Field(description="数据来源标识", default="sporttery")


class ResultSyncRequest(BaseModel):
    """同步请求体:按比赛日拉取竞彩赛果开奖数据。"""

    date: datetime.date = Field(
        description="比赛日(YYYY-MM-DD),与赛果开奖页的日期选择一致",
        examples=["2026-08-25"],
    )


class ResultSyncResultRead(BaseModel):
    """赛果同步结果。"""

    date: datetime.date = Field(description="本次同步的比赛日")
    day_result_count: int = Field(description="该比赛日竞彩网已开赛场次总数")
    created_count: int = Field(description="新建赛果数")
    updated_count: int = Field(description="更新赛果数")
    game_updated_count: int = Field(description="回写比分与完赛状态的场次数")
    skipped_matches: list[str] = Field(
        description="场次未入库等原因被跳过的场次说明"
    )
    source: str = Field(description="数据来源标识", default="sporttery")
