<script setup lang="ts">
/**
 * 深度分析 · 策略推荐 Tab(默认 Tab)。
 *
 * 结论卡片(本场置信度最高推荐)+ SHAP 逻辑归因 + 风险提示。
 * 推荐数据来自策略 store(父页面挂载时已 fetchAll)。
 */
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useStrategyStore } from '@/stores/strategy'
import ShapAttributionChart, {
  type ShapFeature,
} from '@/components/analytics/ShapAttributionChart.vue'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'

const props = defineProps<{ matchId: string }>()

const strategyStore = useStrategyStore()
const { recommendations } = storeToRefs(strategyStore)

/** 本场置信度最高的推荐 */
const topRecommendation = computed(
  () =>
    [...recommendations.value]
      .filter((r) => r.match_id === props.matchId)
      .sort((a, b) => b.confidence_score - a.confidence_score)[0] ?? null,
)

/** SHAP 归因图加载态(模拟高阶计算耗时) */
const isShapLoading = ref(true)

onMounted(() => {
  // 深链直接进入详情页时 store 可能尚未加载策略数据
  void strategyStore.fetchAll()
  // 模型归因计算耗时占位,展示骨架屏
  window.setTimeout(() => {
    isShapLoading.value = false
  }, 600)
})

/** SHAP 归因(演示数据,接入模型推理管道后由后端下发) */
const shapFeatures = ref<ShapFeature[]>([
  { name: '主队主场优势', value: 0.12 },
  { name: '主客 xG 差', value: 0.09 },
  { name: '客队防线漏洞', value: 0.08 },
  { name: '主队近期状态', value: 0.04 },
  { name: '客队伤停影响', value: -0.03 },
  { name: '历史交锋优势', value: -0.06 },
])

/** 风险提示(演示数据) */
const riskWarnings = ref<string[]>([
  '临场可能有大雨,利好防守反击打法',
  '本场主裁判出牌率偏高,中场绞杀或受影响',
])
</script>

<template>
  <section class="strategy-tab">
    <!-- 结论卡片 -->
    <div class="strategy-tab__conclusion">
      <template v-if="topRecommendation">
        <div class="strategy-tab__conclusion-main">
          <span class="strategy-tab__conclusion-label">推荐赛果</span>
          <strong class="strategy-tab__conclusion-outcome">
            {{ topRecommendation.predicted_outcome }}
          </strong>
        </div>
        <div class="strategy-tab__conclusion-item">
          <span>置信度</span>
          <strong>{{ (topRecommendation.confidence_score * 100).toFixed(0) }}%</strong>
        </div>
        <div class="strategy-tab__conclusion-item">
          <span>建议注额比例</span>
          <strong>{{ (topRecommendation.confidence_score * 0.1).toFixed(3) }}(凯利折算)</strong>
        </div>
      </template>
      <p v-else class="strategy-tab__hint">暂无本场推荐</p>
    </div>

    <!-- 逻辑归因 SHAP -->
    <h3 class="strategy-tab__section-title">逻辑归因(SHAP)</h3>
    <SkeletonBlock v-if="isShapLoading" :height="260" />
    <template v-else>
      <ShapAttributionChart :features="shapFeatures" />
      <p class="strategy-tab__hint">
        红色条=利好主队因素,绿色条=利空主队因素(演示数据)
      </p>
    </template>

    <!-- 风险提示 -->
    <h3 class="strategy-tab__section-title">风险提示</h3>
    <ul class="strategy-tab__risks">
      <li v-for="warning in riskWarnings" :key="warning">
        <span class="strategy-tab__risk-icon" aria-hidden="true">⚠</span>
        {{ warning }}
      </li>
    </ul>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;
@use './detail-shared' as shared;

.strategy-tab {
  @include shared.panel;

  &__conclusion {
    display: flex;
    align-items: center;
    gap: vars.$spacing-lg;
    padding: vars.$spacing-lg;
    background: vars.$color-primary-light;
    border: 1px solid vars.$color-primary;
    border-radius: vars.$border-radius;

    &-main {
      display: flex;
      flex-direction: column;
    }

    &-label {
      font-size: vars.$font-size-sm;
      color: vars.$color-text-secondary;
    }

    &-outcome {
      font-size: 24px;
      color: vars.$color-positive;
    }

    &-item {
      display: flex;
      flex-direction: column;

      span {
        font-size: vars.$font-size-sm;
        color: vars.$color-text-secondary;
      }
    }
  }
}
</style>
