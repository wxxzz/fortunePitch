/**
 * 策略与赔率模块 API:凯利指数计算(仅量化分析,不构成投注建议)。
 */
import request from '../request'

/** 凯利计算响应 */
export interface KellyResponse {
  kelly_fraction: number
}

/** 凯利计算参数 */
export interface KellyParams {
  modelProb: number
  decimalOdds: number
}

/** 调用后端凯利指数计算接口 */
export async function calculateKelly(params: KellyParams): Promise<KellyResponse> {
  const { data } = await request.post<KellyResponse>('/api/v1/strategy/kelly', {
    model_prob: params.modelProb,
    decimal_odds: params.decimalOdds,
  })
  return data
}
