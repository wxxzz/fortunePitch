<script setup lang="ts">
/**
 * 命中分布饼图(复盘中心):联赛分布 / 赔率区间分布。
 */
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { PieChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { use } from 'echarts/core'

use([PieChart, LegendComponent, TooltipComponent, CanvasRenderer])

/** 单个分布切片 */
export interface DistributionSlice {
  name: string
  value: number
}

interface Props {
  /** 饼图标题 */
  title: string
  /** 分布数据 */
  slices: DistributionSlice[]
}

const props = defineProps<Props>()

const option = computed(() => ({
  tooltip: { trigger: 'item' as const },
  legend: { bottom: 0 },
  series: [
    {
      name: props.title,
      type: 'pie' as const,
      radius: ['38%', '62%'],
      data: props.slices,
      label: { formatter: '{b}: {d}%' as const },
    },
  ],
}))
</script>

<template>
  <div class="distribution-pie-chart">
    <h4 class="distribution-pie-chart__title">{{ title }}</h4>
    <VChart :option="option" autoresize />
  </div>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.distribution-pie-chart {
  width: 100%;

  &__title {
    margin: 0 0 vars.$spacing-sm;
    font-size: vars.$font-size-md;
  }
}
</style>
