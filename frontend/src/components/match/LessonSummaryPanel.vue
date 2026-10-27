<script setup lang="ts">
/**
 * AI 复盘经验总结面板:手动触发生成,归纳各场 AI 复盘的共性经验;
 * 展示最近一次总结(总结段落 + 经验条目 + 输入统计),并可展开
 * 历史总结查看每次的输入提示词与模型原始响应(经请求日志关联)。
 * 最近一次总结会由后端注入后续 AI 综合分析的提示词。
 */
import { computed, onMounted, ref } from 'vue'
import {
  getLlmLessonSummaryLog,
  listLlmLessonSummaries,
  runLlmLessonSummary,
  type LlmLessonSummary,
  type LlmRequestLog,
} from '@/api/match/analysis'

const summaries = ref<LlmLessonSummary[]>([])
const isLoading = ref(false)
const isGenerating = ref(false)
const error = ref<string | null>(null)

/** 历史总结折叠态(默认收起) */
const isHistoryOpen = ref(false)
/** 当前展开输入输出的总结 ID */
const expandedLogId = ref<number | null>(null)
const loadingLogId = ref<number | null>(null)
/** 已拉取的请求日志缓存(总结 ID -> 日志) */
const logCache = ref<Map<number, LlmRequestLog>>(new Map())

const latestSummary = computed(() => summaries.value[0] ?? null)

/** 历史列表不含最新一次(最新一次已作为主卡片展示) */
const historySummaries = computed(() => summaries.value.slice(1))

const hitStatsText = computed(() => {
  const summary = latestSummary.value
  if (!summary) return ''
  return `输入 ${summary.retrospect_count} 场复盘 · 合计命中 ${summary.total_hit}/${summary.total_decided}`
})

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** 提示词消息的角色标签 */
function roleLabel(role: string): string {
  if (role === 'system') return '系统提示词'
  if (role === 'user') return '用户提示词'
  return role
}

async function load(): Promise<void> {
  isLoading.value = true
  error.value = null
  try {
    summaries.value = await listLlmLessonSummaries()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '经验总结加载失败'
  } finally {
    isLoading.value = false
  }
}

/** 生成 / 重新生成经验总结 */
async function handleGenerate(): Promise<void> {
  isGenerating.value = true
  error.value = null
  try {
    await runLlmLessonSummary()
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'AI 复盘总结生成失败,请稍后重试'
  } finally {
    isGenerating.value = false
  }
}

