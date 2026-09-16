/**
 * 比赛与赛果模块 API:赔率快照(走势历史)。
 */
import request from '../request'
import type { MatchOddsPool } from './game'

/** 单个时间点的完整赔率快照(采集同步留存) */
export interface MatchOddsSnapshot {
  snapshot_id: number
  match_id: string
  pools: MatchOddsPool[]
  snapshot_time: string
}

/** 查询比赛赔率快照历史,按快照时间升序 */
export async function listOddsSnapshots(
  matchId: string,
  params: { offset?: number; limit?: number } = {},
): Promise<MatchOddsSnapshot[]> {
  const { data } = await request.get<MatchOddsSnapshot[]>(
    `/api/v1/match/games/${matchId}/odds-snapshots`,
    { params },
  )
  return data
}
