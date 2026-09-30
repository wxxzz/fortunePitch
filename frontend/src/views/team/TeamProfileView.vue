<script setup lang="ts">
/**
 * 页面C:球队全景档案(Team Profile)。
 *
 * 数据源(均为真实采集/派生数据,缺失时降级提示,不使用演示数据):
 * - 球队档案 + 赛季战绩:fp_base_teams / fp_base_team_fundamentals(积分榜)
 * - 近期赛果:fp_base_team_matches(球队看板,由数据采集页同步)
 * - Elo 评分:fp_analytics_team_ratings(由数据采集页「重算 Elo 评分」重建)
 * - AI 维度分析:fp_llm_team_analyses(进攻/防守/主客场等六维度研判,可手动生成)
 */
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useBaseStore } from '@/stores/base'
import { getTeamFundamentals, type Team, type TeamFundamentals } from '@/api/base/team'
import {
  getTeamDashboard,
  type TeamDashboard,
} from '@/api/base/teamDashboard'
import {
  getLatestTeamAnalysis,
  runTeamAnalysis,
  type TeamAnalysisRating,
  type TeamLlmAnalysis,
} from '@/api/base/teamAnalysis'
import { getTeamRating, type TeamRating } from '@/api/analytics/teamRatings'
import TeamTimeline, {
  type TeamTimelineItem,
} from '@/components/team/TeamTimeline.vue'

const baseStore = useBaseStore()
const { leagues, teams } = storeToRefs(baseStore)

onMounted(() => {
  void baseStore.fetchAll()
})

// ---------- 球队选择(按联赛分组) ----------

const selectedTeamId = ref<number | null>(null)

const teamsByLeague = computed(() => {
  const map = new Map<number, Team[]>()
  for (const team of teams.value) {
    map.set(team.league_id, [...(map.get(team.league_id) ?? []), team])
  }
  return map
})

const selectedTeam = computed<Team | null>(() => {
  if (dashboard.value) return dashboard.value.team
  return (
    teams.value.find((t) => t.team_id === selectedTeamId.value) ?? null
  )
})

// ---------- 档案数据加载 ----------

const dashboard = ref<TeamDashboard | null>(null)
const fundamentals = ref<TeamFundamentals | null>(null)
const rating = ref<TeamRating | null>(null)
const analysis = ref<TeamLlmAnalysis | null>(null)
const isGenerating = ref(false)
const analysisError = ref<string | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)

/** 近期赛果展示条数(看板赛果,时间倒序) */
const RESULT_LIMIT = 10

/** 最近一次加载的序号:快速切换球队时丢弃过期响应,避免旧数据覆盖新选择 */
let loadSequence = 0

async function loadTeamProfile(teamId: number): Promise<void> {
  const sequence = ++loadSequence
  isLoading.value = true
  error.value = null
  dashboard.value = null
  fundamentals.value = null
  rating.value = null
  analysis.value = null
  analysisError.value = null
  isGenerating.value = false
  try {
    // 四路独立加载:看板失败视为页面错误;基本面 / Elo / AI 分析未生成(404)仅降级为缺失
    const [dashResult, fundResult, ratingResult, analysisResult] =
      await Promise.allSettled([
        getTeamDashboard(teamId, { future_limit: 5, result_limit: RESULT_LIMIT }),
        getTeamFundamentals(teamId),
        getTeamRating(teamId),
        getLatestTeamAnalysis(teamId),
      ])
    if (sequence !== loadSequence) return
    if (dashResult.status === 'rejected') {
      throw dashResult.reason
    }
    dashboard.value = dashResult.value
    fundamentals.value =
      fundResult.status === 'fulfilled' ? fundResult.value : null
    rating.value =
      ratingResult.status === 'fulfilled' ? ratingResult.value : null
    analysis.value =
      analysisResult.status === 'fulfilled' ? analysisResult.value : null
  } catch (err) {
    if (sequence !== loadSequence) return
    dashboard.value = null
    error.value = err instanceof Error ? err.message : '球队档案加载失败'
  } finally {
    if (sequence === loadSequence) {
      isLoading.value = false
    }
  }
}

