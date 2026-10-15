<script setup lang="ts">
/**
 * 联赛看板视图:联赛平铺卡片墙 -> 单联赛看板
 * (基本信息 / 积分榜总榜 / 近期赛程与赛果)。
 *
 * 数据来源:基础档案 + 球队基本面积分榜(数据采集页"同步基本面"写入)
 * + 竞彩赛程;仅提供数据分析参考,不构成投注建议。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listLeagues, type League } from '@/api/base/league'
import {
  getLeagueDashboard,
  type LeagueDashboard,
  type LeagueMatchRow,
  type LeagueStandingRow,
} from '@/api/base/leagueDashboard'

const route = useRoute()
const router = useRouter()

const leagues = ref<League[]>([])
const dashboard = ref<LeagueDashboard | null>(null)
const isLoadingLeagues = ref(false)
const isLoadingDashboard = ref(false)
const error = ref<string | null>(null)

/** 最近一次发起的看板请求联赛 ID:过期响应(慢返回)直接丢弃 */
let activeDashboardRequest: number | null = null

/** 路由参数中的联赛 ID(空 = 联赛卡片墙) */
const selectedLeagueId = computed<number | null>(() => {
  const raw = route.params.leagueId
  const value = Array.isArray(raw) ? raw[0] : raw
  return value ? Number(value) : null
})

async function fetchDashboard(leagueId: number): Promise<void> {
  activeDashboardRequest = leagueId
  isLoadingDashboard.value = true
  error.value = null
  try {
    const data = await getLeagueDashboard(leagueId)
    if (activeDashboardRequest !== leagueId) return
    dashboard.value = data
  } catch (err) {
    if (activeDashboardRequest !== leagueId) return
    dashboard.value = null
    error.value = err instanceof Error ? err.message : '联赛看板加载失败'
  } finally {
    if (activeDashboardRequest === leagueId) {
      isLoadingDashboard.value = false
    }
  }
}

onMounted(async () => {
  // 深链/刷新进入单联赛看板时,列表与看板并行拉取
  const initialLeagueId = selectedLeagueId.value
  const leagueListPromise = (async () => {
    isLoadingLeagues.value = true
    try {
      leagues.value = await listLeagues({ limit: 100 })
    } catch (err) {
      error.value = err instanceof Error ? err.message : '联赛列表加载失败'
    } finally {
      isLoadingLeagues.value = false
    }
  })()
  if (initialLeagueId !== null) {
    await Promise.all([leagueListPromise, fetchDashboard(initialLeagueId)])
  } else {
    await leagueListPromise
  }
})

// 路由参数变化(卡片墙 <-> 看板 / 看板间切换)时重拉
watch(selectedLeagueId, (leagueId) => {
  if (leagueId === null) {
    dashboard.value = null
    return
  }
  void fetchDashboard(leagueId)
})

function handleSelect(league: League): void {
  void router.push(`/leagues/${league.league_id}`)
}

function handleBack(): void {
  void router.push('/leagues')
}

function openMatch(matchId: string): void {
  void router.push(`/match/${matchId}`)
}

