<script setup lang="ts">
/**
 * 赛果开奖页:按售卖日展示竞彩各玩法开奖结果与多维度分析。
 *
 * 参考中国竞彩网赛果开奖页(sporttery.cn/jc/zqsgkj)的表格口径:
 * 编号 / 联赛 / 对阵(含让球盘口) / 半场 / 全场 / 5 种玩法开奖结果 / 胜平负 SP。
 * 查询口径与赛事中心一致:按竞彩售卖日范围过滤(最长 31 天),
 * 次日凌晨开赛的比赛归属前一售卖日。
 * 列表下方为多维度分析区:胜平负/让球/总进球/比分/半全场开奖分布
 * 与按联赛的胜负及场均进球,以"赛果开奖 / 多维度分析"选项卡切换。
 * 数据由数据采集页的"同步赛果"写入;页内也提供快捷同步入口
 * (售卖日口径,会同时拉取当日与次日的赛果)。
 */
import { computed, onMounted, ref } from 'vue'
import {
  listMatchResultStats,
  listMatchResults,
  type MatchResultItem,
  type MatchResultStats,
} from '@/api/match/result'
import { syncResults, type ResultSyncResult } from '@/api/collector/match'

/** 内容选项卡:赛果列表 / 多维度分析 */
const CONTENT_TABS = [
  { key: 'results', label: '赛果开奖' },
  { key: 'stats', label: '多维度分析' },
] as const

type ContentTab = (typeof CONTENT_TABS)[number]['key']

/** 售卖日范围上限(天),避免一次同步/统计拉取过多 */
const MAX_RANGE_DAYS = 31

/** 售卖日起止(YYYY-MM-DD),默认今天,与赛事中心的口径一致 */
const startDate = ref(todayIso())
const endDate = ref(todayIso())
const results = ref<MatchResultItem[]>([])
const stats = ref<MatchResultStats | null>(null)
const isLoading = ref(false)
const errorMessage = ref('')
const isSyncing = ref(false)
const syncOutcome = ref<ResultSyncResult | null>(null)
/** 当前激活的内容选项卡 */
const activeTab = ref<ContentTab>('results')

const canQuery = computed(
  () => startDate.value !== '' && endDate.value !== '' && !isLoading.value,
)

const canSubmitResult = computed(
  () =>
    startDate.value !== '' &&
    endDate.value !== '' &&
    !isSyncing.value &&
    !isLoading.value,
)

/** 已开赛场次(非取消)计数,用于汇总条 */
const payoutCount = computed(
  () => results.value.filter((r) => r.full_score !== null).length,
)

/** 多维度分析区的展示卡片(空维度隐藏,热门比分取前 10) */
const statDimensions = computed<
  { title: string; items: MatchResultStats['crs'] }[]
>(() => {
  if (!stats.value) return []
  return [
    { title: '胜平负分布', items: stats.value.had },
    { title: '让球胜平负分布', items: stats.value.hhad },
    { title: '总进球分布', items: stats.value.ttg },
    { title: '热门比分 Top10', items: stats.value.crs.slice(0, 10) },
    { title: '半全场分布', items: stats.value.hafu },
  ].filter((dimension) => dimension.items.length > 0)
})

/** 起止日期间的售卖日列表(含端点);范围非法时返回 null 并提示错误 */
function dateRange(): string[] | null {
  const start = new Date(`${startDate.value}T00:00:00`)
  const end = new Date(`${endDate.value}T00:00:00`)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    errorMessage.value = '售卖日期格式不正确'
    return null
  }
  if (start > end) {
    errorMessage.value = '开始日期不能晚于结束日期'
    return null
  }
  const dayCount = Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1
  if (dayCount > MAX_RANGE_DAYS) {
    errorMessage.value = `时间范围最长 ${MAX_RANGE_DAYS} 天`
    return null
  }
  const days: string[] = []
  for (let offset = 0; offset < dayCount; offset += 1) {
    const cursor = new Date(start)
    cursor.setDate(cursor.getDate() + offset)
    days.push(isoOf(cursor))
  }
  return days
}

async function fetchResults(): Promise<void> {
  if (!canQuery.value) return
  const days = dateRange()
  if (days === null) return
  isLoading.value = true
  errorMessage.value = ''
  try {
    const [list, statsData] = await Promise.all([
      listMatchResults(startDate.value, endDate.value),
      listMatchResultStats(startDate.value, endDate.value),
    ])
    results.value = list
    stats.value = statsData
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : '赛果加载失败'
  } finally {
    isLoading.value = false
  }
}

