<script setup lang="ts">
/**
 * SHAP 归因图:展示 AI 模型预测结果的特征归因分析(SHAP Values)。
 *
 * 横向条形图,正值(红色)表示推高预测概率的特征,
 * 负值(蓝色)表示压低预测概率的特征。
 */
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { use } from 'echarts/core'

use([BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

/** 单个特征的 SHAP 归因值 */
export interface ShapFeature {
  /** 特征名称(如 xG 差、Elo 差、近期状态) */
  name: string
  /** SHAP 值:正数推高预测,负数压低预测 */
  value: number
}

interface Props {
  /** 特征归因列表 */
  features: ShapFeature[]
}

const props = defineProps<Props>()

const sortedFeatures = computed(() =>
  [...props.features].sort((a, b) => Math.abs(b.value) - Math.abs(a.value)),
)

const option = computed(() => ({
  tooltip: {
    trigger: 'axis' as const,
  },
  grid: {
    left: '120px',
    right: '32px',
    top: '16px',
    bottom: '32px',
  },
  xAxis: {
    type: 'value' as const,
    name: 'SHAP 值',
  },
  yAxis: {
    type: 'category' as const,
    data: sortedFeatures.value.map((f) => f.name),
  },
  series: [
    {
      name: '特征归因',
      type: 'bar' as const,
      data: sortedFeatures.value.map((f) => ({
        value: f.value,
        itemStyle: {
          color: f.value >= 0 ? '#c0392b' : '#1a7a4a',
        },
      })),
    },
  ],
}))
</script>

<template>
  <div class="shap-attribution-chart">
    <VChart :option="option" autoresize />
  </div>
</template>

<style lang="scss" scoped>
.shap-attribution-chart {
  width: 100%;
  height: 320px;
}
</style>
