/**
 * 比赛与赛果模块 API:大模型分析。
 */
import request from '../request'

/**
 * LLM 生成耗时较长(推理模型深度分析可超 2 分钟),单独放宽超时。
 * 须大于后端 LLM_TIMEOUT_SECONDS(270 秒):后端先超时并返回明确的
 * 502 错误信息,这里只兜底网络彻底无响应的情况
 */
const LLM_TIMEOUT_MS = 300_000

/** 单种玩法的推荐方案 */
export interface LlmPlayRecommendation {
  play_code: string
  play_name: string
  recommendation: string
  confidence: number
  reasoning: string
  alternatives: string[]
}

/** 大模型分析结果(整体研判 + 分玩法推荐 + 风险提示) */
export interface LlmAnalysis {
  analysis_id: number
  match_id: string
  provider: string
  model: string
  summary: string
  plays: LlmPlayRecommendation[]
  risks: string[]
  created_at: string
}

/** 调用大模型分析单场比赛并保存,输出各竞彩玩法的推荐方案 */
export async function runLlmAnalysis(matchId: string): Promise<LlmAnalysis> {
  const { data } = await request.post<LlmAnalysis>(
    `/api/v1/match/games/${matchId}/llm-analysis`,
    undefined,
    { timeout: LLM_TIMEOUT_MS },
  )
  return data
}

/** 查询比赛最近一次已保存的大模型分析(未生成过时后端返回 404) */
export async function getLlmAnalysis(matchId: string): Promise<LlmAnalysis> {
  const { data } = await request.get<LlmAnalysis>(
    `/api/v1/match/games/${matchId}/llm-analysis`,
  )
  return data
}

/** 单个基本面维度的分析结论 */
export interface LlmFundamentalDimension {
  code: string
  title: string
  edge: 'home' | 'away' | 'even'
  content: string
}

/** 大模型基本面分析结果(整体研判 + 六维度结论 + 风险提示) */
export interface LlmFundamentalAnalysis {
  analysis_id: number
  match_id: string
  provider: string
  model: string
  summary: string
  dimensions: LlmFundamentalDimension[]
  risks: string[]
  created_at: string
}

/** 调用大模型做基本面多维度分析(近期状态/主客场/攻防/战意/交锋/其他),生成后保存 */
export async function runLlmFundamentalAnalysis(
  matchId: string,
): Promise<LlmFundamentalAnalysis> {
  const { data } = await request.post<LlmFundamentalAnalysis>(
    `/api/v1/match/games/${matchId}/llm-fundamentals`,
    undefined,
    { timeout: LLM_TIMEOUT_MS },
  )
  return data
}

/** 查询比赛最近一次已保存的大模型基本面分析(未生成过时后端返回 404) */
export async function getLlmFundamentalAnalysis(
  matchId: string,
): Promise<LlmFundamentalAnalysis> {
  const { data } = await request.get<LlmFundamentalAnalysis>(
    `/api/v1/match/games/${matchId}/llm-fundamentals`,
  )
  return data
}

/** 单种玩法的赔率走势结论 */
export interface LlmTrendPlay {
  play_code: string
  play_name: string
  signal: string
  confidence: number
  reasoning: string
}

/** 大模型赔率走势分析结果(整体研判 + 分玩法走势结论 + 风险提示) */
export interface LlmTrendAnalysis {
  analysis_id: number
  match_id: string
  provider: string
  model: string
  summary: string
  plays: LlmTrendPlay[]
  risks: string[]
  created_at: string
}

/** 调用大模型基于赔率快照走势做市场动向分析,生成后保存 */
export async function runLlmTrendAnalysis(matchId: string): Promise<LlmTrendAnalysis> {
  const { data } = await request.post<LlmTrendAnalysis>(
    `/api/v1/match/games/${matchId}/llm-odds-trend`,
    undefined,
    { timeout: LLM_TIMEOUT_MS },
  )
  return data
}

/** 查询比赛最近一次已保存的大模型赔率走势分析(未生成过时后端返回 404) */
export async function getLlmTrendAnalysis(matchId: string): Promise<LlmTrendAnalysis> {
  const { data } = await request.get<LlmTrendAnalysis>(
    `/api/v1/match/games/${matchId}/llm-odds-trend`,
  )
  return data
}

/** AI 分析结果查询行(推荐 + 比赛上下文) */
export interface LlmRecommendationRow {
  analysis_id: number
  match_id: string
  match_num_str: string
  league_name: string | null
  match_time: string
  business_date: string | null
  home_team_name: string | null
  away_team_name: string | null
  play_code: string
  play_name: string
  recommendation: string
  recommendation_odds: number | null
  /** 与 alternatives 按位对齐的最新赔率(未开售或无法解析时为 null) */
  alternative_odds: (number | null)[]
  /** 该玩法的赛果开奖结果(未同步赛果时为 null) */
  result: string | null
  /** 推荐与开奖的比对结论(未开奖时为 null) */
  is_hit: boolean | null
  confidence: number
  reasoning: string
  alternatives: string[]
  created_at: string
}

