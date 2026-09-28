"""赛事高阶数据派生计算服务。

不新增外部数据源,全部基于已采集数据读时实时计算:
- 球队近况:fp_base_team_matches 已完赛看板行(近 N 场 W/D/L + 场均进失球);
- 历史交锋 H2H:两队看板行按对手 uniform id 交叉过滤、uniform_match_id 去重;
- 攻防强度与期望进球:Dixon-Coles 强度比参数化(积分榜主客拆分 × 近况混合);
- 泊松比分概率:复用 services/poisson.predict_score_grid(rho=-0.10);
- Elo 快照:读 fp_analytics_team_ratings(由 team_rating.recompute_team_ratings 落库)。

计算口径说明:
- 攻防速率 = 0.70 × 赛季主客拆分值 + 0.30 × 近 N 场场均(近 N < 3 场时退化为
  纯赛季值,不引入小样本噪声);赛季主客拆分样本量大且进失环境与本场对阵
  场地一致(主队用主榜、客队用客榜);
- 以联赛场均进球为基准归一强度(1.00 = 联赛均值),自动消除不同联赛进球
  环境的量纲差异;λ = LGH × 主攻 × 客防 是标准 Dixon-Coles 双泊松强度参数化,
  与已有 predict_score_grid(lam, mu) 无缝衔接;
- 数据缺口分级退化:某队积分榜缺 → 该队速率退化为近况值,再缺 → 联赛均值
  (强度 1.0);全库无任何积分榜数据 → strength/poisson 整体为 None
  (前端展示"数据不足",不用全局常数编造预测);
- TeamFundamentals 的 Numeric 字段读出为 Decimal,计算前一律 float() 归一。
"""

import datetime
import typing

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ResourceNotFoundError
from app.models import (
    MatchGame,
    Team,
    TeamFundamentals,
    TeamMatch,
    TeamProfile,
    TeamRating,
)
from app.services import elo, poisson
from app.services.team_dashboard import _row_result

# 近况取样场数默认值
FORM_LIMIT_DEFAULT = 6
# 历史交锋取样场数默认值
H2H_LIMIT_DEFAULT = 10
# 攻防速率:赛季样本权重 / 近况样本权重
SEASON_WEIGHT = 0.70
RECENT_WEIGHT = 0.30
# 近况样本参与混合的最小场数(不足则退化为纯赛季值)
MIN_RECENT_SAMPLE = 3
# λ/μ 夹逼区间,防退化
LAM_MIN, LAM_MAX = 0.2, 4.0
# 泊松 Top 比分返回条数
TOP_SCORES_LIMIT = 5


# ---------- 结果模型(服务层 NamedTuple) ----------


class FormEntry(typing.NamedTuple):
    """近况明细行(看板球队视角)。"""

    match_time: datetime.datetime
    league_name: str | None
    opponent_name: str
    is_home: bool
    home_goals: int
    away_goals: int
    result: str  # W/D/L


class TeamForm(typing.NamedTuple):
    """球队近况汇总。"""

    team_id: int
    team_name: str
    entries: list[FormEntry]  # 时间倒序,截取前 N
    results: str  # 结果串(时间倒序,如 "WWDLLW",最早在左)
    wins: int
    draws: int
    losses: int
    goals_for_avg: float
    goals_against_avg: float
    streak_label: str


class H2HEntry(typing.NamedTuple):
    """历史交锋明细行(按行自身主队视角)。"""

    match_time: datetime.datetime
    league_name: str | None
    home_team_name: str
    away_team_name: str
    home_goals: int
    away_goals: int
    # 以"该行存储的实际主队"视角的 W/D/L(往绩行主客可能与本场相反,
    # 前端按队名归属渲染,汇总时映射回本场视角)
    home_result: str


class H2HSummary(typing.NamedTuple):
    """历史交锋汇总(胜平负以本场 fp_match_games 主队视角)。"""

    entries: list[H2HEntry]
    home_wins: int
    draws: int
    away_wins: int
    avg_total_goals: float | None


