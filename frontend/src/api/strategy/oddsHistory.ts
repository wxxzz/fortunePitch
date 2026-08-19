/**
 * 策略与赔率模块 API:赔率历史。
 */
import request from '../request'

/** 赔率快照记录 */
export interface OddsHistory {
  odds_id: number
  match_id: string
  bookmaker: string
  market_type: string
  initial_value: number
  current_value: number
  update_time: string
}

/** 创建赔率记录参数 */
export interface OddsHistoryCreateParams {
  match_id: string
  bookmaker: string
  market_type: string
  initial_value: number
  current_value: number
  update_time: string
}

/** 分页查询赔率快照,可按比赛过滤(按更新时间升序) */
export async function listOddsHistory(
  params: { match_id?: string; offset?: number; limit?: number } = {},
): Promise<OddsHistory[]> {
  const { data } = await request.get<OddsHistory[]>(
    '/api/v1/strategy/odds-history',
    { params },
  )
  return data
}

/** 创建赔率快照 */
export async function createOddsRecord(
  payload: OddsHistoryCreateParams,
): Promise<OddsHistory> {
  const { data } = await request.post<OddsHistory>(
    '/api/v1/strategy/odds-history',
    payload,
  )
  return data
}

/** 删除赔率快照 */
export async function deleteOddsRecord(oddsId: number): Promise<void> {
  await request.delete(`/api/v1/strategy/odds-history/${oddsId}`)
}
