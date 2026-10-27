import { ref, type Ref } from 'vue'

/** 大模型分析资源的行为配置(run 生成新结果,loadSaved 拉取最近一次已保存结果) */
export interface LlmResourceOptions<T> {
  /** 生成(并保存)新分析 */
  runRequest: (matchId: string) => Promise<T>
  /** 拉取最近一次已保存分析 */
  savedRequest: (matchId: string) => Promise<T>
  /** 生成失败时的兜底文案 */
  runErrorFallback: string
}

/** 大模型分析资源状态(深度分析页三个 AI 分析区块共用同一套交互) */
export interface LlmResource<T> {
  data: Ref<T | null>
  isLoading: Ref<boolean>
  error: Ref<string | null>
  /** 生成 / 重新生成(结果保存入库,每次生成一条历史) */
  run: () => Promise<void>
  /** 拉取最近一次已保存结果(未生成过时按无结果处理) */
  loadSaved: () => Promise<void>
}

/**
 * 单个大模型分析资源的状态与动作。
 *
 * 深度分析页的 AI 综合分析 / AI 基本面分析 / AI 赔率走势分析三个区块
 * 交互同构:生成按钮(loading/错误兜底)+ 静默加载最近一次已保存
 * 结果(未生成过或请求异常均视为无结果,由用户手动生成)。
 */
export function useLlmResource<T>(
  matchId: string,
  options: LlmResourceOptions<T>,
): LlmResource<T> {
  // 断言必不可少:泛型 T 的 UnwrapRef 是延迟条件类型,
  // 去掉断言后 UnwrapRef<T> 无法赋给 T
  const data = ref<T | null>(null) as Ref<T | null>
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  async function run(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      data.value = await options.runRequest(matchId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : options.runErrorFallback
    } finally {
      isLoading.value = false
    }
  }

  async function loadSaved(): Promise<void> {
    if (data.value !== null || isLoading.value) return
    try {
      data.value = await options.savedRequest(matchId)
    } catch {
      // 未生成过(404)或其他异常均视为无已保存结果,由用户手动生成
    }
  }

  return { data, isLoading, error, run, loadSaved }
}