/** 快捷同步:逐个售卖日拉取当日与次日赛果后刷新列表 */
async function handleSync(): Promise<void> {
  if (!canSubmitResult.value) return
  const days = dateRange()
  if (days === null) return
  isSyncing.value = true
  errorMessage.value = ''
  try {
    const skipped: string[] = []
    let dayResultCount = 0
    let createdCount = 0
    let updatedCount = 0
    let gameUpdatedCount = 0
    let source = ''
    for (const day of days) {
      const outcome = await syncResults(day, 'sale')
      dayResultCount += outcome.day_result_count
      createdCount += outcome.created_count
      updatedCount += outcome.updated_count
      gameUpdatedCount += outcome.game_updated_count
      skipped.push(...outcome.skipped_matches)
      source = outcome.source
    }
    syncOutcome.value = {
      date: `${days[0]} ~ ${days[days.length - 1]}`,
      day_result_count: dayResultCount,
      created_count: createdCount,
      updated_count: updatedCount,
      game_updated_count: gameUpdatedCount,
      skipped_matches: skipped,
      source,
    }
    await fetchResults()
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : '赛果同步失败'
  } finally {
    isSyncing.value = false
  }
}

/** 售卖日展示(MM-DD) */
function formatBusinessDate(iso: string | null): string {
  if (!iso) return '—'
  return iso.slice(5)
}

