/**
 * 基础档案模块 API:球队。
 */
import request from '../request'
import type { PageParams } from './league'

/** 球队档案 */
export interface Team {
  team_id: number
  team_name: string
  league_id: number
  stadium: string | null
  manager: string | null
  formation: string | null
}

/** 创建球队参数 */
export interface TeamCreateParams {
  team_name: string
  league_id: number
  stadium?: string | null
  manager?: string | null
  formation?: string | null
}

/** 球队列表查询参数(支持按所属联赛过滤) */
export interface TeamListParams extends PageParams {
  league_id?: number
}

/** 分页查询球队列表,可按所属联赛过滤 */
export async function listTeams(params: TeamListParams = {}): Promise<Team[]> {
  const { data } = await request.get<Team[]>('/api/v1/base/teams', { params })
  return data
}

/** 创建球队 */
export async function createTeam(payload: TeamCreateParams): Promise<Team> {
  const { data } = await request.post<Team>('/api/v1/base/teams', payload)
  return data
}

/** 按 ID 查询球队 */
export async function getTeam(teamId: number): Promise<Team> {
  const { data } = await request.get<Team>(`/api/v1/base/teams/${teamId}`)
  return data
}

/** 删除球队 */
export async function deleteTeam(teamId: number): Promise<void> {
  await request.delete(`/api/v1/base/teams/${teamId}`)
}

/** 球队基本面(积分榜总/主/客三维度赛季战绩) */
export interface TeamFundamentals {
  team_id: number
  season: string
  ranking: number | null
  played: number | null
  wins: number | null
  draws: number | null
  losses: number | null
  goals_for: number | null
  goals_against: number | null
  goal_diff: number | null
  points: number | null
  win_rate: number | null
  home_ranking: number | null
  home_played: number | null
  home_wins: number | null
  home_draws: number | null
  home_losses: number | null
  home_goals_for: number | null
  home_goals_against: number | null
  home_goal_diff: number | null
  home_points: number | null
  home_win_rate: number | null
  away_ranking: number | null
  away_played: number | null
  away_wins: number | null
  away_draws: number | null
  away_losses: number | null
  away_goals_for: number | null
  away_goals_against: number | null
  away_goal_diff: number | null
  away_points: number | null
  away_win_rate: number | null
  update_time: string
}

/** 查询球队基本面(未同步过基本面时后端返回 404) */
export async function getTeamFundamentals(
  teamId: number,
): Promise<TeamFundamentals> {
  const { data } = await request.get<TeamFundamentals>(
    `/api/v1/base/teams/${teamId}/fundamentals`,
  )
  return data
}
