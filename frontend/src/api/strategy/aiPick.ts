/**
 * 策略与赔率模块 API:AI 策略推荐(单场推荐清单 + 自动串关候选)。
 *
 * 数据来源为深度分析页落库的 AI 分析结果,生成时解析选项编码与
 * 生成时点赔率并计算隐含概率/EV/凯利;所有注额均为模拟数据,
 * 分析结果仅供参考,不构成投注建议。
 */
import request from '../request'
import type { UserDecision } from './userDecision'
import type { BetScheme } from './betScheme'

/** AI 推荐批次摘要 */
export interface AiBatchSummary {
  batch_id: number
  business_date: string
  min_confidence: number
  /** 入选单场推荐数 */
  pick_count: number
  /** 跳过数(已开赛/赔率不可解析) */
  skipped_count: number
  /** 串关候选方案数 */
  plan_count: number
  /** 本次重算取代的旧批次 ID */
  superseded_batch_ids: number[]
  created_at: string
}

/** AI 单场推荐明细(含比赛/联赛/主客队富字段) */
export interface AiPick {
  pick_id: number
  batch_id: number
  match_id: string
  /** 场次编号,如 周二002 */
  match_num_str: string
  league_name: string
  match_time: string
  home_team_name: string
  away_team_name: string
  play_code: string
  play_name: string
  /** LLM 原始推荐文案 */
  recommendation: string
  option_code: string
  option_label: string
  /** 生成时点赔率快照 */
  odds: number
  confidence: number
  /** 去水隐含概率 */
  implied_prob: number
  /** 期望值 = confidence * odds - 1 */
  ev: number
  /** 凯利建议资金比例,无正期望为 0 */
  kelly: number
  /** 逆向腿 = 置信度低于市场隐含概率 */
  is_contrarian: boolean
  reasoning: string
  /** 转决策后回填的决策 ID(已转换标记) */
  decision_id: number | null
}

/** AI 串关候选方案中的单条腿 */
export interface AiParlayLeg {
  match_id: string
  match_num_str: string
  match_name: string
  play_code: string
  play_name: string
  option_code: string
  option_label: string
  odds: number
  confidence: number
  is_contrarian: boolean
}

/** AI 串关候选方案 */
export interface AiParlayPlan {
  plan_id: number
  batch_id: number
  parlay_size: number
  plan_name: string
  plan_desc: string
  legs: AiParlayLeg[]
  /** 组合赔率 = Π odds */
  combined_odds: number
  /** 组合置信度 = Π confidence(腿间独立近似) */
  combined_confidence: number
  ev: number
  kelly: number
  /** 逆向腿数(≤ 2) */
  contrarian_count: number
  /** 保存为正式方案后回填(已保存标记) */
  scheme_id: number | null
  created_at: string
}

/** 生成 AI 策略推荐参数(可反复重算,旧批次自动失效) */
export interface AiGenerateParams {
  business_date?: string
  min_confidence?: number
}

/** 单场推荐转模拟决策参数 */
export interface AiPickConvertParams {
  user_id?: number
  stake_amount?: number
}

/** 串关候选转模拟方案参数 */
export interface AiPlanConvertParams {
  user_id?: number
  stake_per_bet?: number
}

/** 单场推荐转模拟决策结果(created=false 表示返回既有决策) */
export interface AiPickConvertResult {
  decision: UserDecision
  created: boolean
}

/** 串关候选转模拟方案结果(幂等) */
export interface AiPlanConvertResult {
  scheme: BetScheme
  created: boolean
}

/** 生成/重算 AI 策略推荐批次 */
export async function generateAiRecommendations(
  payload: AiGenerateParams = {},
): Promise<AiBatchSummary> {
  const { data } = await request.post<AiBatchSummary>(
    '/api/v1/strategy/ai-recommendations/generate',
    payload,
  )
  return data
}

/** 查询 AI 单场推荐清单(最新生效批次,按 EV 倒序) */
export async function listAiPicks(
  params: { business_date?: string; offset?: number; limit?: number } = {},
): Promise<AiPick[]> {
  const { data } = await request.get<AiPick[]>(
    '/api/v1/strategy/ai-picks',
    { params },
  )
  return data
}

/** 查询 AI 串关候选方案(最新生效批次) */
export async function listAiParlayPlans(
  params: { business_date?: string } = {},
): Promise<AiParlayPlan[]> {
  const { data } = await request.get<AiParlayPlan[]>(
    '/api/v1/strategy/ai-parlay-plans',
    { params },
  )
  return data
}

/** 单场推荐转模拟决策(幂等,接入结算/复盘闭环) */
export async function convertAiPick(
  pickId: number,
  payload: AiPickConvertParams = {},
): Promise<AiPickConvertResult> {
  const { data } = await request.post<AiPickConvertResult>(
    `/api/v1/strategy/ai-picks/${pickId}/convert`,
    payload,
  )
  return data
}

/** 串关候选转模拟串关方案(幂等) */
export async function convertAiParlayPlan(
  planId: number,
  payload: AiPlanConvertParams = {},
): Promise<AiPlanConvertResult> {
  const { data } = await request.post<AiPlanConvertResult>(
    `/api/v1/strategy/ai-parlay-plans/${planId}/convert`,
    payload,
  )
  return data
}