watch(selectedTeamId, (teamId) => {
  if (teamId !== null) void loadTeamProfile(teamId)
})

/** 数据缺口提示(引导去数据采集页补数据) */
const gapHints = computed<string[]>(() => {
  if (selectedTeamId.value === null) return []
  const hints: string[] = []
  if (dashboard.value?.profile == null) {
    hints.push('球队看板档案未同步:近期赛果与未来赛事可能缺失,请到数据采集页同步该队看板')
  }
  if (fundamentals.value === null) {
    hints.push('积分榜基本面未同步:赛季战绩将无法展示,请到数据采集页同步该队基本面')
  }
  if (rating.value === null) {
    hints.push('Elo 评分未重算:请到数据采集页触发「重算 Elo 评分」')
  }
  return hints
})

// ---------- 概览指标 ----------

const overviewMetrics = computed(() => [
  {
    label: 'Elo 评分',
    value: rating.value ? String(Math.round(rating.value.rating)) : '--',
  },
  {
    label: '联赛排名',
    value:
      fundamentals.value?.ranking != null
        ? `第 ${fundamentals.value.ranking} 名`
        : '--',
  },
  {
    label: '赛季积分',
    value:
      fundamentals.value?.points != null
        ? String(fundamentals.value.points)
        : '--',
  },
  {
    label: '赛季胜率',
    value:
      fundamentals.value?.win_rate != null
        ? `${fundamentals.value.win_rate.toFixed(1)}%`
        : '--',
  },
])

// ---------- 赛季战绩(积分榜) ----------

/** 赛季战绩表单行(总/主/客三维度) */
interface SeasonRow {
  key: string
  label: string
  played: number | null
  wins: number | null
  draws: number | null
  losses: number | null
  goalsFor: number | null
  goalsAgainst: number | null
  goalDiff: number | null
  points: number | null
  winRate: number | null
}

const seasonRows = computed<SeasonRow[]>(() => {
  const f = fundamentals.value
  if (f === null) return []
  return [
    {
      key: 'total',
      label: '赛季总战绩',
      played: f.played,
      wins: f.wins,
      draws: f.draws,
      losses: f.losses,
      goalsFor: f.goals_for,
      goalsAgainst: f.goals_against,
      goalDiff: f.goal_diff,
      points: f.points,
      winRate: f.win_rate,
    },
    {
      key: 'home',
      label: '主场',
      played: f.home_played,
      wins: f.home_wins,
      draws: f.home_draws,
      losses: f.home_losses,
      goalsFor: f.home_goals_for,
      goalsAgainst: f.home_goals_against,
      goalDiff: f.home_goal_diff,
      points: f.home_points,
      winRate: f.home_win_rate,
    },
    {
      key: 'away',
      label: '客场',
      played: f.away_played,
      wins: f.away_wins,
      draws: f.away_draws,
      losses: f.away_losses,
      goalsFor: f.away_goals_for,
      goalsAgainst: f.away_goals_against,
      goalDiff: f.away_goal_diff,
      points: f.away_points,
      winRate: f.away_win_rate,
    },
  ]
})

/** 单元格展示:空值显示 - */
const cell = (value: number | null): string =>
  value !== null ? String(value) : '-'

/** 胜率列展示:空值显示 - */
const rateCell = (value: number | null): string =>
  value !== null ? `${value.toFixed(1)}%` : '-'

// ---------- 近期赛果(看板) ----------

/** 已完赛看板行(有完赛比分与结果) */
const finishedResults = computed(() =>
  (dashboard.value?.match_results ?? []).filter(
    (m) =>
      m.team_result !== null &&
      m.full_home_score !== null &&
      m.full_away_score !== null,
  ),
)

