/**
 * 赛事分析 Pinia Store:管理泊松预测的状态与请求。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  calculateKelly,
  predictByPoisson,
  type KellyResponse,
  type PoissonPredictResponse,
} from '@/api/analysis'

export const useAnalysisStore = defineStore('analysis', () => {
  // 泊松预测结果
  const poissonResult = ref<PoissonPredictResponse | null>(null)
  const isPredictionLoading = ref(false)
  const predictionError = ref<string | null>(null)

  // 凯利指数结果
  const kellyResult = ref<KellyResponse | null>(null)

  /**
   * 请求 Dixon-Coles 泊松比分预测。
   * @param homeXg 主队期望进球
   * @param awayXg 客队期望进球
   */
  async function fetchPoissonPrediction(homeXg: number, awayXg: number): Promise<void> {
    isPredictionLoading.value = true
    predictionError.value = null
    try {
      poissonResult.value = await predictByPoisson({ homeXg, awayXg })
    } catch (error) {
      predictionError.value = error instanceof Error ? error.message : '预测请求失败'
      poissonResult.value = null
    } finally {
      isPredictionLoading.value = false
    }
  }

  /**
   * 请求凯利指数计算。
   * @param modelProb 模型预测概率
   * @param decimalOdds 十进制赔率
   */
  async function fetchKelly(modelProb: number, decimalOdds: number): Promise<void> {
    try {
      kellyResult.value = await calculateKelly({ modelProb, decimalOdds })
    } catch (error) {
      predictionError.value = error instanceof Error ? error.message : '凯利计算失败'
      kellyResult.value = null
    }
  }

  return {
    poissonResult,
    isPredictionLoading,
    predictionError,
    kellyResult,
    fetchPoissonPrediction,
    fetchKelly,
  }
})
