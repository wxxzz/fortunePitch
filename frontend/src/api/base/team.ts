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

/** 分页查询球队列表 */
export async function listTeams(params: PageParams = {}): Promise<Team[]> {
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
