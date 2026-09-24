/**
 * 策略与赔率模块 API:复盘结算与统计聚合(模拟数据,不涉及真实资金)。
 *
 * 结算口径:单关盈亏用结算时赔率(HAD 优先赛果 SP,其余玩法当前在售赔率),
 * 串关盈亏按明细赔率快照实时计算;未开奖记录保持待结算。
 */
import request from '../request'

/** 复盘核心指标 */
export interface ReviewKpi {
  total_bets: number
  settled: number
  pending: number
  win_count: number
  hit_rate: number
  total_stake: number
  total_profit: number
  roi: number
  max_win_streak: number
}

/** 盈亏曲线数据点 */
export interface ProfitPoint {
  label: string
  cumulative_profit: number
}

/** 维度分析条目(玩法/赔率区间/联赛) */
export interface DimensionStat {
  name: string
  count: number
  hits: number
  hit_rate: number
}

/** 复盘统计聚合结果 */
export interface ReviewStats {
  kpi: ReviewKpi
  profit_curve: ProfitPoint[]
  by_play: DimensionStat[]
  by_odds_range: DimensionStat[]
  by_league: DimensionStat[]
}

/** 结算结果(本次触发实际结算的计数) */
export interface SettlementResult {
  decision_wins: number
  decision_losses: number
  scheme_wins: number
  scheme_losses: number
}

/** 复盘单关决策富明细行 */
export interface ReviewDecision {
  decision_id: number
  user_id: number
  match_id: string
  match_name: string
  league_name: string
  match_time: string
  pool_code: string
  play_name: string
  option_code: string
  option_label: string
  odds: number | null
  stake_amount: number
  result_label: string | null
  result_status: 'WIN' | 'LOSS' | 'PUSH'
  profit_loss: number | null
}

/** 触发复盘结算(幂等:已结算记录不重复处理) */
export async function settleAll(userId?: number): Promise<SettlementResult> {
  const { data } = await request.post<SettlementResult>(
    '/api/v1/strategy/settlement',
    userId === undefined ? {} : { user_id: userId },
  )
  return data
}

/** 查询复盘统计聚合(KPI/盈亏曲线/维度分析) */
export async function getReviewStats(userId?: number): Promise<ReviewStats> {
  const { data } = await request.get<ReviewStats>(
    '/api/v1/strategy/review/stats',
    { params: userId === undefined ? {} : { user_id: userId } },
  )
  return data
}

/** 查询复盘单关决策富明细(按比赛时间倒序) */
export async function listReviewDecisions(
  params: { user_id?: number; result_status?: string; offset?: number; limit?: number } = {},
): Promise<ReviewDecision[]> {
  const { data } = await request.get<ReviewDecision[]>(
    '/api/v1/strategy/review/decisions',
    { params },
  )
  return data
}
