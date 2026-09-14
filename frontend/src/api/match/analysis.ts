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
