<script setup lang="ts">
/**
 * 今日焦点推荐卡片(赛事中心右侧边栏):
 * 数据源优先取 AI 策略推荐(最新生效批次,含赔率快照),
 * 为空时回退到手工/自选推荐记录;点击跳转深度分析页。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useStrategyStore } from '@/stores/strategy'

const router = useRouter()
const strategyStore = useStrategyStore()
const { aiPicks, recommendations, isLoading } = storeToRefs(strategyStore)

/** 焦点条目(AI 推荐与手工推荐归一后的展示结构) */
interface FocusItem {
  key: number
  matchId: string
  matchLabel: string
  playLabel: string
  outcome: string
  confidence: number
}

const strategyLabel: Record<string, string> = {
  WIN_DRAW_LOSS: '胜平负',
  HANDICAP: '让球盘',
  SCORE: '比分',
  TOTAL_GOALS: '总进球',
  HALF_FULL: '半全场',
}

/** 按置信度取前 3 条作为今日焦点:优先 AI 推荐,空时回退推荐记录 */
const focusList = computed<FocusItem[]>(() => {
  if (aiPicks.value.length > 0) {
    return [...aiPicks.value]
      .sort((a, b) => b.confidence - a.confidence)
      .slice(0, 3)
      .map((pick) => ({
        key: pick.pick_id,
        matchId: pick.match_id,
        matchLabel: pick.match_num_str || pick.match_id,
        playLabel: pick.play_name,
        outcome: `${pick.option_label} @ ${pick.odds.toFixed(2)}`,
        confidence: pick.confidence,
      }))
  }
  return [...recommendations.value]
    .sort((a, b) => b.confidence_score - a.confidence_score)
    .slice(0, 3)
    .map((rec) => ({
      key: rec.recommend_id,
      matchId: rec.match_id,
      matchLabel: rec.match_id,
      playLabel: strategyLabel[rec.strategy_type] ?? rec.strategy_type,
      outcome: rec.predicted_outcome,
      confidence: rec.confidence_score,
    }))
})

/** 置信度转星级(1-5 星) */
const starCount = (confidence: number): number =>
  Math.max(1, Math.round(confidence * 5))

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
      v-for="item in focusList"
      :key="item.key"
      type="button"
      class="focus-card__item"
      @click="handleJump(item.matchId)"
    >
      <div class="focus-card__item-top">
        <span class="focus-card__match">{{ item.matchLabel }}</span>
        <span class="focus-card__type">{{ item.playLabel }}</span>
      </div>
      <div class="focus-card__outcome">{{ item.outcome }}</div>
      <div class="focus-card__stars" :aria-label="`置信度 ${(item.confidence * 100).toFixed(0)}%`">
        <span
          v-for="star in 5"
          :key="star"
          class="focus-card__star"
          :class="{ 'focus-card__star--on': star <= starCount(item.confidence) }"
        >
          ★
        </span>
        <span class="focus-card__confidence">
          {{ (item.confidence * 100).toFixed(0) }}%
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
