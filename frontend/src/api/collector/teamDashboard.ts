/**
 * 数据采集模块 API:球队看板同步。
 */
import request from '../request'
import type { Team } from '../base/team'

/** 球队看板同步结果 */
export interface TeamDashboardSyncResult {
  team: Team
  uniform_team_id: number
  profile_created: boolean
  future_count: number
  result_count: number
  created_count: number
  updated_count: number
  pruned_count: number
  source: string
}

/** 球队看板同步参数(team_id 与 uniform_team_id 二选一) */
export interface TeamDashboardSyncParams {
  team_id?: number
  uniform_team_id?: number
  term_limits?: number
}

/** 同步类接口的独立超时 */
const SYNC_TIMEOUT_MS = 120_000

/** 按球队同步看板数据(来源:竞彩网球队专栏) */
export async function syncTeamDashboard(
  payload: TeamDashboardSyncParams,
): Promise<TeamDashboardSyncResult> {
  const { data } = await request.post<TeamDashboardSyncResult>(
    '/api/v1/collector/team-dashboard/sync',
    payload,
    { timeout: SYNC_TIMEOUT_MS },
  )
  return data
}
