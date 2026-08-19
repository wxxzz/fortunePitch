/**
 * 策略与赔率模块 API:策略推荐记录。
 */
import request from '../request'

/** 策略推荐记录 */
export interface Recommendation {
  recommend_id: number
  match_id: string
  strategy_type: string
  predicted_outcome: string
  confidence_score: number
  logic_tags: string[] | null
  created_at: string
}

/** 创建推荐参数 */
export interface RecommendationCreateParams {
  match_id: string
  strategy_type: string
  predicted_outcome: string
  confidence_score: number
  logic_tags?: string[] | null
}

/** 分页查询策略推荐,可按比赛过滤(按生成时间倒序) */
export async function listRecommendations(
  params: { match_id?: string; offset?: number; limit?: number } = {},
): Promise<Recommendation[]> {
  const { data } = await request.get<Recommendation[]>(
    '/api/v1/strategy/recommendations',
    { params },
  )
  return data
}

/** 创建策略推荐 */
export async function createRecommendation(
  payload: RecommendationCreateParams,
): Promise<Recommendation> {
  const { data } = await request.post<Recommendation>(
    '/api/v1/strategy/recommendations',
    payload,
  )
  return data
}

/** 删除策略推荐 */
export async function deleteRecommendation(recommendId: number): Promise<void> {
  await request.delete(`/api/v1/strategy/recommendations/${recommendId}`)
}
