/**
 * 比赛与赛果模块 API:高阶数据(近况/交锋/Elo/攻防强度/泊松概率)。
 */
import request from '../request'

/** 近况明细行(看板球队视角) */
export interface InsightsFormEntry {
  match_time: string
  league_name: string | null
  opponent_name: string
  is_home: boolean
  /** 全场比分(主:客),如 2:1 */
  score: string
  /** 看板球队视角结果:W/D/L */
  result: 'W' | 'D' | 'L'
}

/** 球队近况汇总 */
export interface InsightsTeamForm {
  team_id: number
  team_name: string
  entries: InsightsFormEntry[]
  /** 结果串(时间倒序,最早在左),如 WWDLLW */
  results: string
  wins: number
  draws: number
  losses: number
  goals_for_avg: number
  goals_against_avg: number
  streak_label: string
}

/** 历史交锋明细行(按行自身主队视角) */
export interface InsightsH2HEntry {
  match_time: string
  league_name: string | null
  home_team_name: string
  away_team_name: string
  score: string
  home_result: 'W' | 'D' | 'L'
}

/** 历史交锋汇总(胜平负以本场主队视角) */
export interface InsightsH2H {
  entries: InsightsH2HEntry[]
  home_wins: number
  draws: number
  away_wins: number
  avg_total_goals: number | null
}

/** 双方 Elo 快照(未重算时 rating 各值为 null) */
export interface InsightsElo {
  home_rating: number | null
  away_rating: number | null
  /** 评分差(主-客) */
  rating_diff: number | null
  /** 主队期望得分(含主场优势) */
  home_expected_score: number | null
  home_matches_played: number
  away_matches_played: number
}

/** 攻防强度与期望进球估计(1.00 = 联赛均值) */
export interface InsightsStrength {
  league_avg_home_goals: number | null
  league_avg_away_goals: number | null
  home_attack: number | null
  home_defense: number | null
  away_attack: number | null
  away_defense: number | null
  lam: number | null
  mu: number | null
}

/** 比分概率条目 */
export interface InsightsScoreProb {
  home_goals: number
  away_goals: number
  probability: number
}

/** 总进球分布桶(goals 为 7 时表示 7+) */
export interface InsightsTtgBin {
  goals: number
  probability: number
}

/** Dixon-Coles 泊松比分预测 */
export interface InsightsPoisson {
  home_win: number
  draw: number
  away_win: number
  top_scores: InsightsScoreProb[]
  over_2_5: number
  under_2_5: number
  total_goals_dist: InsightsTtgBin[]
  total_goals_expected: number
}

/** 单场比赛高阶数据聚合 */
export interface MatchInsights {
  match_id: string
  league_name: string
  match_time: string
  home_team_name: string
  away_team_name: string
  elo: InsightsElo
  home_form: InsightsTeamForm
  away_form: InsightsTeamForm
  h2h: InsightsH2H
  strength: InsightsStrength
  poisson: InsightsPoisson | null
}

/** 查询比赛高阶数据(近况/交锋/Elo/攻防强度/泊松概率) */
export async function getMatchInsights(matchId: string): Promise<MatchInsights> {
  const { data } = await request.get<MatchInsights>(
    `/api/v1/match/games/${matchId}/insights`,
  )
  return data
}
