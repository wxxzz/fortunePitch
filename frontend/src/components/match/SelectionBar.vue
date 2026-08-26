<script setup lang="ts">
/**
 * 底部选注栏(有选注时固定悬浮):
 * 已选数量 / 可移除选注标签 / 投注模式切换 / 唤起方案确认弹窗。
 */
import { storeToRefs } from 'pinia'
import { useSelectionStore, type BetMode } from '@/stores/selection'

const emit = defineEmits<{
  (e: 'open-confirm'): void
}>()

const selectionStore = useSelectionStore()
const { selectionList, count, mode } = storeToRefs(selectionStore)
const { remove, clear, setMode } = selectionStore

const MODES: Array<{ value: BetMode; label: string }> = [
  { value: 'single', label: '单关' },
  { value: 'parlay', label: '串关' },
  { value: 'mixed', label: '混合' },
]
</script>

<template>
  <Transition name="selection-bar">
    <div v-if="count > 0" class="selection-bar">
      <div class="selection-bar__tags">
        <span class="selection-bar__count">已选 {{ count }} 项</span>
        <TransitionGroup name="selection-tag" tag="div" class="selection-bar__tag-list">
          <span
            v-for="item in selectionList"
            :key="`${item.matchId}:${item.poolCode}:${item.optionCode}`"
            class="selection-bar__tag"
          >
            {{ item.matchName }} · {{ item.optionLabel }}
            <button
              class="selection-bar__tag-remove"
              type="button"
              aria-label="移除选注"
              @click="remove(`${item.matchId}:${item.poolCode}:${item.optionCode}`)"
            >
              &times;
            </button>
          </span>
        </TransitionGroup>
        <button class="selection-bar__clear" type="button" @click="clear">
          清空
        </button>
      </div>

      <div class="selection-bar__actions">
        <div class="selection-bar__mode" role="group" aria-label="投注模式">
          <button
            v-for="m in MODES"
            :key="m.value"
            class="selection-bar__mode-btn"
            :class="{ 'selection-bar__mode-btn--active': mode === m.value }"
            type="button"
            @click="setMode(m.value)"
          >
            {{ m.label }}
          </button>
        </div>
        <button class="selection-bar__submit" type="button" @click="emit('open-confirm')">
          查看方案
        </button>
      </div>
    </div>
  </Transition>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.selection-bar {
  position: fixed;
  left: vars.$sidebar-width;
  right: 0;
  bottom: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: vars.$spacing-lg;
  padding: vars.$spacing-md vars.$spacing-lg;
  background: vars.$color-surface;
  border-top: 1px solid vars.$color-border;
  box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.08);

  @media (max-width: 900px) {
    left: 0;
    flex-direction: column;
    align-items: stretch;
    gap: vars.$spacing-sm;
  }

  &__tags {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    min-width: 0;
  }

  &__count {
    flex-shrink: 0;
    padding: 2px vars.$spacing-sm;
    border-radius: 999px;
    background: vars.$color-primary;
    color: #fff;
    font-size: vars.$font-size-sm;
    font-weight: 600;
  }

  &__tag-list {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    min-width: 0;
    overflow-x: auto;
    scrollbar-width: none;

    &::-webkit-scrollbar {
      display: none;
    }
  }

  &__tag {
    display: inline-flex;
    align-items: center;
    gap: vars.$spacing-xs;
    flex-shrink: 0;
    padding: 2px vars.$spacing-sm;
    border: 1px solid vars.$color-primary;
    border-radius: 999px;
    color: vars.$color-primary;
    font-size: vars.$font-size-sm;
    white-space: nowrap;
  }

  &__tag-remove {
    border: none;
    background: transparent;
    color: inherit;
    font-size: 14px;
    line-height: 1;
    padding: 0;
    cursor: pointer;

    &:hover {
      color: vars.$color-danger;
    }
  }

  &__clear {
    flex-shrink: 0;
    border: none;
    background: transparent;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &:hover {
      color: vars.$color-danger;
    }
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: vars.$spacing-md;
    flex-shrink: 0;
  }

  &__mode {
    display: flex;
    border: 1px solid vars.$color-border;
    border-radius: 999px;
    overflow: hidden;
  }

  &__mode-btn {
    padding: 4px vars.$spacing-md;
    border: none;
    background: vars.$color-surface;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &--active {
      background: vars.$color-primary;
      color: #fff;
    }
  }

  &__submit {
    padding: 8px vars.$spacing-lg;
    border: none;
    border-radius: 999px;
    background: vars.$color-primary;
    color: #fff;
    font-size: vars.$font-size-md;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s;

    &:hover {
      background: #0f5132;
    }
  }
}

// 进出场动画
.selection-bar-enter-active,
.selection-bar-leave-active {
  transition: transform 0.25s ease, opacity 0.25s ease;
}

.selection-bar-enter-from,
.selection-bar-leave-to {
  transform: translateY(100%);
  opacity: 0;
}

.selection-tag-enter-active,
.selection-tag-leave-active {
  transition: opacity 0.2s ease;
}

.selection-tag-enter-from,
.selection-tag-leave-to {
  opacity: 0;
}
</style>