function formatTime(matchTime: string): string {
  return new Date(matchTime).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatScore(row: LeagueMatchRow): string {
  if (row.home_score === null || row.away_score === null) return '- : -'
  return `${row.home_score} : ${row.away_score}`
}

const statusLabel: Record<string, string> = {
  PENDING: '未开赛',
  LIVE: '进行中',
  FINISHED: '已完赛',
}

/** 联赛级别标签(1 = 顶级) */
function tierLabel(tier: number): string {
  return tier <= 1 ? '顶级联赛' : `${tier} 级联赛`
}

/** 前 4 名(欧战区口径)着色强调 */
function rankClass(row: LeagueStandingRow): string {
  return row.ranking !== null && row.ranking <= 4
    ? 'league-dashboard__rank--top'
    : ''
}
</script>

<template>
  <section class="league-dashboard">
    <!-- 联赛卡片墙(默认视图) -->
    <template v-if="selectedLeagueId === null">
      <header class="league-dashboard__header">
        <h2 class="league-dashboard__title">联赛看板</h2>
        <p class="league-dashboard__subtitle">
          选择联赛查看基本信息 · 积分榜 · 近期赛程与赛果
        </p>
      </header>

      <p v-if="error && selectedLeagueId === null" class="league-dashboard__error" role="alert">{{ error }}</p>
      <p v-if="isLoadingLeagues" class="league-dashboard__hint">加载中…</p>

      <div v-else class="league-dashboard__grid">
        <button
          v-for="league in leagues"
          :key="league.league_id"
          type="button"
          class="league-dashboard__tile"
          @click="handleSelect(league)"
        >
          <span class="league-dashboard__tile-country">{{ league.country }}</span>
          <strong class="league-dashboard__tile-name">{{ league.league_name }}</strong>
          <span class="league-dashboard__tile-meta">
            <em class="league-dashboard__tile-tier">{{ tierLabel(league.tier) }}</em>
            {{ league.season }} 赛季
          </span>
        </button>
      </div>

      <p v-if="!isLoadingLeagues && leagues.length === 0" class="league-dashboard__empty">
        暂无联赛档案 · 请先在"数据采集"页同步联赛
      </p>
    </template>

    <!-- 单联赛看板 -->
    <template v-else>
      <header class="league-dashboard__detail-header">
        <button class="league-dashboard__back" type="button" @click="handleBack">
          ← 返回联赛列表
        </button>
        <div class="league-dashboard__detail-title">
          <h2 class="league-dashboard__title">{{ dashboard?.league.league_name ?? '…' }}</h2>
          <p v-if="dashboard" class="league-dashboard__subtitle">
            {{ dashboard.league.country }} · {{ tierLabel(dashboard.league.tier) }} ·
            {{ dashboard.league.season }} 赛季 · 已入库 {{ dashboard.team_count }} 支球队
          </p>
        </div>
      </header>

      <p v-if="error && dashboard === null" class="league-dashboard__error" role="alert">{{ error }}</p>
      <!-- 切换联赛时保留旧数据,仅以提示标注加载状态 -->
      <p v-if="isLoadingDashboard" class="league-dashboard__hint">看板数据加载中…</p>

      <template v-if="dashboard !== null">
        <h3 class="league-dashboard__section-title">积分榜(总榜)</h3>
        <table class="league-dashboard__table">
          <thead>
            <tr>
              <th>排名</th><th>球队</th><th>赛</th><th>胜</th><th>平</th><th>负</th>
              <th>进/失</th><th>净胜</th><th>积分</th><th>胜率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in dashboard.standings" :key="row.team_id">
              <td :class="rankClass(row)">{{ row.ranking ?? '-' }}</td>
              <td class="league-dashboard__team">{{ row.team_name }}</td>
              <td>{{ row.played ?? '-' }}</td>
              <td>{{ row.wins ?? '-' }}</td>
              <td>{{ row.draws ?? '-' }}</td>
              <td>{{ row.losses ?? '-' }}</td>
              <td>{{ row.goals_for ?? '-' }} / {{ row.goals_against ?? '-' }}</td>
              <td>{{ row.goal_diff ?? '-' }}</td>
              <td class="league-dashboard__points">{{ row.points ?? '-' }}</td>
              <td>{{ row.win_rate !== null ? `${row.win_rate.toFixed(0)}%` : '-' }}</td>
            </tr>
            <tr v-if="dashboard.standings.length === 0">
              <td colspan="10" class="league-dashboard__empty">
                该联赛暂无入库球队 · 请先在"数据采集"页同步球队清单
              </td>
            </tr>
          </tbody>
        </table>
        <p class="league-dashboard__hint">
          积分榜来自"数据采集"页同步的球队基本面(总榜);未同步的球队排末尾、战绩为空。
        </p>

        <div class="league-dashboard__matches">
          <div class="league-dashboard__matches-col">
            <h3 class="league-dashboard__section-title">近期赛程</h3>
            <button
              v-for="row in dashboard.upcoming_fixtures"
              :key="row.match_id"
              type="button"
              class="league-dashboard__match"
              @click="openMatch(row.match_id)"
            >
              <span class="league-dashboard__match-num">{{ row.match_num_str || '—' }}</span>
              <span class="league-dashboard__match-time">{{ formatTime(row.match_time) }}</span>
              <span class="league-dashboard__match-teams">
                {{ row.home_team_name }} vs {{ row.away_team_name }}
              </span>
              <span class="league-dashboard__match-status">{{ statusLabel[row.match_status] ?? row.match_status }}</span>
            </button>
            <p v-if="dashboard.upcoming_fixtures.length === 0" class="league-dashboard__empty">
              暂无近期赛程
            </p>
          </div>

          <div class="league-dashboard__matches-col">
            <h3 class="league-dashboard__section-title">近期赛果</h3>
            <button
              v-for="row in dashboard.recent_results"
              :key="row.match_id"
              type="button"
              class="league-dashboard__match"
              @click="openMatch(row.match_id)"
            >
              <span class="league-dashboard__match-num">{{ row.match_num_str || '—' }}</span>
              <span class="league-dashboard__match-time">{{ formatTime(row.match_time) }}</span>
              <span class="league-dashboard__match-teams">
                {{ row.home_team_name }} vs {{ row.away_team_name }}
              </span>
              <span class="league-dashboard__match-score">{{ formatScore(row) }}</span>
            </button>
            <p v-if="dashboard.recent_results.length === 0" class="league-dashboard__empty">
              暂无近期赛果
            </p>
          </div>
        </div>
      </template>

      <p class="league-dashboard__footer">
        点击赛程/赛果行进入比赛详情;数据仅用于分析参考,不构成投注建议。
      </p>
    </template>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.league-dashboard {
  max-width: 1080px;
  margin: 0 auto;

  &__header {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: vars.$spacing-md;
    margin-bottom: vars.$spacing-lg;
  }

  &__detail-header {
    display: flex;
    align-items: flex-start;
    gap: vars.$spacing-lg;
    margin-bottom: vars.$spacing-lg;
  }

  &__detail-title {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
  }

  &__title {
    margin: 0;
  }

  &__subtitle {
    margin: 0;
    color: vars.$color-text-secondary;
  }

  &__back {
    padding: vars.$spacing-xs vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    color: vars.$color-text-secondary;
    cursor: pointer;
    white-space: nowrap;

    &:hover {
      color: vars.$color-primary;
      border-color: vars.$color-primary;
    }
  }

  &__section-title {
    margin: vars.$spacing-lg 0 vars.$spacing-sm;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__hint,
  &__footer {
    margin: vars.$spacing-sm 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  // ---------- 联赛卡片墙 ----------

  &__grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: vars.$spacing-md;
  }

  &__tile {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: vars.$spacing-xs;
    padding: vars.$spacing-lg;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    cursor: pointer;
    text-align: left;
    transition: border-color 0.15s ease, transform 0.15s ease;

    &:hover {
      border-color: vars.$color-primary;
      transform: translateY(-2px);
    }
  }

  &__tile-country {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__tile-name {
    font-size: vars.$font-size-md;
    color: vars.$color-text-primary;
  }

  &__tile-meta {
    display: inline-flex;
    align-items: center;
    gap: vars.$spacing-sm;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__tile-tier {
    padding: vars.$spacing-xs vars.$spacing-sm;
    border-radius: vars.$border-radius;
    background: vars.$color-primary;
    color: #fff;
    font-size: vars.$font-size-sm;
    font-style: normal;
  }

  // ---------- 积分榜 ----------

  &__table {
    width: 100%;
    border-collapse: collapse;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;

    th,
    td {
      padding: vars.$spacing-sm vars.$spacing-md;
      border-bottom: 1px solid vars.$color-border;
      text-align: left;
    }

    th {
      background: vars.$color-surface-hover;
      white-space: nowrap;
    }
  }

  &__points {
    font-weight: 600;
  }

  &__team {
    font-weight: 600;
  }

  &__rank--top {
    color: vars.$color-primary;
    font-weight: 700;
  }

  // ---------- 赛程 / 赛果 ----------

  &__matches {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: vars.$spacing-lg;
    align-items: start;
  }

  &__matches-col {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-sm;
  }

  &__match {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: vars.$spacing-sm;
    padding: vars.$spacing-sm vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    cursor: pointer;
    text-align: left;

    &:hover {
      border-color: vars.$color-primary;
    }
  }

  &__match-num {
    min-width: 52px;
    font-weight: 600;
    font-size: vars.$font-size-sm;
  }

  &__match-time {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    white-space: nowrap;
  }

  &__match-teams {
    flex: 1;
    white-space: nowrap;
  }

  &__match-status,
  &__match-score {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    white-space: nowrap;
  }

  &__match-score {
    font-weight: 700;
    color: vars.$color-text-primary;
  }

  &__empty {
    padding: vars.$spacing-lg;
    border: 1px dashed vars.$color-border;
    border-radius: vars.$border-radius;
    color: vars.$color-text-secondary;
    text-align: center;
  }
}
</style>
