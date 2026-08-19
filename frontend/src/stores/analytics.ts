/**
 * 高阶数据分析模块 Store:泊松预测 / 球队高阶指标。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  predictByPoisson,
  type PoissonPredictResponse,
} from '@/api/analytics/poisson'
import {
  listTeamStats,
  type TeamMatchStat,
} from '@/api/analytics/teamStats'

export const useAnalyticsStore = defineStore('analytics', () => {
  // 泊松预测结果
  const poissonResult = ref<PoissonPredictResponse | null>(null)
  const isPredictionLoading = ref(false)
  const predictionError = ref<string | null>(null)

  // 球队高阶指标
  const teamStats = ref<TeamMatchStat[]>([])

  /** 请求 Dixon-Coles 泊松比分预测 */
  async function fetchPoissonPrediction(homeXg: number, awayXg: number): Promise<void> {
    isPredictionLoading.value = true
    predictionError.value = null
    try {
      poissonResult.value = await predictByPoisson({ homeXg, awayXg })
    } catch (err) {
      predictionError.value = err instanceof Error ? err.message : '预测请求失败'
      poissonResult.value = null
    } finally {
      isPredictionLoading.value = false
    }
  }

  /** 拉取球队高阶指标,可按比赛过滤 */
  async function fetchTeamStats(matchId?: string): Promise<void> {
    try {
      teamStats.value = await listTeamStats(
        matchId ? { match_id: matchId } : { limit: 50 },
      )
    } catch (err) {
      predictionError.value = err instanceof Error ? err.message : '高阶指标加载失败'
    }
  }

  return {
    poissonResult,
    isPredictionLoading,
    predictionError,
    teamStats,
    fetchPoissonPrediction,
    fetchTeamStats,
  }
})
