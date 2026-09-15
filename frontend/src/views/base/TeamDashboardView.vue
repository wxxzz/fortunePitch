<script setup lang="ts">
/**
 * 球队看板视图:参考竞彩网球队专栏(sporttery.cn/zqlszl/qdzl)的看板页。
 *
 * - 球队头卡:队徽/全称/简称/所属国家
 * - 战绩统计:按已完赛看板比赛实时计算(支持联赛与主客筛选)
 * - 未来赛事 + 赛程赛果:数据存于 fp_base_team_matches,
 *   由“同步数据”按钮触发竞彩网球队专栏采集
 * - 筛选状态记录在 URL 查询参数(?league=&side=&limit=),刷新后保持
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import KpiCard from '@/components/retrospect/KpiCard.vue'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
import { listTeams, type Team } from '@/api/base/team'
import {
  getTeamDashboard,
  type TeamDashboard,
  type TeamMatch,
} from '@/api/base/teamDashboard'
import { syncTeamDashboard } from '@/api/collector/teamDashboard'
import { useBaseStore } from '@/stores/base'

const route = useRoute()
const router = useRouter()
const baseStore = useBaseStore()
const { leagues, isLoading: isBaseLoading } = storeToRefs(baseStore)

// ---------- 路由参数 ----------

function parseTeamId(value: unknown): number | null {
  const id = Number(value)
  return Number.isInteger(id) && id > 0 ? id : null
}

const teamId = computed(() => parseTeamId(route.params.teamId))
const leagueFilter = computed(() => parseTeamId(route.query.league))
const sideFilter = computed(() => {
  const side = route.query.side
  return side === 'home' || side === 'away' ? side : null
})
const resultLimit = computed(() => {
  const limit = Number(route.query.limit)
  return [10, 20, 50].includes(limit) ? limit : 10
})

function applyQuery(patch: Record<string, string | null>): void {
  const query: Record<string, string> = {}
  if (leagueFilter.value !== null) query.league = String(leagueFilter.value)
  if (sideFilter.value !== null) query.side = sideFilter.value
  if (resultLimit.value !== 10) query.limit = String(resultLimit.value)
  for (const [key, value] of Object.entries(patch)) {
    if (value === null) {
      delete query[key]
    } else {
      query[key] = value
    }
  }
  void router.replace({ query })
}

// ---------- 球队选择(联赛 -> 球队 级联) ----------

const teamsByLeague = ref(new Map<number, Team[]>())
const isTeamsLoading = ref(false)

async function loadTeams(targetLeagueId: number): Promise<void> {
  if (teamsByLeague.value.has(targetLeagueId)) return
  isTeamsLoading.value = true
  try {
    const teams = await listTeams({ league_id: targetLeagueId, limit: 100 })
    teamsByLeague.value = new Map(teamsByLeague.value).set(targetLeagueId, teams)
  } finally {
    isTeamsLoading.value = false
  }
}

// 看板数据(必须在 currentTeam 之前声明,避免即时 watch 触发 TDZ)
const dashboard = ref<TeamDashboard | null>(null)

const currentTeam = computed<Team | null>(() => {
  if (dashboard.value) return dashboard.value.team
  for (const teams of teamsByLeague.value.values()) {
    const found = teams.find((t) => t.team_id === teamId.value)
    if (found) return found
  }
  return null
})

/** 看板球队所在联赛(用于级联选择的联赛默认值) */
const currentLeagueId = computed<number | null>(
  () => currentTeam.value?.league_id ?? null,
)

watch(
  currentLeagueId,
  (nextLeagueId) => {
    if (nextLeagueId !== null) void loadTeams(nextLeagueId)
  },
  { immediate: true },
)

function handleTeamChange(team: Team): void {
  void router.push({
    path: `/base/team-dashboard/${team.team_id}`,
    query: {},
  })
}

function handleLeagueChange(event: Event): void {
  const leagueId = Number((event.target as HTMLSelectElement).value)
  if (Number.isInteger(leagueId) && leagueId > 0) void loadTeams(leagueId)
}

