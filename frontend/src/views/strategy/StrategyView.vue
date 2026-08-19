<script setup lang="ts">
/**
 * 策略与赔率模块视图:赔率走势 / AI 推荐(含归因标签)/ 模拟决策复盘 / 凯利指数。
 */
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useStrategyStore } from '@/stores/strategy'
import OddsTrendChart, {
  type OddsTrendPoint,
} from '@/components/strategy/OddsTrendChart.vue'

const strategyStore = useStrategyStore()
const { oddsHistory, recommendations, decisions, kellyResult, isLoading, error } =
  storeToRefs(strategyStore)

onMounted(() => {
  void strategyStore.fetchAll()
})

/** 将欧赔历史按采集时间聚合为走势图数据 */
const euroOddsTrend = computed<OddsTrendPoint[]>(() => {
  const euroRecords = oddsHistory.value.filter((o) => o.market_type === 'EURO_ODDS')
  return euroRecords.map((o) => ({
    time: new Date(o.update_time).toLocaleDateString(),
    homeWin: o.initial_value,
    draw: o.current_value,
    awayWin: o.initial_value,
  }))
})

// 凯利计算表单(本地状态)
const modelProb = ref<number>(0.55)
const decimalOdds = ref<number>(2.0)

async function handleKelly(): Promise<void> {
  await strategyStore.fetchKelly(modelProb.value, decimalOdds.value)
}

const statusLabel: Record<string, string> = {
  WIN: '命中',
  LOSS: '未中',
  PUSH: '走盘',
}
</script>

<template>
  <section class="strategy-view">
    <h2 class="strategy-view__title">策略与赔率 · 市场数据与 AI 推荐</h2>

    <p v-if="error" class="strategy-view__error" role="alert">{{ error }}</p>
    <p v-if="isLoading" class="strategy-view__hint">加载中…</p>

    <h3 class="strategy-view__section-title">欧赔走势</h3>
    <OddsTrendChart v-if="euroOddsTrend.length > 0" :points="euroOddsTrend" />
    <p v-else class="strategy-view__hint">暂无欧赔数据</p>

    <h3 class="strategy-view__section-title">AI 策略推荐(含归因标签)</h3>
    <table class="strategy-view__table">
      <thead>
        <tr>
          <th>比赛</th><th>策略类型</th><th>推荐结果</th><th>置信度</th><th>归因标签</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="rec in recommendations" :key="rec.recommend_id">
          <td>{{ rec.match_id }}</td>
          <td>{{ rec.strategy_type }}</td>
          <td>{{ rec.predicted_outcome }}</td>
          <td>{{ (rec.confidence_score * 100).toFixed(0) }}%</td>
          <td>
            <span
              v-for="tag in rec.logic_tags ?? []"
              :key="tag"
              class="strategy-view__tag"
            >
              {{ tag }}
            </span>
          </td>
        </tr>
        <tr v-if="recommendations.length === 0">
          <td colspan="5" class="strategy-view__empty">暂无推荐</td>
        </tr>
      </tbody>
    </table>

    <h3 class="strategy-view__section-title">凯利指数(量化分析,不构成投注建议)</h3>
    <div class="strategy-view__kelly">
      <label class="strategy-view__field">
        <span>模型概率</span>
        <input v-model.number="modelProb" type="number" min="0.01" max="0.99" step="0.01" />
      </label>
      <label class="strategy-view__field">
        <span>十进制赔率</span>
        <input v-model.number="decimalOdds" type="number" min="1.01" step="0.05" />
      </label>
      <button class="strategy-view__submit" type="button" @click="handleKelly">
        计算
      </button>
      <span v-if="kellyResult" class="strategy-view__kelly-result">
        建议资金比例:{{ (kellyResult.kelly_fraction * 100).toFixed(1) }}%
      </span>
    </div>

    <h3 class="strategy-view__section-title">模拟决策复盘</h3>
    <table class="strategy-view__table">
      <thead>
        <tr>
          <th>决策 ID</th><th>用户</th><th>推荐 ID</th><th>注额(模拟)</th><th>状态</th><th>盈亏</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="decision in decisions" :key="decision.decision_id">
          <td>{{ decision.decision_id }}</td>
          <td>{{ decision.user_id }}</td>
          <td>{{ decision.recommend_id }}</td>
          <td>{{ decision.stake_amount.toFixed(2) }}</td>
          <td
            class="strategy-view__status"
            :class="`strategy-view__status--${decision.result_status.toLowerCase()}`"
          >
            {{ statusLabel[decision.result_status] ?? decision.result_status }}
          </td>
          <td>{{ decision.profit_loss?.toFixed(2) ?? '-' }}</td>
        </tr>
        <tr v-if="decisions.length === 0">
          <td colspan="6" class="strategy-view__empty">暂无决策记录</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.strategy-view {
  max-width: 1080px;
  margin: 0 auto;

  &__title {
    margin: 0 0 vars.$spacing-lg;
  }

  &__section-title {
    margin: vars.$spacing-lg 0 vars.$spacing-sm;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__hint {
    color: vars.$color-text-secondary;
  }

  &__table {
    width: 100%;
    border-collapse: collapse;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;

    th,
    td {
      padding: vars.$spacing-sm vars.$spacing-md;
      border-bottom: 1px solid vars.$color-border;
      text-align: left;
    }

    th {
      background: vars.$color-surface-hover;
    }
  }

  &__tag {
    display: inline-block;
    margin: 0 vars.$spacing-xs vars.$spacing-xs 0;
    padding: vars.$spacing-xs vars.$spacing-sm;
    background: vars.$color-primary-light;
    border-radius: vars.$border-radius;
    font-size: vars.$font-size-sm;
    color: vars.$color-primary;
  }

  &__kelly {
    display: flex;
    align-items: flex-end;
    gap: vars.$spacing-lg;
    padding: vars.$spacing-lg;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__field {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;

    input {
      padding: vars.$spacing-sm;
      border: 1px solid vars.$color-border;
      border-radius: vars.$border-radius;
    }
  }

  &__submit {
    padding: vars.$spacing-sm vars.$spacing-lg;
    border: none;
    border-radius: vars.$border-radius;
    background: vars.$color-primary;
    color: #fff;
    cursor: pointer;
  }

  &__kelly-result {
    font-weight: 600;
    color: vars.$color-primary;
  }

  &__status--win {
    color: vars.$color-primary;
    font-weight: 600;
  }

  &__status--loss {
    color: vars.$color-danger;
    font-weight: 600;
  }

  &__empty {
    color: vars.$color-text-secondary;
    text-align: center;
  }
}
</style>