/** 展开 / 收起某次总结的输入输出(日志按需拉取并缓存) */
async function toggleLog(summary: LlmLessonSummary): Promise<void> {
  if (expandedLogId.value === summary.summary_id) {
    expandedLogId.value = null
    return
  }
  expandedLogId.value = summary.summary_id
  if (logCache.value.has(summary.summary_id) || summary.log_id === null) return
  loadingLogId.value = summary.summary_id
  try {
    const log = await getLlmLessonSummaryLog(summary.summary_id)
    logCache.value = new Map(logCache.value).set(summary.summary_id, log)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '请求日志加载失败'
    expandedLogId.value = null
  } finally {
    loadingLogId.value = null
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="lesson" aria-label="AI 复盘总结">
    <header class="lesson__toolbar">
      <div>
        <h3 class="lesson__title">AI 复盘总结</h3>
        <p class="lesson__hint">
          归纳各场 AI 复盘的共性经验,提炼可复用的分析方法;
          最近一次总结将注入后续 AI 综合分析的提示词 · 仅供改进分析方法参考,不构成投注建议
        </p>
      </div>
      <button
        class="lesson__button"
        type="button"
        :disabled="isGenerating || isLoading"
        :aria-busy="isGenerating"
        @click="handleGenerate"
      >
        {{ isGenerating ? '总结中…' : '生成总结' }}
      </button>
    </header>

    <p v-if="error" class="lesson__error" role="alert">{{ error }}</p>
    <p v-if="isLoading" class="lesson__hint">加载中…</p>
    <p v-else-if="!latestSummary && !error" class="lesson__empty">
      尚未生成过复盘经验总结:对各场比赛生成 AI 复盘后,点击「生成总结」
      归纳共性经验(约需 10~30 秒)。
    </p>

    <!-- 最近一次总结:总结段落 + 经验条目 + 输入统计 -->
    <template v-if="latestSummary">
      <div class="lesson__latest">
        <span class="lesson__meta">
          模型 {{ latestSummary.model }} · 生成于 {{ formatTime(latestSummary.created_at) }}
          · {{ hitStatsText }}
        </span>
        <p class="lesson__summary-text">{{ latestSummary.summary }}</p>
        <ol v-if="latestSummary.lessons.length" class="lesson__lessons">
          <li
            v-for="lesson in latestSummary.lessons"
            :key="lesson"
            class="lesson__lesson"
          >
            {{ lesson }}
          </li>
        </ol>
        <button
          class="lesson__log-toggle"
          type="button"
          @click="toggleLog(latestSummary)"
        >
          {{ expandedLogId === latestSummary.summary_id ? '收起输入输出' : '查看输入输出' }}
        </button>
        <div
          v-if="expandedLogId === latestSummary.summary_id"
          class="lesson__log"
        >
          <template v-if="logCache.has(latestSummary.summary_id)">
            <div
              v-for="(message, index) in logCache.get(latestSummary.summary_id)!.request_messages"
              :key="index"
              class="lesson__log-block"
            >
              <span class="lesson__log-label">{{ roleLabel(message.role) }}</span>
              <pre class="lesson__log-pre">{{ message.content }}</pre>
            </div>
            <div class="lesson__log-block">
              <span class="lesson__log-label">模型原始响应</span>
              <pre class="lesson__log-pre">{{ logCache.get(latestSummary.summary_id)!.response_content ?? '(无响应内容)' }}</pre>
            </div>
          </template>
          <p v-else-if="loadingLogId === latestSummary.summary_id" class="lesson__hint">
            日志加载中…
          </p>
          <p v-else-if="latestSummary.log_id === null" class="lesson__hint">
            该次总结没有关联的请求日志
          </p>
        </div>
      </div>

      <!-- 历史总结(不含最新一次) -->
      <div v-if="historySummaries.length" class="lesson__history">
        <button
          class="lesson__history-toggle"
          type="button"
          @click="isHistoryOpen = !isHistoryOpen"
        >
          {{ isHistoryOpen ? '收起历史总结' : `历史总结(${historySummaries.length})` }}
        </button>
        <ul v-if="isHistoryOpen" class="lesson__history-list">
          <li
            v-for="summary in historySummaries"
            :key="summary.summary_id"
            class="lesson__history-item"
          >
            <div class="lesson__history-head">
              <span class="lesson__meta">
                {{ formatTime(summary.created_at) }} · 输入 {{ summary.retrospect_count }} 场复盘
                · 命中 {{ summary.total_hit }}/{{ summary.total_decided }}
              </span>
              <button
                class="lesson__log-toggle"
                type="button"
                @click="toggleLog(summary)"
              >
                {{ expandedLogId === summary.summary_id ? '收起输入输出' : '查看输入输出' }}
              </button>
            </div>
            <p class="lesson__history-summary">{{ summary.summary }}</p>
            <div v-if="expandedLogId === summary.summary_id" class="lesson__log">
              <template v-if="logCache.has(summary.summary_id)">
                <div
                  v-for="(message, index) in logCache.get(summary.summary_id)!.request_messages"
                  :key="index"
                  class="lesson__log-block"
                >
                  <span class="lesson__log-label">{{ roleLabel(message.role) }}</span>
                  <pre class="lesson__log-pre">{{ message.content }}</pre>
                </div>
                <div class="lesson__log-block">
                  <span class="lesson__log-label">模型原始响应</span>
                  <pre class="lesson__log-pre">{{ logCache.get(summary.summary_id)!.response_content ?? '(无响应内容)' }}</pre>
                </div>
              </template>
              <p v-else-if="loadingLogId === summary.summary_id" class="lesson__hint">
                日志加载中…
              </p>
              <p v-else-if="summary.log_id === null" class="lesson__hint">
                该次总结没有关联的请求日志
              </p>
            </div>
          </li>
        </ul>
      </div>
    </template>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.lesson {
  display: flex;
  flex-direction: column;
  gap: vars.$spacing-md;
  padding: vars.$spacing-md vars.$spacing-lg;
  background: vars.$color-surface;
  border: 1px solid vars.$color-border;
  border-radius: vars.$border-radius;

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
  &__empty {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__error {
    color: vars.$color-danger;
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

  &__latest {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-sm;
    padding: vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-primary-light;
  }

  &__meta {
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
    line-height: 1.6;
  }

  &__log-toggle {
    align-self: flex-start;
    padding: 0;
    border: none;
    background: transparent;
    color: vars.$color-primary;
    font-size: vars.$font-size-sm;
    text-decoration: underline;
    cursor: pointer;
  }

  &__log {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-sm;
  }

  &__log-block {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
  }

  &__log-label {
    font-size: vars.$font-size-sm;
    font-weight: 600;
    color: vars.$color-text-secondary;
  }

  &__log-pre {
    max-height: 320px;
    margin: 0;
    padding: vars.$spacing-sm;
    overflow: auto;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface-hover;
    font-size: vars.$font-size-sm;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-all;
  }

  &__history {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-sm;
  }

  &__history-toggle {
    align-self: flex-start;
    padding: 0;
    border: none;
    background: transparent;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
    text-decoration: underline;
    cursor: pointer;
  }

  &__history-list {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-sm;
  }

  &__history-item {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
    padding: vars.$spacing-sm vars.$spacing-md;
    border: 1px dashed vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__history-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: vars.$spacing-md;
  }

  &__history-summary {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    line-height: 1.6;
  }
}
</style>
