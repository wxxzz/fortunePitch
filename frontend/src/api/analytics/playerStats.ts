/**
 * 高阶数据分析模块 API:球员单场表现。
 */
import request from '../request'

/** 球员单场表现 */
export interface PlayerMatchPerformance {
  performance_id: number
  match_id: string
  player_id: number
  minutes_played: number | null
  goals: number
  assists: number
  key_passes: number
  rating: number | null
}

/** 创建球员表现参数 */
export interface PlayerStatCreateParams {
  match_id: string
  player_id: number
  minutes_played?: number | null
  goals?: number
  assists?: number
  key_passes?: number
  rating?: number | null
}

/** 分页查询球员单场表现,可按比赛过滤 */
export async function listPlayerStats(
  params: { match_id?: string; offset?: number; limit?: number } = {},
): Promise<PlayerMatchPerformance[]> {
  const { data } = await request.get<PlayerMatchPerformance[]>(
    '/api/v1/analytics/player-stats',
    { params },
  )
  return data
}

/** 创建球员单场表现 */
export async function createPlayerStat(
  payload: PlayerStatCreateParams,
): Promise<PlayerMatchPerformance> {
  const { data } = await request.post<PlayerMatchPerformance>(
    '/api/v1/analytics/player-stats',
    payload,
  )
  return data
}

/** 删除球员表现记录 */
export async function deletePlayerStat(performanceId: number): Promise<void> {
  await request.delete(`/api/v1/analytics/player-stats/${performanceId}`)
}
