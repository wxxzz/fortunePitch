<script setup lang="ts">
/**
 * 泊松比分预测器:输入主客队期望进球(xG),展示 Dixon-Coles 模型预测结果。
 */
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useAnalyticsStore } from '@/stores/analytics'

const analyticsStore = useAnalyticsStore()
const { poissonResult, isPredictionLoading, predictionError } = storeToRefs(analyticsStore)

const homeXg = ref<number>(1.5)
const awayXg = ref<number>(1.1)

async function handlePredict(): Promise<void> {
  await analyticsStore.fetchPoissonPrediction(homeXg.value, awayXg.value)
}

const probabilityPercent = (value: number): string => `${(value * 100).toFixed(1)}%`
</script>

<template>
  <div class="poisson-predictor">
    <h3 class="poisson-predictor__title">Dixon-Coles 泊松比分预测</h3>

    <div class="poisson-predictor__panel">
      <label class="poisson-predictor__field">
        <span>主队期望进球 (xG)</span>
        <input v-model.number="homeXg" type="number" min="0.1" max="10" step="0.1" />
      </label>
      <label class="poisson-predictor__field">
        <span>客队期望进球 (xG)</span>
        <input v-model.number="awayXg" type="number" min="0.1" max="10" step="0.1" />
      </label>
      <button
        class="poisson-predictor__submit"
        type="button"
        :disabled="isPredictionLoading"
        @click="handlePredict"
      >
        {{ isPredictionLoading ? '计算中…' : '运行模型' }}
      </button>
    </div>

    <p v-if="predictionError" class="poisson-predictor__error" role="alert">
      {{ predictionError }}
    </p>

    <div v-if="poissonResult" class="poisson-predictor__result">
      <div class="poisson-predictor__probs">
        <div class="poisson-predictor__prob">
          <span class="poisson-predictor__prob-label">主胜</span>
          <strong class="poisson-predictor__prob-value">
            {{ probabilityPercent(poissonResult.probabilities.home_win) }}
          </strong>
        </div>
        <div class="poisson-predictor__prob">
          <span class="poisson-predictor__prob-label">平局</span>
          <strong class="poisson-predictor__prob-value">
            {{ probabilityPercent(poissonResult.probabilities.draw) }}
          </strong>
        </div>
        <div class="poisson-predictor__prob">
          <span class="poisson-predictor__prob-label">客胜</span>
          <strong class="poisson-predictor__prob-value">
            {{ probabilityPercent(poissonResult.probabilities.away_win) }}
          </strong>
        </div>
      </div>

      <table class="poisson-predictor__table">
        <thead>
          <tr><th>比分</th><th>概率</th></tr>
        </thead>
        <tbody>
          <tr
            v-for="score in poissonResult.top_scores"
            :key="`${score.home_goals}-${score.away_goals}`"
          >
            <td>{{ score.home_goals }} : {{ score.away_goals }}</td>
            <td>{{ probabilityPercent(score.probability) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.poisson-predictor {
  margin-top: vars.$spacing-lg;

  &__title {
    margin: 0 0 vars.$spacing-md;
  }

  &__panel {
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
      font-size: vars.$font-size-md;
    }
  }

  &__submit {
    padding: vars.$spacing-sm vars.$spacing-lg;
    border: none;
    border-radius: vars.$border-radius;
    background: vars.$color-primary;
    color: #fff;
    cursor: pointer;

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  }

  &__error {
    color: vars.$color-danger;
  }

  &__probs {
    display: flex;
    gap: vars.$spacing-lg;
    margin: vars.$spacing-md 0;
  }

  &__prob {
    display: flex;
    flex-direction: column;
    align-items: center;
    flex: 1;
    padding: vars.$spacing-md;
    background: vars.$color-primary-light;
    border-radius: vars.$border-radius;

    &-label {
      font-size: vars.$font-size-sm;
      color: vars.$color-text-secondary;
    }

    &-value {
      font-size: vars.$font-size-lg;
      color: vars.$color-primary;
    }
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
}
</style>
