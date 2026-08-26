/**
 * 数据采集模块 API:赛事(在售赛程)同步。
 */
import request from '../request'

/** 赛事同步结果 */
export interface MatchSyncResult {
  date: string
  /** 该售卖日竞彩网在售场次总数 */
  day_match_count: number
  created_count: number
  updated_count: number
  /** 联赛档案未入库而被跳过的联赛名称 */
  skipped_leagues: string[]
  /** 球队档案未入库等原因被跳过的场次说明 */
  skipped_matches: string[]
  source: string
}

/** 按售卖日同步竞彩在售赛程(来源:中国竞彩网赛程赛果页) */
export async function syncMatches(date: string): Promise<MatchSyncResult> {
  const { data } = await request.post<MatchSyncResult>(
    '/api/v1/collector/matches/sync',
    { date },
  )
  return data
}