class StrengthEstimate(typing.NamedTuple):
    """攻防强度与期望进球估计。"""

    league_avg_home_goals: float | None
    league_avg_away_goals: float | None
    home_attack: float | None  # 主队进攻强度(1.00 = 联赛均值)
    home_defense: float | None  # 主队防守强度(失球比,越低越好)
    away_attack: float | None
    away_defense: float | None
    lam: float | None  # 主队期望进球
    mu: float | None  # 客队期望进球


class PoissonForecast(typing.NamedTuple):
    """Dixon-Coles 泊松比分预测。"""

    home_win: float
    draw: float
    away_win: float
    top_scores: list[tuple[int, int, float]]  # (主进球, 客进球, 概率) 前 5
    over_2_5: float
    under_2_5: float
    total_goals_dist: list[tuple[int, float]]  # 桶 0..6 与 7+
    total_goals_expected: float


class EloSnapshot(typing.NamedTuple):
    """双方 Elo 快照(未重算时 rating 各值为 None)。"""

    home_rating: float | None
    away_rating: float | None
    rating_diff: float | None  # home - away
    home_expected_score: float | None  # 含主场优势的主队期望得分
    home_matches_played: int
    away_matches_played: int


class MatchInsights(typing.NamedTuple):
    """单场比赛高阶数据聚合。"""

    game: MatchGame
    elo: EloSnapshot
    home_form: TeamForm
    away_form: TeamForm
    h2h: H2HSummary
    strength: StrengthEstimate
    poisson: PoissonForecast | None


# ---------- 近况 ----------


def _build_team_form(
    team: Team, finished_rows: list[TeamMatch], limit: int
) -> TeamForm:
    """由已完赛看板行构建球队近况(时间倒序前 limit 场)。"""
    rows = sorted(finished_rows, key=lambda row: row.match_time, reverse=True)
    entries: list[FormEntry] = []
    goals_for = goals_against = 0
    for row in rows[:limit]:
        result = _row_result(row) or "D"
        entries.append(
            FormEntry(
                match_time=row.match_time,
                league_name=row.league_name,
                opponent_name=(
                    row.away_team_name if row.is_home else row.home_team_name
                ),
                is_home=row.is_home,
                home_goals=row.full_home_score or 0,
                away_goals=row.full_away_score or 0,
                result=result,
            )
        )
        own = row.full_home_score if row.is_home else row.full_away_score
        opp = row.full_away_score if row.is_home else row.full_home_score
        goals_for += own or 0
        goals_against += opp or 0

    results = "".join(entry.result for entry in entries)
    wins = results.count("W")
    draws = results.count("D")
    losses = results.count("L")
    played = len(entries)
    return TeamForm(
        team_id=team.team_id,
        team_name=team.team_name,
        entries=entries,
        results=results,
        wins=wins,
        draws=draws,
        losses=losses,
        goals_for_avg=round(goals_for / played, 2) if played else 0.0,
        goals_against_avg=round(goals_against / played, 2) if played else 0.0,
        streak_label=_streak_label(results),
    )


def _streak_label(results: str) -> str:
    """由结果串推导状态标签(连胜/连败/连续平局/X 场不败)。"""
    if not results:
        return "无近期比赛"
    latest = results[0]
    streak = 0
    for char in results:
        if char != latest:
            break
        streak += 1
    if latest == "W":
        return f"连胜 {streak} 场"
    if latest == "L":
        return f"连败 {streak} 场"
    if latest == "D":
        return f"连续平局 {streak} 场"
    return "无近期比赛"


# ---------- 历史交锋 ----------


def _score_result(home_goals: int, away_goals: int) -> str:
    """按行主队视角由比分推导 W/D/L。"""
    if home_goals > away_goals:
        return "W"
    if home_goals < away_goals:
        return "L"
    return "D"


