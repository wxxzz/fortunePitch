/**
 * 数据分析相关 API。
 */
import request from './request'

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

/** Dixon-Coles 泊松预测响应 */
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

/** 凯利指数计算响应 */
export interface KellyResponse {
  kelly_fraction: number
}

/** 凯利指数计算请求参数 */
export interface KellyParams {
  modelProb: number
  decimalOdds: number
}

/** 调用后端泊松比分预测接口 */
export async function predictByPoisson(
  params: PoissonPredictParams,
): Promise<PoissonPredictResponse> {
  const { data } = await request.post<PoissonPredictResponse>(
    '/api/v1/analysis/poisson',
    {
      home_xg: params.homeXg,
      away_xg: params.awayXg,
    },
  )
  return data
}

/** 调用后端凯利指数计算接口 */
export async function calculateKelly(
  params: KellyParams,
): Promise<KellyResponse> {
  const { data } = await request.post<KellyResponse>(
    '/api/v1/analysis/kelly',
    {
      model_prob: params.modelProb,
      decimal_odds: params.decimalOdds,
    },
  )
  return data
}
