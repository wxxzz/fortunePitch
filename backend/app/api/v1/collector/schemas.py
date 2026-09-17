"""数据采集模块 Pydantic Schema:联赛 / 球队 / 球员 / 赛事同步。"""

import datetime
import typing

from pydantic import BaseModel, Field, model_validator

from app.api.v1.base.schemas import LeagueRead, TeamRead


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


class TeamFundamentalsSyncResultRead(BaseModel):
    """球队基本面同步结果。"""

    league: LeagueRead
    season: str = Field(description="基本面所属赛季,如 2026-2027")
    team_count: int = Field(description="写入基本面数据的球队数")
    created_count: int = Field(description="新建基本面数")
    updated_count: int = Field(description="更新基本面数")
    skipped_teams: list[str] = Field(
        description="积分榜未覆盖的球队(如赛季初尚未开赛)"
    )
    uniform_league_id: int = Field(description="竞彩网统一联赛 ID")
    source: str = Field(description="数据来源标识", default="sporttery")


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
    odds_snapshot_count: int = Field(
        default=0,
        description="因赔率变化而新增的赔率快照条数(未变不落快照)",
    )
    skipped_leagues: list[str] = Field(
        description="联赛档案未入库而被跳过的联赛,请先同步对应联赛"
    )
    skipped_matches: list[str] = Field(
        description="球队档案未入库等原因被跳过的场次说明"
    )
    source: str = Field(description="数据来源标识", default="sporttery")


class ResultSyncRequest(BaseModel):
    """同步请求体:按比赛日或售卖日拉取竞彩赛果开奖数据。"""

    date: datetime.date = Field(
        description="日期(YYYY-MM-DD),与所选 date_type 口径一致",
        examples=["2026-08-25"],
    )
    date_type: typing.Literal["match", "sale"] = Field(
        default="match",
        description=(
            "日期口径:match=比赛日(与赛果开奖页的日期选择一致);"
            "sale=售卖日(同时拉取该日与次日的赛果,覆盖次日凌晨场)"
        ),
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


class TeamDashboardSyncRequest(BaseModel):
    """同步请求体:按球队拉取竞彩网球队专栏数据。"""

    team_id: int | None = Field(
        default=None, description="本地球队 ID(需已同步球队档案映射)", examples=[3]
    )
    uniform_team_id: int | None = Field(
        default=None,
        description="竞彩网统一球队 ID(球队专栏页 URL 的 tid)",
        examples=[220],
    )
    term_limits: int = Field(
        default=20,
        ge=1,
        le=100,
        description="赛程赛果拉取的近期完赛条数上限",
    )

    @model_validator(mode="after")
    def check_exactly_one_id(self) -> "TeamDashboardSyncRequest":
        """team_id 与 uniform_team_id 必须二选一。"""
        if (self.team_id is None) == (self.uniform_team_id is None):
            raise ValueError("team_id 与 uniform_team_id 必须二选一")
        return self


class TeamDashboardSyncResultRead(BaseModel):
    """球队看板同步结果。"""

    team: TeamRead = Field(description="同步的本地球队")
    uniform_team_id: int = Field(description="竞彩网统一球队 ID")
    profile_created: bool = Field(description="是否新建了竞彩网档案映射")
    future_count: int = Field(description="本次拉取的未来赛事条数")
    result_count: int = Field(description="本次拉取的赛程赛果条数")
    created_count: int = Field(description="新建看板比赛数")
    updated_count: int = Field(description="更新看板比赛数")
    pruned_count: int = Field(description="修剪的失效未开赛行数")
    source: str = Field(description="数据来源标识", default="sporttery")
