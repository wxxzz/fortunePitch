<script setup lang="ts">
/**
 * 赔率走势图:基于 ECharts 封装的独立可视化组件。
 *
 * 通过 Props 传入时间序列数据,组件内部完成 ECharts option 组装,
 * 父组件无需感知图表细节。
 */
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { use } from 'echarts/core'

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

/** 单个时间点的赔率快照 */
export interface OddsTrendPoint {
  /** 采集时间(ISO 字符串或可读文本) */
  time: string
  /** 主胜欧赔 */
  homeWin: number
  /** 平局欧赔 */
  draw: number
  /** 客胜欧赔 */
  awayWin: number
}

interface Props {
  /** 赔率时间序列 */
  points: OddsTrendPoint[]
}

const props = defineProps<Props>()

const option = computed(() => ({
  tooltip: {
    trigger: 'axis' as const,
  },
  legend: {
    data: ['主胜', '平局', '客胜'],
  },
  grid: {
    left: '48px',
    right: '16px',
    top: '40px',
    bottom: '32px',
  },
  xAxis: {
    type: 'category' as const,
    data: props.points.map((p) => p.time),
  },
  yAxis: {
    type: 'value' as const,
    name: '欧赔',
    scale: true,
  },
  series: [
    {
      name: '主胜',
      type: 'line' as const,
      data: props.points.map((p) => p.homeWin),
    },
    {
      name: '平局',
      type: 'line' as const,
      data: props.points.map((p) => p.draw),
    },
    {
      name: '客胜',
      type: 'line' as const,
      data: props.points.map((p) => p.awayWin),
    },
  ],
}))
</script>

<template>
  <div class="odds-trend-chart">
    <VChart :option="option" autoresize />
  </div>
</template>

<style lang="scss" scoped>
.odds-trend-chart {
  width: 100%;
  height: 320px;
}
</style>
