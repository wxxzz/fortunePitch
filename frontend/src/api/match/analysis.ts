/**
 * 比赛与赛果模块 API:大模型分析。
 */
import request from '../request'

/** LLM 生成耗时较长(深度分析 10~30 秒),单独放宽超时 */
const LLM_TIMEOUT_MS = 120_000

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