/** 本地时区的今天(YYYY-MM-DD),避免 UTC 偏移导致日期错位 */
function todayIso(): string {
  const now = new Date()
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** Date 转本地时区 ISO 日期(YYYY-MM-DD) */
function isoOf(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

onMounted(() => {
  void fetchResults()
})
</script>

<template>
  <section class="results">
    <header class="results__header">
      <h2 class="results__title">赛果开奖</h2>
      <p class="results__subtitle">
        数据来源:中国竞彩网赛果开奖页(sporttery.cn/jc/zqsgkj)。
        按售卖日范围展示(最长 31 天,与赛事中心口径一致,
        次日凌晨开赛的比赛归属前一售卖日);比分与玩法结果由同步赛果写入,
        取消场次保留状态不展示比分。
      </p>
    </header>

    <div class="results__toolbar">
      <label class="results__filter">
        <span>售卖日起</span>
        <input
          v-model="startDate"
          class="results__date-input"
          type="date"
          :disabled="isLoading || isSyncing"
          @change="fetchResults"
        />
      </label>
      <label class="results__filter">
        <span>售卖日止</span>
        <input
          v-model="endDate"
          class="results__date-input"
          type="date"
          :disabled="isLoading || isSyncing"
          @change="fetchResults"
        />
      </label>
      <button
        class="results__btn"
        type="button"
        :disabled="!canQuery"
        @click="fetchResults"
      >
        查询
      </button>
      <button
        class="results__btn results__btn--sync"
        type="button"
        :disabled="!canSubmitResult"
        @click="handleSync"
      >
        {{ isSyncing ? '同步中…' : '同步赛果' }}
      </button>
      <span v-if="results.length > 0" class="results__meta">
        共 {{ results.length }} 场 · 已开奖 {{ payoutCount }} 场
      </span>
    </div>

    <p v-if="errorMessage" class="results__error" role="alert">{{ errorMessage }}</p>
    <p v-if="isLoading" class="results__hint">加载中…</p>

    <p
      v-if="syncOutcome && syncOutcome.skipped_matches.length > 0"
      class="results__note"
    >
      ⚠ 以下场次未入库已跳过:{{ syncOutcome.skipped_matches.join(';') }}
    </p>

    <div class="results__tabs" role="tablist">
      <button
        v-for="tab in CONTENT_TABS"
        :key="tab.key"
        class="results__tab"
        :class="{ 'results__tab--active': activeTab === tab.key }"
        type="button"
        role="tab"
        :aria-selected="activeTab === tab.key"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <table v-if="activeTab === 'results' && results.length > 0" class="results__table">
      <thead>
        <tr>
          <th>编号</th>
          <th>售卖日</th>
          <th>联赛</th>
          <th>主队</th>
          <th>比分</th>
          <th>客队</th>
          <th>半场</th>
          <th>胜平负</th>
          <th>让球</th>
          <th>比分</th>
          <th>总进球</th>
          <th>半全场</th>
          <th>主胜 SP</th>
          <th>平 SP</th>
          <th>客胜 SP</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="item in results"
          :key="item.match_id"
          :class="{ 'results__row--cancelled': item.full_score === null }"
        >
          <td class="results__num">{{ item.match_num_str }}</td>
          <td class="results__date">{{ formatBusinessDate(item.business_date) }}</td>
          <td class="results__league">{{ item.league_name }}</td>
          <td class="results__team results__team--home">
            {{ item.home_team_name }}
            <span v-if="item.goal_line" class="results__goal-line">
              ({{ item.goal_line }})
            </span>
          </td>
          <td class="results__score">{{ item.full_score ?? '—' }}</td>
          <td class="results__team">{{ item.away_team_name }}</td>
          <td class="results__half">{{ item.half_score ?? '—' }}</td>
          <td class="results__play">{{ item.had ?? '—' }}</td>
          <td class="results__play">{{ item.hhad ?? '—' }}</td>
          <td class="results__play">{{ item.crs ?? '—' }}</td>
          <td class="results__play">{{ item.ttg ?? '—' }}</td>
          <td class="results__play">{{ item.hafu ?? '—' }}</td>
          <td class="results__sp">{{ item.sp_h?.toFixed(2) ?? '—' }}</td>
          <td class="results__sp">{{ item.sp_d?.toFixed(2) ?? '—' }}</td>
          <td class="results__sp">{{ item.sp_a?.toFixed(2) ?? '—' }}</td>
        </tr>
      </tbody>
    </table>
    <p
      v-else-if="activeTab === 'results' && !isLoading && !errorMessage"
      class="results__empty"
    >
      该日期暂无赛果,请先点击"同步赛果"(场次需已在数据采集页同步赛事)。
    </p>

    <section
      v-if="activeTab === 'stats'"
      class="results__stats"
      aria-label="赛果多维度分析"
    >
      <template v-if="stats && stats.settled > 0">
        <h3 class="results__stats-title">多维度分析</h3>
        <p class="results__stats-meta">
          {{ stats.start_date }} ~ {{ stats.end_date }},已开赛
          {{ stats.settled }} 场<template v-if="stats.cancelled > 0">
            · 取消/无效 {{ stats.cancelled }} 场</template
          >,取消场次不参与统计。
        </p>

        <div v-if="statDimensions.length > 0" class="results__stats-grid">
          <div
            v-for="dimension in statDimensions"
            :key="dimension.title"
            class="results__stat-card"
          >
            <h4 class="results__stat-card-title">{{ dimension.title }}</h4>
            <div
              v-for="item in dimension.items"
              :key="item.label"
              class="results__stat-row"
            >
              <span class="results__stat-label">{{ item.label }}</span>
              <span class="results__stat-bar">
                <span
                  class="results__stat-bar-fill"
                  :style="{ width: `${(item.pct * 100).toFixed(1)}%` }"
                />
              </span>
              <span class="results__stat-count">{{ item.count }} 场</span>
              <span class="results__stat-pct">{{ (item.pct * 100).toFixed(0) }}%</span>
            </div>
          </div>
        </div>

        <div v-if="stats.leagues.length > 0" class="results__stat-card">
          <h4 class="results__stat-card-title">联赛分布</h4>
          <table class="results__stats-table">
            <thead>
              <tr>
                <th>联赛</th>
                <th>已开赛</th>
                <th>主胜</th>
                <th>平</th>
                <th>客胜</th>
                <th>场均进球</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="league in stats.leagues" :key="league.league_name">
                <td class="results__stats-league">{{ league.league_name }}</td>
                <td>{{ league.total }}</td>
                <td>{{ league.home_win }}</td>
                <td>{{ league.draw }}</td>
                <td>{{ league.away_win }}</td>
                <td class="results__sp">
                  {{ league.avg_total_goals?.toFixed(2) ?? '—' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <p v-else-if="!isLoading && !errorMessage" class="results__empty">
        该日期暂无已开赛赛果,可先"同步赛果"后再查看多维度分析。
      </p>
    </section>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.results {
  max-width: 1280px;
  margin: 0 auto;

  &__header {
    margin-bottom: vars.$spacing-lg;
  }

  &__title {
    margin: 0 0 vars.$spacing-xs;
  }

  &__subtitle {
    margin: 0;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-md;
  }

  &__toolbar {
    display: flex;
    align-items: flex-end;
    gap: vars.$spacing-md;
    padding: vars.$spacing-md vars.$spacing-lg;
    margin-bottom: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    flex-wrap: wrap;
  }

  &__filter {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;

    input {
      padding: vars.$spacing-xs vars.$spacing-sm;
      border: 1px solid vars.$color-border;
      border-radius: vars.$border-radius;
      background: #fff;
    }
  }

  &__btn {
    padding: vars.$spacing-sm vars.$spacing-md;
    border: none;
    border-radius: vars.$border-radius;
    background: vars.$color-primary;
    color: #fff;
    font-size: vars.$font-size-md;
    cursor: pointer;
    transition: background 0.2s;

    &:hover:not(:disabled) {
      background: #0f5132;
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    &--sync {
      background: vars.$color-surface;
      border: 1px solid vars.$color-primary;
      color: vars.$color-primary;

      &:hover:not(:disabled) {
        background: vars.$color-primary-light;
      }
    }
  }

  &__meta {
    margin-left: auto;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__hint {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__note {
    padding: vars.$spacing-sm vars.$spacing-md;
    border-radius: vars.$border-radius;
    background: rgba(212, 136, 6, 0.1);
    color: vars.$color-warning;
    font-size: vars.$font-size-sm;
  }

  &__empty {
    padding: vars.$spacing-lg;
    text-align: center;
    color: vars.$color-text-secondary;
    background: vars.$color-surface;
    border: 1px dashed vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__table {
    width: 100%;
    border-collapse: collapse;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    overflow: hidden;
    font-size: vars.$font-size-md;

    th,
    td {
      padding: vars.$spacing-sm vars.$spacing-sm;
      border-bottom: 1px solid vars.$color-border;
      text-align: center;
      white-space: nowrap;
    }

    th {
      background: vars.$color-surface-hover;
      color: vars.$color-text-secondary;
      font-size: vars.$font-size-sm;
      font-weight: 600;
    }

    tbody tr:hover {
      background: vars.$color-surface-hover;
    }
  }

  &__row--cancelled {
    color: vars.$color-text-secondary;
    background: vars.$color-bg;
  }

  &__num {
    font-weight: 600;
  }

  &__date {
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
    white-space: nowrap;
  }

  &__league {
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
  }

  &__team {
    font-weight: 600;

    &--home {
      text-align: right;
    }
  }

  &__goal-line {
    color: vars.$color-info;
    font-size: vars.$font-size-sm;
  }

  &__score {
    font-weight: 700;
    color: vars.$color-positive;
  }

  &__half {
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
  }

  &__play {
    font-weight: 600;
    color: vars.$color-positive;
  }

  &__row--cancelled .results__play,
  &__row--cancelled .results__score {
    color: vars.$color-text-secondary;
    font-weight: 400;
  }

  &__sp {
    font-variant-numeric: tabular-nums;
  }

  &__tabs {
    display: flex;
    gap: vars.$spacing-xs;
    margin-bottom: vars.$spacing-md;
    border-bottom: 2px solid vars.$color-border;
  }

  &__tab {
    display: flex;
    align-items: center;
    gap: vars.$spacing-xs;
    padding: vars.$spacing-sm vars.$spacing-md;
    border: none;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    background: transparent;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-md;
    cursor: pointer;
    transition: color 0.15s ease, border-color 0.15s ease;

    &:hover {
      color: vars.$color-primary;
    }

    &--active {
      border-bottom-color: vars.$color-primary;
      color: vars.$color-primary;
      font-weight: 600;
    }
  }

  &__stats {
    margin-top: 0;
  }

  &__stats-title {
    margin: 0 0 vars.$spacing-xs;
  }

  &__stats-meta {
    margin: 0 0 vars.$spacing-md;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: vars.$spacing-md;
    margin-bottom: vars.$spacing-md;
  }

  &__stat-card {
    padding: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__stat-card-title {
    margin: 0 0 vars.$spacing-sm;
    font-size: vars.$font-size-md;
  }

  &__stat-row {
    display: grid;
    grid-template-columns: 64px 1fr 56px 44px;
    align-items: center;
    gap: vars.$spacing-sm;
    padding: 2px 0;
    font-size: vars.$font-size-sm;
  }

  &__stat-label {
    font-weight: 600;
  }

  &__stat-bar {
    height: 8px;
    border-radius: 4px;
    background: vars.$color-surface-hover;
    overflow: hidden;
  }

  &__stat-bar-fill {
    display: block;
    height: 100%;
    border-radius: 4px;
    background: vars.$color-primary;
  }

  &__stat-count {
    color: vars.$color-text-secondary;
    text-align: right;
  }

  &__stat-pct {
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    text-align: right;
  }

  &__stats-table {
    width: 100%;
    border-collapse: collapse;
    font-size: vars.$font-size-md;

    th,
    td {
      padding: vars.$spacing-xs vars.$spacing-sm;
      border-bottom: 1px solid vars.$color-border;
      text-align: center;
      white-space: nowrap;
    }

    th {
      color: vars.$color-text-secondary;
      font-size: vars.$font-size-sm;
      font-weight: 600;
    }

    th:first-child,
    td:first-child {
      text-align: left;
    }
  }

  &__stats-league {
    font-weight: 600;
  }
}
</style>
