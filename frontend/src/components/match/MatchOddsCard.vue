<script setup lang="ts">
/**
 * 赛事玩法赔率卡片(赛事中心列表项):
 * 渐变头部(联赛/编号/时间/状态 + 对阵)+ 玩法标签页 + 选项赔率网格。
 * 选项勾选状态由 selection store 全局管理,底部选注栏联动。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { MatchGame } from '@/api/match/game'
import { useSelectionStore } from '@/stores/selection'

const props = defineProps<{
  game: MatchGame
  leagueName: string
  homeName: string
  awayName: string
}>()

const emit = defineEmits<{
  (e: 'open-detail', matchId: string): void
}>()

const router = useRouter()

const selectionStore = useSelectionStore()
const { isSelected } = selectionStore

/** 点击球队名称进入球队看板页 */
function openTeamDashboard(teamId: number): void {
  void router.push(`/base/team-dashboard/${teamId}`)
}

const statusLabel: Record<string, string> = {
  PENDING: '未开',
  LIVE: '滚球',
  FINISHED: '终场',
}

const pools = computed(() => props.game.odds?.pools ?? [])
const activePoolCode = ref<string>(pools.value[0]?.poolCode ?? '')
const activePool = computed(
  () => pools.value.find((p) => p.poolCode === activePoolCode.value) ?? null,
)

/** 赔率异步到达或当前玩法消失时,回退到第一个有数据的玩法 */
watch(
  () => pools.value.map((p) => p.poolCode).join(','),
  (codes) => {
    if (!codes.split(',').includes(activePoolCode.value)) {
      activePoolCode.value = pools.value[0]?.poolCode ?? ''
    }
  },
)

/** 玩法标签名(让球玩法附带盘口,如"让球(-1)") */
function playTitle(poolCode: string): string {
  const pool = pools.value.find((p) => p.poolCode === poolCode)
  if (!pool) return ''
  return pool.goalLine ? `${pool.playName}(${pool.goalLine})` : pool.playName
}

function handleToggle(optionCode: string, optionLabel: string, odds: number): void {
  if (!activePool.value) return
  selectionStore.toggle({
    matchId: props.game.match_id,
    matchName: `${props.homeName} vs ${props.awayName}`,
    poolCode: activePool.value.poolCode,
    playName: playTitle(activePool.value.poolCode),
    optionCode,
    optionLabel,
    odds,
  })
}

function isSelectedOption(optionCode: string): boolean {
  if (!activePool.value) return false
  return isSelected(props.game.match_id, activePool.value.poolCode, optionCode)
}
</script>

