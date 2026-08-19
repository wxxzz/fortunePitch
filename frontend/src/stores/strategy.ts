/**
 * 策略与赔率模块 Store:赔率历史 / 策略推荐 / 用户决策 / 凯利指数。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listOddsHistory,
  type OddsHistory,
} from '@/api/strategy/oddsHistory'
import {
  listRecommendations,
  type Recommendation,
} from '@/api/strategy/recommendation'
import {
  listUserDecisions,
  type UserDecision,
} from '@/api/strategy/userDecision'
import { calculateKelly, type KellyResponse } from '@/api/strategy/kelly'

export const useStrategyStore = defineStore('strategy', () => {
  const oddsHistory = ref<OddsHistory[]>([])
  const recommendations = ref<Recommendation[]>([])
  const decisions = ref<UserDecision[]>([])
  const kellyResult = ref<KellyResponse | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  /** 拉取策略模块全部数据 */
  async function fetchAll(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      const [odds, recs, decs] = await Promise.all([
        listOddsHistory({ limit: 100 }),
        listRecommendations({ limit: 50 }),
        listUserDecisions({ limit: 50 }),
      ])
      oddsHistory.value = odds
      recommendations.value = recs
      decisions.value = decs
    } catch (err) {
      error.value = err instanceof Error ? err.message : '策略数据加载失败'
    } finally {
      isLoading.value = false
    }
  }

  /** 计算凯利指数(仅量化分析,不构成投注建议) */
  async function fetchKelly(modelProb: number, decimalOdds: number): Promise<void> {
    try {
      kellyResult.value = await calculateKelly({ modelProb, decimalOdds })
    } catch (err) {
      error.value = err instanceof Error ? err.message : '凯利计算失败'
      kellyResult.value = null
    }
  }

  return {
    oddsHistory,
    recommendations,
    decisions,
    kellyResult,
    isLoading,
    error,
    fetchAll,
    fetchKelly,
  }
})