const timelineItems = computed<TeamTimelineItem[]>(() =>
  finishedResults.value.slice(0, RESULT_LIMIT).map((m) => {
    const isHome = m.is_home
    return {
      opponent: isHome ? m.away_team_name : m.home_team_name,
      isHome,
      goalsFor: (isHome ? m.full_home_score : m.full_away_score) ?? 0,
      goalsAgainst: (isHome ? m.full_away_score : m.full_home_score) ?? 0,
      date: formatDate(m.match_time),
    }
  }),
)

/** 近期赛果串(时间倒序,如 "WWDLLW") */
const formResults = computed(() =>
  finishedResults.value
    .slice(0, RESULT_LIMIT)
    .map((m) => m.team_result as 'W' | 'D' | 'L'),
)

const formCounts = computed(() => {
  const counts = { wins: 0, draws: 0, losses: 0 }
  for (const result of formResults.value) {
    if (result === 'W') counts.wins += 1
    else if (result === 'D') counts.draws += 1
    else counts.losses += 1
  }
  return counts
})

/** 当前连胜/连平/连败标签(从最近一场往前数) */
const streakLabel = computed<string | null>(() => {
  const results = formResults.value
  if (results.length === 0) return null
  const first = results[0]
  let count = 1
  while (count < results.length && results[count] === first) count += 1
  const labels = { W: '连胜', D: '连平', L: '连败' } as const
  return `${count}${labels[first]}`
})

/** 本地时区日期文本 YYYY-MM-DD */
function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

// ---------- 队徽 ----------

/** logo 允许的 URL 形态:http(s) 或协议相对地址 */
const LOGO_SCHEME_PREFIXES = ['http://', 'https://', '//']

const logoSrc = computed<string | null>(() => {
  const url = dashboard.value?.profile?.logo_url ?? null
  if (!url) return null
  if (!LOGO_SCHEME_PREFIXES.some((prefix) => url.startsWith(prefix))) return null
  return url.startsWith('//') ? `https:${url}` : url
})

// ---------- AI 维度分析 ----------

/** 评级徽章文案:strong=红(强)/ average=灰(中)/ weak=绿(弱) */
const RATING_LABELS: Record<TeamAnalysisRating, string> = {
  strong: '强',
  average: '中',
  weak: '弱',
}

/** 生成时间展示(本地时区) */
const analysisTime = computed(() => {
  const createdAt = analysis.value?.created_at
  return createdAt !== undefined ? formatDateTime(createdAt) : ''
})

/** 数据缺口时提示:分析仍可生成,但结论会声明数据不足 */
const analysisGapHint = computed<string | null>(() => {
  if (fundamentals.value === null || dashboard.value?.profile == null) {
    return '积分榜或看板数据不完整:分析仍可生成,但结论会声明数据不足,建议先到数据采集页补全数据'
  }
  return null
})

/** 手动生成一次 AI 分析;完成或失败都会刷新到面板,切换球队时丢弃过期响应 */
async function generateAnalysis(): Promise<void> {
  const teamId = selectedTeamId.value
  if (teamId === null || isGenerating.value) return
  const sequence = loadSequence
  isGenerating.value = true
  analysisError.value = null
  try {
    const result = await runTeamAnalysis(teamId)
    if (sequence !== loadSequence) return
    analysis.value = result
  } catch (err) {
    if (sequence !== loadSequence) return
    analysisError.value = err instanceof Error ? err.message : 'AI 分析生成失败'
  } finally {
    if (sequence === loadSequence) {
      isGenerating.value = false
    }
  }
}

/** 本地时区日期时间文本 YYYY-MM-DD HH:mm */
function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${formatDate(value)} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
</script>

