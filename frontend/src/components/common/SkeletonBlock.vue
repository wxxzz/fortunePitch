<script setup lang="ts">
/**
 * 骨架屏占位块:高阶数据/模型计算加载时的专业加载态。
 */
interface Props {
  /** 高度(px) */
  height?: number
  /** 宽度,默认 100% */
  width?: string
  /** 是否显示"模型计算中"文案 */
  label?: string
}

withDefaults(defineProps<Props>(), {
  height: 120,
  width: '100%',
  label: '模型计算中…',
})
</script>

<template>
  <div class="skeleton-block" :aria-label="label">
    <div class="skeleton-block__bar" />
    <p class="skeleton-block__label">{{ label }}</p>
  </div>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.skeleton-block {
  display: flex;
  flex-direction: column;
  gap: vars.$spacing-sm;

  &__bar {
    height: v-bind('`${height}px`');
    width: v-bind('width');
    border-radius: vars.$border-radius;
    background: linear-gradient(
      90deg,
      vars.$color-surface-hover 25%,
      #f4f6f8 50%,
      vars.$color-surface-hover 75%
    );
    background-size: 200% 100%;
    animation: skeleton-shimmer 1.4s ease infinite;
  }

  &__label {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    text-align: center;
  }
}

@keyframes skeleton-shimmer {
  0% {
    background-position: 200% 0;
  }

  100% {
    background-position: -200% 0;
  }
}
</style>
