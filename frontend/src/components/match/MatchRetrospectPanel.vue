<script setup lang="ts">
/**
 * 赛事复盘面板:先比对最近一次 AI 综合分析的推荐与官方开奖结果
 * (逐玩法命中比对,系统实时计算),再调用大模型对比对结果做事后
 * 复盘,输出总结与经验教训并落库;生成后切换为展示已保存复盘
 * (含逐玩法归因与生成时点快照)。
 */
import { computed, onMounted, ref } from 'vue'
import {
  getLlmRetrospectView,
  runLlmRetrospect,
  type LlmRetrospectComparisonItem,
  type LlmRetrospectView,
} from '@/api/match/analysis'

/** 比对行统一形状:实时预览与快照明细同构,归因仅快照有值 */
type RetrospectRow = LlmRetrospectComparisonItem & { review?: string | null }

const props = defineProps<{
  /** 比赛 ID */
  matchId: string
}>()

const view = ref<LlmRetrospectView | null>(null)
const isLoading = ref(false)
const isGenerating = ref(false)
const error = ref<string | null>(null)

/** 已保存复盘存在时展示其明细快照(含归因),否则展示实时比对预览 */
const isRetrospectGenerated = computed(() => view.value?.retrospect != null)

/** 比对行(统一字段:快照明细与实时预览同构,归因仅快照有值) */
const comparisonRows = computed<RetrospectRow[]>(() => {
  if (view.value?.retrospect) return view.value.retrospect.items
  return view.value?.comparison ?? []
})

const hitStatsText = computed(() => {
  const retrospect = view.value?.retrospect
  if (!retrospect) return ''
  const pct =
    retrospect.total_count > 0
      ? `(${((retrospect.hit_count / retrospect.total_count) * 100).toFixed(0)}%)`
      : ''
  // 统计只计已开奖玩法;快照明细可能另含未开奖项(行内显示"未开奖")
  return `命中 ${retrospect.hit_count} / ${retrospect.total_count} ${pct}(已开奖玩法)`
})

/** 生成前置条件:赛果已同步 + 已生成 AI 综合分析 + 有已开奖玩法可比对 */
const canGenerate = computed(() => {
  if (!view.value) return false
  if (!view.value.result_available || !view.value.analysis_available) return false
  return comparisonRows.value.some((row) => row.is_hit !== null)
})

/** 未满足前置条件的原因提示(空串 = 可生成) */
const blockedReason = computed((): string => {
  if (!view.value) return ''
  if (!view.value.result_available) {
    return '赛果未同步或尚未开奖,请先在赛果开奖页同步赛果'
  }
  if (!view.value.analysis_available) {
    return '尚未生成 AI 综合分析,请先在「AI 分析」页签生成分析'
  }
  if (!canGenerate.value) return '没有已开奖玩法可比对'
  return ''
})

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function load(): Promise<void> {
  isLoading.value = true
  error.value = null
  try {
    view.value = await getLlmRetrospectView(props.matchId)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '复盘数据加载失败'
  } finally {
    isLoading.value = false
  }
}

