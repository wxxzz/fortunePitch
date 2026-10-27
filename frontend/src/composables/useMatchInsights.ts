import { reactive, ref } from 'vue'
import { getMatchInsights, type MatchInsights } from '@/api/match/insights'

/**
 * 赛事高阶数据 / 历史交锋共享 payload 的加载状态。
 *
 * 两个 Tab 展示同一份 insights 数据的不同切面,由父组件持有单一实例、
 * 首次切到任一 Tab 时懒加载;load 自带已加载/加载中守卫,可重复调用。
 * 返回 reactive 捆绑对象,便于作为单一 prop 传给两个 Tab 组件。
 */
export function useMatchInsights(matchId: string) {
  const insights = ref<MatchInsights | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const hasLoaded = ref(false)

  async function load(): Promise<void> {
    if (hasLoaded.value || isLoading.value) return
    isLoading.value = true
    error.value = null
    try {
      insights.value = await getMatchInsights(matchId)
      // 成功后才标记已加载,失败时切回本 Tab 可重试
      hasLoaded.value = true
    } catch (err) {
      error.value = err instanceof Error ? err.message : '高阶数据加载失败'
    } finally {
      isLoading.value = false
    }
  }

  return reactive({ insights, isLoading, error, hasLoaded, load })
}

export type MatchInsightsState = ReturnType<typeof useMatchInsights>
