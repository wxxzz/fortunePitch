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

/** 球队当前 Elo 评分(未重算过时后端返回 404) */
export interface TeamRating {
  team_id: number
  rating: number
  matches_played: number
  last_match_time: string | null
  update_time: string
}

/** 查询单支球队当前 Elo 评分 */
export async function getTeamRating(teamId: number): Promise<TeamRating> {
  const { data } = await request.get<TeamRating>(
    `/api/v1/analytics/team-ratings/${teamId}`,
  )
  return data
}

/** 全量回放已完赛看板赛果,重建各队当前 Elo 评分(幂等) */
export async function recomputeTeamRatings(): Promise<TeamRatingRecomputeResult> {
  const { data } = await request.post<TeamRatingRecomputeResult>(
    '/api/v1/analytics/team-ratings/recompute',
  )
  return data
}
