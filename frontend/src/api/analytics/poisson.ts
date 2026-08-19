/**
 * 高阶数据分析模块 API:Dixon-Coles 泊松比分预测。
 */
import request from '../request'

/** 胜平负概率预测结果 */
export interface MatchProbabilities {
  home_win: number
  draw: number
  away_win: number
}

/** 单个比分概率 */
export interface ScoreProbability {
  home_goals: number
  away_goals: number
  probability: number
}

/** 泊松预测响应 */
export interface PoissonPredictResponse {
  probabilities: MatchProbabilities
  top_scores: ScoreProbability[]
  total_goals_expected: number
}

/** 泊松预测请求参数 */
export interface PoissonPredictParams {
  homeXg: number
  awayXg: number
}

/** 调用后端泊松比分预测接口 */
export async function predictByPoisson(
  params: PoissonPredictParams,
): Promise<PoissonPredictResponse> {
  const { data } = await request.post<PoissonPredictResponse>(
    '/api/v1/analytics/poisson',
    {
      home_xg: params.homeXg,
      away_xg: params.awayXg,
    },
  )
  return data
}
