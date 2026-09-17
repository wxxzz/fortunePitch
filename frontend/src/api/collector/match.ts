/**
 * 数据采集模块 API:赛事(在售赛程)与赛果(开奖)同步。
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

/** 赛果同步结果 */
export interface ResultSyncResult {
  date: string
  /** 该比赛日竞彩网已开赛场次总数 */
  day_result_count: number
  created_count: number
  updated_count: number
  /** 回写比分与完赛状态的场次数 */
  game_updated_count: number
  /** 场次未入库等原因被跳过的场次说明 */
  skipped_matches: string[]
  source: string
}

/**
 * 同步竞彩赛果开奖数据(来源:中国竞彩网赛果开奖页)。
 * @param dateType match=比赛日(默认,与赛果开奖页日期一致);sale=售卖日
 *   (同时拉取该日与次日的赛果,覆盖次日凌晨场,与赛事中心口径一致)
 */
export async function syncResults(
  date: string,
  dateType: 'match' | 'sale' = 'match',
): Promise<ResultSyncResult> {
  const { data } = await request.post<ResultSyncResult>(
    '/api/v1/collector/results/sync',
    { date, date_type: dateType },
  )
  return data
}
