/**
 * 数据采集模块 API:球队看板同步。
 */
import request from '../request'
import type { Team } from '../base/team'
import type { League } from '../base/league'

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

/** 联赛批量看板同步结果(本地已入库球队逐队同步) */
export interface TeamDashboardLeagueSyncResult {
  league: League
  team_count: number
  synced_count: number
  future_count: number
  result_count: number
  created_count: number
  updated_count: number
  pruned_count: number
  skipped_teams: string[]
  source: string
}

/** 联赛批量看板同步参数 */
export interface TeamDashboardLeagueSyncParams {
  league_id: number
  term_limits?: number
}

/** 同步类接口的独立超时 */
const SYNC_TIMEOUT_MS = 120_000

/** 联赛批量同步的超时(逐队顺序同步,球队较多时耗时较长) */
const LEAGUE_SYNC_TIMEOUT_MS = 600_000

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

/** 按联赛的本地球队名单批量同步全部球队看板(单队失败计入跳过列表) */
export async function syncLeagueTeamDashboards(
  payload: TeamDashboardLeagueSyncParams,
): Promise<TeamDashboardLeagueSyncResult> {
  const { data } = await request.post<TeamDashboardLeagueSyncResult>(
    '/api/v1/collector/team-dashboard/sync-league',
    payload,
    { timeout: LEAGUE_SYNC_TIMEOUT_MS },
  )
  return data
}