function handleTeamSelectChange(event: Event): void {
  const teamIdValue = Number((event.target as HTMLSelectElement).value)
  const team = (teamsByLeague.value.get(currentLeagueId.value ?? -1) ?? []).find(
    (t) => t.team_id === teamIdValue,
  )
  if (team) handleTeamChange(team)
}

function handleLeagueFilterChange(event: Event): void {
  applyQuery({ league: (event.target as HTMLSelectElement).value || null })
}

function handleLimitChange(event: Event): void {
  applyQuery({ limit: (event.target as HTMLSelectElement).value })
}

// ---------- 看板数据 ----------

const isLoading = ref(false)
const error = ref<string | null>(null)

async function loadDashboard(): Promise<void> {
  if (teamId.value === null) return
  isLoading.value = true
  error.value = null
  try {
    dashboard.value = await getTeamDashboard(teamId.value, {
      uniform_league_id: leagueFilter.value ?? undefined,
      home_away: sideFilter.value ?? undefined,
      future_limit: 10,
      result_limit: resultLimit.value,
    })
  } catch (err) {
    dashboard.value = null
    error.value = err instanceof Error ? err.message : '看板加载失败'
  } finally {
    isLoading.value = false
  }
}

watch(
  [teamId, leagueFilter, sideFilter, resultLimit],
  () => {
    void loadDashboard()
  },
  { immediate: true },
)

// ---------- 数据同步 ----------

const isSyncing = ref(false)
const syncMessage = ref<string | null>(null)

async function handleSync(): Promise<void> {
  if (teamId.value === null || isSyncing.value) return
  isSyncing.value = true
  syncMessage.value = null
  try {
    const result = await syncTeamDashboard({ team_id: teamId.value })
    syncMessage.value =
      `同步完成:未来赛事 ${result.future_count} 场,赛程赛果 ${result.result_count} 场` +
      `(新增 ${result.created_count} / 更新 ${result.updated_count})`
    await loadDashboard()
  } catch (err) {
    syncMessage.value = err instanceof Error ? err.message : '同步失败'
  } finally {
    isSyncing.value = false
  }
}

// ---------- 展示辅助 ----------

