/**
 * 赛事中心选注状态:玩法选项勾选 / 投注模式 / 预计总赔率。
 *
 * 选择以 `matchId:poolCode:optionCode` 为键,保证同场同玩法可多选、
 * 跨场次独立;投注模式(单关/串关/混合)仅影响预计赔率展示口径。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/** 投注模式 */
export type BetMode = 'single' | 'parlay' | 'mixed'

/** 单条选注 */
export interface OddsSelection {
  matchId: string
  matchName: string
  poolCode: string
  playName: string
  optionCode: string
  optionLabel: string
  odds: number
}

/** 选注键:matchId:poolCode:optionCode */
export const selectionKey = (
  matchId: string,
  poolCode: string,
  optionCode: string,
): string => `${matchId}:${poolCode}:${optionCode}`

export const useSelectionStore = defineStore('selection', () => {
  const selections = ref<Map<string, OddsSelection>>(new Map())
  const mode = ref<BetMode>('single')

  const selectionList = computed<OddsSelection[]>(() =>
    Array.from(selections.value.values()),
  )
  const count = computed(() => selections.value.size)

  /** 是否已勾选某选项 */
  function isSelected(
    matchId: string,
    poolCode: string,
    optionCode: string,
  ): boolean {
    return selections.value.has(selectionKey(matchId, poolCode, optionCode))
  }

  /** 勾选/取消勾选(返回操作后的选中态) */
  function toggle(selection: Omit<OddsSelection, never>): boolean {
    const key = selectionKey(
      selection.matchId,
      selection.poolCode,
      selection.optionCode,
    )
    const next = new Map(selections.value)
    if (next.has(key)) {
      next.delete(key)
      selections.value = next
      return false
    }
    next.set(key, selection)
    selections.value = next
    return true
  }

  /** 移除单条选注 */
  function remove(key: string): void {
    const next = new Map(selections.value)
    next.delete(key)
    selections.value = next
  }

  /** 切换投注模式 */
  function setMode(value: BetMode): void {
    mode.value = value
  }

  /** 清空全部选注 */
  function clear(): void {
    selections.value = new Map()
  }

  /** 预计总赔率:单关各自独立展示,串关/混合取全乘积 */
  const totalOdds = computed<number | null>(() => {
    const list = selectionList.value
    if (list.length === 0) return null
    if (mode.value === 'single') return null
    return list.reduce((product, item) => product * item.odds, 1)
  })

  return {
    selections,
    selectionList,
    count,
    mode,
    totalOdds,
    isSelected,
    toggle,
    remove,
    setMode,
    clear,
  }
})
