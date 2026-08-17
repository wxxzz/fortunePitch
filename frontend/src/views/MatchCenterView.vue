<script setup lang="ts">
/**
 * 赛事中心:输入主客队期望进球(xG),调用 Dixon-Coles 泊松模型
 * 输出比分分布与胜平负概率。
 */
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useAnalysisStore } from '@/stores/analysis'
import OddsTrendChart, { type OddsTrendPoint } from '@/components/OddsTrendChart.vue'

const analysisStore = useAnalysisStore()
const { poissonResult, isPredictionLoading, predictionError } = storeToRefs(analysisStore)

const homeXg = ref<number>(1.5)
const awayXg = ref<number>(1.1)

async function handlePredict(): Promise<void> {
  await analysisStore.fetchPoissonPrediction(homeXg.value, awayXg.value)
}

/** 演示用赔率走势数据(接入真实数据源后替换) */
const oddsTrendPoints = ref<OddsTrendPoint[]>([
  { time: '08-01', homeWin: 2.10, draw: 3.40, awayWin: 3.20 },
  { time: '08-05', homeWin: 2.05, draw: 3.45, awayWin: 3.30 },
  { time: '08-10', homeWin: 1.95, draw: 3.50, awayWin: 3.55 },
  { time: '08-15', homeWin: 1.90, draw: 3.55, awayWin: 3.70 },
])

const probabilityPercent = (value: number): string =>
  `${(value * 100).toFixed(1)}%`
</script>

<template>
  <section class="match-center">
    <h2 class="match-center__title">赛事中心 · 比分概率预测</h2>

    <div class="match-center__panel">
      <label class="match-center__field">
        <span>主队期望进球 (xG)</span>
        <input v-model.number="homeXg" type="number" min="0.1" max="10" step="0.1" />
      </label>
      <label class="match-center__field">
        <span>客队期望进球 (xG)</span>
        <input v-model.number="awayXg" type="number" min="0.1" max="10" step="0.1" />
      </label>
      <button
        class="match-center__submit"
        type="button"
        :disabled="isPredictionLoading"
        @click="handlePredict"
      >
        {{ isPredictionLoading ? '计算中…' : '运行泊松模型' }}
      </button>
    </div>

    <p v-if="predictionError" class="match-center__error" role="alert">
      {{ predictionError }}
    </p>

    <div v-if="poissonResult" class="match-center__result">
      <div class="match-center__probs">
        <div class="match-center__prob">
          <span class="match-center__prob-label">主胜</span>
          <strong class="match-center__prob-value">
            {{ probabilityPercent(poissonResult.probabilities.home_win) }}
          </strong>
        </div>
        <div class="match-center__prob">
          <span class="match-center__prob-label">平局</span>
          <strong class="match-center__prob-value">
            {{ probabilityPercent(poissonResult.probabilities.draw) }}
          </strong>
        </div>
        <div class="match-center__prob">
          <span class="match-center__prob-label">客胜</span>
          <strong class="match-center__prob-value">
            {{ probabilityPercent(poissonResult.probabilities.away_win) }}
          </strong>
        </div>
      </div>

      <table class="match-center__table">
        <thead>
          <tr>
            <th>比分</th>
            <th>概率</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="score in poissonResult.top_scores" :key="`${score.home_goals}-${score.away_goals}`">
            <td>{{ score.home_goals }} : {{ score.away_goals }}</td>
            <td>{{ probabilityPercent(score.probability) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h3 class="match-center__section-title">欧赔走势</h3>
    <OddsTrendChart :points="oddsTrendPoints" />
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.match-center {
  max-width: 960px;
  margin: 0 auto;

  &__title {
    margin: 0 0 vars.$spacing-lg;
  }

  &__section-title {
    margin: vars.$spacing-lg 0 vars.$spacing-md;
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
    margin-bottom: vars.$spacing-md;
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
