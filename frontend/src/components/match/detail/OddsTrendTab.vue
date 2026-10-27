<script setup lang="ts">
/**
 * 深度分析 · 赔率走势 Tab。
 *
 * 赔率快照走势(按玩法切换)+ AI 赔率走势分析。
 * 快照与走势数据由本组件独占持有(懒加载);生成分析结束后向父级
 * 发出 analysisSettled 事件,由父级刷新 AI 分析 Tab 的日志查看器。
 */
import { onMounted } from 'vue'
import OddsTrendChart from '@/components/strategy/OddsTrendChart.vue'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
import {
  getLlmTrendAnalysis,
  runLlmTrendAnalysis,
} from '@/api/match/analysis'
import { useOddsTrend } from '@/composables/useOddsTrend'
import { useLlmResource } from '@/composables/useLlmResource'
import { PROVIDER_LABELS } from './constants'

const props = defineProps<{ matchId: string }>()

const emit = defineEmits<{ analysisSettled: [] }>()

const {
  snapshots,
  isLoading: isTrendLoading,
  error: trendError,
  activePoolCode,
  poolOptions: trendPoolOptions,
  currentPoolCode,
  poolLabel: trendPoolLabel,
  seriesNames: trendSeriesNames,
  points: trendPoints,
  load: loadOddsSnapshots,
} = useOddsTrend(props.matchId)

const {
  data: trendLlmAnalysis,
  isLoading: isTrendLlmLoading,
  error: trendLlmError,
  run: runTrendAnalysis,
  loadSaved: loadSavedTrendAnalysis,
} = useLlmResource(props.matchId, {
  runRequest: runLlmTrendAnalysis,
  savedRequest: getLlmTrendAnalysis,
  runErrorFallback: '赔率走势分析失败,请稍后重试',
})

onMounted(() => {
  void (async () => {
    await loadOddsSnapshots()
    // 快照就绪后顺带加载最近一次已保存的走势分析(无快照时后端会 422,静默忽略)
    if (snapshots.value.length > 0) void loadSavedTrendAnalysis()
  })()
})

/** 生成 / 重新生成大模型赔率走势分析(生成后保存,每次生成一条历史) */
async function handleRunTrendAnalysis(): Promise<void> {
  await runTrendAnalysis()
  // 基本面/走势分析的日志也按比赛 ID 留痕,通知父级防御性刷新日志查看器
  // (日志查看器仅挂在 AI 分析 Tab,未挂载时父级侧为空操作)
  emit('analysisSettled')
}
</script>