<template>
  <article class="odds-card">
    <!-- 渐变头部:联赛/编号/时间/状态 + 对阵 -->
    <header class="odds-card__header">
      <div class="odds-card__meta">
        <span class="odds-card__league">{{ leagueName || '未知联赛' }}</span>
        <span class="odds-card__num">
          {{ game.match_num_str || `编号 ${game.match_id}` }}
        </span>
        <span class="odds-card__time">
          {{ new Date(game.match_time).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }}
        </span>
        <span
          class="odds-card__status"
          :class="`odds-card__status--${game.match_status.toLowerCase()}`"
        >
          {{ statusLabel[game.match_status] ?? game.match_status }}
        </span>
        <button
          class="odds-card__detail-btn"
          type="button"
          @click="emit('open-detail', game.match_id)"
        >
          深度分析 →
        </button>
      </div>
      <div class="odds-card__teams">
        <button
          class="odds-card__team-btn"
          type="button"
          :title="`${homeName} 球队看板`"
          @click="openTeamDashboard(game.home_team_id)"
        >
          {{ homeName }}
        </button>
        <span v-if="game.home_score !== null" class="odds-card__score">
          {{ game.home_score }} : {{ game.away_score }}
        </span>
        <span v-else class="odds-card__vs">VS</span>
        <button
          class="odds-card__team-btn"
          type="button"
          :title="`${awayName} 球队看板`"
          @click="openTeamDashboard(game.away_team_id)"
        >
          {{ awayName }}
        </button>
      </div>
    </header>

    <!-- 玩法内容 -->
    <template v-if="pools.length > 0">
      <nav class="odds-card__tabs" aria-label="玩法选择">
        <button
          v-for="pool in pools"
          :key="pool.poolCode"
          class="odds-card__tab"
          :class="{ 'odds-card__tab--active': pool.poolCode === activePoolCode }"
          type="button"
          @click="activePoolCode = pool.poolCode"
        >
          {{ playTitle(pool.poolCode) }}
        </button>
      </nav>

      <div v-if="activePool" class="odds-card__options">
        <button
          v-for="option in activePool.options"
          :key="option.code"
          class="odds-card__option"
          :class="{ 'odds-card__option--selected': isSelectedOption(option.code) }"
          type="button"
          @click="handleToggle(option.code, option.label, option.odds)"
        >
          <span class="odds-card__option-label">{{ option.label }}</span>
          <span class="odds-card__option-odds">{{ option.odds.toFixed(2) }}</span>
        </button>
      </div>
    </template>
    <p v-else class="odds-card__empty">暂无在售赔率,请先在数据采集页同步赛事</p>
  </article>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.odds-card {
  background: vars.$color-surface;
  border-radius: vars.$border-radius + 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;

  &__header {
    padding: vars.$spacing-md vars.$spacing-lg;
    background: linear-gradient(135deg, #1a7a4a, #0f5132);
    color: #fff;
  }

  &__meta {
    display: flex;
    align-items: center;
    gap: vars.$spacing-md;
    margin-bottom: vars.$spacing-sm;
    font-size: vars.$font-size-sm;
    opacity: 0.92;
  }

  &__league {
    font-weight: 600;
  }

  &__num {
    opacity: 0.85;
  }

  &__detail-btn {
    margin-left: auto;
    padding: 2px vars.$spacing-sm;
    border: 1px solid rgba(255, 255, 255, 0.5);
    border-radius: 999px;
    background: transparent;
    color: #fff;
    font-size: vars.$font-size-sm;
    cursor: pointer;

    &:hover {
      background: rgba(255, 255, 255, 0.15);
    }
  }

  &__status {
    padding: 0 vars.$spacing-xs;
    border-radius: 4px;
    font-size: 11px;
    background: rgba(255, 255, 255, 0.2);

    &--pending {
      background: rgba(212, 136, 6, 0.85);
    }

    &--live {
      background: rgba(214, 69, 65, 0.9);
    }

    &--finished {
      background: rgba(255, 255, 255, 0.25);
    }
  }

  &__teams {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: vars.$spacing-md;
    padding: vars.$spacing-xs 0;
  }

  &__team-btn {
    flex: 1;
    padding: 0;
    border: none;
    background: transparent;
    color: inherit;
    text-align: center;
    font-size: 17px;
    font-weight: 600;
    cursor: pointer;
    transition: text-decoration-color 0.2s;
    // 悬停显示下划线提示可点击进入球队看板
    text-decoration: underline;
    text-decoration-color: transparent;

    &:hover,
    &:focus-visible {
      text-decoration-color: rgba(255, 255, 255, 0.85);
    }

    @media (max-width: 600px) {
      font-size: 15px;
    }
  }

  &__vs {
    padding: 2px vars.$spacing-sm;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.18);
    font-size: vars.$font-size-sm;
    font-weight: 600;
  }

  &__score {
    padding: 2px vars.$spacing-sm;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.18);
    font-size: 16px;
    font-weight: 700;
  }

  &__tabs {
    display: flex;
    border-bottom: 1px solid vars.$color-border;
    background: vars.$color-bg;
    overflow-x: auto;

    &::-webkit-scrollbar {
      display: none;
    }
    scrollbar-width: none;
  }

  &__tab {
    padding: vars.$spacing-sm vars.$spacing-md;
    border: none;
    border-bottom: 2px solid transparent;
    background: transparent;
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-md;
    white-space: nowrap;
    cursor: pointer;
    transition: color 0.2s, border-color 0.2s;

    &--active {
      color: vars.$color-primary;
      border-bottom-color: vars.$color-primary;
      font-weight: 600;
      background: vars.$color-surface;
    }
  }

  &__options {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: vars.$spacing-sm;
    padding: vars.$spacing-md vars.$spacing-lg;
  }

  &__option {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: vars.$spacing-sm 4px;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;

    &:hover {
      border-color: vars.$color-primary;
      transform: translateY(-2px);
      box-shadow: 0 2px 8px rgba(26, 122, 74, 0.15);
    }

    &--selected {
      background: vars.$color-primary;
      border-color: vars.$color-primary;
      color: #fff;

      .odds-card__option-odds {
        color: #fff;
      }
    }
  }

  &__option-label {
    font-size: vars.$font-size-md;
  }

  &__option-odds {
    font-size: 15px;
    font-weight: 700;
    color: vars.$color-positive;
  }

  &__empty {
    margin: 0;
    padding: vars.$spacing-md vars.$spacing-lg;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }
}
</style>
