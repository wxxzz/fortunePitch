<script setup lang="ts">
/**
 * AI 分析结果查询页:按售卖日 + 置信度查询已保存的 AI 分玩法推荐。
 *
 * 数据来源为赛事中心深度分析页"AI 分析"落库的结果
 * (每场比赛仅取最近一次分析,历史多份时以最新为准);
 * 五种玩法选项卡(胜平负/让球胜平负/比分/总进球/半全场)展示
 * 比赛场次编号、主客队、玩法推荐与备选(附最新赔率,如 主胜@1.63)、
 * 赛果开奖与命中比对、置信度与依据。
 * 结果为数据分析参考,不构成投注建议。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  listLlmRecommendations,
  type LlmRecommendationRow,
} from '@/api/match/analysis'

const router = useRouter()

/** 五种玩法选项卡(编码与后端口径一致) */
const PLAY_TABS = [
  { code: 'HAD', label: '胜平负' },
  { code: 'HHAD', label: '让球胜平负' },
  { code: 'CRS', label: '比分' },
  { code: 'TTG', label: '总进球' },
  { code: 'HAFU', label: '半全场' },
] as const

/** 售卖日期(YYYY-MM-DD),默认今天,与赛事中心口径一致 */
const selectedDate = ref(todayIso())
/** 置信度下限(0~1),默认 0.60 */
const minConfidence = ref<number>(0.6)
/** 当前激活的玩法选项卡 */
const activePlayCode = ref<string>('HAD')

const rows = ref<LlmRecommendationRow[]>([])
const isLoading = ref(false)
const errorMessage = ref('')

const canQuery = computed(() => selectedDate.value !== '' && !isLoading.value)

/** 各玩法选项卡的推荐条数 */
const playCounts = computed<Record<string, number>>(() => {
  const counts: Record<string, number> = {}
  for (const tab of PLAY_TABS) {
    counts[tab.code] = rows.value.filter((r) => r.play_code === tab.code).length
  }
  return counts
})

/** 当前选项卡的推荐列表(后端已按置信度倒序) */
const activeRows = computed<LlmRecommendationRow[]>(() =>
  rows.value.filter((r) => r.play_code === activePlayCode.value),
)

const totalCount = computed(() => rows.value.length)

/** 当前选项卡已开奖推荐的命中统计(未开奖条目不计入) */
const hitStats = computed<{ hit: number; settled: number }>(() => {
  let hit = 0
  let settled = 0
  for (const row of activeRows.value) {
    if (row.is_hit !== null) {
      settled += 1
      if (row.is_hit) hit += 1
    }
  }
  return { hit, settled }
})

/** 置信度展示档位:高(>=0.70)/ 中(>=0.50)/ 低 */
function confidenceTone(confidence: number): 'high' | 'mid' | 'low' {
  if (confidence >= 0.7) return 'high'
  if (confidence >= 0.5) return 'mid'
  return 'low'
}

/** 选项带最新赔率的展示文案,如 主胜@1.63(未开售时仅显示选项名) */
function formatOptionWithOdds(label: string, odds: number | null): string {
  return odds !== null ? `${label}@${odds.toFixed(2)}` : label
}

/** 开赛时间展示(本地时区,MM-DD HH:mm) */
function formatMatchTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

async function fetchRecommendations(): Promise<void> {
  if (!canQuery.value) return
  const confidence = Number(minConfidence.value)
  if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
    errorMessage.value = '置信度下限需在 0 ~ 1 之间'
    return
  }
  isLoading.value = true
  errorMessage.value = ''
  try {
    rows.value = await listLlmRecommendations({
      business_date: selectedDate.value,
      min_confidence: confidence,
    })
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : '查询失败,请稍后重试'
  } finally {
    isLoading.value = false
  }
}

function selectPlay(code: string): void {
  activePlayCode.value = code
}

function openMatchDetail(matchId: string): void {
  void router.push(`/match/${matchId}`)
}

