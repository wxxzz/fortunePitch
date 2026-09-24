/**
 * 策略与赔率模块 API:投注方案分析(中奖概率与期望值,纯计算不落库)。
 *
 * 概率口径为赔率隐含概率(去水归一),期望值如实反映返还率折扣;
 * 注额均为模拟数据,结果不构成投注建议。
 */
import request from '../request'

/** 单条选注的分析结果 */
export interface PlanSelectionAnalysis {
  match_id: string
  match_name: string
  pool_code: string
  play_name: string
  option_code: string
  option_label: string
  /** 分析采用的赔率(优先当前在售值) */
  odds: number
  /** 隐含概率(去水归一),0~1 */
  implied_prob: number
  /** 公平赔率 = 1 / 隐含概率 */
  fair_odds: number
  /** 每 1 元投入的期望损益,负为折价 */
  ev_per_unit: number
  /** 凯利建议资金比例,无正期望为 0 */
  kelly_fraction: number
}

/** 投注方案整体分析结果 */
export interface PlanAnalysis {
  mode: 'single' | 'parlay' | 'mixed'
  /** 概率口径,implied=赔率隐含概率(去水归一) */
  probability_source: string
  selections: PlanSelectionAnalysis[]
  bet_count: number
  total_stake: number
  max_odds: number
  /** 方案中奖概率(至少一注命中,串关为至少 N 场被覆盖) */
  win_prob: number
  expected_return: number
  expected_value: number
  ev_pct: number
}

/** 方案分析请求中的单条选注(勾选时点快照) */
export interface PlanSelectionPayload {
  match_id: string
  match_name: string
  pool_code: string
  play_name: string
  option_code: string
  option_label: string
  odds: number
}

/** 方案分析请求参数 */
export interface PlanAnalysisParams {
  mode: 'single' | 'parlay' | 'mixed'
  stake_per_bet: number
  /** N串1 的 N,串关/混合模式必填 */
  parlay_size?: number
  selections: PlanSelectionPayload[]
}

/** 分析投注方案的中奖概率与期望值 */
export async function analyzeBetPlan(
  payload: PlanAnalysisParams,
): Promise<PlanAnalysis> {
  const { data } = await request.post<PlanAnalysis>(
    '/api/v1/strategy/plan-analysis',
    payload,
  )
  return data
}
