<script setup lang="ts">
/**
 * 页面A:赛事中心(Match Center)- 列表页。
 * 顶部筛选区 + 赛事列表区(左:联赛/时间/状态;中:对阵与标签;右:核心赔率)
 * + 右侧边栏(今日焦点推荐)。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useMatchStore } from '@/stores/match'
import { useBaseStore } from '@/stores/base'
import FocusRecommendCard from '@/components/match/FocusRecommendCard.vue'
import OddsTrendChart, {
  type OddsTrendPoint,
} from '@/components/strategy/OddsTrendChart.vue'

const router = useRouter()
const matchStore = useMatchStore()
const { games, isLoading, error } = storeToRefs(matchStore)

const baseStore = useBaseStore()
const { leagues, teams } = storeToRefs(baseStore)

onMounted(() => {
  void matchStore.fetchGames()
  void baseStore.fetchAll()
})

// ---------- 筛选区 ----------

const selectedLeagueId = ref<number | null>(null)
const selectedDate = ref<string>('')
const isTopFiveOnly = ref(false)

/** 五大联赛关键字(数据源筛选:仅看五大联赛) */
const TOP_FIVE_KEYWORDS = ['英超', '西甲', '意甲', '德甲', '法甲']

const teamLeagueName = computed(() => {
  const map = new Map<number, string>()
  for (const team of teams.value) {
    const league = leagues.value.find((l) => l.league_id === team.league_id)
    map.set(team.team_id, league?.league_name ?? '')
  }
  return map
})

/** 应用筛选后的比赛列表 */
const filteredGames = computed(() =>
  games.value.filter((game) => {
    if (selectedLeagueId.value !== null) {
      const homeLeague = teamLeagueName.value.get(game.home_team_id)
      if (homeLeague !== leagues.value.find((l) => l.league_id === selectedLeagueId.value)?.league_name) {
        return false
      }
    }
    if (selectedDate.value) {
      const gameDate = new Date(game.match_time).toISOString().slice(0, 10)
      if (gameDate !== selectedDate.value) {
        return false
      }
    }
    if (isTopFiveOnly.value) {
      const leagueName = teamLeagueName.value.get(game.home_team_id) ?? ''
      if (!TOP_FIVE_KEYWORDS.some((kw) => leagueName.includes(kw))) {
        return false
      }
    }
    return true
  }),
)

// ---------- 赛事列表 ----------

const expandedMatchId = ref<string | null>(null)

const statusLabel: Record<string, string> = {
  PENDING: '未开',
  LIVE: '滚球',
  FINISHED: '终场',
}

const teamName = (teamId: number): string =>
  teams.value.find((t) => t.team_id === teamId)?.team_name ?? `球队 #${teamId}`

/** 比赛核心标签(接入数据源后由后端下发) */
const matchTags = (_matchId: string): string[] => []

/** 演示用赔率走势(数据源接入后替换为该场真实欧赔历史) */
const demoTrendPoints = (matchId: string): OddsTrendPoint[] => [
  { time: 'T-5d', homeWin: 2.1, draw: 3.4, awayWin: 3.2 },
  { time: 'T-3d', homeWin: 2.0, draw: 3.45, awayWin: 3.35 },
  { time: 'T-1d', homeWin: 1.92, draw: 3.5, awayWin: 3.6 },
  { time: '即时', homeWin: 1.88, draw: 3.55, awayWin: 3.7 },
]

function toggleExpand(matchId: string): void {
  expandedMatchId.value = expandedMatchId.value === matchId ? null : matchId
}

function handleOpenDetail(matchId: string): void {
  void router.push(`/match/${matchId}`)
}
</script>

