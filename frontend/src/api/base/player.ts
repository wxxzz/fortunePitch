/**
 * 基础档案模块 API:球员。
 */
import request from '../request'
import type { PageParams } from './league'

/** 球员档案 */
export interface Player {
  player_id: number
  player_name: string
  team_id: number
  position: string | null
  birth_date: string | null
  market_value: number | null
}

/** 创建球员参数 */
export interface PlayerCreateParams {
  player_name: string
  team_id: number
  position?: string | null
  birth_date?: string | null
  market_value?: number | null
}

/** 分页查询球员列表 */
export async function listPlayers(params: PageParams = {}): Promise<Player[]> {
  const { data } = await request.get<Player[]>('/api/v1/base/players', { params })
  return data
}

/** 创建球员 */
export async function createPlayer(payload: PlayerCreateParams): Promise<Player> {
  const { data } = await request.post<Player>('/api/v1/base/players', payload)
  return data
}

/** 按 ID 查询球员 */
export async function getPlayer(playerId: number): Promise<Player> {
  const { data } = await request.get<Player>(`/api/v1/base/players/${playerId}`)
  return data
}

/** 删除球员 */
export async function deletePlayer(playerId: number): Promise<void> {
  await request.delete(`/api/v1/base/players/${playerId}`)
}
