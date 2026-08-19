/**
 * 策略与赔率模块 API:用户模拟决策(复盘统计用,不涉及真实资金)。
 */
import request from '../request'

/** 结算状态 */
export type DecisionStatus = 'WIN' | 'LOSS' | 'PUSH'

/** 用户决策记录 */
export interface UserDecision {
  decision_id: number
  user_id: number
  recommend_id: number
  user_bet_type: string
  stake_amount: number
  result_status: DecisionStatus
  profit_loss: number | null
}

/** 创建决策参数 */
export interface UserDecisionCreateParams {
  user_id: number
  recommend_id: number
  user_bet_type: string
  stake_amount: number
  result_status?: DecisionStatus
  profit_loss?: number | null
}

/** 分页查询用户决策,可按用户过滤 */
export async function listUserDecisions(
  params: { user_id?: number; offset?: number; limit?: number } = {},
): Promise<UserDecision[]> {
  const { data } = await request.get<UserDecision[]>(
    '/api/v1/strategy/user-decisions',
    { params },
  )
  return data
}

/** 创建用户模拟决策 */
export async function createUserDecision(
  payload: UserDecisionCreateParams,
): Promise<UserDecision> {
  const { data } = await request.post<UserDecision>(
    '/api/v1/strategy/user-decisions',
    payload,
  )
  return data
}

/** 删除用户决策 */
export async function deleteUserDecision(decisionId: number): Promise<void> {
  await request.delete(`/api/v1/strategy/user-decisions/${decisionId}`)
}
