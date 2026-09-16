/**
 * 策略与赔率模块 API:串关虚拟投注方案(模拟数据,不涉及真实资金)。
 */
import request from '../request'

/** 串关方案选注明细 */
export interface BetSchemeItem {
  item_id: number
  match_id: string
  match_name: string
  pool_code: string
  play_name: string
  option_code: string
  option_label: string
  odds: number
}

/** 串关投注方案 */
export interface BetScheme {
  scheme_id: number
  user_id: number
  parlay_size: number
  stake_per_bet: number
  bet_count: number
  total_stake: number
  max_odds: number | null
  status: string
  created_at: string
  items: BetSchemeItem[]
}

/** 创建串关方案的选注条目(勾选时点快照) */
export interface BetSchemeItemPayload {
  match_id: string
  match_name: string
  pool_code: string
  play_name: string
  option_code: string
  option_label: string
  odds: number
}

/** 创建串关方案参数(注数与单注最高赔率由服务端计算) */
export interface BetSchemeCreateParams {
  user_id: number
  parlay_size: number
  stake_per_bet: number
  items: BetSchemeItemPayload[]
}

/** 保存串关虚拟投注方案 */
export async function saveBetScheme(
  payload: BetSchemeCreateParams,
): Promise<BetScheme> {
  const { data } = await request.post<BetScheme>(
    '/api/v1/strategy/bet-schemes',
    payload,
  )
  return data
}

/** 分页查询串关方案,可按用户过滤(按创建时间倒序) */
export async function listBetSchemes(
  params: { user_id?: number; offset?: number; limit?: number } = {},
): Promise<BetScheme[]> {
  const { data } = await request.get<BetScheme[]>(
    '/api/v1/strategy/bet-schemes',
    { params },
  )
  return data
}