/** 生成 / 重新生成 AI 复盘 */
async function handleGenerate(): Promise<void> {
  isGenerating.value = true
  error.value = null
  try {
    const retrospect = await runLlmRetrospect(props.matchId)
    // 重新拉取视图,保证比对明细与最新复盘一致
    view.value = await getLlmRetrospectView(props.matchId)
    if (view.value.retrospect?.retrospect_id !== retrospect.retrospect_id) {
      view.value = { ...view.value, retrospect }
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'AI 复盘生成失败,请稍后重试'
  } finally {
    isGenerating.value = false
  }
}

/** 供父组件在外部数据变化(如重新生成分析)后刷新 */
defineExpose({ refresh: load })

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="retro" aria-label="赛事复盘">
    <header class="retro__toolbar">
      <div>
        <h3 class="retro__title">赛事复盘</h3>
        <p class="retro__hint">
          先比对最近一次 AI 综合分析推荐与官方开奖结果,再由大模型归因复盘,
          输出总结与经验教训 · 仅供改进分析方法参考,不构成投注建议
        </p>
      </div>
      <button
        class="retro__button"
        type="button"
        :disabled="isGenerating || isLoading || !canGenerate"
        :aria-busy="isGenerating"
        @click="handleGenerate"
      >
        {{
          isGenerating
            ? '正在复盘…'
            : isRetrospectGenerated
              ? '重新生成复盘'
              : '生成 AI 复盘'
        }}
      </button>
    </header>

    <p v-if="error" class="retro__error" role="alert">{{ error }}</p>
    <p v-if="isLoading" class="retro__hint">加载中…</p>

    <template v-else-if="view">
      <p v-if="blockedReason" class="retro__blocked" role="note">
        {{ blockedReason }}
      </p>

      <!-- 比对表:AI 推荐 vs 官方开奖(已生成复盘时为快照明细,含事后归因) -->
      <h4 class="retro__section-title">
        推荐与开奖比对
        <span v-if="isRetrospectGenerated" class="retro__hit-stats">
          {{ hitStatsText }}
        </span>
      </h4>
      <div v-if="comparisonRows.length" class="retro__table-wrap">
        <table class="retro__table">
          <thead>
            <tr>
              <th scope="col">玩法</th>
              <th scope="col">AI 推荐</th>
              <th scope="col">开奖结果</th>
              <th scope="col">命中</th>
              <th scope="col">当时理由</th>
              <th v-if="isRetrospectGenerated" scope="col">事后归因</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in comparisonRows"
              :key="row.play_code"
              :class="{
                'retro__row--hit': row.is_hit === true,
                'retro__row--miss': row.is_hit === false,
              }"
            >
              <td class="retro__cell retro__cell--play">{{ row.play_name }}</td>
              <td class="retro__cell">
                <strong>{{ row.recommendation }}</strong>
                <span class="retro__confidence">
                  ({{ (row.confidence * 100).toFixed(0) }}%)
                </span>
              </td>
              <td class="retro__cell">{{ row.result ?? '未开奖' }}</td>
              <td class="retro__cell">
                <span v-if="row.is_hit === true" class="retro__hit">✓ 命中</span>
                <span v-else-if="row.is_hit === false" class="retro__miss">✗ 未中</span>
                <span v-else class="retro__pending">未开奖</span>
              </td>
              <td class="retro__cell retro__cell--reason">{{ row.reasoning }}</td>
              <td
                v-if="isRetrospectGenerated"
                class="retro__cell retro__cell--reason"
              >
                {{ row.review ?? '—' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="retro__hint">暂无可比对的 AI 推荐数据</p>

      <!-- 已保存的复盘结果 -->
      <template v-if="view.retrospect">
        <h4 class="retro__section-title">复盘总结</h4>
        <div class="retro__summary">
          <span class="retro__meta">
            模型 {{ view.retrospect.model }} · 生成于
            {{ formatTime(view.retrospect.created_at) }}
          </span>
          <p class="retro__summary-text">{{ view.retrospect.summary }}</p>
        </div>

        <h4 class="retro__section-title">经验教训</h4>
        <ol v-if="view.retrospect.lessons.length" class="retro__lessons">
          <li
            v-for="lesson in view.retrospect.lessons"
            :key="lesson"
            class="retro__lesson"
          >
            {{ lesson }}
          </li>
        </ol>
      </template>

      <p v-else-if="canGenerate" class="retro__hint">
        点击"生成 AI 复盘",大模型将基于上方比对结果与赛前分析理由,
        逐玩法归因并提炼可复用的经验教训(约需 10~30 秒)。
      </p>
    </template>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.retro {
  display: flex;
  flex-direction: column;
  gap: vars.$spacing-md;

  &__toolbar {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: vars.$spacing-md;
  }

  &__title {
    margin: 0 0 vars.$spacing-xs;
    font-size: vars.$font-size-md;
  }

  &__hint,
  &__error,
  &__blocked {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__blocked {
    padding: vars.$spacing-sm vars.$spacing-md;
    border: 1px dashed vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__button {
    flex-shrink: 0;
    padding: vars.$spacing-xs vars.$spacing-lg;
    border: none;
    border-radius: vars.$border-radius;
    background: vars.$color-primary;
    color: #fff;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &:hover:not(:disabled) {
      opacity: 0.9;
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  &__section-title {
    margin: vars.$spacing-xs 0 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-primary;
  }

  &__hit-stats {
    margin-left: vars.$spacing-sm;
    font-weight: 600;
    color: vars.$color-primary;
  }

  &__table-wrap {
    overflow-x: auto;
  }

  &__table {
    width: 100%;
    border-collapse: collapse;
    font-size: vars.$font-size-sm;
    text-align: left;

    th,
    td {
      padding: vars.$spacing-sm vars.$spacing-md;
      border-bottom: 1px solid vars.$color-border;
      vertical-align: top;
    }

    th {
      color: vars.$color-text-secondary;
      font-weight: 600;
      white-space: nowrap;
    }
  }

  &__row--hit td {
    background: rgba(34, 139, 34, 0.06);
  }

  &__row--miss td {
    background: rgba(214, 69, 65, 0.06);
  }

  &__cell {
    &--play {
      white-space: nowrap;
      font-weight: 600;
    }

    &--reason {
      min-width: 160px;
      color: vars.$color-text-secondary;
    }
  }

  &__confidence {
    margin-left: vars.$spacing-xs;
    color: vars.$color-text-secondary;
  }

  &__hit {
    color: vars.$color-primary;
    font-weight: 600;
    white-space: nowrap;
  }

  &__miss {
    color: vars.$color-danger;
    font-weight: 600;
    white-space: nowrap;
  }

  &__pending {
    color: vars.$color-text-secondary;
    white-space: nowrap;
  }

  &__summary {
    padding: vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
  }

  &__meta {
    display: block;
    margin-bottom: vars.$spacing-xs;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__summary-text {
    margin: 0;
    line-height: 1.7;
  }

  &__lessons {
    margin: 0;
    padding-left: 1.2em;
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
  }

  &__lesson {
    padding: vars.$spacing-sm vars.$spacing-md;
    border-left: 3px solid vars.$color-primary;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    line-height: 1.6;
  }
}
</style>
