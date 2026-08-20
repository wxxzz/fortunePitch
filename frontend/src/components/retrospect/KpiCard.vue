<script setup lang="ts">
/**
 * 复盘中心核心指标卡片。
 */
interface Props {
  /** 指标名称 */
  label: string
  /** 指标值(展示文本) */
  value: string
  /** 语义色调:up=正向(红),down=负向(绿),flat=中性 */
  tone?: 'up' | 'down' | 'flat'
}

withDefaults(defineProps<Props>(), {
  tone: 'flat',
})
</script>

<template>
  <div class="kpi-card" :class="`kpi-card--${tone}`">
    <span class="kpi-card__label">{{ label }}</span>
    <strong class="kpi-card__value">{{ value }}</strong>
  </div>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.kpi-card {
  display: flex;
  flex-direction: column;
  gap: vars.$spacing-xs;
  flex: 1;
  padding: vars.$spacing-lg;
  background: vars.$color-surface;
  border: 1px solid vars.$color-border;
  border-top: 3px solid vars.$color-neutral;
  border-radius: vars.$border-radius;

  &__label {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__value {
    font-size: 22px;
  }

  // 红=正向/利好,绿=负向/利空
  &--up {
    border-top-color: vars.$color-positive;

    .kpi-card__value {
      color: vars.$color-positive;
    }
  }

  &--down {
    border-top-color: vars.$color-negative;

    .kpi-card__value {
      color: vars.$color-negative;
    }
  }
}
</style>
