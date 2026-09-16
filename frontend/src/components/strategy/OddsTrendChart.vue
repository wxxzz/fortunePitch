<script setup lang="ts">
/**
 * 赔率走势图:基于 ECharts 封装的通用多序列折线图。
 *
 * 通过 Props 传入序列名与时间序列数据,组件内部完成 ECharts option 组装,
 * 父组件无需感知图表细节;支持任意玩法选项数(胜平负 3 线 ~ 比分 31 线,
 * 序列多时依赖图例点击切换显隐)。
 */
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { use } from 'echarts/core'

use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

/** 单个时间点的赔率快照(序列值与 seriesNames 一一对应) */
export interface OddsTrendPoint {
  /** 采集时间(已格式化的展示文本) */
  time: string
  /** 各序列在该时点的赔率值,缺失为 null(折线断点) */
  values: (number | null)[]
}

interface Props {
  /** 序列名(选项展示名,如 主胜/平/客胜 或 1:2/2:1…) */
  seriesNames: string[]
  /** 赔率时间序列(按时间升序) */
  points: OddsTrendPoint[]
}

const props = defineProps<Props>()

const option = computed(() => ({
  tooltip: {
    trigger: 'axis' as const,
  },
  legend: {
    type: 'scroll' as const,
    data: props.seriesNames,
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
    name: '赔率',
    scale: true,
  },
  series: props.seriesNames.map((name, index) => ({
    name,
    type: 'line' as const,
    // 玩法中途开售/停售时容忍空洞,避免折线中断
    connectNulls: true,
    data: props.points.map((p) => p.values[index] ?? null),
  })),
}))
</script>

<template>
  <div class="odds-trend-chart">
    <VChart v-if="seriesNames.length > 0 && points.length > 0" :option="option" autoresize />
    <p v-else class="odds-trend-chart__empty">暂无走势数据</p>
  </div>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.odds-trend-chart {
  width: 100%;
  height: 320px;

  &__empty {
    margin: 0;
    padding: vars.$spacing-lg 0;
    text-align: center;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }
}
</style>
