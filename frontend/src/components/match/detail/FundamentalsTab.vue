<script setup lang="ts">
/**
 * 深度分析 · 基本面 Tab。
 *
 * 双方联赛积分榜战绩对比(总榜 + 主/客场维度)+ AI 基本面多维度分析。
 * 基本面数据由本组件独占持有(挂载时以双方 teamId 懒加载);生成分析
 * 结束后向父级发出 analysisSettled 事件,由父级刷新 AI 分析 Tab 的日志查看器。
 */
import { onMounted } from 'vue'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
import {
  getLlmFundamentalAnalysis,
  runLlmFundamentalAnalysis,
} from '@/api/match/analysis'
import {
  useMatchFundamentals,
  type FundamentalsLine,
} from '@/composables/useMatchFundamentals'
import { useLlmResource } from '@/composables/useLlmResource'
import { EDGE_LABELS, PROVIDER_LABELS } from './constants'

const props = defineProps<{
  matchId: string
  homeTeamId: number
  awayTeamId: number
  homeTeamName: string
  awayTeamName: string
}>()

const emit = defineEmits<{ analysisSettled: [] }>()

const {
  isLoading: isFundamentalsLoading,
  load,
  season: fundamentalsSeason,
  homeHomeLine,
  awayAwayLine,
  homeTotalLine,
  awayTotalLine,
  has: hasFundamentals,
} = useMatchFundamentals()

const {
  data: llmFundamental,
  isLoading: isFundamentalLlmLoading,
  error: fundamentalLlmError,
  run: runFundamentalAnalysis,
  loadSaved: loadSavedFundamentalAnalysis,
} = useLlmResource(props.matchId, {
  runRequest: runLlmFundamentalAnalysis,
  savedRequest: getLlmFundamentalAnalysis,
  runErrorFallback: '基本面分析失败,请稍后重试',
})

onMounted(() => {
  void load(props.homeTeamId, props.awayTeamId)
  // 加载最近一次已保存的基本面分析(未生成过时按无结果处理)
  void loadSavedFundamentalAnalysis()
})

/** 生成 / 重新生成基本面多维度分析(生成后保存,每次生成一条历史) */
async function handleRunFundamentalAnalysis(): Promise<void> {
  await runFundamentalAnalysis()
  // 基本面分析的日志也按比赛 ID 留痕,通知父级防御性刷新日志查看器
  // (日志查看器仅挂在 AI 分析 Tab,未挂载时父级侧为空操作)
  emit('analysisSettled')
}

const fmt = (value: number | null | undefined): string =>
  value !== null && value !== undefined ? String(value) : '-'

const fmtRate = (value: number | null | undefined): string =>
  value !== null && value !== undefined ? `${value.toFixed(0)}%` : '-'

/** 对比表指标行(值为 null-safe 展示函数) */
interface MetricRow {
  label: string
  value: (line: FundamentalsLine | null) => string
}

const METRIC_ROWS: MetricRow[] = [
  { label: '排名', value: (l) => fmt(l?.ranking) },
  { label: '已赛', value: (l) => fmt(l?.played) },
  { label: '胜 / 平 / 负', value: (l) => `${fmt(l?.wins)} / ${fmt(l?.draws)} / ${fmt(l?.losses)}` },
  { label: '进球 / 失球', value: (l) => `${fmt(l?.goals_for)} / ${fmt(l?.goals_against)}` },
  { label: '净胜球', value: (l) => fmt(l?.goal_diff) },
  { label: '积分', value: (l) => fmt(l?.points) },
  { label: '胜率', value: (l) => fmtRate(l?.win_rate) },
]
</script>