<template>
  <section class="team-profile">
    <div class="team-profile__header">
      <h2 class="team-profile__title">球队全景档案</h2>
      <label class="team-profile__selector">
        <span>选择球队</span>
        <select v-model.number="selectedTeamId">
          <option :value="null">请选择</option>
          <optgroup
            v-for="league in leagues"
            :key="league.league_id"
            :label="league.league_name"
          >
            <option
              v-for="team in teamsByLeague.get(league.league_id) ?? []"
              :key="team.team_id"
              :value="team.team_id"
            >
              {{ team.team_name }}
            </option>
          </optgroup>
        </select>
      </label>
    </div>

    <p v-if="!selectedTeam" class="team-profile__hint">请先选择一支球队查看全景档案。</p>
    <p v-if="error" class="team-profile__error" role="alert">{{ error }}</p>
    <p v-if="isLoading" class="team-profile__hint">档案加载中…</p>

    <template v-if="selectedTeam && !isLoading && !error">
      <!-- 数据缺口提示 -->
      <ul v-if="gapHints.length > 0" class="team-profile__gaps">
        <li v-for="hint in gapHints" :key="hint">{{ hint }}</li>
      </ul>

      <!-- 顶部概览:身份 + 核心指标 -->
      <header class="team-profile__overview">
        <div class="team-profile__identity">
          <img
            v-if="logoSrc"
            class="team-profile__logo"
            :src="logoSrc"
            :alt="`${selectedTeam.team_name}队徽`"
          />
          <span v-else class="team-profile__badge">{{ selectedTeam.team_name.slice(0, 2) }}</span>
          <div>
            <strong class="team-profile__name">{{ selectedTeam.team_name }}</strong>
            <span class="team-profile__meta">
              {{ selectedTeam.formation ?? '阵型未知' }} ·
              主场 {{ selectedTeam.stadium ?? '未知' }} ·
              主教练 {{ selectedTeam.manager ?? '未知' }}
            </span>
          </div>
        </div>
        <div class="team-profile__metrics">
          <div v-for="metric in overviewMetrics" :key="metric.label" class="team-profile__metric">
            <span class="team-profile__metric-label">{{ metric.label }}</span>
            <strong class="team-profile__metric-value">{{ metric.value }}</strong>
          </div>
        </div>
      </header>

      <div class="team-profile__body">
        <!-- 左侧:赛季战绩(积分榜) -->
        <div class="team-profile__panel">
          <h3 class="team-profile__section-title">赛季战绩(积分榜)</h3>
          <table v-if="seasonRows.length > 0" class="team-profile__table">
            <thead>
              <tr>
                <th>维度</th><th>赛</th><th>胜</th><th>平</th><th>负</th>
                <th>进</th><th>失</th><th>净胜</th><th>积分</th><th>胜率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in seasonRows" :key="row.key">
                <td class="team-profile__table-dim">{{ row.label }}</td>
                <td>{{ cell(row.played) }}</td>
                <td class="team-profile__table--pos">{{ cell(row.wins) }}</td>
                <td>{{ cell(row.draws) }}</td>
                <td class="team-profile__table--neg">{{ cell(row.losses) }}</td>
                <td>{{ cell(row.goalsFor) }}</td>
                <td>{{ cell(row.goalsAgainst) }}</td>
                <td>{{ cell(row.goalDiff) }}</td>
                <td>{{ cell(row.points) }}</td>
                <td>{{ rateCell(row.winRate) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="team-profile__hint">积分榜基本面未同步,暂无赛季战绩数据。</p>
        </div>

        <!-- 右侧:近期赛果(看板) -->
        <div class="team-profile__panel">
          <h3 class="team-profile__section-title">近期赛果</h3>
          <template v-if="formResults.length > 0">
            <div class="team-profile__form">
              <span class="team-profile__form-dots">
                <span
                  v-for="(result, index) in formResults"
                  :key="index"
                  class="team-profile__form-dot"
                  :class="`team-profile__form-dot--${result.toLowerCase()}`"
                >
                  {{ result }}
                </span>
              </span>
              <span class="team-profile__form-count">
                {{ formCounts.wins }}胜{{ formCounts.draws }}平{{ formCounts.losses }}负
              </span>
              <span v-if="streakLabel" class="team-profile__streak">{{ streakLabel }}</span>
            </div>
            <TeamTimeline :items="timelineItems" />
          </template>
          <p v-else class="team-profile__hint">看板赛果未同步,暂无近期赛果数据。</p>
        </div>
      </div>

      <!-- AI 维度分析(全宽) -->
      <div class="team-profile__panel team-profile__panel--full">
        <div class="team-profile__analysis-head">
          <h3 class="team-profile__section-title">AI 维度分析</h3>
          <button
            class="team-profile__generate"
            type="button"
            :disabled="isGenerating"
            @click="generateAnalysis"
          >
            {{ isGenerating ? '分析生成中…' : '生成 AI 分析' }}
          </button>
        </div>

        <p v-if="analysisGapHint" class="team-profile__hint">{{ analysisGapHint }}</p>
        <p v-if="analysisError" class="team-profile__error" role="alert">{{ analysisError }}</p>

        <template v-if="analysis">
          <p class="team-profile__summary">{{ analysis.summary }}</p>
          <div class="team-profile__dims">
            <article
              v-for="dim in analysis.dimensions"
              :key="dim.dim_id"
              class="team-profile__dim"
            >
              <header class="team-profile__dim-head">
                <strong>{{ dim.title }}</strong>
                <span
                  class="team-profile__rating"
                  :class="`team-profile__rating--${dim.rating}`"
                >
                  {{ RATING_LABELS[dim.rating] }}
                </span>
              </header>
              <p class="team-profile__dim-content">{{ dim.content }}</p>
            </article>
          </div>
          <div v-if="analysis.risks.length > 0" class="team-profile__risks">
            <strong>风险提示</strong>
            <ul>
              <li v-for="risk in analysis.risks" :key="risk">{{ risk }}</li>
            </ul>
          </div>
          <p class="team-profile__analysis-meta">
            {{ analysis.provider }} / {{ analysis.model }} · 生成于 {{ analysisTime }} ·
            结论为数据研判,不构成投注建议
          </p>
        </template>
        <p v-else-if="!isGenerating && !analysisError" class="team-profile__hint">
          尚未生成过 AI 分析,点击「生成 AI 分析」获得进攻 / 防守 / 主客场等多维度研判。
        </p>
      </div>
    </template>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.team-profile {
  max-width: 1080px;
  margin: 0 auto;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: vars.$spacing-md;
  }

  &__title {
    margin: 0;
  }

  &__selector {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;

    select {
      min-width: 200px;
      padding: vars.$spacing-xs vars.$spacing-sm;
      border: 1px solid vars.$color-border;
      border-radius: vars.$border-radius;
      background: #fff;
    }
  }

  &__hint {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__gaps {
    margin: 0 0 vars.$spacing-md;
    padding: vars.$spacing-sm vars.$spacing-md;
    background: vars.$color-primary-light;
    border-radius: vars.$border-radius;
    color: vars.$color-primary;
    font-size: vars.$font-size-sm;

    li {
      list-style: none;
    }
  }

  &__overview {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: vars.$spacing-lg;
    padding: vars.$spacing-lg;
    margin-bottom: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    flex-wrap: wrap;
  }

  &__identity {
    display: flex;
    align-items: center;
    gap: vars.$spacing-md;
  }

  &__logo,
  &__badge {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    object-fit: contain;
    background: vars.$color-surface-hover;
    border: 1px solid vars.$color-border;
    flex-shrink: 0;
  }

  &__badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: vars.$color-primary;
    color: #fff;
    font-size: vars.$font-size-lg;
    font-weight: 700;
  }

  &__name {
    display: block;
    font-size: vars.$font-size-lg;
  }

  &__meta {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__metrics {
    display: flex;
    gap: vars.$spacing-lg;
  }

  &__metric {
    display: flex;
    flex-direction: column;
    align-items: center;

    &-label {
      font-size: vars.$font-size-sm;
      color: vars.$color-text-secondary;
    }

    &-value {
      font-size: vars.$font-size-md;
    }
  }

  &__body {
    display: flex;
    gap: vars.$spacing-lg;
    align-items: flex-start;
    flex-wrap: wrap;
  }

  &__panel {
    flex: 1;
    min-width: 340px;
    padding: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;

    &--full {
      width: 100%;
      min-width: 100%;
      margin-top: vars.$spacing-lg;
    }
  }

  &__section-title {
    margin: 0 0 vars.$spacing-sm;
    font-size: vars.$font-size-md;
  }

  &__table {
    width: 100%;
    border-collapse: collapse;
    font-variant-numeric: tabular-nums;

    th,
    td {
      padding: vars.$spacing-xs vars.$spacing-sm;
      border-bottom: 1px solid vars.$color-border;
      text-align: center;
      font-size: vars.$font-size-sm;
    }

    th {
      color: vars.$color-text-secondary;
      font-weight: 600;
    }

    &-dim {
      text-align: left;
      font-weight: 600;
    }

    // 红=正向(胜),绿=负向(负)
    &--pos {
      color: vars.$color-positive;
    }

    &--neg {
      color: vars.$color-negative;
    }
  }

  &__form {
    display: flex;
    align-items: center;
    gap: vars.$spacing-md;
    margin-bottom: vars.$spacing-sm;
    flex-wrap: wrap;
  }

  &__form-dots {
    display: inline-flex;
    gap: vars.$spacing-xs;
  }

  &__form-dot {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    color: #fff;
    font-size: 12px;
    font-weight: 700;

    // 红=胜,灰=平,绿=负
    &--w {
      background: vars.$color-positive;
    }

    &--d {
      background: vars.$color-neutral;
    }

    &--l {
      background: vars.$color-negative;
    }
  }

  &__form-count {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__streak {
    padding: 2px vars.$spacing-sm;
    border-radius: 999px;
    background: vars.$color-primary-light;
    color: vars.$color-primary;
    font-size: vars.$font-size-sm;
  }

  &__analysis-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: vars.$spacing-md;
    margin-bottom: vars.$spacing-sm;
    flex-wrap: wrap;

    .team-profile__section-title {
      margin-bottom: 0;
    }
  }

  &__generate {
    padding: vars.$spacing-xs vars.$spacing-md;
    border: none;
    border-radius: vars.$border-radius;
    background: vars.$color-primary;
    color: #fff;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &:disabled {
      background: vars.$color-neutral;
      cursor: not-allowed;
    }
  }

  &__summary {
    margin: vars.$spacing-sm 0;
    font-size: vars.$font-size-md;
    line-height: 1.6;
  }

  &__dims {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: vars.$spacing-md;
    margin: vars.$spacing-md 0;
  }

  &__dim {
    padding: vars.$spacing-sm vars.$spacing-md;
    background: vars.$color-surface-hover;
    border-radius: vars.$border-radius;

    &-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    &-content {
      margin: vars.$spacing-xs 0 0;
      font-size: vars.$font-size-sm;
      color: vars.$color-text-secondary;
      line-height: 1.6;
    }
  }

  // 评级徽章:红=强,灰=中,绿=弱
  &__rating {
    padding: 2px vars.$spacing-sm;
    border-radius: 999px;
    color: #fff;
    font-size: vars.$font-size-sm;

    &--strong {
      background: vars.$color-positive;
    }

    &--average {
      background: vars.$color-neutral;
    }

    &--weak {
      background: vars.$color-negative;
    }
  }

  &__risks {
    font-size: vars.$font-size-sm;

    ul {
      margin: vars.$spacing-xs 0 0;
      padding-left: vars.$spacing-md;
      color: vars.$color-text-secondary;
    }
  }

  &__analysis-meta {
    margin: vars.$spacing-sm 0 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }
}
</style>
