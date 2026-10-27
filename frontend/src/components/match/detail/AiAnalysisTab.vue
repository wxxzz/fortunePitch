<script setup lang="ts">
/**
 * 深度分析 · AI 分析 Tab。
 *
 * 大模型综合分析(聚合联赛信息、双方基本面、在售玩法赔率,以及已生成的
 * AI 基本面分析与赔率走势分析结论)+ 每次调用的分析日志查看器。
 * 暴露 refresh() 供父级在其他 Tab 生成分析后防御性刷新日志列表。
 */
import { onMounted, ref } from 'vue'
import {
  getLlmAnalysis,
  runLlmAnalysis,
} from '@/api/match/analysis'
import LlmLogViewer from '@/components/match/LlmLogViewer.vue'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
import { useLlmResource } from '@/composables/useLlmResource'
import { PROVIDER_LABELS } from './constants'

const props = defineProps<{ matchId: string }>()

const {
  data: llmAnalysis,
  isLoading: isLlmLoading,
  error: llmError,
  run: runAnalysis,
  loadSaved: loadSavedAnalysis,
} = useLlmResource(props.matchId, {
  runRequest: runLlmAnalysis,
  savedRequest: getLlmAnalysis,
  runErrorFallback: '大模型分析失败,请稍后重试',
})

/** 分析日志查看器(生成成功或失败后刷新,失败调用同样留痕) */
const llmLogViewer = ref<InstanceType<typeof LlmLogViewer> | null>(null)

/** 刷新日志列表(查看器未挂载时为空操作) */
function refresh(): void {
  llmLogViewer.value?.refresh()
}

defineExpose({ refresh })

onMounted(() => {
  // 挂载时加载最近一次已保存的分析(未生成过时按无结果处理)
  void loadSavedAnalysis()
})

/** 生成 / 重新生成大模型分析;成功与失败调用都会写日志,结束后刷新日志列表 */
async function handleRunAnalysis(): Promise<void> {
  await runAnalysis()
  refresh()
}
</script>

<template>
  <section class="ai-analysis-tab">
    <div class="ai-analysis-tab__llm-toolbar">
      <button
        class="ai-analysis-tab__llm-button"
        type="button"
        :disabled="isLlmLoading"
        :aria-busy="isLlmLoading"
        @click="handleRunAnalysis"
      >
        {{ isLlmLoading ? '正在分析…' : llmAnalysis ? '重新生成分析' : '生成 AI 分析' }}
      </button>
      <p class="ai-analysis-tab__hint">
        后端将聚合本场联赛信息、双方基本面、在售玩法赔率,以及已生成的
        AI 基本面分析与赔率走势分析结论调用大模型 · 仅供参考,不构成投注建议
      </p>
    </div>

    <p v-if="llmError" class="ai-analysis-tab__error" role="alert">{{ llmError }}</p>

    <SkeletonBlock
      v-if="isLlmLoading"
      :height="240"
      label="正在调用大模型分析(约需 10~30 秒)…"
    />

    <template v-else-if="llmAnalysis">
      <div class="ai-analysis-tab__llm-summary">
        <span class="ai-analysis-tab__llm-meta">
          模型 {{ llmAnalysis.model }}({{ PROVIDER_LABELS[llmAnalysis.provider] ?? llmAnalysis.provider }})
          · 生成于 {{ new Date(llmAnalysis.created_at).toLocaleString() }}
        </span>
        <p class="ai-analysis-tab__llm-summary-text">{{ llmAnalysis.summary }}</p>
      </div>

      <h3 class="ai-analysis-tab__section-title">分玩法推荐</h3>
      <div class="ai-analysis-tab__llm-plays">
        <article
          v-for="play in llmAnalysis.plays"
          :key="play.play_code"
          class="ai-analysis-tab__llm-play"
        >
          <header class="ai-analysis-tab__llm-play-head">
            <span class="ai-analysis-tab__llm-play-name">{{ play.play_name }}</span>
            <strong class="ai-analysis-tab__llm-play-rec">{{ play.recommendation }}</strong>
          </header>
          <div class="ai-analysis-tab__llm-confidence">
            <span>置信度 {{ (play.confidence * 100).toFixed(0) }}%</span>
            <div class="ai-analysis-tab__llm-bar" role="presentation">
              <span
                class="ai-analysis-tab__llm-bar-fill"
                :style="{ width: `${Math.round(play.confidence * 100)}%` }"
              />
            </div>
          </div>
          <p class="ai-analysis-tab__llm-reasoning">{{ play.reasoning }}</p>
          <p v-if="play.alternatives.length" class="ai-analysis-tab__hint">
            次选:{{ play.alternatives.join(' / ') }}
          </p>
        </article>
      </div>

      <h3 class="ai-analysis-tab__section-title">风险提示</h3>
      <ul v-if="llmAnalysis.risks.length" class="ai-analysis-tab__risks">
        <li v-for="risk in llmAnalysis.risks" :key="risk">
          <span class="ai-analysis-tab__risk-icon" aria-hidden="true">⚠</span>
          {{ risk }}
        </li>
      </ul>
      <p v-else class="ai-analysis-tab__hint">模型未给出额外风险提示</p>
    </template>

    <p v-else class="ai-analysis-tab__hint">
      点击"生成 AI 分析",大模型将基于本场基本面、赔率与联赛信息,
      并结合已生成的 AI 基本面分析与赔率走势分析结论,输出各竞彩玩法的推荐方案。
    </p>

    <!-- 分析日志:查看每次大模型调用的请求参数与响应结果 -->
    <LlmLogViewer ref="llmLogViewer" :match-id="matchId" />
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;
@use './detail-shared' as shared;

.ai-analysis-tab {
  @include shared.panel;
  @include shared.actions;
  @include shared.llm;
}
</style>