<template>
  <section class="fundamentals-tab">
    <SkeletonBlock
      v-if="isFundamentalsLoading"
      :height="240"
      label="加载球队基本面…"
    />
    <template v-else-if="hasFundamentals">
      <h3 class="fundamentals-tab__section-title">
        联赛总战绩对比<span v-if="fundamentalsSeason">({{ fundamentalsSeason }} 赛季)</span>
      </h3>
      <table class="fundamentals-tab__table">
        <thead>
          <tr>
            <th>指标</th>
            <th>{{ homeTeamName }}</th>
            <th>{{ awayTeamName }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in METRIC_ROWS" :key="row.label">
            <td>{{ row.label }}</td>
            <td>{{ row.value(homeTotalLine) }}</td>
            <td>{{ row.value(awayTotalLine) }}</td>
          </tr>
        </tbody>
      </table>

      <h3 class="fundamentals-tab__section-title">主场战绩 vs 客场战绩</h3>
      <p class="fundamentals-tab__hint">
        主队取主场维度,客队取客场维度,与本场对阵环境一致
      </p>
      <table class="fundamentals-tab__table">
        <thead>
          <tr>
            <th>指标</th>
            <th>{{ homeTeamName }}(主场)</th>
            <th>{{ awayTeamName }}(客场)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in METRIC_ROWS" :key="row.label">
            <td>{{ row.label }}</td>
            <td>{{ row.value(homeHomeLine) }}</td>
            <td>{{ row.value(awayAwayLine) }}</td>
          </tr>
        </tbody>
      </table>
      <p class="fundamentals-tab__hint">
        数据来源:竞彩网积分榜 · 在“数据采集”页同步基本面后更新
      </p>
    </template>
    <p v-else class="fundamentals-tab__hint">
      暂无球队基本面数据。请在“数据采集”页对两队所属联赛执行“同步基本面”。
    </p>

    <!-- AI 基本面多维度分析(球队档案 / 赛程赛果 / 积分榜聚合调用) -->
    <h3 class="fundamentals-tab__section-title">AI 基本面分析</h3>
    <div class="fundamentals-tab__llm-toolbar">
      <button
        class="fundamentals-tab__llm-button"
        type="button"
        :disabled="isFundamentalLlmLoading"
        :aria-busy="isFundamentalLlmLoading"
        @click="handleRunFundamentalAnalysis"
      >
        {{
          isFundamentalLlmLoading
            ? '正在分析…'
            : llmFundamental
              ? '重新生成基本面分析'
              : '生成基本面分析'
        }}
      </button>
      <p class="fundamentals-tab__hint">
        基于球队档案、近期赛程赛果、积分榜与后续赛程做多维度基本面研判 ·
        仅供参考,不构成投注建议
      </p>
    </div>

    <p v-if="fundamentalLlmError" class="fundamentals-tab__error" role="alert">
      {{ fundamentalLlmError }}
    </p>

    <SkeletonBlock
      v-if="isFundamentalLlmLoading"
      :height="240"
      label="正在调用大模型分析基本面(约需 10~30 秒)…"
    />

    <template v-else-if="llmFundamental">
      <div class="fundamentals-tab__llm-summary">
        <span class="fundamentals-tab__llm-meta">
          模型 {{ llmFundamental.model }}({{
            PROVIDER_LABELS[llmFundamental.provider] ?? llmFundamental.provider
          }})
          · 生成于 {{ new Date(llmFundamental.created_at).toLocaleString() }}
        </span>
        <p class="fundamentals-tab__llm-summary-text">{{ llmFundamental.summary }}</p>
      </div>

      <div class="fundamentals-tab__llm-dimensions">
        <article
          v-for="dim in llmFundamental.dimensions"
          :key="dim.code"
          class="fundamentals-tab__llm-dim"
        >
          <header class="fundamentals-tab__llm-dim-head">
            <span class="fundamentals-tab__llm-dim-title">{{ dim.title }}</span>
            <span
              class="fundamentals-tab__llm-edge"
              :class="`fundamentals-tab__llm-edge--${dim.edge}`"
            >
              {{ EDGE_LABELS[dim.edge] ?? '势均力敌' }}
            </span>
          </header>
          <p class="fundamentals-tab__llm-reasoning">{{ dim.content }}</p>
        </article>
      </div>

      <template v-if="llmFundamental.risks.length">
        <h4 class="fundamentals-tab__section-title">风险提示</h4>
        <ul class="fundamentals-tab__risks">
          <li v-for="risk in llmFundamental.risks" :key="risk">
            <span class="fundamentals-tab__risk-icon" aria-hidden="true">⚠</span>
            {{ risk }}
          </li>
        </ul>
      </template>
    </template>

    <p v-else class="fundamentals-tab__hint">
      点击“生成基本面分析”,大模型将从近期状态、主客场表现、攻防效率、
      战意与动机、历史交锋等维度输出基本面研判。
    </p>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;
@use './detail-shared' as shared;

.fundamentals-tab {
  @include shared.panel;
  @include shared.actions;
  @include shared.llm;

  &__llm-dimensions {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: vars.$spacing-md;
  }

  &__llm-dim {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-sm;
    padding: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__llm-dim-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: vars.$spacing-sm;
  }

  &__llm-dim-title {
    font-weight: 600;
  }

  &__llm-edge {
    padding: 2px vars.$spacing-sm;
    border-radius: vars.$border-radius;
    font-size: vars.$font-size-sm;
    white-space: nowrap;

    &--home {
      background: rgba(34, 139, 34, 0.12);
      color: vars.$color-positive;
    }

    &--away {
      background: rgba(30, 100, 190, 0.12);
      color: #1e64be;
    }

    &--even {
      background: vars.$color-surface-hover;
      color: vars.$color-text-secondary;
    }
  }
}
</style>
