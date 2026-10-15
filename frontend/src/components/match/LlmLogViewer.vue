<script setup lang="ts">
/**
 * 大模型调用日志查看器:按时间倒序展示本场的 LLM 调用记录,
 * 逐条展开可查看完整提示词、调用参数与模型原始输出,
 * 供深度分析页排障与效果核对(失败调用同样留痕)。
 */
import { computed, onMounted, ref } from 'vue'
import {
  listLlmRequestLogs,
  type LlmRequestLog,
} from '@/api/match/analysis'

const props = defineProps<{
  /** 比赛 ID(日志按比赛维度过滤,球队维度分析不串入) */
  matchId: string
}>()

const logs = ref<LlmRequestLog[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
/** 当前展开明细的日志 ID 集合(可同时展开多条) */
const expandedLogIds = ref<Set<number>>(new Set())

/** 调用类型编码 -> 展示名 */
const ANALYSIS_TYPE_LABELS: Record<string, string> = {
  analysis: 'AI 综合分析',
  fundamental: 'AI 基本面分析',
  odds_trend: 'AI 赔率走势分析',
  team: '球队维度分析',
}

function typeLabel(log: LlmRequestLog): string {
  return ANALYSIS_TYPE_LABELS[log.analysis_type] ?? log.analysis_type
}

/** 服务商标识转展示名 */
const PROVIDER_LABELS: Record<string, string> = {
  qwen: '阿里云千问',
  ark: '火山方舟',
}

/** 调用耗时展示:毫秒转秒 */
function formatDuration(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} 秒` : `${ms} 毫秒`
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** token 用量摘要(缺失时返回空串,不占位) */
function tokenSummary(log: LlmRequestLog): string {
  if (log.total_tokens === null) return ''
  const parts = [`共 ${log.total_tokens} tokens`]
  if (log.prompt_tokens !== null && log.completion_tokens !== null) {
    parts.push(`(提示 ${log.prompt_tokens} / 输出 ${log.completion_tokens})`)
  }
  return parts.join(' ')
}

/** 调用参数摘要行(analysis_type 已作为类型徽章展示在头部,不在此重复) */
const PARAM_KEYS = ['temperature', 'max_tokens', 'timeout_seconds'] as const

function paramEntries(log: LlmRequestLog): { key: string; value: string }[] {
  return PARAM_KEYS.filter((key) => log.request_params[key] !== undefined).map(
    (key) => ({ key, value: String(log.request_params[key]) }),
  )
}

function toggleExpand(logId: number): void {
  const next = new Set(expandedLogIds.value)
  if (next.has(logId)) {
    next.delete(logId)
  } else {
    next.add(logId)
  }
  expandedLogIds.value = next
}

const successCount = computed(
  () => logs.value.filter((log) => log.status === 'SUCCESS').length,
)

async function load(): Promise<void> {
  isLoading.value = true
  error.value = null
  try {
    logs.value = await listLlmRequestLogs(props.matchId)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '分析日志加载失败'
  } finally {
    isLoading.value = false
  }
}

/** 供父组件在生成分析后刷新(成功与失败调用都会写日志) */
defineExpose({ refresh: load })

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="llm-log" aria-label="大模型调用日志">
    <header class="llm-log__header">
      <h3 class="llm-log__title">分析日志</h3>
      <button
        class="llm-log__refresh"
        type="button"
        :disabled="isLoading"
        @click="load"
      >
        {{ isLoading ? '加载中…' : '刷新' }}
      </button>
    </header>
    <p class="llm-log__hint">
      记录本场每次大模型调用的请求参数与响应结果(成功与失败均留痕),
      点击条目展开完整提示词与模型原始输出 · 仅供排障参考
    </p>

    <p v-if="error" class="llm-log__error" role="alert">{{ error }}</p>

    <p v-if="isLoading && logs.length === 0" class="llm-log__hint">加载中…</p>

    <template v-else>
      <p v-if="logs.length === 0" class="llm-log__empty">
        暂无调用记录 · 点击上方"生成 AI 分析"后可在此查看日志
      </p>

      <p v-else-if="successCount < logs.length" class="llm-log__hint">
        最近 {{ logs.length }} 次调用中 {{ successCount }} 次成功,
        {{ logs.length - successCount }} 次失败
      </p>

      <article
        v-for="log in logs"
        :key="log.log_id"
        class="llm-log__item"
        :class="{ 'llm-log__item--failed': log.status === 'FAILED' }"
      >
        <button
          class="llm-log__item-head"
          type="button"
          :aria-expanded="expandedLogIds.has(log.log_id)"
          @click="toggleExpand(log.log_id)"
        >
          <span
            class="llm-log__status"
            :class="`llm-log__status--${log.status.toLowerCase()}`"
          >
            {{ log.status === 'SUCCESS' ? '成功' : '失败' }}
          </span>
          <span class="llm-log__type">{{ typeLabel(log) }}</span>
          <span class="llm-log__model">
            {{ PROVIDER_LABELS[log.provider] ?? log.provider }} · {{ log.model }}
          </span>
          <span class="llm-log__meta">
            {{ formatTime(log.created_at) }} · {{ formatDuration(log.duration_ms) }}
            <template v-if="tokenSummary(log)"> · {{ tokenSummary(log) }}</template>
          </span>
          <span class="llm-log__chevron" aria-hidden="true">
            {{ expandedLogIds.has(log.log_id) ? '▾' : '▸' }}
          </span>
        </button>

        <div v-if="expandedLogIds.has(log.log_id)" class="llm-log__detail">
          <p v-if="log.error_message" class="llm-log__error">
            {{ log.error_message }}
            <template v-if="log.error_detail">:{{ log.error_detail }}</template>
          </p>

          <h4 class="llm-log__detail-title">请求参数</h4>
          <dl class="llm-log__params">
            <div v-for="entry in paramEntries(log)" :key="entry.key" class="llm-log__param">
              <dt>{{ entry.key }}</dt>
              <dd>{{ entry.value }}</dd>
            </div>
            <div class="llm-log__param">
              <dt>base_url</dt>
              <dd>{{ log.base_url }}</dd>
            </div>
            <div v-if="log.http_status !== null" class="llm-log__param">
              <dt>http_status</dt>
              <dd>{{ log.http_status }}</dd>
            </div>
          </dl>

          <h4 class="llm-log__detail-title">提示词</h4>
          <div
            v-for="(message, index) in log.request_messages"
            :key="index"
            class="llm-log__message"
          >
            <span class="llm-log__message-role">{{ message.role }}</span>
            <pre class="llm-log__pre">{{ message.content }}</pre>
          </div>

          <h4 class="llm-log__detail-title">响应结果(模型原始输出)</h4>
          <pre v-if="log.response_content" class="llm-log__pre">{{
            log.response_content
          }}</pre>
          <p v-else class="llm-log__hint">无响应内容(调用未返回即失败)</p>
        </div>
      </article>
    </template>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.llm-log {
  display: flex;
  flex-direction: column;
  gap: vars.$spacing-sm;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &__title {
    margin: 0;
    font-size: vars.$font-size-md;
  }

  &__refresh {
    padding: vars.$spacing-xs vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &:hover:not(:disabled) {
      border-color: vars.$color-primary;
      color: vars.$color-primary;
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  &__hint,
  &__error {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__empty {
    padding: vars.$spacing-lg;
    border: 1px dashed vars.$color-border;
    border-radius: vars.$border-radius;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
    text-align: center;
  }

  &__item {
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    overflow: hidden;

    &--failed {
      border-color: rgba(214, 69, 65, 0.45);
    }
  }

  &__item-head {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: vars.$spacing-sm;
    width: 100%;
    padding: vars.$spacing-sm vars.$spacing-md;
    border: none;
    background: transparent;
    text-align: left;
    cursor: pointer;

    &:hover {
      background: vars.$color-surface-hover;
    }
  }

  &__status {
    padding: 2px vars.$spacing-sm;
    border-radius: vars.$border-radius;
    font-size: vars.$font-size-sm;
    font-weight: 600;

    &--success {
      background: rgba(34, 139, 34, 0.12);
      color: vars.$color-positive;
    }

    &--failed {
      background: rgba(214, 69, 65, 0.12);
      color: vars.$color-danger;
    }
  }

  &__type {
    font-size: vars.$font-size-sm;
    font-weight: 600;
    white-space: nowrap;
  }

  &__model,
  &__meta {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    white-space: nowrap;
  }

  &__model {
    flex: 1;
    min-width: 120px;
  }

  &__chevron {
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
  }

  &__detail {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-sm;
    padding: vars.$spacing-md;
    border-top: 1px solid vars.$color-border;
    background: vars.$color-surface-hover;
  }

  &__detail-title {
    margin: vars.$spacing-xs 0 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-primary;
  }

  &__params {
    display: flex;
    flex-wrap: wrap;
    gap: vars.$spacing-sm;
    margin: 0;
  }

  &__param {
    display: flex;
    align-items: baseline;
    gap: vars.$spacing-xs;
    padding: vars.$spacing-xs vars.$spacing-sm;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    font-size: vars.$font-size-sm;

    dt {
      color: vars.$color-text-secondary;
    }

    dd {
      margin: 0;
      font-weight: 600;
    }
  }

  &__message {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
  }

  &__message-role {
    align-self: flex-start;
    padding: 1px vars.$spacing-sm;
    border-radius: vars.$border-radius;
    background: vars.$color-primary;
    color: #fff;
    font-size: vars.$font-size-sm;
  }

  &__pre {
    margin: 0;
    padding: vars.$spacing-sm vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    color: vars.$color-text-primary;
    font-family: inherit;
    font-size: vars.$font-size-sm;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 420px;
    overflow-y: auto;
  }
}
</style>