/** 本地时区的今天(YYYY-MM-DD),避免 UTC 偏移导致日期错位 */
function todayIso(): string {
  const now = new Date()
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

onMounted(() => {
  void fetchRecommendations()
})
</script>

<template>
  <section class="ai-analysis">
    <header class="ai-analysis__header">
      <h2 class="ai-analysis__title">AI 分析结果</h2>
      <p class="ai-analysis__subtitle">
        查询已保存的大模型分析推荐:按售卖日过滤,每场比赛取最近一次分析,
        输出五种玩法的推荐与备选选项(附最新赔率)、开奖对比、置信度与依据。
        结果为数据分析参考,不构成投注建议。
      </p>
    </header>

    <div class="ai-analysis__toolbar">
      <label class="ai-analysis__filter">
        <span>售卖日期</span>
        <input
          v-model="selectedDate"
          class="ai-analysis__date-input"
          type="date"
          :disabled="isLoading"
          @change="fetchRecommendations"
        />
      </label>
      <label class="ai-analysis__filter">
        <span>置信度下限</span>
        <input
          v-model.number="minConfidence"
          class="ai-analysis__confidence-input"
          type="number"
          min="0"
          max="1"
          step="0.05"
          :disabled="isLoading"
        />
      </label>
      <button
        class="ai-analysis__btn"
        type="button"
        :disabled="!canQuery"
        @click="fetchRecommendations"
      >
        查询
      </button>
      <span v-if="totalCount > 0" class="ai-analysis__meta">
        共 {{ totalCount }} 条推荐<template v-if="hitStats.settled > 0">
          · 当前玩法已开奖命中 {{ hitStats.hit }}/{{ hitStats.settled }}</template
        >
      </span>
    </div>

    <p v-if="errorMessage" class="ai-analysis__error" role="alert">{{ errorMessage }}</p>
    <p v-if="isLoading" class="ai-analysis__hint">加载中…</p>

    <div class="ai-analysis__tabs" role="tablist">
      <button
        v-for="tab in PLAY_TABS"
        :key="tab.code"
        class="ai-analysis__tab"
        :class="{ 'ai-analysis__tab--active': activePlayCode === tab.code }"
        type="button"
        role="tab"
        :aria-selected="activePlayCode === tab.code"
        @click="selectPlay(tab.code)"
      >
        {{ tab.label }}
        <span class="ai-analysis__tab-count">{{ playCounts[tab.code] ?? 0 }}</span>
      </button>
    </div>

    <table v-if="activeRows.length > 0" class="ai-analysis__table">
      <thead>
        <tr>
          <th>编号</th>
          <th>联赛 / 开赛</th>
          <th>主队</th>
          <th>客队</th>
          <th>推荐</th>
          <th>置信度</th>
          <th>备选</th>
          <th>开奖结果</th>
          <th>对比</th>
          <th>依据</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in activeRows" :key="`${row.match_id}:${row.play_code}`">
          <td class="ai-analysis__match-num">{{ row.match_num_str || '—' }}</td>
          <td class="ai-analysis__match-cell">
            <button
              class="ai-analysis__match-btn"
              type="button"
              @click="openMatchDetail(row.match_id)"
            >
              <span class="ai-analysis__league">{{ row.league_name ?? '—' }}</span>
              <span class="ai-analysis__time">{{ formatMatchTime(row.match_time) }}</span>
            </button>
          </td>
          <td class="ai-analysis__team ai-analysis__team--home">{{ row.home_team_name ?? '—' }}</td>
          <td class="ai-analysis__team">{{ row.away_team_name ?? '—' }}</td>
          <td class="ai-analysis__recommendation">
            {{ formatOptionWithOdds(row.recommendation, row.recommendation_odds) }}
          </td>
          <td>
            <span
              class="ai-analysis__confidence"
              :class="`ai-analysis__confidence--${confidenceTone(row.confidence)}`"
            >
              {{ (row.confidence * 100).toFixed(0) }}%
            </span>
          </td>
          <td class="ai-analysis__alternatives">
            <template v-if="row.alternatives.length > 0">
              {{
                row.alternatives
                  .map((alt, index) => formatOptionWithOdds(alt, row.alternative_odds[index] ?? null))
                  .join(' / ')
              }}
            </template>
            <template v-else>—</template>
          </td>
          <td class="ai-analysis__result">{{ row.result ?? '—' }}</td>
          <td>
            <span
              v-if="row.is_hit !== null"
              class="ai-analysis__hit"
              :class="
                row.is_hit ? 'ai-analysis__hit--hit' : 'ai-analysis__hit--miss'
              "
            >
              {{ row.is_hit ? '命中' : '未中' }}
            </span>
            <span v-else class="ai-analysis__hit ai-analysis__hit--pending">未开奖</span>
          </td>
          <td class="ai-analysis__reasoning">{{ row.reasoning }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else-if="!isLoading && !errorMessage" class="ai-analysis__empty">
      该日期暂无{{ PLAY_TABS.find((t) => t.code === activePlayCode)?.label }}玩法的 AI 推荐。
      可在赛事中心对比赛做深度分析后,再回到本页查询。
    </p>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.ai-analysis {
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

      &:focus {
        outline: none;
        border-color: vars.$color-primary;
      }
    }
  }

  &__confidence-input {
    width: 80px;
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

  &__tab-count {
    padding: 0 6px;
    border-radius: 10px;
    background: vars.$color-surface-hover;
    font-size: vars.$font-size-sm;
    line-height: 1.6;
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
      padding: vars.$spacing-sm;
      border-bottom: 1px solid vars.$color-border;
      text-align: center;
      vertical-align: top;
    }

    th {
      background: vars.$color-surface-hover;
      color: vars.$color-text-secondary;
      font-size: vars.$font-size-sm;
      font-weight: 600;
      white-space: nowrap;
    }

    tbody tr:hover {
      background: vars.$color-surface-hover;
    }
  }

  &__match-num {
    white-space: nowrap;
    font-weight: 600;
    color: vars.$color-text-primary;
  }

  &__match-cell {
    text-align: left;
  }

  &__match-btn {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 0;
    border: none;
    background: transparent;
    cursor: pointer;
    text-align: left;

    &:hover .ai-analysis__league,
    &:focus-visible .ai-analysis__league {
      text-decoration: underline;
    }
  }

  &__league {
    font-weight: 600;
    color: vars.$color-text-primary;
    text-decoration: underline transparent;
    transition: text-decoration-color 0.15s ease;
  }

  &__time {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__team {
    font-weight: 600;

    &--home {
      color: vars.$color-primary;
    }
  }

  &__recommendation {
    font-weight: 600;
    color: vars.$color-primary;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  &__confidence {
    display: inline-block;
    min-width: 44px;
    padding: 2px vars.$spacing-sm;
    border-radius: 10px;
    font-weight: 600;

    &--high {
      background: rgba(198, 40, 40, 0.1);
      color: vars.$color-positive;
    }

    &--mid {
      background: rgba(212, 136, 6, 0.12);
      color: vars.$color-warning;
    }

    &--low {
      background: vars.$color-surface-hover;
      color: vars.$color-text-secondary;
    }
  }

  &__alternatives {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    white-space: nowrap;
  }

  &__result {
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  &__hit {
    display: inline-block;
    min-width: 44px;
    padding: 2px vars.$spacing-sm;
    border-radius: 10px;
    font-size: vars.$font-size-sm;
    font-weight: 600;

    &--hit {
      background: rgba(15, 81, 50, 0.1);
      color: vars.$color-primary;
    }

    &--miss {
      background: rgba(192, 57, 43, 0.08);
      color: vars.$color-danger;
    }

    &--pending {
      background: vars.$color-surface-hover;
      color: vars.$color-text-secondary;
    }
  }

  &__reasoning {
    min-width: 280px;
    max-width: 420px;
    text-align: left;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    line-height: 1.5;
    white-space: normal;
  }

  &__empty {
    padding: vars.$spacing-lg;
    text-align: center;
    color: vars.$color-text-secondary;
    background: vars.$color-surface;
    border: 1px dashed vars.$color-border;
    border-radius: vars.$border-radius;
  }
}
</style>
