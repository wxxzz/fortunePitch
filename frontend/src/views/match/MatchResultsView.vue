<script setup lang="ts">
/**
 * 赛果开奖页:按售卖日展示竞彩各玩法开奖结果。
 *
 * 参考中国竞彩网赛果开奖页(sporttery.cn/jc/zqsgkj)的表格口径:
 * 编号 / 联赛 / 对阵(含让球盘口) / 半场 / 全场 / 5 种玩法开奖结果 / 胜平负 SP。
 * 查询口径与赛事中心一致:按竞彩售卖日过滤,次日凌晨开赛的比赛归属前一售卖日。
 * 数据由数据采集页的"同步赛果"写入;页内也提供快捷同步入口
 * (售卖日口径,会同时拉取当日与次日的赛果)。
 */
import { computed, onMounted, ref } from 'vue'
import {
  listMatchResults,
  type MatchResultItem,
} from '@/api/match/result'
import { syncResults, type ResultSyncResult } from '@/api/collector/match'

/** 售卖日期(YYYY-MM-DD),默认今天,与赛事中心的口径一致 */
const selectedDate = ref(todayIso())
const results = ref<MatchResultItem[]>([])
const isLoading = ref(false)
const errorMessage = ref('')
const isSyncing = ref(false)
const syncOutcome = ref<ResultSyncResult | null>(null)

const canQuery = computed(() => selectedDate.value !== '' && !isLoading.value)

const canSubmitResult = computed(
  () => selectedDate.value !== '' && !isSyncing.value && !isLoading.value,
)

/** 已开赛场次(非取消)计数,用于汇总条 */
const payoutCount = computed(
  () => results.value.filter((r) => r.full_score !== null).length,
)

async function fetchResults(): Promise<void> {
  if (!canQuery.value) return
  isLoading.value = true
  errorMessage.value = ''
  try {
    results.value = await listMatchResults(selectedDate.value)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : '赛果加载失败'
  } finally {
    isLoading.value = false
  }
}

/** 快捷同步:按售卖日拉取当日与次日赛果后刷新列表 */
async function handleSync(): Promise<void> {
  if (!canSubmitResult.value) return
  isSyncing.value = true
  errorMessage.value = ''
  try {
    syncOutcome.value = await syncResults(selectedDate.value, 'sale')
    await fetchResults()
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : '赛果同步失败'
  } finally {
    isSyncing.value = false
  }
}

/** 本地时区的今天(YYYY-MM-DD),避免 UTC 偏移导致日期错位 */
function todayIso(): string {
  const now = new Date()
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
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
        按售卖日展示(与赛事中心口径一致,次日凌晨开赛的比赛归属前一售卖日);
        比分与玩法结果由同步赛果写入,取消场次保留状态不展示比分。
      </p>
    </header>

    <div class="results__toolbar">
      <label class="results__filter">
        <span>售卖日期</span>
        <input
          v-model="selectedDate"
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

    <table v-if="results.length > 0" class="results__table">
      <thead>
        <tr>
          <th>编号</th>
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
    <p v-else-if="!isLoading && !errorMessage" class="results__empty">
      该日期暂无赛果,请先点击"同步赛果"(场次需已在数据采集页同步赛事)。
    </p>
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
}
</style>
