/**
 * 高阶数据分析模块 API:球队 Elo 评分(看板赛果回放)。
 */
import request from '../request'

/** Elo 评分重算结果摘要 */
export interface TeamRatingRecomputeResult {
  matches_replayed: number
  teams_rated: number
  matches_skipped: number
}

/** 全量回放已完赛看板赛果,重建各队当前 Elo 评分(幂等) */
export async function recomputeTeamRatings(): Promise<TeamRatingRecomputeResult> {
  const { data } = await request.post<TeamRatingRecomputeResult>(
    '/api/v1/analytics/team-ratings/recompute',
  )
  return data
}
