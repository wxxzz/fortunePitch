<script setup lang="ts">
/**
 * 顶部状态栏(Top Bar):展示滚球赛事数量、数据更新时间、模拟总资产,
 * 并提供右侧滚球抽屉的开关入口。
 */
import { computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useMatchStore } from '@/stores/match'
import { useStrategyStore } from '@/stores/strategy'

const emit = defineEmits<{ togglePanel: [] }>()

const matchStore = useMatchStore()
const { games, gamesUpdatedAt } = storeToRefs(matchStore)

const strategyStore = useStrategyStore()
const { decisions } = storeToRefs(strategyStore)

onMounted(() => {
  void matchStore.fetchGames()
  void strategyStore.fetchAll()
})

/** 当前滚球(LIVE)赛事数量 */
const liveCount = computed(() => games.value.filter((g) => g.match_status === 'LIVE').length)

/** 数据更新时间(本地拉取时间) */
const updatedAtText = computed(() =>
  gamesUpdatedAt.value ? new Date(gamesUpdatedAt.value).toLocaleTimeString() : '--:--',
)

/** 模拟总资产 = 初始虚拟资金 10000 + 累计盈亏 */
const simulatedAsset = computed(() => {
  const profit = decisions.value.reduce(
    (sum, d) => sum + (d.profit_loss ?? 0),
    10_000,
  )
  return profit.toLocaleString(undefined, { maximumFractionDigits: 2 })
})
</script>

<template>
  <header class="top-bar">
    <div class="top-bar__stats">
      <div class="top-bar__stat">
        <span class="top-bar__stat-label">滚球赛事</span>
        <strong class="top-bar__stat-value top-bar__stat-value--live">
          {{ liveCount }} 场
        </strong>
      </div>
      <div class="top-bar__stat">
        <span class="top-bar__stat-label">数据更新</span>
        <strong class="top-bar__stat-value">{{ updatedAtText }}</strong>
      </div>
      <div class="top-bar__stat">
        <span class="top-bar__stat-label">模拟总资产(虚拟)</span>
        <strong
          class="top-bar__stat-value"
          :class="simulatedAsset.startsWith('-') ? 'top-bar__stat-value--down' : 'top-bar__stat-value--up'"
        >
          ¥ {{ simulatedAsset }}
        </strong>
      </div>
    </div>

    <button type="button" class="top-bar__panel-btn" @click="emit('togglePanel')">
      滚球快讯
    </button>
  </header>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: vars.$topbar-height;
  padding: 0 vars.$spacing-lg;
  background: vars.$color-surface;
  border-bottom: 1px solid vars.$color-border;

  &__stats {
    display: flex;
    gap: vars.$spacing-lg;
  }

  &__stat {
    display: flex;
    align-items: baseline;
    gap: vars.$spacing-sm;

    &-label {
      font-size: vars.$font-size-sm;
      color: vars.$color-text-secondary;
    }

    &-value {
      font-size: vars.$font-size-md;

      // 语义色:红=正向/利好,绿=负向/利空
      &--live {
        color: vars.$color-positive;
      }

      &--up {
        color: vars.$color-positive;
      }

      &--down {
        color: vars.$color-negative;
      }
    }
  }

  &__panel-btn {
    padding: vars.$spacing-xs vars.$spacing-md;
    border: 1px solid vars.$color-primary;
    border-radius: vars.$border-radius;
    background: vars.$color-primary-light;
    color: vars.$color-primary;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &:hover {
      background: vars.$color-primary;
      color: #fff;
    }
  }
}
</style>
