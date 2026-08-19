"""基础档案模块 Pydantic Schema:联赛 / 球队 / 球员。"""

import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------- 联赛 ----------

class LeagueCreate(BaseModel):
    """创建联赛请求体。"""

    league_name: str = Field(max_length=128)
    country: str = Field(max_length=64)
    tier: int = Field(default=1, ge=1, le=5, description="联赛级别:1=顶级,2=次级")
    season: str = Field(default="2025-2026", max_length=16)


class LeagueRead(BaseModel):
    """联赛响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    league_id: int
    league_name: str
    country: str
    tier: int
    season: str


# ---------- 球队 ----------

class TeamCreate(BaseModel):
    """创建球队请求体。"""

    team_name: str = Field(max_length=128)
    league_id: int
    stadium: str | None = Field(default=None, max_length=128)
    manager: str | None = Field(default=None, max_length=64)
    formation: str | None = Field(default=None, max_length=8, description="常规阵型,如 4-3-3")


class TeamRead(BaseModel):
    """球队响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    team_id: int
    team_name: str
    league_id: int
    stadium: str | None
    manager: str | None
    formation: str | None


# ---------- 球员 ----------

class PlayerCreate(BaseModel):
    """创建球员请求体。"""

    player_name: str = Field(max_length=128)
    team_id: int
    position: str | None = Field(default=None, max_length=8, description="场上位置,如 CB/CAM/ST")
    birth_date: datetime.date | None = None
    market_value: float | None = Field(default=None, ge=0, description="市场身价(欧元)")


class PlayerRead(BaseModel):
    """球员响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    player_id: int
    player_name: str
    team_id: int
    position: str | None
    birth_date: datetime.date | None
    market_value: float | None