async def _load_h2h(
    session: AsyncSession,
    *,
    home_team_id: int,
    away_team_id: int,
    home_uniform_id: int | None,
    away_uniform_id: int | None,
    limit: int,
) -> H2HSummary:
    """两队看板交叉过滤 + uniform_match_id 去重构建历史交锋。"""
    rows: dict[int, TeamMatch] = {}
    # uniform_match_id -> 该行主队是否为本场主队(精确视角,不依赖队名匹配:
    # 行来自本场主队看板且 is_home、或来自客队看板且非主队时成立)
    row_home_is_match_home: dict[int, bool] = {}
    for team_id, opponent_uniform in (
        (home_team_id, away_uniform_id),
        (away_team_id, home_uniform_id),
    ):
        if opponent_uniform is None:
            continue
        team_rows = (
            await session.scalars(
                select(TeamMatch).where(
                    TeamMatch.team_id == team_id,
                    TeamMatch.full_home_score.is_not(None),
                    or_(
                        TeamMatch.uniform_home_team_id == opponent_uniform,
                        TeamMatch.uniform_away_team_id == opponent_uniform,
                    ),
                )
            )
        ).all()
        for row in team_rows:
            if row.uniform_match_id in rows:
                continue
            rows[row.uniform_match_id] = row
            row_home_is_match_home[row.uniform_match_id] = (
                row.is_home if team_id == home_team_id else not row.is_home
            )

    ordered = sorted(rows.values(), key=lambda row: row.match_time, reverse=True)
    entries: list[H2HEntry] = []
    perspectives: list[bool] = []
    for row in ordered[:limit]:
        entries.append(
            H2HEntry(
                match_time=row.match_time,
                league_name=row.league_name,
                home_team_name=row.home_team_name,
                away_team_name=row.away_team_name,
                home_goals=row.full_home_score or 0,
                away_goals=row.full_away_score or 0,
                home_result=_score_result(
                    row.full_home_score or 0, row.full_away_score or 0
                ),
            )
        )
        perspectives.append(row_home_is_match_home[row.uniform_match_id])

    # 汇总映射回本场视角:行主队即本场主队时行主胜计主胜,否则 W/L 翻转
    home_wins = draws = away_wins = 0
    total_goals = 0
    for entry, home_is_match_home in zip(entries, perspectives):
        if home_is_match_home:
            mapped = entry.home_result
        else:
            mapped = {"W": "L", "D": "D", "L": "W"}[entry.home_result]
        if mapped == "W":
            home_wins += 1
        elif mapped == "D":
            draws += 1
        else:
            away_wins += 1
        total_goals += entry.home_goals + entry.away_goals

    return H2HSummary(
        entries=entries,
        home_wins=home_wins,
        draws=draws,
        away_wins=away_wins,
        avg_total_goals=round(total_goals / len(entries), 2) if entries else None,
    )


# ---------- 攻防强度与期望进球 ----------


async def _load_league_averages(
    session: AsyncSession, league_id: int | None
) -> tuple[float | None, float | None]:
    """聚合联赛主/客队场均进球(联赛样本不足时全库兜底;均无数据返回 None)。"""
    for scope in (league_id, None):
        stmt = select(
            func.sum(TeamFundamentals.home_goals_for),
            func.sum(TeamFundamentals.home_played),
            func.sum(TeamFundamentals.away_goals_for),
            func.sum(TeamFundamentals.away_played),
        )
        if scope is not None:
            stmt = stmt.join(Team).where(Team.league_id == scope)
        home_goals, home_played, away_goals, away_played = (
            await session.execute(stmt)
        ).one()
        if home_played and away_played:
            return (
                float(home_goals) / float(home_played),
                float(away_goals) / float(away_played),
            )
    return None, None


def _season_rate(fund: TeamFundamentals | None, prefix: str, kind: str) -> float | None:
    """积分榜主/客拆分的场均进(失)球;数据缺失返回 None。"""
    if fund is None:
        return None
    played = getattr(fund, f"{prefix}played")
    goals = getattr(fund, f"{prefix}goals_{kind}")
    if not played or goals is None:
        return None
    return float(goals) / float(played)


