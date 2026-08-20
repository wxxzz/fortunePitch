<script setup lang="ts">
/**
 * 球队六维能力雷达图:攻防、控球、定位球、防守压迫等维度。
 */
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { RadarChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { use } from 'echarts/core'

use([RadarChart, LegendComponent, TooltipComponent, CanvasRenderer])

/** 单个能力维度 */
export interface TeamDimension {
  /** 维度名称(如 进攻 / 防守 / 控球) */
  name: string
  /** 能力值(0-100) */
  value: number
}

interface Props {
  /** 六维能力值 */
  dimensions: TeamDimension[]
}

const props = defineProps<Props>()

const MAX_SCORE: number = 100

const option = computed(() => ({
  tooltip: {},
  radar: {
    indicator: props.dimensions.map((d) => ({
      name: d.name,
      max: MAX_SCORE,
    })),
    radius: '65%',
  },
  series: [
    {
      type: 'radar',
      data: [
        {
          value: props.dimensions.map((d) => d.value),
          name: '球队六维能力',
          areaStyle: { opacity: 0.25 },
          itemStyle: { color: '#1a7a4a' },
        },
      ],
    },
  ],
}))
</script>

<template>
  <div class="team-radar-chart">
    <VChart :option="option" autoresize />
  </div>
</template>

<style lang="scss" scoped>
.team-radar-chart {
  width: 100%;
  height: 320px;
}
</style>
