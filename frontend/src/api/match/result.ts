/**
 * 比赛与赛果模块 API:赛果开奖查询。
 */
import request from '../request'

/** 单场赛果开奖 */
export interface MatchResultItem {
  match_id: string
  /** 场次编号,如 周二002 */
  match_num_str: string
  league_name: string
  home_team_name: string
  away_team_name: string
  match_time: string
  /** 让球盘口,如 -1 */
  goal_line: string | null
  /** 半场比分,如 0:1 */
  half_score: string | null
  /** 全场比分,如 1:2 */
  full_score: string | null
  had: string | null
  hhad: string | null
  crs: string | null
  ttg: string | null
  hafu: string | null
  sp_h: number | null
  sp_d: number | null
  sp_a: number | null
  /** 开奖状态,如 Payout=已开奖 */
  pool_status: string
}

/** 按比赛日查询赛果开奖列表(未同步的日期返回空列表) */
export async function listMatchResults(date: string): Promise<MatchResultItem[]> {
  const { data } = await request.get<MatchResultItem[]>('/api/v1/match/results', {
    params: { date },
  })
  return data
}
