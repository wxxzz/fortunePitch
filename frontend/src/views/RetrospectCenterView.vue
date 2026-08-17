<script setup lang="ts">
/**
 * 复盘中心:展示历史预测与实际结果的对比,
 * 以及 SHAP 特征归因分析,保证 AI 结论可解释。
 */
import { ref } from 'vue'
import ShapAttributionChart, { type ShapFeature } from '@/components/ShapAttributionChart.vue'

/** 复盘记录条目 */
interface RetrospectItem {
  matchName: string
  kickoffDate: string
  predictedSummary: string
  actualScore: string
  /** 预测结论是否正确(以胜平负结果衡量) */
  isHit: boolean
}

/** 演示用复盘数据(接入真实数据源后替换) */
const retrospectItems = ref<RetrospectItem[]>([
  {
    matchName: '阿森纳 vs 切尔西',
    kickoffDate: '2026-08-10',
    predictedSummary: '主胜 52.3% / 平 24.8% / 客胜 22.9%',
    actualScore: '2 : 1',
    isHit: true,
  },
  {
    matchName: '皇马 vs 巴萨',
    kickoffDate: '2026-08-09',
    predictedSummary: '主胜 38.1% / 平 26.5% / 客胜 35.4%',
    actualScore: '1 : 1',
    isHit: false,
  },
])

/** 演示用 SHAP 归因数据(接入模型推理管道后替换) */
const shapFeatures = ref<ShapFeature[]>([
  { name: '主客 xG 差', value: 0.32 },
  { name: '主客 Elo 差', value: 0.21 },
  { name: '主队近期状态', value: 0.08 },
  { name: '客队伤停影响', value: -0.05 },
  { name: '历史交锋优势', value: -0.12 },
])
</script>

<template>
  <section class="retrospect-center">
    <h2 class="retrospect-center__title">复盘中心 · 预测结果回溯</h2>

    <table class="retrospect-center__table">
      <thead>
        <tr>
          <th>比赛</th>
          <th>开赛日期</th>
          <th>模型预测</th>
          <th>实际比分</th>
          <th>命中</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in retrospectItems" :key="item.matchName">
          <td>{{ item.matchName }}</td>
          <td>{{ item.kickoffDate }}</td>
          <td>{{ item.predictedSummary }}</td>
          <td>{{ item.actualScore }}</td>
          <td
            class="retrospect-center__hit"
            :class="item.isHit ? 'retrospect-center__hit--yes' : 'retrospect-center__hit--no'"
          >
            {{ item.isHit ? '命中' : '未中' }}
          </td>
        </tr>
      </tbody>
    </table>

    <h3 class="retrospect-center__section-title">模型归因分析(SHAP)</h3>
    <p class="retrospect-center__hint">
      红色条表示推高预测概率的特征,绿色条表示压低预测概率的特征。
    </p>
    <ShapAttributionChart :features="shapFeatures" />
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.retrospect-center {
  max-width: 960px;
  margin: 0 auto;

  &__title {
    margin: 0 0 vars.$spacing-lg;
  }

  &__section-title {
    margin: vars.$spacing-lg 0 vars.$spacing-sm;
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

  &__hit--yes {
    color: vars.$color-primary;
    font-weight: 600;
  }

  &__hit--no {
    color: vars.$color-danger;
    font-weight: 600;
  }
}
</style>