/** 按售卖日查询各场比赛最近一次 AI 分析的分玩法推荐(置信度倒序) */
export async function listLlmRecommendations(
  params: {
    business_date: string
    min_confidence?: number
    play_code?: string
  },
): Promise<LlmRecommendationRow[]> {
  const { data } = await request.get<LlmRecommendationRow[]>(
    '/api/v1/match/llm-recommendations',
    { params },
  )
  return data
}

/** 单条提示词消息(system / user) */
export interface LlmRequestMessage {
  role: string
  content: string
}

/** 大模型调用日志(完整请求参数与响应结果,供排障查看) */
export interface LlmRequestLog {
  log_id: number
  provider: string
  model: string
  base_url: string
  request_messages: LlmRequestMessage[]
  request_params: Record<string, unknown>
  response_content: string | null
  status: 'SUCCESS' | 'FAILED'
  http_status: number | null
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  duration_ms: number
  error_message: string | null
  error_detail: string | null
  created_at: string
  /** 调用类型:analysis=综合分析 / fundamental=基本面 / odds_trend=赔率走势 */
  analysis_type: string
}

/** 查询比赛的大模型调用日志(按调用时间倒序,含三类分析与失败调用) */
export async function listLlmRequestLogs(
  matchId: string,
  limit = 20,
): Promise<LlmRequestLog[]> {
  const { data } = await request.get<LlmRequestLog[]>(
    `/api/v1/match/games/${matchId}/llm-request-logs`,
    { params: { limit } },
  )
  return data
}

/** 复盘比对明细行(生成时点快照,含大模型事后归因) */
export interface LlmRetrospectItem {
  play_code: string
  play_name: string
  recommendation: string
  confidence: number
  alternatives: string[]
  result: string | null
  is_hit: boolean | null
  reasoning: string
  review: string | null
}

/** 大模型赛事复盘结果(总结 + 逐玩法归因明细 + 经验教训) */
export interface LlmRetrospect {
  retrospect_id: number
  match_id: string
  analysis_id: number
  provider: string
  model: string
  summary: string
  lessons: string[]
  hit_count: number
  total_count: number
  items: LlmRetrospectItem[]
  created_at: string
}

/** 复盘比对预览行(最近一次 AI 推荐 vs 官方开奖,系统实时计算) */
export interface LlmRetrospectComparisonItem {
  play_code: string
  play_name: string
  recommendation: string
  confidence: number
  alternatives: string[]
  result: string | null
  is_hit: boolean | null
  reasoning: string
}

/** 赛事复盘 Tab 视图(比对预览 + 最近一次已保存复盘) */
export interface LlmRetrospectView {
  match_id: string
  result_available: boolean
  analysis_available: boolean
  comparison: LlmRetrospectComparisonItem[]
  retrospect: LlmRetrospect | null
}

/** 查询赛事复盘视图(比对预览实时计算,含最近一次已保存复盘) */
export async function getLlmRetrospectView(
  matchId: string,
): Promise<LlmRetrospectView> {
  const { data } = await request.get<LlmRetrospectView>(
    `/api/v1/match/games/${matchId}/llm-retrospect`,
  )
  return data
}

/** 对比赛事结果与 AI 分析结果,调用大模型生成赛事复盘并保存 */
export async function runLlmRetrospect(matchId: string): Promise<LlmRetrospect> {
  const { data } = await request.post<LlmRetrospect>(
    `/api/v1/match/games/${matchId}/llm-retrospect`,
    undefined,
    { timeout: LLM_TIMEOUT_MS },
  )
  return data
}

/** AI 复盘经验总结(归纳各场复盘的共性经验,供后续综合分析参考) */
export interface LlmLessonSummary {
  summary_id: number
  provider: string
  model: string
  /** 经验归纳总结 */
  summary: string
  /** 共性经验条目(5~10 条) */
  lessons: string[]
  /** 本次总结输入覆盖的复盘场次数 */
  retrospect_count: number
  /** 输入复盘的合计命中数(已开奖玩法口径) */
  total_hit: number
  total_decided: number
  /** 本次总结的请求日志 ID(日志写失败为 null) */
  log_id: number | null
  created_at: string
}

/** 查询 AI 复盘经验总结历史(按生成时间倒序) */
export async function listLlmLessonSummaries(
  limit = 20,
): Promise<LlmLessonSummary[]> {
  const { data } = await request.get<LlmLessonSummary[]>(
    '/api/v1/match/llm-lesson-summaries',
    { params: { limit } },
  )
  return data
}

/** 调用大模型归纳各场 AI 复盘的共性经验并保存(手动触发) */
export async function runLlmLessonSummary(): Promise<LlmLessonSummary> {
  const { data } = await request.post<LlmLessonSummary>(
    '/api/v1/match/llm-lesson-summaries',
    undefined,
    { timeout: LLM_TIMEOUT_MS },
  )
  return data
}

/** 查询某次经验总结的请求日志(该次总结的输入提示词与模型原始响应) */
export async function getLlmLessonSummaryLog(
  summaryId: number,
): Promise<LlmRequestLog> {
  const { data } = await request.get<LlmRequestLog>(
    `/api/v1/match/llm-lesson-summaries/${summaryId}/request-log`,
  )
  return data
}