def _blend_rate(
    season_rate: float | None, recent_avg: float | None, recent_count: int
) -> float | None:
    """赛季值 × 近况值加权混合;近况样本不足或全缺时退化。"""
    if season_rate is None and recent_avg is None:
        return None
    if recent_avg is None or recent_count < MIN_RECENT_SAMPLE:
        return season_rate
    if season_rate is None:
        return recent_avg
    return SEASON_WEIGHT * season_rate + RECENT_WEIGHT * recent_avg


def _estimate_strength(
    league_avg_home_goals: float | None,
    league_avg_away_goals: float | None,
    home_fund: TeamFundamentals | None,
    away_fund: TeamFundamentals | None,
    home_form: TeamForm,
    away_form: TeamForm,
) -> StrengthEstimate:
    """Dixon-Coles 强度比参数化计算 λ/μ。

    速率混合与归一化口径见模块 docstring;数据全缺时各值为 None。
    """
    if league_avg_home_goals is None or league_avg_away_goals is None:
        return StrengthEstimate(None, None, None, None, None, None, None, None)

    home_recent_n = len(home_form.entries)
    away_recent_n = len(away_form.entries)
    home_scored = _blend_rate(
        _season_rate(home_fund, "home_", "for"),
        home_form.goals_for_avg,
        home_recent_n,
    )
    home_conceded = _blend_rate(
        _season_rate(home_fund, "home_", "against"),
        home_form.goals_against_avg,
        home_recent_n,
    )
    away_scored = _blend_rate(
        _season_rate(away_fund, "away_", "for"),
        away_form.goals_for_avg,
        away_recent_n,
    )
    away_conceded = _blend_rate(
        _season_rate(away_fund, "away_", "against"),
        away_form.goals_against_avg,
        away_recent_n,
    )
    # 数据缺口退化:速率缺 → 联赛均值(强度 1.0)
    if home_scored is None:
        home_scored = league_avg_home_goals
    if home_conceded is None:
        home_conceded = league_avg_away_goals
    if away_scored is None:
        away_scored = league_avg_away_goals
    if away_conceded is None:
        away_conceded = league_avg_home_goals

    home_attack = home_scored / league_avg_home_goals
    home_defense = home_conceded / league_avg_away_goals
    away_attack = away_scored / league_avg_away_goals
    away_defense = away_conceded / league_avg_home_goals
    lam = min(max(league_avg_home_goals * home_attack * away_defense, LAM_MIN), LAM_MAX)
    mu = min(max(league_avg_away_goals * away_attack * home_defense, LAM_MIN), LAM_MAX)
    return StrengthEstimate(
        league_avg_home_goals=round(league_avg_home_goals, 3),
        league_avg_away_goals=round(league_avg_away_goals, 3),
        home_attack=round(home_attack, 3),
        home_defense=round(home_defense, 3),
        away_attack=round(away_attack, 3),
        away_defense=round(away_defense, 3),
        lam=round(lam, 2),
        mu=round(mu, 2),
    )


# ---------- 泊松预测 ----------


def _forecast(lam: float, mu: float) -> PoissonForecast:
    """复用 predict_score_grid 生成胜平负概率与总进球分布。"""
    grid = poisson.predict_score_grid(lam, mu)
    score_probs = [
        (i, j, grid.grid[i][j])
        for i in range(len(grid.grid))
        for j in range(len(grid.grid))
    ]
    score_probs.sort(key=lambda item: item[2], reverse=True)
    top_scores = [
        (i, j, round(prob, 4)) for i, j, prob in score_probs[:TOP_SCORES_LIMIT]
    ]

    over_2_5 = sum(
        grid.grid[i][j]
        for i in range(len(grid.grid))
        for j in range(len(grid.grid))
        if i + j >= 3
    )
    buckets: list[tuple[int, float]] = []
    for total in range(7):
        prob = sum(
            grid.grid[i][j]
            for i in range(len(grid.grid))
            for j in range(len(grid.grid))
            if i + j == total
        )
        buckets.append((total, round(prob, 4)))
    prob_7plus = sum(
        grid.grid[i][j]
        for i in range(len(grid.grid))
        for j in range(len(grid.grid))
        if i + j >= 7
    )
    buckets.append((7, round(prob_7plus, 4)))

    return PoissonForecast(
        home_win=round(grid.home_win_prob, 4),
        draw=round(grid.draw_prob, 4),
        away_win=round(grid.away_win_prob, 4),
        top_scores=top_scores,
        over_2_5=round(over_2_5, 4),
        under_2_5=round(1.0 - over_2_5, 4),
        total_goals_dist=buckets,
        total_goals_expected=round(grid.total_goals_expected, 2),
    )


