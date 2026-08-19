/**
 * 基础档案模块 API:联赛。
 */
import request from '../request'

/** 联赛档案 */
export interface League {
  league_id: number
  league_name: string
  country: string
  tier: number
  season: string
}

/** 创建联赛参数 */
export interface LeagueCreateParams {
  league_name: string
  country: string
  tier?: number
  season?: string
}

/** 分页参数 */
export interface PageParams {
  offset?: number
  limit?: number
}

/** 分页查询联赛列表 */
export async function listLeagues(params: PageParams = {}): Promise<League[]> {
  const { data } = await request.get<League[]>('/api/v1/base/leagues', { params })
  return data
}

/** 创建联赛 */
export async function createLeague(payload: LeagueCreateParams): Promise<League> {
  const { data } = await request.post<League>('/api/v1/base/leagues', payload)
  return data
}

/** 按 ID 查询联赛 */
export async function getLeague(leagueId: number): Promise<League> {
  const { data } = await request.get<League>(`/api/v1/base/leagues/${leagueId}`)
  return data
}

/** 删除联赛 */
export async function deleteLeague(leagueId: number): Promise<void> {
  await request.delete(`/api/v1/base/leagues/${leagueId}`)
}
