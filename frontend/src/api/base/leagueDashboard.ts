/**
 * 基础档案模块 API:联赛看板。
 */
import request from '../request'
import type { League } from './league'

/** 积分榜行(总榜;基本面未同步时战绩字段为 null) */
export interface LeagueStandingRow {
  team_id: number
  team_name: string
  /** 基本面数据所属赛季(未同步为 null) */
  season: string | null
  ranking: number | null
  played: number | null
  wins: number | null
  draws: number | null
  losses: number | null
  goals_for: number | null
  goals_against: number | null
  goal_diff: number | null
  points: number | null
  /** 胜率(%),未同步为 null */
  win_rate: number | null
}

/** 联赛赛程/赛果行(含主客队名与完赛比分) */
export interface LeagueMatchRow {
  match_id: string
  match_num_str: string
  match_time: string
  match_status: 'PENDING' | 'LIVE' | 'FINISHED'
  home_team_name: string
  away_team_name: string
  home_score: number | null
  away_score: number | null
}

/** 联赛看板聚合数据 */
export interface LeagueDashboard {
  league: League
  /** 已入库球队数 */
  team_count: number
  /** 积分榜(总榜,按排名升序,未同步基本面球队排末尾) */
  standings: LeagueStandingRow[]
  /** 近期赛果(已完赛,开赛时间倒序) */
  recent_results: LeagueMatchRow[]
  /** 近期赛程(未完赛,开赛时间正序) */
  upcoming_fixtures: LeagueMatchRow[]
}

/** 看板查询参数(赛果/赛程条数) */
export interface LeagueDashboardParams {
  result_limit?: number
  fixture_limit?: number
}

/** 查询联赛看板(基本信息 + 积分榜 + 近期赛程赛果) */
export async function getLeagueDashboard(
  leagueId: number,
  params: LeagueDashboardParams = {},
): Promise<LeagueDashboard> {
  const { data } = await request.get<LeagueDashboard>(
    `/api/v1/base/leagues/${leagueId}/dashboard`,
    { params },
  )
  return data
}
