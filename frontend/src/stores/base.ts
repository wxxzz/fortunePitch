/**
 * 基础档案模块 Store:联赛 / 球队 / 球员档案管理。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  createLeague,
  deleteLeague,
  listLeagues,
  type League,
  type LeagueCreateParams,
} from '@/api/base/league'
import {
  createTeam,
  listTeams,
  type Team,
  type TeamCreateParams,
} from '@/api/base/team'
import {
  createPlayer,
  listPlayers,
  type Player,
  type PlayerCreateParams,
} from '@/api/base/player'

export const useBaseStore = defineStore('base', () => {
  const leagues = ref<League[]>([])
  const teams = ref<Team[]>([])
  const players = ref<Player[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  /** 拉取全部基础档案 */
  async function fetchAll(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      const [leagueList, teamList, playerList] = await Promise.all([
        listLeagues({ limit: 100 }),
        listTeams({ limit: 100 }),
        listPlayers({ limit: 100 }),
      ])
      leagues.value = leagueList
      teams.value = teamList
      players.value = playerList
    } catch (err) {
      error.value = err instanceof Error ? err.message : '基础档案加载失败'
    } finally {
      isLoading.value = false
    }
  }

  /** 新增联赛 */
  async function addLeague(payload: LeagueCreateParams): Promise<void> {
    await createLeague(payload)
    leagues.value = await listLeagues({ limit: 100 })
  }

  /** 新增球队 */
  async function addTeam(payload: TeamCreateParams): Promise<void> {
    await createTeam(payload)
    teams.value = await listTeams({ limit: 100 })
  }

  /** 新增球员 */
  async function addPlayer(payload: PlayerCreateParams): Promise<void> {
    await createPlayer(payload)
    players.value = await listPlayers({ limit: 100 })
  }

  /** 删除联赛 */
  async function removeLeague(leagueId: number): Promise<void> {
    await deleteLeague(leagueId)
    leagues.value = leagues.value.filter((l) => l.league_id !== leagueId)
  }

  return {
    leagues,
    teams,
    players,
    isLoading,
    error,
    fetchAll,
    addLeague,
    addTeam,
    addPlayer,
    removeLeague,
  }
})
