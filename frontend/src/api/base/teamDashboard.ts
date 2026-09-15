/**
 * 基础档案模块 API:球队看板。
 */
import request from '../request'
import type { Team } from './team'

/** 竞彩网球队档案(看板数据源映射) */
export interface TeamProfile {
  team_id: number
  uniform_team_id: number
  gm_team_id: number | null
  wbsj_team_id: number | null
  abbrev_name: string
  full_name: string | null
  country_name: string | null
  logo_url: string | null
  update_time: string
}

/** 球队看板比赛(未来赛事与赛程赛果,以看板球队视角) */
export interface TeamMatch {
  team_id: number
  uniform_match_id: number
  uniform_league_id: number | null
  league_name: string | null
  match_time: string
  gameweek: string | null
  phase_name: string | null
  home_team_name: string
  away_team_name: string
  uniform_home_team_id: number | null
  uniform_away_team_id: number | null
  is_home: boolean
  half_home_score: number | null
  half_away_score: number | null
  full_home_score: number | null
  full_away_score: number | null
  /** 看板球队视角结果:W=胜 D=平 L=负,未开赛为 null */
  team_result: 'W' | 'D' | 'L' | null
}

/** 看板数据覆盖的参赛联赛 */
export interface DashboardLeague {
  uniform_league_id: number | null
  league_name: string | null
}

/** 看板战绩统计(按已完赛看板比赛实时计算) */
export interface DashboardStatistics {
  played: number
  wins: number
  draws: number
  losses: number
  goals_for: number
  goals_against: number
  goal_diff: number
  win_rate: number
}

/** 球队看板聚合数据 */
export interface TeamDashboard {
  team: Team
  /** 竞彩网档案映射,未同步过看板数据时为 null */
  profile: TeamProfile | null
  leagues: DashboardLeague[]
  future_matches: TeamMatch[]
  match_results: TeamMatch[]
  statistics: DashboardStatistics
}

/** 看板查询参数(筛选与条数) */
export interface TeamDashboardParams {
  uniform_league_id?: number
  home_away?: 'home' | 'away'
  future_limit?: number
  result_limit?: number
}

/** 查询球队看板(档案 + 未来赛事 + 赛程赛果 + 战绩统计) */
export async function getTeamDashboard(
  teamId: number,
  params: TeamDashboardParams = {},
): Promise<TeamDashboard> {
  const { data } = await request.get<TeamDashboard>(
    `/api/v1/base/teams/${teamId}/dashboard`,
    { params },
  )
  return data
}
