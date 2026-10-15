/**
 * 比赛与赛果模块 API:补充信息(伤停/阵型等人工录入)。
 */
import request from '../request'

/** 比赛补充信息(未录入时各字段为 null) */
export interface MatchExtraInfo {
  match_id: string
  injuries: string | null
  formations: string | null
  other_notes: string | null
  updated_at: string | null
}

/** 保存比赛补充信息请求体(整体覆盖语义,空文本等同清空) */
export interface MatchExtraInfoPayload {
  injuries: string
  formations: string
  other_notes: string
}

/** 查询比赛补充信息(未录入时后端返回空记录,不报 404) */
export async function getMatchExtraInfo(matchId: string): Promise<MatchExtraInfo> {
  const { data } = await request.get<MatchExtraInfo>(
    `/api/v1/match/games/${matchId}/extra-info`,
  )
  return data
}

/** 保存(整体覆盖)比赛补充信息 */
export async function saveMatchExtraInfo(
  matchId: string,
  payload: MatchExtraInfoPayload,
): Promise<MatchExtraInfo> {
  const { data } = await request.put<MatchExtraInfo>(
    `/api/v1/match/games/${matchId}/extra-info`,
    payload,
  )
  return data
}
