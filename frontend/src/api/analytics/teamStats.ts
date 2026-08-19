/**
 * 高阶数据分析模块 API:球队高阶指标。
 */
import request from '../request'

/** 球队单场高阶指标 */
export interface TeamMatchStat {
  stat_id: number
  match_id: string
  team_id: number
  xg: number | null
  xga: number | null
  possession: number | null
  shot_accuracy: number | null
  ppda: number | null
}

/** 创建球队指标参数 */
export interface TeamStatCreateParams {
  match_id: string
  team_id: number
  xg?: number | null
  xga?: number | null
  possession?: number | null
  shot_accuracy?: number | null
  ppda?: number | null
}

/** 分页查询球队高阶指标,可按比赛过滤 */
export async function listTeamStats(
  params: { match_id?: string; offset?: number; limit?: number } = {},
): Promise<TeamMatchStat[]> {
  const { data } = await request.get<TeamMatchStat[]>('/api/v1/analytics/team-stats', {
    params,
  })
  return data
}

/** 创建球队单场指标 */
export async function createTeamStat(
  payload: TeamStatCreateParams,
): Promise<TeamMatchStat> {
  const { data } = await request.post<TeamMatchStat>(
    '/api/v1/analytics/team-stats',
    payload,
  )
  return data
}

/** 删除球队指标记录 */
export async function deleteTeamStat(statId: number): Promise<void> {
  await request.delete(`/api/v1/analytics/team-stats/${statId}`)
}
