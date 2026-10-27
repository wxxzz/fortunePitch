<script setup lang="ts">
/**
 * 深度分析 · 其他信息 Tab。
 *
 * 人工录入的场外情报(伤停/阵型/其他,自由文本),保存后自动注入
 * AI 综合分析与基本面分析的提示词。表单状态由父组件持有(与顶部
 * 对战卡片的阵型摘要共享),切换 Tab 不丢编辑中内容。
 */
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
import {
  EXTRA_FIELD_MAX_LENGTH,
  type MatchExtraInfoState,
} from '@/composables/useMatchExtraInfo'

defineProps<{ state: MatchExtraInfoState }>()
</script>

<template>
  <section class="extra-info-tab">
    <p class="extra-info-tab__hint">
      人工录入的场外情报(自由文本),保存后自动注入 AI 综合分析与基本面分析的
      提示词,作为"人工录入补充信息"证据段;三个字段均为空时不注入。
      重新保存后需重新生成 AI 分析才会体现最新内容。
    </p>

    <p v-if="state.loadError" class="extra-info-tab__error" role="alert">
      {{ state.loadError }}
      <button
        class="extra-info-tab__retry"
        type="button"
        @click="state.load"
      >
        重新加载
      </button>
    </p>
    <SkeletonBlock v-else-if="state.isLoading" :height="320" label="加载补充信息…" />

    <template v-else>
      <label class="extra-info-tab__field">
        <span class="extra-info-tab__label">伤停信息</span>
        <textarea
          v-model="state.form.injuries"
          rows="6"
          :maxlength="EXTRA_FIELD_MAX_LENGTH"
          placeholder="双方伤停/停赛球员与影响评估,如:主队中场核心累积黄牌停赛;客队主力中卫拉伤缺阵"
        />
      </label>

      <label class="extra-info-tab__field">
        <span class="extra-info-tab__label">阵型信息</span>
        <textarea
          v-model="state.form.formations"
          rows="4"
          :maxlength="EXTRA_FIELD_MAX_LENGTH"
          placeholder="预计首发阵型/战术打法,如:主队 4-3-3 高位压迫;客队 4-2-3-1 防守反击"
        />
      </label>

      <label class="extra-info-tab__field">
        <span class="extra-info-tab__label">其他补充</span>
        <textarea
          v-model="state.form.other_notes"
          rows="4"
          :maxlength="EXTRA_FIELD_MAX_LENGTH"
          placeholder="天气/裁判/战意等其他值得注意的情报"
        />
      </label>

      <div class="extra-info-tab__llm-toolbar">
        <button
          class="extra-info-tab__llm-button"
          type="button"
          :disabled="state.isSaving"
          :aria-busy="state.isSaving"
          @click="state.save"
        >
          {{ state.isSaving ? '保存中…' : '保存补充信息' }}
        </button>
        <p v-if="state.isDirty" class="extra-info-tab__dirty" role="status">
          有未保存的更改,切换页签前请先保存
        </p>
        <p v-if="state.updatedAt" class="extra-info-tab__hint">
          最近保存:{{ new Date(state.updatedAt).toLocaleString() }}
        </p>
      </div>

      <p v-if="state.saveMessage" class="extra-info-tab__saved" role="status">
        {{ state.saveMessage }}
      </p>
      <p v-if="state.saveError" class="extra-info-tab__error" role="alert">
        {{ state.saveError }}
      </p>
    </template>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;
@use './detail-shared' as shared;

.extra-info-tab {
  @include shared.panel;
  @include shared.actions;

  &__field {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
  }

  &__label {
    font-size: vars.$font-size-sm;
    font-weight: 600;
    color: vars.$color-text-primary;
  }

  textarea {
    padding: vars.$spacing-sm vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    color: vars.$color-text-primary;
    font-size: vars.$font-size-sm;
    line-height: 1.6;
    resize: vertical;

    &:focus {
      outline: none;
      border-color: vars.$color-primary;
    }
  }

  &__dirty {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-warning;
  }

  &__retry {
    margin-left: vars.$spacing-sm;
    padding: 0;
    border: none;
    background: transparent;
    color: vars.$color-primary;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &:hover {
      text-decoration: underline;
    }
  }

  &__saved {
    margin: 0;
    padding: vars.$spacing-sm vars.$spacing-md;
    border-radius: vars.$border-radius;
    background: vars.$color-primary-light;
    color: vars.$color-primary;
    font-size: vars.$font-size-sm;
  }
}
</style>
