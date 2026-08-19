<script setup lang="ts">
/**
 * 高阶数据分析模块视图:球队 xG/xGA 指标 + SHAP 模型归因。
 */
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useAnalyticsStore } from '@/stores/analytics'
import ShapAttributionChart, {
  type ShapFeature,
} from '@/components/analytics/ShapAttributionChart.vue'

const analyticsStore = useAnalyticsStore()
const { teamStats, predictionError } = storeToRefs(analyticsStore)

onMounted(() => {
  void analyticsStore.fetchTeamStats()
})

/** SHAP 归因数据(接入模型推理管道后由后端下发) */
const shapFeatures = ref<ShapFeature[]>([
  { name: '主客 xG 差', value: 0.32 },
  { name: '主客 Elo 差', value: 0.21 },
  { name: '主队近期状态', value: 0.08 },
  { name: '客队伤停影响', value: -0.05 },
  { name: '历史交锋优势', value: -0.12 },
])
</script>

<template>
  <section class="analytics-view">
    <h2 class="analytics-view__title">高阶数据分析 · xG 指标与模型归因</h2>

    <p v-if="predictionError" class="analytics-view__error" role="alert">{{ predictionError }}</p>

    <h3 class="analytics-view__section-title">球队单场高阶指标</h3>
    <table class="analytics-view__table">
      <thead>
        <tr>
          <th>比赛</th><th>球队</th><th>xG</th><th>xGA</th><th>控球率</th><th>射正率</th><th>PPDA</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="stat in teamStats" :key="stat.stat_id">
          <td>{{ stat.match_id }}</td>
          <td>{{ stat.team_id }}</td>
          <td>{{ stat.xg ?? '-' }}</td>
          <td>{{ stat.xga ?? '-' }}</td>
          <td>{{ stat.possession !== null ? `${stat.possession}%` : '-' }}</td>
          <td>{{ stat.shot_accuracy !== null ? `${stat.shot_accuracy}%` : '-' }}</td>
          <td>{{ stat.ppda ?? '-' }}</td>
        </tr>
        <tr v-if="teamStats.length === 0">
          <td colspan="7" class="analytics-view__empty">暂无数据</td>
        </tr>
      </tbody>
    </table>

    <h3 class="analytics-view__section-title">模型归因分析(SHAP)</h3>
    <p class="analytics-view__hint">
      红色条表示推高预测概率的特征,绿色条表示压低预测概率的特征。
    </p>
    <ShapAttributionChart :features="shapFeatures" />
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.analytics-view {
  max-width: 960px;
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
    margin: 0 0 vars.$spacing-md;
    font-size: vars.$font-size-sm;
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

  &__empty {
    color: vars.$color-text-secondary;
    text-align: center;
  }
}
</style>
