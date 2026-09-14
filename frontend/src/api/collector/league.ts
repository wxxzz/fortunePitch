/**
 * 数据采集模块 API:联赛 / 球队 / 球员同步。
 */
import request from '../request'
import type { League } from '../base/league'

/** 联赛同步结果 */
export interface LeagueSyncResult {
  league: League
  action: 'created' | 'updated'
  uniform_league_id: number
  source: string
}

/** 球队同步结果 */
export interface TeamSyncResult {
  league: League
  team_count: number
  created_count: number
  updated_count: number
  uniform_league_id: number
  source: string
}

/** 球员同步结果中的球队计数 */
export interface TeamPlayerCount {
  team_name: string
  player_count: number
}

/** 球队基本面同步结果 */
export interface TeamFundamentalsSyncResult {
  league: League
  season: string
  team_count: number
  created_count: number
  updated_count: number
  skipped_teams: string[]
  uniform_league_id: number
  source: string
}

/** 球员同步结果 */
export interface PlayerSyncResult {
  league: League
  team_count: number
  player_count: number
  created_count: number
  updated_count: number
  matches_scanned: number
  team_player_counts: TeamPlayerCount[]
  skipped_teams: string[]
  source: string
}

/** 同步类接口的独立超时(球员同步需扫描多场比赛,耗时较长) */
const SYNC_TIMEOUT_MS = 120_000

/** 按名称同步联赛信息(来源:中国竞彩网联赛资料) */
export async function syncLeague(leagueName: string): Promise<LeagueSyncResult> {
  const { data } = await request.post<LeagueSyncResult>(
    '/api/v1/collector/leagues/sync',
    { league_name: leagueName },
    { timeout: SYNC_TIMEOUT_MS },
  )
  return data
}

/** 按联赛名称同步球队清单(自动先同步联赛档案) */
export async function syncTeams(leagueName: string): Promise<TeamSyncResult> {
  const { data } = await request.post<TeamSyncResult>(
    '/api/v1/collector/teams/sync',
    { league_name: leagueName },
    { timeout: SYNC_TIMEOUT_MS },
  )
  return data
}

/** 按联赛名称同步球队基本面(积分榜总/主/客三榜,自动先同步联赛与球队) */
export async function syncFundamentals(
  leagueName: string,
): Promise<TeamFundamentalsSyncResult> {
  const { data } = await request.post<TeamFundamentalsSyncResult>(
    '/api/v1/collector/fundamentals/sync',
    { league_name: leagueName },
    { timeout: SYNC_TIMEOUT_MS },
  )
  return data
}

/** 按联赛名称同步球员名单(自动先同步联赛与球队) */
export async function syncPlayers(leagueName: string): Promise<PlayerSyncResult> {
  const { data } = await request.post<PlayerSyncResult>(
    '/api/v1/collector/players/sync',
    { league_name: leagueName },
    { timeout: SYNC_TIMEOUT_MS },
  )
  return data
}
