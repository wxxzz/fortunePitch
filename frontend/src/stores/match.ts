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

  /** 拉取比赛列表 */
  async function fetchGames(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      games.value = await listGames({ limit: 50 })
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
    fetchGames,
    selectMatch,
    addGame,
    submitScore,
  }
})