const LIMIT_OPTIONS = [10, 20, 50] as const

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number): string => String(n).padStart(2, '0')
  const dateText = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  // 赛果行只有日期(零点),仅展示日期部分
  if (date.getHours() === 0 && date.getMinutes() === 0) return dateText
  return `${dateText} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** logo 允许的 URL 形态:http(s) 或协议相对地址 */
const LOGO_SCHEME_PREFIXES = ['http://', 'https://', '//']

function logoSrc(url: string | null): string | null {
  if (!url) return null
  if (!LOGO_SCHEME_PREFIXES.some((prefix) => url.startsWith(prefix))) return null
  return url.startsWith('//') ? `https:${url}` : url
}

/** 比分展示:半场(全场),缺失时为 - */
function scoreText(match: TeamMatch): string {
  const half =
    match.half_home_score !== null && match.half_away_score !== null
      ? `${match.half_home_score}:${match.half_away_score}`
      : '-'
  const full =
    match.full_home_score !== null && match.full_away_score !== null
      ? `${match.full_home_score}:${match.full_away_score}`
      : '-'
  return `${half}(${full})`
}

const RESULT_LABELS: Record<string, string> = { W: '胜', D: '平', L: '负' }
</script>

<template>
  <section class="team-dashboard">
    <!-- 顶部:返回 + 球队选择 -->
    <header class="team-dashboard__header">
      <h2 class="team-dashboard__title">
        <button
          class="team-dashboard__back"
          type="button"
          @click="void router.push('/base')"
        >
          ‹ 基础档案管理
        </button>
        球队看板
      </h2>
      <div class="team-dashboard__picker">
        <label class="team-dashboard__picker-label" for="league-select">联赛</label>
        <select
          id="league-select"
          class="team-dashboard__select"
          :value="currentLeagueId ?? ''"
          :disabled="isBaseLoading"
          @change="handleLeagueChange"
        >
          <option value="" disabled>请选择联赛</option>
          <option v-for="lg in leagues" :key="lg.league_id" :value="lg.league_id">
            {{ lg.league_name }}
          </option>
        </select>
        <label class="team-dashboard__picker-label" for="team-select">球队</label>
        <select
          id="team-select"
          class="team-dashboard__select"
          :value="teamId ?? ''"
          :disabled="isTeamsLoading || currentLeagueId === null"
          @change="handleTeamSelectChange"
        >
          <option value="" disabled>请选择球队</option>
          <option
            v-for="tm in teamsByLeague.get(currentLeagueId ?? -1) ?? []"
            :key="tm.team_id"
            :value="tm.team_id"
          >
            {{ tm.team_name }}
          </option>
        </select>
      </div>
    </header>

    <p v-if="error" class="team-dashboard__error" role="alert">{{ error }}</p>

    <div v-if="isLoading">
      <SkeletonBlock :height="160" label="看板数据加载中…" />
    </div>

    <template v-else-if="dashboard">
      <!-- 球队头卡 -->
      <div class="team-dashboard__team-card">
        <div class="team-dashboard__team-identity">
          <div class="team-dashboard__logo-wrap">
            <img
              v-if="logoSrc(dashboard.profile?.logo_url ?? null)"
              class="team-dashboard__logo"
              :src="logoSrc(dashboard.profile?.logo_url ?? null) ?? undefined"
              :alt="`${dashboard.team.team_name}队徽`"
            />
            <span v-else class="team-dashboard__logo team-dashboard__logo--fallback">
              {{ dashboard.team.team_name.slice(0, 1) }}
            </span>
          </div>
          <div class="team-dashboard__team-meta">
            <h3 class="team-dashboard__team-name">
              {{ dashboard.profile?.full_name ?? dashboard.team.team_name }}
            </h3>
            <p class="team-dashboard__team-sub">
              简称 {{ dashboard.profile?.abbrev_name ?? dashboard.team.team_name }}
              <template v-if="dashboard.profile?.country_name">
                · {{ dashboard.profile.country_name }}
              </template>
              <template v-if="dashboard.profile">
                · 竞彩网ID {{ dashboard.profile.uniform_team_id }}
              </template>
            </p>
          </div>
        </div>
        <p v-if="dashboard.profile" class="team-dashboard__sync-time">
          数据更新于 {{ formatDateTime(dashboard.profile.update_time) }}
        </p>
      </div>

      <!-- 未同步提示 -->
      <p v-if="dashboard.profile === null" class="team-dashboard__empty-tip" role="status">
        尚未同步该球队的看板数据,点击“同步数据”从竞彩网球队专栏拉取。
      </p>
      <p v-if="syncMessage" class="team-dashboard__sync-message" role="status">
        {{ syncMessage }}
      </p>

      <!-- 筛选与同步 -->
      <div class="team-dashboard__controls">
        <label class="team-dashboard__picker-label" for="league-filter">赛事</label>
        <select
          id="league-filter"
          class="team-dashboard__select"
          :value="leagueFilter ?? ''"
          @change="handleLeagueFilterChange"
        >
          <option value="">全部赛事</option>
          <option
            v-for="lg in dashboard.leagues"
            :key="lg.uniform_league_id ?? lg.league_name ?? ''"
            :value="lg.uniform_league_id ?? ''"
          >
            {{ lg.league_name ?? `联赛${lg.uniform_league_id}` }}
          </option>
        </select>

        <div class="team-dashboard__segmented" role="group" aria-label="主客筛选">
          <button
            v-for="opt in [
              { value: null, label: '全部' },
              { value: 'home', label: '主场' },
              { value: 'away', label: '客场' },
            ]"
            :key="opt.label"
            class="team-dashboard__segment"
            :class="{ 'team-dashboard__segment--active': sideFilter === opt.value }"
            type="button"
            @click="applyQuery({ side: opt.value })"
          >
            {{ opt.label }}
          </button>
        </div>

        <label class="team-dashboard__picker-label" for="limit-select">场次</label>
        <select
          id="limit-select"
          class="team-dashboard__select"
          :value="resultLimit"
          @change="handleLimitChange"
        >
          <option v-for="opt in LIMIT_OPTIONS" :key="opt" :value="opt">
            最近 {{ opt }} 场
          </option>
        </select>

        <button
          class="team-dashboard__sync-btn"
          type="button"
          :disabled="isSyncing"
          @click="handleSync"
        >
          {{ isSyncing ? '同步中…' : '同步数据' }}
        </button>
      </div>

      <!-- 战绩统计 -->
      <div class="team-dashboard__kpis">
        <KpiCard label="场次" :value="String(dashboard.statistics.played)" />
        <KpiCard label="胜" :value="String(dashboard.statistics.wins)" tone="up" />
        <KpiCard label="平" :value="String(dashboard.statistics.draws)" />
        <KpiCard label="负" :value="String(dashboard.statistics.losses)" tone="down" />
        <KpiCard label="进球" :value="String(dashboard.statistics.goals_for)" />
        <KpiCard label="失球" :value="String(dashboard.statistics.goals_against)" />
        <KpiCard
          label="净胜球"
          :value="String(dashboard.statistics.goal_diff)"
          :tone="dashboard.statistics.goal_diff >= 0 ? 'up' : 'down'"
        />
        <KpiCard label="胜率" :value="`${dashboard.statistics.win_rate}%`" tone="up" />
      </div>

      <!-- 未来赛事 -->
      <h3 class="team-dashboard__section-title">未来赛事</h3>
      <table class="team-dashboard__table">
        <thead>
          <tr>
            <th>开赛时间</th><th>轮次</th><th>赛事</th><th>主队</th><th>客队</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="match in dashboard.future_matches" :key="match.uniform_match_id">
            <td>{{ formatDateTime(match.match_time) }}</td>
            <td>{{ match.gameweek ?? '-' }}</td>
            <td>{{ match.league_name ?? '-' }}</td>
            <td
              class="team-dashboard__team-cell"
              :class="{ 'team-dashboard__team-cell--self': match.is_home }"
            >
              {{ match.home_team_name }}
            </td>
            <td
              class="team-dashboard__team-cell"
              :class="{ 'team-dashboard__team-cell--self': !match.is_home }"
            >
              {{ match.away_team_name }}
            </td>
          </tr>
          <tr v-if="dashboard.future_matches.length === 0">
            <td colspan="5" class="team-dashboard__empty">暂无未来赛事数据</td>
          </tr>
        </tbody>
      </table>

      <!-- 赛程赛果 -->
      <h3 class="team-dashboard__section-title">赛程赛果</h3>
      <table class="team-dashboard__table">
        <thead>
          <tr>
            <th>比赛日期</th><th>赛事</th><th>主队</th><th>比分(半/全)</th><th>客队</th><th>结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="match in dashboard.match_results" :key="match.uniform_match_id">
            <td>{{ formatDateTime(match.match_time) }}</td>
            <td>{{ match.league_name ?? '-' }}</td>
            <td
              class="team-dashboard__team-cell"
              :class="{ 'team-dashboard__team-cell--self': match.is_home }"
            >
              {{ match.home_team_name }}
            </td>
            <td class="team-dashboard__score">{{ scoreText(match) }}</td>
            <td
              class="team-dashboard__team-cell"
              :class="{ 'team-dashboard__team-cell--self': !match.is_home }"
            >
              {{ match.away_team_name }}
            </td>
            <td>
              <span
                v-if="match.team_result"
                class="team-dashboard__result"
                :class="`team-dashboard__result--${match.team_result.toLowerCase()}`"
              >
                {{ RESULT_LABELS[match.team_result] ?? match.team_result }}
              </span>
              <span v-else class="team-dashboard__empty">-</span>
            </td>
          </tr>
          <tr v-if="dashboard.match_results.length === 0">
            <td colspan="6" class="team-dashboard__empty">暂无赛果数据</td>
          </tr>
        </tbody>
      </table>
    </template>

    <p v-else-if="teamId === null" class="team-dashboard__empty-tip">
      请从基础档案管理的球队列表点击“看板”进入,或在上方选择球队。
    </p>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.team-dashboard {
  max-width: 1280px;
  margin: 0 auto;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: vars.$spacing-md;
    margin-bottom: vars.$spacing-md;
  }

  &__title {
    margin: 0;
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
  }

  &__back {
    border: none;
    background: transparent;
    padding: 2px vars.$spacing-xs;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-md;
    cursor: pointer;
    border-radius: 4px;

    &:hover {
      background: vars.$color-surface-hover;
      color: vars.$color-text-primary;
    }
  }

  &__picker {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
  }

  &__picker-label {
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
  }

  &__select {
    padding: vars.$spacing-xs vars.$spacing-sm;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    font-size: vars.$font-size-md;
  }

  &__error {
    color: vars.$color-danger;
  }

  // ---------- 球队头卡 ----------

  &__team-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: vars.$spacing-md;
    padding: vars.$spacing-lg;
    margin-bottom: vars.$spacing-md;
    background: linear-gradient(135deg, vars.$color-primary-light, vars.$color-surface 65%);
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__team-identity {
    display: flex;
    align-items: center;
    gap: vars.$spacing-md;
  }

  &__logo-wrap {
    flex-shrink: 0;
  }

  &__logo {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    object-fit: contain;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;

    &--fallback {
      display: flex;
      align-items: center;
      justify-content: center;
      color: vars.$color-primary;
      font-size: vars.$font-size-lg;
      font-weight: 600;
    }
  }

  &__team-name {
    margin: 0;
    font-size: vars.$font-size-lg;
  }

  &__team-sub {
    margin: vars.$spacing-xs 0 0;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
  }

  &__sync-time {
    margin: 0;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
  }

  &__empty-tip {
    padding: vars.$spacing-md;
    background: vars.$color-primary-light;
    border-radius: vars.$border-radius;
    color: vars.$color-primary;
  }

  &__sync-message {
    margin: vars.$spacing-sm 0;
    color: vars.$color-info;
    font-size: vars.$font-size-sm;
  }

  // ---------- 筛选与同步 ----------

  &__controls {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: vars.$spacing-sm;
    margin-bottom: vars.$spacing-md;
  }

  &__segmented {
    display: inline-flex;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    overflow: hidden;
  }

  &__segment {
    padding: vars.$spacing-xs vars.$spacing-sm;
    border: none;
    background: vars.$color-surface;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &--active {
      background: vars.$color-primary;
      color: #ffffff;
    }
  }

  &__sync-btn {
    margin-left: auto;
    padding: vars.$spacing-xs vars.$spacing-lg;
    border: 1px solid vars.$color-primary;
    border-radius: vars.$border-radius;
    background: vars.$color-primary;
    color: #ffffff;
    font-size: vars.$font-size-md;
    cursor: pointer;

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  }

  // ---------- 统计 ----------

  &__kpis {
    display: flex;
    flex-wrap: wrap;
    gap: vars.$spacing-sm;
    margin-bottom: vars.$spacing-md;
  }

  // ---------- 表格 ----------

  &__section-title {
    margin: vars.$spacing-md 0 vars.$spacing-sm;
  }

  &__table {
    width: 100%;
    border-collapse: collapse;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    margin-bottom: vars.$spacing-md;

    th,
    td {
      padding: vars.$spacing-sm vars.$spacing-md;
      border-bottom: 1px solid vars.$color-border;
      text-align: left;
      font-size: vars.$font-size-md;
    }

    th {
      background: vars.$color-surface-hover;
    }
  }

  &__team-cell {
    &--self {
      color: vars.$color-primary;
      font-weight: 600;
    }
  }

  &__score {
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  &__result {
    display: inline-block;
    min-width: 32px;
    padding: 2px vars.$spacing-sm;
    border-radius: 999px;
    font-size: vars.$font-size-sm;
    text-align: center;

    // 红=胜,灰=平,绿=负
    &--w {
      background: rgba(214, 69, 65, 0.12);
      color: vars.$color-positive;
    }

    &--d {
      background: rgba(138, 146, 156, 0.15);
      color: vars.$color-neutral;
    }

    &--l {
      background: rgba(30, 142, 90, 0.12);
      color: vars.$color-negative;
    }
  }

  &__empty {
    color: vars.$color-text-secondary;
    text-align: center;
  }
}
</style>
