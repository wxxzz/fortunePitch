/**
 * 比赛与赛果模块 Store:比赛列表 / 事件。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  createGame,
  listGames,
  updateScore,
  type MatchGame,
  type MatchGameCreateParams,
  type ScoreUpdateParams,
} from '@/api/match/game'
import { listEvents, type MatchEvent } from '@/api/match/event'

export const useMatchStore = defineStore('match', () => {
  const games = ref<MatchGame[]>([])
  const events = ref<MatchEvent[]>([])
  const selectedMatchId = ref<string | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  // 最近一次成功拉取比赛列表的时间戳(TopBar 数据更新时间展示用)
  const gamesUpdatedAt = ref<number | null>(null)
  // 默认筛选:售卖日范围 = [今天, 今天+1天] → 默认显示“当天及次日”
  const today = new Date()
  const startBusinessDate = ref<string | null>(
    formatLocalDate(today),
  )
  const endBusinessDate = ref<string | null>(
    formatLocalDate(addDays(today, 1)),
  )

  /** 分页拉取的单页条数(后端上限 100)与页数上限(防御性封顶) */
  const PAGE_SIZE = 100
  const MAX_PAGES = 5

  /** 本地时区的 YYYY-MM-DD(toISOString 会偏移到 UTC,凌晨场次算错日) */
  function formatLocalDate(date: Date): string {
    const pad = (n: number): string => String(n).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  }

  /** 加 n 天(保持本地时区) */
  function addDays(date: Date, days: number): Date {
    const result = new Date(date)
    result.setDate(result.getDate() + days)
    return result
  }

  /** 拉取比赛列表(按售卖日范围过滤,翻页拉全,覆盖跨售卖日的全部在售场次) */
  async function fetchGames(): Promise<void> {
    if (isLoading.value) return
    isLoading.value = true
    error.value = null
    try {
      const collected: MatchGame[] = []
      for (let page = 0; page < MAX_PAGES; page += 1) {
        const batch = await listGames({
          offset: page * PAGE_SIZE,
          limit: PAGE_SIZE,
          start_date: startBusinessDate.value ?? undefined,
          end_date: endBusinessDate.value ?? undefined,
        })
        collected.push(...batch)
        if (batch.length < PAGE_SIZE) break
      }
      games.value = collected
      gamesUpdatedAt.value = Date.now()
    } catch (err) {
      error.value = err instanceof Error ? err.message : '比赛列表加载失败'
    } finally {
      isLoading.value = false
    }
  }

  /** 选中比赛并拉取其事件列表 */
  async function selectMatch(matchId: string): Promise<void> {
    selectedMatchId.value = matchId
    try {
      events.value = await listEvents(matchId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '比赛事件加载失败'
    }
  }

  /** 新增比赛 */
  async function addGame(payload: MatchGameCreateParams): Promise<void> {
    await createGame(payload)
    await fetchGames()
  }

  /** 录入完赛比分 */
  async function submitScore(matchId: string, payload: ScoreUpdateParams): Promise<void> {
    await updateScore(matchId, payload)
    await fetchGames()
  }

  return {
    games,
    events,
    selectedMatchId,
    isLoading,
    error,
    gamesUpdatedAt,
    startBusinessDate,
    endBusinessDate,
    fetchGames,
    selectMatch,
    addGame,
    submitScore,
  }
})
