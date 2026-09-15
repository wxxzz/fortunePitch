"""临时脚本:排查赛事中心缺数据问题。"""

import asyncio
import datetime
from collections import Counter

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import League, MatchGame, Team


async def main() -> None:
    async with AsyncSessionLocal() as session:
        games = (await session.scalars(select(MatchGame))).all()
        print("total games:", len(games))
        dates = Counter(g.match_time.date() if isinstance(g.match_time, datetime.datetime) else g.match_time for g in games)
        for day, count in sorted(dates.items()):
            print("date:", day, "count:", count)

        target = await session.get(MatchGame, "2041505")
        print("match 2041505 exists:", target is not None)
        if target is not None:
            league = await session.get(League, target.league_id)
            home = await session.get(Team, target.home_team_id)
            away = await session.get(Team, target.away_team_id)
            print(
                "  time:", target.match_time,
                "| league:", league.league_name if league else None,
                "| home:", home.team_name if home else None,
                "| away:", away.team_name if away else None,
                "| status:", target.match_status,
            )
        like_rows = (
            await session.execute(
                select(MatchGame.match_id, MatchGame.match_time).where(
                    MatchGame.match_id.like("%2041505%")
                )
            )
        ).all()
        print("like 2041505:", like_rows)


asyncio.run(main())