<template>
  <section class="odds-trend-tab">
    <p v-if="trendError" class="odds-trend-tab__error" role="alert">{{ trendError }}</p>
    <SkeletonBlock v-if="isTrendLoading" :height="320" label="加载赔率走势…" />
    <template v-else-if="snapshots.length > 0">
      <nav class="odds-trend-tab__pools" role="tablist" aria-label="玩法选择">
        <button
          v-for="pool in trendPoolOptions"
          :key="pool.poolCode"
          type="button"
          role="tab"
          class="odds-trend-tab__pool"
          :class="{ 'odds-trend-tab__pool--active': pool.poolCode === currentPoolCode }"
          :aria-selected="pool.poolCode === currentPoolCode"
          @click="activePoolCode = pool.poolCode"
        >
          {{ trendPoolLabel(pool) }}
        </button>
      </nav>
      <OddsTrendChart :series-names="trendSeriesNames" :points="trendPoints" />
      <p class="odds-trend-tab__hint">
        快照随每次"同步赛事"生成,仅记录赔率发生变化的时间点 ·
        序列较多时可点击图例切换显隐
      </p>
    </template>
    <p v-else class="odds-trend-tab__hint">
      暂无走势数据。赔率快照随每次"同步赛事"生成,多次同步后即可查看变化趋势
    </p>

    <!-- AI 赔率走势分析(基于快照序列聚合调用) -->
    <h3 class="odds-trend-tab__section-title">AI 赔率走势分析</h3>
    <div class="odds-trend-tab__llm-toolbar">
      <button
        class="odds-trend-tab__llm-button"
        type="button"
        :disabled="isTrendLlmLoading || snapshots.length === 0"
        :aria-busy="isTrendLlmLoading"
        @click="handleRunTrendAnalysis"
      >
        {{
          isTrendLlmLoading
            ? '正在分析…'
            : trendLlmAnalysis
              ? '重新生成走势分析'
              : '赔率走势分析'
        }}
      </button>
      <p class="odds-trend-tab__hint">
        基于赔率快照走势调用大模型研判市场资金动向 · 仅供参考,不构成投注建议
      </p>
    </div>

    <p v-if="trendLlmError" class="odds-trend-tab__error" role="alert">
      {{ trendLlmError }}
    </p>

    <SkeletonBlock
      v-if="isTrendLlmLoading"
      :height="240"
      label="正在调用大模型分析赔率走势(约需 10~30 秒)…"
    />

    <template v-else-if="trendLlmAnalysis">
      <div class="odds-trend-tab__llm-summary">
        <span class="odds-trend-tab__llm-meta">
          模型 {{ trendLlmAnalysis.model }}({{
            PROVIDER_LABELS[trendLlmAnalysis.provider] ?? trendLlmAnalysis.provider
          }})
          · 生成于 {{ new Date(trendLlmAnalysis.created_at).toLocaleString() }}
        </span>
        <p class="odds-trend-tab__llm-summary-text">{{ trendLlmAnalysis.summary }}</p>
      </div>

      <h3 class="odds-trend-tab__section-title">分玩法走势结论</h3>
      <div class="odds-trend-tab__llm-plays">
        <article
          v-for="play in trendLlmAnalysis.plays"
          :key="play.play_code"
          class="odds-trend-tab__llm-play"
        >
          <header class="odds-trend-tab__llm-play-head">
            <span class="odds-trend-tab__llm-play-name">{{ play.play_name }}</span>
            <strong class="odds-trend-tab__llm-play-rec">{{ play.signal }}</strong>
          </header>
          <div class="odds-trend-tab__llm-confidence">
            <span>置信度 {{ (play.confidence * 100).toFixed(0) }}%</span>
            <div class="odds-trend-tab__llm-bar" role="presentation">
              <span
                class="odds-trend-tab__llm-bar-fill"
                :style="{ width: `${Math.round(play.confidence * 100)}%` }"
              />
            </div>
          </div>
          <p class="odds-trend-tab__llm-reasoning">{{ play.reasoning }}</p>
        </article>
      </div>

      <h3 class="odds-trend-tab__section-title">风险提示</h3>
      <ul v-if="trendLlmAnalysis.risks.length" class="odds-trend-tab__risks">
        <li v-for="risk in trendLlmAnalysis.risks" :key="risk">
          <span class="odds-trend-tab__risk-icon" aria-hidden="true">⚠</span>
          {{ risk }}
        </li>
      </ul>
      <p v-else class="odds-trend-tab__hint">模型未给出额外风险提示</p>
    </template>

    <p v-else-if="snapshots.length > 0" class="odds-trend-tab__hint">
      点击"赔率走势分析",大模型将基于本场赔率快照序列输出市场资金动向研判。
    </p>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;
@use './detail-shared' as shared;

.odds-trend-tab {
  @include shared.panel;
  @include shared.actions;
  @include shared.llm;

  &__pools {
    display: flex;
    flex-wrap: wrap;
    gap: vars.$spacing-xs;
  }

  &__pool {
    padding: vars.$spacing-xs vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: 999px;
    background: vars.$color-surface;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &--active {
      border-color: vars.$color-primary;
      background: vars.$color-primary;
      color: #fff;
      font-weight: 600;
    }
  }
}
</style>
