/**
 * 数据采集模块 API:联赛同步。
 */
import request from '../request'
import type { League } from '../base/league'

/** 联赛同步结果 */
export interface LeagueSyncResult {
  league: League
  action: 'created' | 'updated'
  uniform_league_id: number
  source: string
}

/** 按名称同步联赛信息(来源:中国竞彩网联赛资料) */
export async function syncLeague(leagueName: string): Promise<LeagueSyncResult> {
  const { data } = await request.post<LeagueSyncResult>(
    '/api/v1/collector/leagues/sync',
    { league_name: leagueName },
  )
  return data
}
