"""数据采集模块 Pydantic Schema:联赛同步。"""

from pydantic import BaseModel, Field

from app.api.v1.base.schemas import LeagueRead


class LeagueSyncRequest(BaseModel):
    """联赛同步请求体:按名称从竞彩网拉取联赛信息。"""

    league_name: str = Field(
        min_length=1, max_length=128, description="联赛名称,如“西甲”", examples=["西甲"]
    )


class LeagueSyncResultRead(BaseModel):
    """联赛同步结果。"""

    league: LeagueRead
    action: str = Field(description="created=新建档案,updated=更新已有档案")
    uniform_league_id: int = Field(description="竞彩网统一联赛 ID")
    source: str = Field(description="数据来源标识", default="sporttery")