# ---------- 聚合 ----------


async def get_match_insights(
    session: AsyncSession,
    match_id: str,
    *,
    form_limit: int = FORM_LIMIT_DEFAULT,
    h2h_limit: int = H2H_LIMIT_DEFAULT,
) -> MatchInsights:
    """聚合单场比赛高阶数据(近况/交锋/Elo/强度/泊松)。

    Args:
        session: 异步数据库会话。
        match_id: 比赛 ID。
        form_limit: 近况取样场数。
        h2h_limit: 历史交锋取样场数。

    Returns:
        高阶数据聚合结果。

    Raises:
        ResourceNotFoundError: 比赛不存在。
    """
    game = (
        await session.execute(
            select(MatchGame)
            .options(
                selectinload(MatchGame.league),
                selectinload(MatchGame.home_team),
                selectinload(MatchGame.away_team),
            )
            .where(MatchGame.match_id == match_id)
        )
    ).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError(MatchGame.__tablename__, match_id)

    home_team, away_team = game.home_team, game.away_team

    # 双方已完赛看板行各查一次(近况与强度共用)
    finished_by_team: dict[int, list[TeamMatch]] = {}
    for team_id in (home_team.team_id, away_team.team_id):
        finished_by_team[team_id] = list(
            await session.scalars(
                select(TeamMatch).where(
                    TeamMatch.team_id == team_id,
                    TeamMatch.full_home_score.is_not(None),
                )
            )
        )
    home_form = _build_team_form(
        home_team, finished_by_team[home_team.team_id], form_limit
    )
    away_form = _build_team_form(
        away_team, finished_by_team[away_team.team_id], form_limit
    )

    # uniform id 映射(H2H 对手过滤)
    profiles = list(
        await session.scalars(
            select(TeamProfile).where(
                TeamProfile.team_id.in_([home_team.team_id, away_team.team_id])
            )
        )
    )
    uniform_by_team = {profile.team_id: profile.uniform_team_id for profile in profiles}
    h2h = await _load_h2h(
        session,
        home_team_id=home_team.team_id,
        away_team_id=away_team.team_id,
        home_uniform_id=uniform_by_team.get(home_team.team_id),
        away_uniform_id=uniform_by_team.get(away_team.team_id),
        limit=h2h_limit,
    )

    # Elo 快照
    ratings = list(
        await session.scalars(
            select(TeamRating).where(
                TeamRating.team_id.in_([home_team.team_id, away_team.team_id])
            )
        )
    )
    rating_by_team = {rating.team_id: rating for rating in ratings}
    home_rating_row = rating_by_team.get(home_team.team_id)
    away_rating_row = rating_by_team.get(away_team.team_id)
    if home_rating_row and away_rating_row:
        elo_snapshot = EloSnapshot(
            home_rating=home_rating_row.rating,
            away_rating=away_rating_row.rating,
            rating_diff=round(home_rating_row.rating - away_rating_row.rating, 2),
            home_expected_score=round(
                elo.expected_score(
                    home_rating_row.rating, away_rating_row.rating
                ),
                4,
            ),
            home_matches_played=home_rating_row.matches_played,
            away_matches_played=away_rating_row.matches_played,
        )
    else:
        elo_snapshot = EloSnapshot(
            home_rating=home_rating_row.rating if home_rating_row else None,
            away_rating=away_rating_row.rating if away_rating_row else None,
            rating_diff=None,
            home_expected_score=None,
            home_matches_played=(
                home_rating_row.matches_played if home_rating_row else 0
            ),
            away_matches_played=(
                away_rating_row.matches_played if away_rating_row else 0
            ),
        )

    # 攻防强度与泊松
    league_avg_home, league_avg_away = await _load_league_averages(
        session, game.league_id
    )
    fund_rows = list(
        await session.scalars(
            select(TeamFundamentals).where(
                TeamFundamentals.team_id.in_([home_team.team_id, away_team.team_id])
            )
        )
    )
    fund_by_team = {row.team_id: row for row in fund_rows}
    strength = _estimate_strength(
        league_avg_home,
        league_avg_away,
        fund_by_team.get(home_team.team_id),
        fund_by_team.get(away_team.team_id),
        home_form,
        away_form,
    )
    forecast = _forecast(strength.lam, strength.mu) if strength.lam and strength.mu else None

    return MatchInsights(
        game=game,
        elo=elo_snapshot,
        home_form=home_form,
        away_form=away_form,
        h2h=h2h,
        strength=strength,
        poisson=forecast,
    )


