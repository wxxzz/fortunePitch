/**
 * 基础档案模块 API:联赛多维度分析。
 */
import request from '../request'

/** 有限标签分布行(如半全场的"胜胜"、总进球的"5+") */
export interface LabelCount {
  label: string
  count: number
}

/** 热门命中统计(每场取胜平负 SP 最低项为热门) */
export interface LeagueFavoriteStats {
  count: number
  hit_count: number
  /** 命中率(0~1,无场次为 null) */
  hit_rate: number | null
  /** 热门项平均 SP */
  avg_sp: number | null
}

/** 联赛多维度分析数据(对已完赛场次的统计) */
export interface LeagueInsights {
  league_id: number
  league_name: string
  season: string
  finished_count: number
  home_win: number
  draw: number
  away_win: number
  home_win_rate: number | null
  draw_rate: number | null
  away_win_rate: number | null
  avg_total_goals: number | null
  avg_home_goals: number | null
  avg_away_goals: number | null
  over2_5_count: number
  over2_5_rate: number | null
  btts_count: number
  btts_rate: number | null
  /** 总进球分布(0/1/2/3/4/5+,固定顺序) */
  total_goals: LabelCount[]
  /** 半全场分布(按出现次数降序) */
  half_full: LabelCount[]
  /** 让球胜平负分布(固定顺序,仅非零项) */
  handicap: LabelCount[]
  /** 热门命中统计(无 SP 数据为 null) */
  favorite: LeagueFavoriteStats | null
}

/** 查询联赛多维度分析(胜平负/进球/半全场/让球/热门命中分布) */
export async function getLeagueInsights(leagueId: number): Promise<LeagueInsights> {
  const { data } = await request.get<LeagueInsights>(
    `/api/v1/base/leagues/${leagueId}/insights`,
  )
  return data
}
