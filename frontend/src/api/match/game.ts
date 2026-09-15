/**
 * 比赛与赛果模块 API:比赛。
 */
import request from '../request'

/** 比赛状态 */
export type MatchStatus = 'PENDING' | 'LIVE' | 'FINISHED'

/** 玩法选项(赔率) */
export interface MatchOddsOption {
  code: string
  label: string
  odds: number
}

/** 单种玩法赔率(HAD/HHAD/CRS/TTG/HAFU) */
export interface MatchOddsPool {
  poolCode: string
  playName: string
  goalLine?: string
  options: MatchOddsOption[]
}

/** 比赛在售玩法赔率 */
export interface MatchOdds {
  match_id: string
  pools: MatchOddsPool[]
  update_time: string
}

/** 比赛基础信息 */
export interface MatchGame {
  match_id: string
  league_id: number
  home_team_id: number
  away_team_id: number
  referee_id: number | null
  match_time: string
  match_status: MatchStatus
  home_score: number | null
  away_score: number | null
  /** 竞彩在售玩法赔率(未同步或未开售时为空) */
  odds: MatchOdds | null
}

/** 创建比赛参数 */
export interface MatchGameCreateParams {
  match_id: string
  league_id: number
  home_team_id: number
  away_team_id: number
  match_time: string
  referee_id?: number | null
  match_status?: MatchStatus
}

/** 录入比分参数 */
export interface ScoreUpdateParams {
  home_score: number
  away_score: number
}

/** 分页查询比赛列表,支持按售卖日范围过滤 */
export async function listGames(params: {
  offset?: number
  limit?: number
  start_date?: string
  end_date?: string
} = {}): Promise<MatchGame[]> {
  const { data } = await request.get<MatchGame[]>('/api/v1/match/games', { params })
  return data
}

/** 创建比赛 */
export async function createGame(payload: MatchGameCreateParams): Promise<MatchGame> {
  const { data } = await request.post<MatchGame>('/api/v1/match/games', payload)
  return data
}

/** 按比赛编号查询 */
export async function getGame(matchId: string): Promise<MatchGame> {
  const { data } = await request.get<MatchGame>(`/api/v1/match/games/${matchId}`)
  return data
}

/** 录入完赛比分 */
export async function updateScore(
  matchId: string,
  payload: ScoreUpdateParams,
): Promise<MatchGame> {
  const { data } = await request.patch<MatchGame>(
    `/api/v1/match/games/${matchId}/score`,
    payload,
  )
  return data
}

/** 删除比赛 */
export async function deleteGame(matchId: string): Promise<void> {
  await request.delete(`/api/v1/match/games/${matchId}`)
}
