import { computed, ref } from 'vue'
import {
  listOddsSnapshots,
  type MatchOddsSnapshot,
} from '@/api/match/oddsSnapshot'

/** 快照中出现过的玩法(取并集,让球附最后一次出现的盘口) */
export interface TrendPoolOption {
  poolCode: string
  playName: string
  goalLine?: string
}

/** 快照时间格式化为 MM-DD HH:mm */
function formatSnapshotTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/**
 * 赔率快照走势数据:快照懒加载 + 玩法选择 + 当前玩法的序列/点位。
 *
 * 由赔率走势 Tab 独占持有,首次进入该 Tab 时 load();
 * load 自带已加载/加载中守卫,失败时重进 Tab 可重试。
 */
export function useOddsTrend(matchId: string) {
  const snapshots = ref<MatchOddsSnapshot[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const hasLoaded = ref(false)
  const activePoolCode = ref('')

  async function load(): Promise<void> {
    if (hasLoaded.value || isLoading.value) return
    isLoading.value = true
    error.value = null
    try {
      snapshots.value = await listOddsSnapshots(matchId)
      // 成功后才标记已加载,失败时切回本 Tab 可重试
      hasLoaded.value = true
      if (activePoolCode.value === '') {
        activePoolCode.value = snapshots.value[0]?.pools[0]?.poolCode ?? ''
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : '赔率走势加载失败'
    } finally {
      isLoading.value = false
    }
  }

  const poolOptions = computed<TrendPoolOption[]>(() => {
    const map = new Map<string, TrendPoolOption>()
    // 快照按时间升序遍历,后出现者覆盖;盘口缺失时保留先前值
    for (const snapshot of snapshots.value) {
      for (const pool of snapshot.pools) {
        const existing = map.get(pool.poolCode)
        map.set(pool.poolCode, {
          poolCode: pool.poolCode,
          playName: pool.playName,
          goalLine: pool.goalLine ?? existing?.goalLine,
        })
      }
    }
    return [...map.values()]
  })

  /** 当前展示的玩法(选择失效时回退到第一个可用玩法) */
  const currentPoolCode = computed(() => {
    const codes = poolOptions.value.map((p) => p.poolCode)
    return codes.includes(activePoolCode.value)
      ? activePoolCode.value
      : (codes[0] ?? '')
  })

  function poolLabel(pool: TrendPoolOption): string {
    return pool.goalLine ? `${pool.playName}(${pool.goalLine})` : pool.playName
  }

  /** 当前玩法在各快照中的选项并集(按首次出现顺序) */
  const series = computed(() => {
    const map = new Map<string, string>()
    for (const snapshot of snapshots.value) {
      const pool = snapshot.pools.find(
        (p) => p.poolCode === currentPoolCode.value,
      )
      if (!pool) continue
      for (const option of pool.options) {
        if (!map.has(option.code)) map.set(option.code, option.label)
      }
    }
    return [...map.entries()].map(([code, label]) => ({ code, label }))
  })

  const seriesNames = computed(() => series.value.map((s) => s.label))

  const points = computed(() =>
    snapshots.value.map((snapshot) => {
      const pool = snapshot.pools.find(
        (p) => p.poolCode === currentPoolCode.value,
      )
      const oddsByCode = new Map(
        pool?.options.map((o) => [o.code, o.odds]) ?? [],
      )
      return {
        time: formatSnapshotTime(snapshot.snapshot_time),
        values: series.value.map((s) => oddsByCode.get(s.code) ?? null),
      }
    }),
  )

  return {
    snapshots,
    isLoading,
    error,
    activePoolCode,
    poolOptions,
    currentPoolCode,
    poolLabel,
    series,
    seriesNames,
    points,
    load,
  }
}
