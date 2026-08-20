<script setup lang="ts">
/**
 * 数据模型页:核心算法模型说明与在线演示
 * (Elo 评分 / xG / Dixon-Coles 泊松 / SHAP 归因)。
 */
import { ref } from 'vue'
import PoissonPredictor from '@/components/match/PoissonPredictor.vue'
import ShapAttributionChart, {
  type ShapFeature,
} from '@/components/analytics/ShapAttributionChart.vue'

/** 模型卡片定义 */
const MODELS = [
  {
    name: 'Elo 评分',
    formula: "R' = R + K × (S − E),  E = 1 / (1 + 10^((R_away − R_home − HFA)/400))",
    description:
      '基于比赛结果动态更新球队实力评分,含主场优势修正;更新过程零和,详见 docs/algorithm.md。',
  },
  {
    name: 'xG 预期进球',
    formula: 'xG = σ(b₀ + b₁·d + b₂·θ + b₃·isHeader)',
    description:
      '以射门距离 d 与射门张角 θ 的 Logistic 回归估计单次射门进球概率,球队总 xG 为各次射门之和。',
  },
  {
    name: 'Dixon-Coles 泊松',
    formula: 'P(i,j) = τ(i,j;λ,μ,ρ) · Pois(i;λ) · Pois(j;μ)',
    description:
      '将比分建模为双泊松分布,τ 修正低比分相关性偏差;由比分矩阵导出胜平负概率与 Top 比分。',
  },
  {
    name: '凯利指数',
    formula: 'f* = (p × odds − 1) / (odds − 1)',
    description:
      '衡量模型概率与市场赔率的偏差,输出建议资金比例;无正期望时返回 0。仅用于量化分析与教学演示。',
  },
] as const

/** 全局 SHAP 归因(演示数据) */
const shapFeatures = ref<ShapFeature[]>([
  { name: '主客 xG 差', value: 0.32 },
  { name: '主客 Elo 差', value: 0.21 },
  { name: '主队近期状态', value: 0.08 },
  { name: '客队伤停影响', value: -0.05 },
  { name: '历史交锋优势', value: -0.12 },
])
</script>

<template>
  <section class="data-model">
    <h2 class="data-model__title">数据模型</h2>

    <div class="data-model__cards">
      <article v-for="model in MODELS" :key="model.name" class="data-model__card">
        <h3 class="data-model__card-title">{{ model.name }}</h3>
        <code class="data-model__formula">{{ model.formula }}</code>
        <p class="data-model__desc">{{ model.description }}</p>
      </article>
    </div>

    <div class="data-model__panel">
      <PoissonPredictor />
    </div>

    <div class="data-model__panel">
      <h3 class="data-model__section-title">全局特征归因(SHAP,演示数据)</h3>
      <ShapAttributionChart :features="shapFeatures" />
    </div>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.data-model {
  max-width: 960px;
  margin: 0 auto;

  &__title {
    margin: 0 0 vars.$spacing-lg;
  }

  &__cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
    gap: vars.$spacing-md;
    margin-bottom: vars.$spacing-lg;
  }

  &__card {
    padding: vars.$spacing-lg;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__card-title {
    margin: 0 0 vars.$spacing-sm;
  }

  &__formula {
    display: block;
    padding: vars.$spacing-sm vars.$spacing-md;
    margin-bottom: vars.$spacing-sm;
    background: vars.$color-bg;
    border-radius: vars.$border-radius;
    font-size: vars.$font-size-sm;
  }

  &__desc {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
    line-height: 1.6;
  }

  &__panel {
    padding: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    margin-bottom: vars.$spacing-lg;
  }

  &__section-title {
    margin: 0 0 vars.$spacing-sm;
    font-size: vars.$font-size-md;
  }
}
</style>
