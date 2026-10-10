<script setup lang="ts">
/**
 * AI 串关候选方案卡片:
 * 展示自动组出的 2-4 串候选(逐腿快照 + 组合赔率/置信度/EV/凯利),
 * 可一键保存为正式模拟串关方案(经串关组合规则校验)。
 *
 * 组合置信度按腿间独立近似(浅盘日让平存在相关性);
 * 注额均为模拟数据,分析结果仅供参考,不构成投注建议。
 */
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useStrategyStore } from '@/stores/strategy'
import { convertAiParlayPlan } from '@/api/strategy/aiPick'

const strategyStore = useStrategyStore()
const { aiPlans } = storeToRefs(strategyStore)

/** 默认每注模拟注额 */
const DEFAULT_STAKE_PER_BET = 100
const stakes = ref<Record<number, number>>({})
const convertingIds = ref<Set<number>>(new Set())
const convertMessage = ref<string | null>(null)

async function handleConvert(planId: number): Promise<void> {
  convertingIds.value = new Set(convertingIds.value).add(planId)
  convertMessage.value = null
  try {
    const result = await convertAiParlayPlan(planId, {
      stake_per_bet: stakes.value[planId] ?? DEFAULT_STAKE_PER_BET,
    })
    convertMessage.value = result.created
      ? `已保存为模拟串关方案 #${result.scheme.scheme_id}(${result.scheme.bet_count} 注)`
      : `该候选已保存过(方案 #${result.scheme.scheme_id})`
    // 保存状态与方案清单同步刷新
    await strategyStore.fetchAll()
  } catch (err) {
    convertMessage.value = err instanceof Error ? err.message : '保存失败'
  } finally {
    const next = new Set(convertingIds.value)
    next.delete(planId)
    convertingIds.value = next
  }
}
</script>

<template>
  <div class="ai-parlay-plan">
    <p v-if="convertMessage" class="ai-parlay-plan__message" role="status">
      {{ convertMessage }}
    </p>

    <div v-if="aiPlans.length === 0" class="ai-parlay-plan__empty">
      暂无串关候选 · 生成推荐后将自动从高置信代表腿组 2-4 串方案
    </div>

    <div
      v-for="plan in aiPlans"
      :key="plan.plan_id"
      class="ai-parlay-plan__card"
    >
      <div class="ai-parlay-plan__header">
        <span class="ai-parlay-plan__name">{{ plan.plan_name }}</span>
        <span class="ai-parlay-plan__desc">{{ plan.plan_desc }}</span>
      </div>

      <ul class="ai-parlay-plan__legs">
        <li
          v-for="leg in plan.legs"
          :key="`${plan.plan_id}-${leg.match_id}-${leg.play_code}`"
          class="ai-parlay-plan__leg"
          :class="{ 'ai-parlay-plan__leg--contrarian': leg.is_contrarian }"
        >
          <span class="ai-parlay-plan__leg-num">{{ leg.match_num_str }}</span>
          <span class="ai-parlay-plan__leg-match">{{ leg.match_name }}</span>
          <span class="ai-parlay-plan__leg-play">{{ leg.play_name }} · {{ leg.option_label }} @ {{ leg.odds.toFixed(2) }}</span>
          <span class="ai-parlay-plan__leg-confidence">
            {{ (leg.confidence * 100).toFixed(0) }}%{{ leg.is_contrarian ? ' · 逆向' : '' }}
          </span>
        </li>
      </ul>

      <div class="ai-parlay-plan__metrics">
        <span>组合赔率 <strong>{{ plan.combined_odds.toFixed(2) }}</strong></span>
        <span>组合置信度 <strong>{{ (plan.combined_confidence * 100).toFixed(1) }}%</strong></span>
        <span>EV <strong>{{ (plan.ev * 100).toFixed(1) }}%</strong></span>
        <span>凯利 <strong>{{ (plan.kelly * 100).toFixed(1) }}%</strong></span>
        <span>逆向腿 <strong>{{ plan.contrarian_count }}</strong>/2</span>
      </div>

      <div class="ai-parlay-plan__footer">
        <template v-if="plan.scheme_id !== null">
          <span class="ai-parlay-plan__done">已保存为方案 #{{ plan.scheme_id }}</span>
        </template>
        <template v-else>
          <input
            v-model.number="stakes[plan.plan_id]"
            type="number"
            min="1"
            max="10000"
            :placeholder="String(DEFAULT_STAKE_PER_BET)"
            aria-label="每注模拟注额"
          />
          <button
            type="button"
            :disabled="convertingIds.has(plan.plan_id)"
            @click="handleConvert(plan.plan_id)"
          >
            {{ convertingIds.has(plan.plan_id) ? '保存中…' : '保存为模拟串关方案' }}
          </button>
        </template>
      </div>
    </div>

    <p class="ai-parlay-plan__disclaimer">
      组合置信度按腿间独立近似(浅盘日让平存在相关性);逆向腿数不超过 2 条(校准规则)。
      模拟投注 · 分析结果仅供参考,不构成投注建议。
    </p>
  </div>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.ai-parlay-plan {
  display: flex;
  flex-direction: column;
  gap: vars.$spacing-md;

  &__message {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-primary;
  }

  &__empty {
    padding: vars.$spacing-lg;
    border: 1px dashed vars.$color-border;
    border-radius: vars.$border-radius;
    color: vars.$color-text-secondary;
    text-align: center;
  }

  &__card {
    padding: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__header {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: vars.$spacing-sm;
    margin-bottom: vars.$spacing-sm;
  }

  &__name {
    font-size: vars.$font-size-md;
    font-weight: 700;
  }

  &__desc {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__legs {
    margin: 0 0 vars.$spacing-sm;
    padding: 0;
    list-style: none;
  }

  &__leg {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: vars.$spacing-sm;
    padding: vars.$spacing-xs 0;

    &--contrarian .ai-parlay-plan__leg-confidence {
      color: vars.$color-warning;
    }
  }

  &__leg-num {
    font-weight: 600;
    white-space: nowrap;
  }

  &__leg-match {
    white-space: nowrap;
  }

  &__leg-play {
    color: vars.$color-text-secondary;
    white-space: nowrap;
  }

  &__leg-confidence {
    margin-left: auto;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    white-space: nowrap;
  }

  &__metrics {
    display: flex;
    flex-wrap: wrap;
    gap: vars.$spacing-lg;
    padding: vars.$spacing-sm 0;
    border-top: 1px solid vars.$color-border;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;

    strong {
      color: vars.$color-text-primary;
    }
  }

  &__footer {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    padding-top: vars.$spacing-sm;
    border-top: 1px solid vars.$color-border;

    input {
      width: 90px;
      padding: vars.$spacing-xs vars.$spacing-sm;
      border: 1px solid vars.$color-border;
      border-radius: vars.$border-radius;
    }

    button {
      padding: vars.$spacing-xs vars.$spacing-lg;
      border: 1px solid vars.$color-primary;
      border-radius: vars.$border-radius;
      background: vars.$color-surface;
      color: vars.$color-primary;
      cursor: pointer;

      &:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
    }
  }

  &__done {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__disclaimer {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }
}
</style>
