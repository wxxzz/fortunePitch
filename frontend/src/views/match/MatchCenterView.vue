<script setup lang="ts">
/**
 * 页面A:赛事中心(Match Center)- 列表页(融合式)。
 * 顶部筛选区 + 赛事玩法赔率卡片流(MatchOddsCard)
 * + 右侧边栏(今日焦点推荐)+ 底部选注栏与投注确认弹窗。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useMatchStore } from '@/stores/match'
import { useBaseStore } from '@/stores/base'
import FocusRecommendCard from '@/components/match/FocusRecommendCard.vue'
import MatchOddsCard from '@/components/match/MatchOddsCard.vue'
import SelectionBar from '@/components/match/SelectionBar.vue'
import BetConfirmModal from '@/components/match/BetConfirmModal.vue'

const router = useRouter()
const matchStore = useMatchStore()
const { games, isLoading, error, startBusinessDate, endBusinessDate } = storeToRefs(matchStore)

const baseStore = useBaseStore()
const { leagues, teams } = storeToRefs(baseStore)

onMounted(() => {
  void matchStore.fetchGames()
  void baseStore.fetchAll()
})

// ---------- 筛选区 ----------

const selectedLeagueId = ref<number | null>(null)
// 使用 store 中已经定义好的售卖日范围，后端已经按售卖日过滤，前端不需要再重复过滤日期
const isTopFiveOnly = ref(false)

// 售卖日范围变化时重新拉取数据
watch([startBusinessDate, endBusinessDate], () => {
  void matchStore.fetchGames()
})

/** 五大联赛关键字(数据源筛选:仅看五大联赛) */
const TOP_FIVE_KEYWORDS = ['英超', '西甲', '意甲', '德甲', '法甲']

const teamLeagueName = computed(() => {
  // Build league map first for O(1) lookups
  const leagueById = new Map<number, string>(leagues.value.map((lg: { league_id: number; league_name: string }) => [lg.league_id, lg.league_name]))
  const map = new Map<number, string>()
  for (const team of teams.value) {
    map.set(team.team_id, leagueById.get(team.league_id) ?? '')
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

const teamName = (teamId: number): string =>
  teams.value.find((t) => t.team_id === teamId)?.team_name ?? `球队 #${teamId}`

function handleOpenDetail(matchId: string): void {
  void router.push(`/match/${matchId}`)
}

// ---------- 选注与投注确认 ----------

const isConfirmVisible = ref(false)
const successMessage = ref('')

function openConfirm(): void {
  isConfirmVisible.value = true
}

function closeConfirm(): void {
  isConfirmVisible.value = false
}

function handleConfirmSuccess(betCount: number): void {
  isConfirmVisible.value = false
  successMessage.value = `已提交 ${betCount} 注模拟投注,可在复盘中心查看`
  window.setTimeout(() => {
    successMessage.value = ''
  }, 4000)
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
          <div class="match-center__date-range">
            <input v-model="startBusinessDate" type="date" />
            <span class="match-center__date-sep">至</span>
            <input v-model="endBusinessDate" type="date" />
          </div>
        </label>
        <label class="match-center__filter match-center__filter--check">
          <input v-model="isTopFiveOnly" type="checkbox" />
          <span>仅看五大联赛</span>
        </label>
      </div>

      <p v-if="error" class="match-center__error" role="alert">{{ error }}</p>
      <p v-if="isLoading" class="match-center__hint">加载中…</p>
      <p v-if="successMessage" class="match-center__success" role="status">
        {{ successMessage }}
      </p>

      <!-- 赛事玩法赔率卡片流 -->
      <div class="match-center__list">
        <MatchOddsCard
          v-for="game in filteredGames"
          :key="game.match_id"
          :game="game"
          :league-name="teamLeagueName.get(game.home_team_id) ?? ''"
          :home-name="teamName(game.home_team_id)"
          :away-name="teamName(game.away_team_id)"
          @open-detail="handleOpenDetail"
        />
        <p v-if="!isLoading && filteredGames.length === 0" class="match-center__hint">
          暂无符合条件的比赛
        </p>
      </div>
    </div>

    <!-- 右侧边栏:今日焦点推荐 -->
    <aside class="match-center__aside">
      <FocusRecommendCard />
    </aside>

    <!-- 底部选注栏(有选注时固定悬浮) -->
    <SelectionBar @open-confirm="openConfirm" />

    <!-- 投注确认弹窗 -->
    <BetConfirmModal
      v-if="isConfirmVisible"
      @close="closeConfirm"
      @success="handleConfirmSuccess"
    />
  </div>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.match-center {
  display: flex;
  gap: vars.$spacing-lg;
  align-items: flex-start;
  // 为底部固定选注栏留出空间
  padding-bottom: 72px;

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

  &__date-range {
    display: flex;
    align-items: center;
    gap: vars.$spacing-xs;
  }

  &__date-sep {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__success {
    padding: vars.$spacing-sm vars.$spacing-md;
    border-radius: vars.$border-radius;
    background: vars.$color-primary-light;
    color: vars.$color-primary;
    font-size: vars.$font-size-sm;
  }

  &__hint {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__list {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-md;
  }
}
</style>
