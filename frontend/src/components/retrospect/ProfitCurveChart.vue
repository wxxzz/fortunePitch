<script setup lang="ts">
/**
 * 模拟资金收益走势折线图(复盘中心)。
 */
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { use } from 'echarts/core'

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

/** 单个收益节点 */
export interface ProfitPoint {
  /** 序号或日期标签 */
  label: string
  /** 累计盈亏 */
  cumulativeProfit: number
}

interface Props {
  /** 收益走势节点序列 */
  points: ProfitPoint[]
}

const props = defineProps<Props>()

const option = computed(() => ({
  tooltip: { trigger: 'axis' as const },
  grid: { left: '56px', right: '16px', top: '24px', bottom: '32px' },
  xAxis: {
    type: 'category' as const,
    data: props.points.map((p) => p.label),
  },
  yAxis: {
    type: 'value' as const,
    name: '累计盈亏',
    scale: true,
  },
  series: [
    {
      name: '模拟资金收益',
      type: 'line' as const,
      smooth: true,
      data: props.points.map((p) => p.cumulativeProfit),
      areaStyle: { opacity: 0.12 },
    },
  ],
}))
</script>

<template>
  <div class="profit-curve-chart">
    <VChart :option="option" autoresize />
  </div>
</template>

<style lang="scss" scoped>
.profit-curve-chart {
  width: 100%;
  height: 280px;
}
</style>
