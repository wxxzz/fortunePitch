<script setup lang="ts">
/**
 * 今日焦点推荐卡片(赛事中心右侧边栏):
 * 展示推荐场次、策略类型及置信度星级,点击跳转深度分析页。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useStrategyStore } from '@/stores/strategy'

const router = useRouter()
const strategyStore = useStrategyStore()
const { recommendations, isLoading } = storeToRefs(strategyStore)

/** 按置信度取前 3 条作为今日焦点 */
const focusList = computed(() =>
  [...recommendations.value]
    .sort((a, b) => b.confidence_score - a.confidence_score)
    .slice(0, 3),
)

/** 置信度转星级(1-5 星) */
const starCount = (confidence: number): number =>
  Math.max(1, Math.round(confidence * 5))

const strategyLabel: Record<string, string> = {
  WIN_DRAW_LOSS: '胜平负',
  HANDICAP: '让球盘',
  SCORE: '比分',
}

function handleJump(matchId: string): void {
  void router.push(`/match/${matchId}`)
}
</script>

<template>
  <div class="focus-card">
    <h3 class="focus-card__title">今日焦点推荐</h3>

    <p v-if="isLoading" class="focus-card__hint">加载中…</p>
    <p v-else-if="focusList.length === 0" class="focus-card__hint">暂无推荐</p>

    <button
      v-for="rec in focusList"
      :key="rec.recommend_id"
      type="button"
      class="focus-card__item"
      @click="handleJump(rec.match_id)"
    >
      <div class="focus-card__item-top">
        <span class="focus-card__match">{{ rec.match_id }}</span>
        <span class="focus-card__type">
          {{ strategyLabel[rec.strategy_type] ?? rec.strategy_type }}
        </span>
      </div>
      <div class="focus-card__outcome">{{ rec.predicted_outcome }}</div>
      <div class="focus-card__stars" :aria-label="`置信度 ${(rec.confidence_score * 100).toFixed(0)}%`">
        <span
          v-for="star in 5"
          :key="star"
          class="focus-card__star"
          :class="{ 'focus-card__star--on': star <= starCount(rec.confidence_score) }"
        >
          ★
        </span>
        <span class="focus-card__confidence">
          {{ (rec.confidence_score * 100).toFixed(0) }}%
        </span>
      </div>
    </button>
  </div>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.focus-card {
  padding: vars.$spacing-md;
  background: vars.$color-surface;
  border: 1px solid vars.$color-border;
  border-radius: vars.$border-radius;

  &__title {
    margin: 0 0 vars.$spacing-md;
    font-size: vars.$font-size-md;
  }

  &__hint {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__item {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
    width: 100%;
    margin-bottom: vars.$spacing-sm;
    padding: vars.$spacing-md;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-bg;
    text-align: left;
    cursor: pointer;

    &:hover {
      border-color: vars.$color-primary;
    }
  }

  &__item-top {
    display: flex;
    justify-content: space-between;
    font-size: vars.$font-size-sm;
  }

  &__match {
    font-weight: 600;
  }

  &__type {
    color: vars.$color-text-secondary;
  }

  &__outcome {
    color: vars.$color-positive;
    font-weight: 700;
  }

  &__stars {
    display: flex;
    align-items: center;
    gap: 2px;
  }

  &__star {
    color: vars.$color-border;

    &--on {
      color: vars.$color-warning;
    }
  }

  &__confidence {
    margin-left: vars.$spacing-xs;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }
}
</style>
