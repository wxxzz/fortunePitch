/**
 * 比赛与赛果模块 API:比赛事件。
 */
import request from '../request'

/** 比赛事件 */
export interface MatchEvent {
  event_id: number
  match_id: string
  event_type: string
  event_minute: number
  player_id: number | null
  is_home_team: boolean
}

/** 创建事件参数 */
export interface MatchEventCreateParams {
  match_id: string
  event_type: string
  event_minute: number
  player_id?: number | null
  is_home_team?: boolean
}

/** 查询指定比赛的事件列表(按发生时间升序) */
export async function listEvents(matchId: string): Promise<MatchEvent[]> {
  const { data } = await request.get<MatchEvent[]>('/api/v1/match/events', {
    params: { match_id: matchId },
  })
  return data
}

/** 创建比赛事件 */
export async function createEvent(payload: MatchEventCreateParams): Promise<MatchEvent> {
  const { data } = await request.post<MatchEvent>('/api/v1/match/events', payload)
  return data
}

/** 删除比赛事件 */
export async function deleteEvent(eventId: number): Promise<void> {
  await request.delete(`/api/v1/match/events/${eventId}`)
}
