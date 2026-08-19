<script setup lang="ts">
/**
 * 比赛与赛果模块视图:赛事中心。
 * 比赛列表 + 选中比赛的事件时间线 + 泊松概率预测入口。
 */
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useMatchStore } from '@/stores/match'
import { useAnalyticsStore } from '@/stores/analytics'
import PoissonPredictor from '@/components/match/PoissonPredictor.vue'

const matchStore = useMatchStore()
const { games, events, selectedMatchId, isLoading, error } = storeToRefs(matchStore)

const analyticsStore = useAnalyticsStore()

onMounted(() => {
  void matchStore.fetchGames()
})

const statusLabel: Record<string, string> = {
  PENDING: '未开赛',
  LIVE: '进行中',
  FINISHED: '已完赛',
}

function handleSelect(matchId: string): void {
  void matchStore.selectMatch(matchId)
  void analyticsStore.fetchTeamStats(matchId)
}
</script>

<template>
  <section class="match-center">
    <h2 class="match-center__title">赛事中心 · 比赛与赛果</h2>

    <p v-if="error" class="match-center__error" role="alert">{{ error }}</p>
    <p v-if="isLoading" class="match-center__hint">加载中…</p>

    <table class="match-center__table">
      <thead>
        <tr>
          <th>比赛编号</th><th>开赛时间</th><th>状态</th><th>比分</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="game in games"
          :key="game.match_id"
          :class="{ 'match-center__row--active': game.match_id === selectedMatchId }"
        >
          <td>{{ game.match_id }}</td>
          <td>{{ new Date(game.match_time).toLocaleString() }}</td>
          <td>{{ statusLabel[game.match_status] ?? game.match_status }}</td>
          <td>
            {{
              game.home_score === null
                ? '-'
                : `${game.home_score} : ${game.away_score}`
            }}
          </td>
          <td>
            <button
              class="match-center__btn"
              type="button"
              @click="handleSelect(game.match_id)"
            >
              查看事件
            </button>
          </td>
        </tr>
        <tr v-if="games.length === 0">
          <td colspan="5" class="match-center__empty">暂无比赛数据</td>
        </tr>
      </tbody>
    </table>

    <div v-if="selectedMatchId" class="match-center__events">
      <h3 class="match-center__section-title">
        事件时间线 · {{ selectedMatchId }}
      </h3>
      <ol class="match-center__timeline">
        <li v-for="event in events" :key="event.event_id">
          <span class="match-center__minute">{{ event.event_minute }}'</span>
          <span
            class="match-center__tag"
            :class="event.is_home_team ? 'match-center__tag--home' : 'match-center__tag--away'"
          >
            {{ event.is_home_team ? '主' : '客' }}
          </span>
          {{ event.event_type }}
        </li>
        <li v-if="events.length === 0" class="match-center__empty">暂无事件</li>
      </ol>
    </div>

    <PoissonPredictor />
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.match-center {
  max-width: 960px;
  margin: 0 auto;

  &__title {
    margin: 0 0 vars.$spacing-lg;
  }

  &__section-title {
    margin: vars.$spacing-lg 0 vars.$spacing-sm;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__hint {
    color: vars.$color-text-secondary;
  }

  &__table {
    width: 100%;
    border-collapse: collapse;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;

    th,
    td {
      padding: vars.$spacing-sm vars.$spacing-md;
      border-bottom: 1px solid vars.$color-border;
      text-align: left;
    }

    th {
      background: vars.$color-surface-hover;
    }
  }

  &__row--active {
    background: vars.$color-primary-light;
  }

  &__btn {
    padding: vars.$spacing-xs vars.$spacing-sm;
    border: 1px solid vars.$color-primary;
    border-radius: vars.$border-radius;
    background: transparent;
    color: vars.$color-primary;
    cursor: pointer;
  }

  &__timeline {
    list-style: none;
    margin: 0;
    padding: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;

    li {
      padding: vars.$spacing-xs 0;
      display: flex;
      align-items: center;
      gap: vars.$spacing-sm;
    }
  }

  &__minute {
    min-width: 36px;
    font-weight: 600;
    color: vars.$color-primary;
  }

  &__tag {
    padding: 0 vars.$spacing-xs;
    border-radius: vars.$border-radius;
    font-size: vars.$font-size-sm;
    color: #fff;

    &--home {
      background: vars.$color-primary;
    }

    &--away {
      background: vars.$color-danger;
    }
  }

  &__empty {
    color: vars.$color-text-secondary;
    text-align: center;
  }
}
</style>
