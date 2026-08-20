<script setup lang="ts">
/**
 * 球队近 N 场比赛时间轴:展示赛果、比分及 xG 差值,直观呈现状态起伏。
 */
import { computed } from 'vue'

/** 单场比赛节点 */
export interface TeamTimelineItem {
  /** 对手名称 */
  opponent: string
  /** 是否主场 */
  isHome: boolean
  /** 我方进球 */
  goalsFor: number
  /** 对方进球 */
  goalsAgainst: number
  /** xG 差值(我方 xG - 对方 xG) */
  xgDiff: number
  /** 比赛日期(显示用文本) */
  date: string
}

interface Props {
  /** 时间轴节点(按时间倒序或正序传入均可,组件按传入顺序渲染) */
  items: TeamTimelineItem[]
}

const props = defineProps<Props>()

/** 赛果:W 胜 / D 平 / L 负 */
const resultOf = (item: TeamTimelineItem): 'W' | 'D' | 'L' => {
  if (item.goalsFor > item.goalsAgainst) return 'W'
  if (item.goalsFor < item.goalsAgainst) return 'L'
  return 'D'
}

const toneClass = computed(() =>
  props.items.map((item) => `team-timeline__result--${resultOf(item).toLowerCase()}`),
)
</script>

<template>
  <ol class="team-timeline">
    <li v-for="(item, index) in items" :key="`${item.date}-${item.opponent}`" class="team-timeline__item">
      <span class="team-timeline__dot" :class="toneClass[index]">
        {{ resultOf(item) }}
      </span>
      <div class="team-timeline__body">
        <div class="team-timeline__row">
          <span class="team-timeline__opponent">
            {{ item.isHome ? 'vs' : '@' }} {{ item.opponent }}
          </span>
          <span class="team-timeline__score">{{ item.goalsFor }} : {{ item.goalsAgainst }}</span>
        </div>
        <div class="team-timeline__meta">
          <span>{{ item.date }}</span>
          <span
            class="team-timeline__xg"
            :class="item.xgDiff >= 0 ? 'team-timeline__xg--pos' : 'team-timeline__xg--neg'"
          >
            xG差 {{ item.xgDiff >= 0 ? '+' : '' }}{{ item.xgDiff.toFixed(2) }}
          </span>
        </div>
      </div>
    </li>
    <li v-if="items.length === 0" class="team-timeline__empty">暂无近期比赛</li>
  </ol>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.team-timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  position: relative;

  &::before {
    content: '';
    position: absolute;
    left: 15px;
    top: 8px;
    bottom: 8px;
    width: 2px;
    background: vars.$color-border;
  }

  &__item {
    position: relative;
    display: flex;
    gap: vars.$spacing-md;
    padding: vars.$spacing-sm 0;
    padding-left: 0;
  }

  &__dot {
    position: relative;
    z-index: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    color: #fff;
    font-size: 13px;
    font-weight: 700;
    flex-shrink: 0;

    // 红=利好(胜),绿=利空(负),灰=中性(平)
    &--w {
      background: vars.$color-positive;
    }

    &--l {
      background: vars.$color-negative;
    }

    &--d {
      background: vars.$color-neutral;
    }
  }

  &__body {
    flex: 1;
    min-width: 0;
  }

  &__row {
    display: flex;
    justify-content: space-between;
    gap: vars.$spacing-md;
  }

  &__opponent {
    font-weight: 600;
  }

  &__score {
    font-weight: 700;
  }

  &__meta {
    display: flex;
    justify-content: space-between;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__xg--pos {
    color: vars.$color-positive;
  }

  &__xg--neg {
    color: vars.$color-negative;
  }

  &__empty {
    color: vars.$color-text-secondary;
    text-align: center;
    padding: vars.$spacing-lg 0;
  }
}
</style>
