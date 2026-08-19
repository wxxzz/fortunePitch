"""比赛与赛果模块 Pydantic Schema:比赛 / 事件。"""

import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import MatchStatus


# ---------- 比赛 ----------

class MatchGameCreate(BaseModel):
    """创建比赛请求体。"""

    match_id: str = Field(max_length=64, description="比赛全局唯一标识(外部数据源)")
    league_id: int
    home_team_id: int
    away_team_id: int
    referee_id: int | None = None
    match_time: datetime.datetime
    match_status: MatchStatus = MatchStatus.PENDING
    home_score: int | None = Field(default=None, ge=0)
    away_score: int | None = Field(default=None, ge=0)


class MatchGameRead(BaseModel):
    """比赛响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    match_id: str
    league_id: int
    home_team_id: int
    away_team_id: int
    referee_id: int | None
    match_time: datetime.datetime
    match_status: MatchStatus
    home_score: int | None
    away_score: int | None


class MatchScoreUpdate(BaseModel):
    """更新比分请求体(完赛录入)。"""

    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)


# ---------- 比赛事件 ----------

class MatchEventCreate(BaseModel):
    """创建比赛事件请求体。"""

    match_id: str = Field(max_length=64)
    event_type: str = Field(
        max_length=32, description="GOAL / RED_CARD / YELLOW_CARD / SUBSTITUTION"
    )
    event_minute: int = Field(ge=0, le=130)
    player_id: int | None = None
    is_home_team: bool = True


class MatchEventRead(BaseModel):
    """比赛事件响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    event_id: int
    match_id: str
    event_type: str
    event_minute: int
    player_id: int | None
    is_home_team: bool