# ---------- AI 摘要 ----------


def format_insights_summary(insights: MatchInsights) -> str:
    """把高阶数据渲染为紧凑中文摘要(固定结构,约 350 字)。

    供 AI 综合分析提示词注入;各段缺数据时输出"数据不足"。
    """
    home_name = insights.game.home_team.team_name
    away_name = insights.game.away_team.team_name

    elo = insights.elo
    if elo.home_rating is not None and elo.away_rating is not None:
        elo_line = (
            f"- Elo 评分:{home_name} {elo.home_rating:.0f}"
            f"({elo.home_matches_played} 场)/ {away_name} {elo.away_rating:.0f}"
            f"({elo.away_matches_played} 场),差 {elo.rating_diff:+.0f},"
            f"主队期望得分 {elo.home_expected_score:.2f}"
        )
    else:
        elo_line = "- Elo 评分:数据不足(尚未重算评分)"

    def form_line(name: str, form: TeamForm) -> str:
        if not form.results:
            return f"{name} 近期无已赛记录"
        return (
            f"{name} 近 {len(form.results)} 场 {form.wins}胜{form.draws}平"
            f"{form.losses}负,场均进 {form.goals_for_avg} 失 "
            f"{form.goals_against_avg},{form.streak_label}"
        )

    h2h = insights.h2h
    if h2h.entries:
        h2h_line = (
            f"- 历史交锋:近 {len(h2h.entries)} 次交手{home_name} "
            f"{h2h.home_wins}胜{h2h.draws}平{h2h.away_wins}负"
            f"(以{home_name}视角),场均总进球 {h2h.avg_total_goals}"
        )
    else:
        h2h_line = "- 历史交锋:数据不足(无交锋记录)"

    strength = insights.strength
    if strength.home_attack is not None:
        strength_line = (
            f"- 攻防强度(1.00=联赛均值):{home_name}攻 {strength.home_attack} "
            f"防 {strength.home_defense};{away_name}攻 {strength.away_attack} "
            f"防 {strength.away_defense}"
        )
    else:
        strength_line = "- 攻防强度:数据不足"

    if insights.poisson is not None:
        top = insights.poisson.top_scores[0]
        poisson_line = (
            f"- 模型预测:λ={strength.lam} μ={strength.mu};"
            f"主胜 {insights.poisson.home_win:.0%} 平 "
            f"{insights.poisson.draw:.0%} 客胜 {insights.poisson.away_win:.0%};"
            f"大于 2.5 球 {insights.poisson.over_2_5:.0%};"
            f"最可能比分 {top[0]}:{top[1]}({top[2]:.1%})"
        )
    else:
        poisson_line = "- 模型预测:数据不足(无法计算泊松概率)"

    return "\n".join(
        [
            f"- 近况:{form_line(home_name, insights.home_form)};"
            f"{form_line(away_name, insights.away_form)}",
            h2h_line,
            elo_line,
            strength_line,
            poisson_line,
        ]
    )
