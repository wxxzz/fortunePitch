/**
 * 基础档案模块 API:大模型球队维度分析。
 */
import request from '../request'

/** 维度编码 */
export type TeamAnalysisDimCode =
  | 'ATTACK'
  | 'DEFENSE'
  | 'HOME_FORM'
  | 'AWAY_FORM'
  | 'RECENT_FORM'
  | 'OTHER'

/** 维度评级:strong=强 / average=中 / weak=弱 */
export type TeamAnalysisRating = 'strong' | 'average' | 'weak'

/** 单个维度的分析结论 */
export interface TeamLlmAnalysisDim {
  dim_id: number
  code: TeamAnalysisDimCode
  title: string
  rating: TeamAnalysisRating
  content: string
}

/** 大模型球队维度分析结果(整体研判 + 六维度结论 + 风险提示) */
export interface TeamLlmAnalysis {
  analysis_id: number
  team_id: number
  provider: string
  model: string
  summary: string
  risks: string[]
  dimensions: TeamLlmAnalysisDim[]
  created_at: string
}

/** 生成并保存一次球队维度分析 */
export async function runTeamAnalysis(teamId: number): Promise<TeamLlmAnalysis> {
  const { data } = await request.post<TeamLlmAnalysis>(
    `/api/v1/base/teams/${teamId}/llm-analysis`,
  )
  return data
}

/** 查询球队最近一次已保存的维度分析(未生成过时后端返回 404) */
export async function getLatestTeamAnalysis(
  teamId: number,
): Promise<TeamLlmAnalysis> {
  const { data } = await request.get<TeamLlmAnalysis>(
    `/api/v1/base/teams/${teamId}/llm-analysis`,
  )
  return data
}

/** 查询球队的历史维度分析列表(按生成时间倒序,最近 20 条) */
export async function listTeamAnalyses(
  teamId: number,
): Promise<TeamLlmAnalysis[]> {
  const { data } = await request.get<TeamLlmAnalysis[]>(
    `/api/v1/base/teams/${teamId}/llm-analyses`,
  )
  return data
}