<template>
  <div class="match-center">
    <div class="match-center__main">
      <h2 class="match-center__title">赛事中心</h2>

      <!-- 顶部筛选区 -->
      <div class="match-center__filters">
        <label class="match-center__filter">
          <span>联赛</span>
          <select v-model.number="selectedLeagueId">
            <option :value="null">全部联赛</option>
            <option v-for="league in leagues" :key="league.league_id" :value="league.league_id">
              {{ league.league_name }}
            </option>
          </select>
        </label>
        <label class="match-center__filter">
          <span>日期</span>
          <input v-model="selectedDate" type="date" />
        </label>
        <label class="match-center__filter match-center__filter--check">
          <input v-model="isTopFiveOnly" type="checkbox" />
          <span>仅看五大联赛</span>
        </label>
      </div>

      <p v-if="error" class="match-center__error" role="alert">{{ error }}</p>
      <p v-if="isLoading" class="match-center__hint">加载中…</p>

      <!-- 赛事列表区 -->
      <div class="match-center__list">
        <div
          v-for="game in filteredGames"
          :key="game.match_id"
          class="match-center__row"
        >
          <div class="match-center__row-main" @click="toggleExpand(game.match_id)">
            <!-- 左:联赛 / 开赛时间 / 状态 -->
            <div class="match-center__row-left">
              <span class="match-center__league">
                {{ teamLeagueName.get(game.home_team_id) || '未知联赛' }}
              </span>
              <span class="match-center__time">
                {{ new Date(game.match_time).toLocaleString() }}
              </span>
              <span
                class="match-center__status"
                :class="`match-center__status--${game.match_status.toLowerCase()}`"
              >
                {{ statusLabel[game.match_status] ?? game.match_status }}
              </span>
            </div>

            <!-- 中:主队 vs 客队 + 核心标签 -->
            <div class="match-center__row-middle">
              <div class="match-center__versus">
                <span class="match-center__team">{{ teamName(game.home_team_id) }}</span>
                <span
                  v-if="game.home_score !== null"
                  class="match-center__score"
                >
                  {{ game.home_score }} : {{ game.away_score }}
                </span>
                <span v-else class="match-center__vs">vs</span>
                <span class="match-center__team">{{ teamName(game.away_team_id) }}</span>
              </div>
              <div class="match-center__tags">
                <span v-for="tag in matchTags(game.match_id)" :key="tag" class="match-center__tag">
                  {{ tag }}
                </span>
              </div>
            </div>

            <!-- 右:核心赔率(演示) + 操作 -->
            <div class="match-center__row-right">
              <span class="match-center__odds-hint">欧赔 / 亚盘</span>
              <button
                class="match-center__detail-btn"
                type="button"
                @click.stop="handleOpenDetail(game.match_id)"
              >
                深度分析
              </button>
            </div>
          </div>

          <!-- 展开区:赔率走势迷你折线图 -->
          <div v-if="expandedMatchId === game.match_id" class="match-center__expand">
            <OddsTrendChart :points="demoTrendPoints(game.match_id)" />
            <p class="match-center__hint">演示数据 · 赔率数据源接入后展示真实走势</p>
          </div>
        </div>
        <p v-if="!isLoading && filteredGames.length === 0" class="match-center__hint">
          暂无符合条件的比赛
        </p>
      </div>
    </div>

    <!-- 右侧边栏:今日焦点推荐 -->
    <aside class="match-center__aside">
      <FocusRecommendCard />
    </aside>
  </div>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.match-center {
  display: flex;
  gap: vars.$spacing-lg;
  align-items: flex-start;

  &__main {
    flex: 1;
    min-width: 0;
  }

  &__aside {
    width: 280px;
    flex-shrink: 0;
    position: sticky;
    top: vars.$spacing-lg;
  }

  &__title {
    margin: 0 0 vars.$spacing-md;
  }

  &__filters {
    display: flex;
    align-items: flex-end;
    gap: vars.$spacing-lg;
    padding: vars.$spacing-md vars.$spacing-lg;
    margin-bottom: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__filter {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-xs;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;

    select,
    input[type='date'] {
      padding: vars.$spacing-xs vars.$spacing-sm;
      border: 1px solid vars.$color-border;
      border-radius: vars.$border-radius;
      background: #fff;
    }

    &--check {
      flex-direction: row;
      align-items: center;
      padding-bottom: vars.$spacing-xs;
    }
  }

  &__error {
    color: vars.$color-danger;
  }

  &__hint {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__list {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-sm;
  }

  &__row {
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    overflow: hidden;
  }

  &__row-main {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: vars.$spacing-lg;
    padding: vars.$spacing-md vars.$spacing-lg;
    cursor: pointer;

    &:hover {
      background: vars.$color-surface-hover;
    }
  }

  &__row-left {
    display: flex;
    flex-direction: column;
    gap: 2px;
    width: 170px;
    flex-shrink: 0;
  }

  &__league {
    font-weight: 600;
  }

  &__time {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__status {
    align-self: flex-start;
    padding: 0 vars.$spacing-xs;
    border-radius: 4px;
    font-size: 11px;
    color: #fff;
    background: vars.$color-neutral;

    &--live {
      background: vars.$color-positive;
    }

    &--finished {
      background: vars.$color-neutral;
    }

    &--pending {
      background: vars.$color-warning;
    }
  }

  &__row-middle {
    flex: 1;
    min-width: 0;
  }

  &__versus {
    display: flex;
    align-items: center;
    gap: vars.$spacing-md;
    font-size: 15px;
  }

  &__team {
    font-weight: 600;
  }

  &__score {
    color: vars.$color-positive;
    font-weight: 700;
  }

  &__vs {
    color: vars.$color-text-secondary;
    font-size: vars.$font-size-sm;
  }

  &__tags {
    margin-top: vars.$spacing-xs;
  }

  &__tag {
    display: inline-block;
    margin-right: vars.$spacing-xs;
    padding: 0 vars.$spacing-sm;
    border: 1px solid vars.$color-border;
    border-radius: 999px;
    font-size: 11px;
    color: vars.$color-text-secondary;
  }

  &__row-right {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: vars.$spacing-xs;
    flex-shrink: 0;
  }

  &__odds-hint {
    font-size: 11px;
    color: vars.$color-text-secondary;
  }

  &__detail-btn {
    padding: vars.$spacing-xs vars.$spacing-md;
    border: 1px solid vars.$color-primary;
    border-radius: vars.$border-radius;
    background: transparent;
    color: vars.$color-primary;
    cursor: pointer;

    &:hover {
      background: vars.$color-primary;
      color: #fff;
    }
  }

  &__expand {
    padding: 0 vars.$spacing-lg vars.$spacing-md;
  }
}
</style>
