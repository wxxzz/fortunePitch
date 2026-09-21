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
  /** 竞彩售卖日(次日凌晨开赛归属前一售卖日) */
  business_date: string | null
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

/** 按售卖日范围查询赛果开奖列表(与赛事中心口径一致,未同步的日期返回空列表) */
export async function listMatchResults(
  startDate: string,
  endDate: string,
): Promise<MatchResultItem[]> {
  const { data } = await request.get<MatchResultItem[]>('/api/v1/match/results', {
    params: { start_date: startDate, end_date: endDate },
  })
  return data
}

/** 单个统计条目(标签 / 次数 / 占比) */
export interface ResultStatItem {
  label: string
  count: number
  /** 该维度有效场次中的占比,0~1 */
  pct: number
}

/** 按联赛的赛果统计行 */
export interface ResultLeagueStat {
  league_name: string
  total: number
  home_win: number
  draw: number
  away_win: number
  avg_total_goals: number | null
}

/** 赛果开奖多维度统计 */
export interface MatchResultStats {
  start_date: string
  end_date: string
  /** 范围内总场次(含取消/无效) */
  total: number
  settled: number
  cancelled: number
  had: ResultStatItem[]
  hhad: ResultStatItem[]
  ttg: ResultStatItem[]
  crs: ResultStatItem[]
  hafu: ResultStatItem[]
  leagues: ResultLeagueStat[]
}

/** 按售卖日范围统计赛果开奖的多维度分布(未同步的日期各维度为空) */
export async function listMatchResultStats(
  startDate: string,
  endDate: string,
): Promise<MatchResultStats> {
  const { data } = await request.get<MatchResultStats>('/api/v1/match/results/stats', {
    params: { start_date: startDate, end_date: endDate },
  })
  return data
}
