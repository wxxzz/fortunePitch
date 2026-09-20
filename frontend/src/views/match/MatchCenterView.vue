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
import {
  runLlmAnalysis,
  runLlmFundamentalAnalysis,
  runLlmTrendAnalysis,
} from '@/api/match/analysis'
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

/** 应用筛选后的比赛列表(默认按场次编号升序,编号缺失时按开赛时间兜底) */
const filteredGames = computed(() =>
  games.value
    .filter((game) => {
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
    })
    .slice()
    .sort((a, b) => {
      const numA = a.match_num_str
      const numB = b.match_num_str
      if (numA && numB && numA !== numB) return numA < numB ? -1 : 1
      if (numA && !numB) return -1
      if (!numA && numB) return 1
      return new Date(a.match_time).getTime() - new Date(b.match_time).getTime()
    }),
)

// ---------- 赛事列表 ----------

const teamName = (teamId: number): string =>
  teams.value.find((t) => t.team_id === teamId)?.team_name ?? `球队 #${teamId}`

function handleOpenDetail(matchId: string): void {
  void router.push(`/match/${matchId}`)
}

// ---------- 批量 AI 分析 ----------

/** 批量分析类型,与深度分析页的三个单场分析接口一一对应 */
type BatchKind = 'fundamental' | 'trend' | 'analysis'

const BATCH_META: Record<
  BatchKind,
  { label: string; run: (matchId: string) => Promise<unknown> }
> = {
  fundamental: { label: '批量基本面分析', run: runLlmFundamentalAnalysis },
  trend: { label: '批量赔率走势分析', run: runLlmTrendAnalysis },
  analysis: { label: '批量AI综合分析', run: runLlmAnalysis },
}

const runningBatch = ref<BatchKind | null>(null)
const batchDone = ref(0)
const batchTotal = ref(0)
const batchFailures = ref<string[]>([])
const batchSummary = ref('')
/** 用户请求取消:当前场次完成后停止,不再发起后续调用 */
const batchCancelled = ref(false)

const isBatchRunning = computed(() => runningBatch.value !== null)

const runningBatchLabel = computed(() =>
  runningBatch.value === null ? '' : BATCH_META[runningBatch.value].label,
)

/** 场次展示名:优先场次编号,缺失时用主客队名 */
function gameLabel(matchId: string): string {
  const game = filteredGames.value.find((g) => g.match_id === matchId)
  if (!game) return matchId
  if (game.match_num_str) return game.match_num_str
  return `${teamName(game.home_team_id)} vs ${teamName(game.away_team_id)}`
}

/** 逐场串行调用深度分析接口:单场失败不影响后续,结果落库后可在深度分析页查看 */
async function handleBatchAnalysis(kind: BatchKind): Promise<void> {
  if (isBatchRunning.value) return
  const targets = filteredGames.value.map((g) => g.match_id)
  if (targets.length === 0) return
  const { label, run } = BATCH_META[kind]
  if (
    !window.confirm(
      `将对当前筛选出的 ${targets.length} 场比赛逐场执行「${label}」,` +
        '单场约需 10~30 秒,期间请勿关闭页面,是否继续?',
    )
  ) {
    return
  }
  runningBatch.value = kind
  batchDone.value = 0
  batchTotal.value = targets.length
  batchFailures.value = []
  batchSummary.value = ''
  batchCancelled.value = false
  for (const matchId of targets) {
    if (batchCancelled.value) break
    try {
      await run(matchId)
    } catch {
      batchFailures.value.push(gameLabel(matchId))
    }
    batchDone.value += 1
  }
  const cancelled = batchCancelled.value && batchDone.value < batchTotal.value
  const okCount = batchDone.value - batchFailures.value.length
  batchSummary.value =
    (cancelled ? `已取消,已分析 ${okCount}/${batchTotal.value} 场成功` : `「${label}」完成:${okCount}/${batchTotal.value} 场成功`) +
    (batchFailures.value.length > 0
      ? `,失败场次:${batchFailures.value.join('、')}`
      : '')
  runningBatch.value = null
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

      <!-- 批量 AI 分析工具栏:逐场调用深度分析接口(串行) -->
      <div class="match-center__batch">
        <button
          class="match-center__batch-btn"
          type="button"
          :disabled="isBatchRunning || filteredGames.length === 0"
          @click="handleBatchAnalysis('fundamental')"
        >
          {{ runningBatch === 'fundamental' ? '分析中…' : '批量基本面分析' }}
        </button>
        <button
          class="match-center__batch-btn"
          type="button"
          :disabled="isBatchRunning || filteredGames.length === 0"
          @click="handleBatchAnalysis('trend')"
        >
          {{ runningBatch === 'trend' ? '分析中…' : '批量赔率走势分析' }}
        </button>
        <button
          class="match-center__batch-btn"
          type="button"
          :disabled="isBatchRunning || filteredGames.length === 0"
          @click="handleBatchAnalysis('analysis')"
        >
          {{ runningBatch === 'analysis' ? '分析中…' : '批量AI综合分析' }}
        </button>
        <button
          v-if="isBatchRunning"
          class="match-center__batch-btn match-center__batch-btn--cancel"
          type="button"
          @click="batchCancelled = true"
        >
          取消剩余
        </button>
        <span class="match-center__batch-hint">
          对筛选出的 {{ filteredGames.length }} 场逐场调用大模型,结果保存后可在深度分析页查看 ·
          仅供参考,不构成投注建议
        </span>
      </div>
      <p v-if="isBatchRunning" class="match-center__batch-progress" role="status">
        {{ runningBatchLabel }}进行中:{{ batchDone }}/{{ batchTotal }}
        <template v-if="batchFailures.length > 0">(已失败 {{ batchFailures.length }} 场)</template>
      </p>
      <p v-else-if="batchSummary" class="match-center__batch-summary" role="status">
        {{ batchSummary }}
      </p>

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

  &__batch {
    display: flex;
    align-items: center;
    gap: vars.$spacing-sm;
    padding: vars.$spacing-sm vars.$spacing-lg;
    margin-bottom: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    flex-wrap: wrap;
  }

  &__date-sep {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__batch-btn {
    padding: vars.$spacing-xs vars.$spacing-md;
    border: 1px solid vars.$color-primary;
    border-radius: vars.$border-radius;
    background: vars.$color-surface;
    color: vars.$color-primary;
    font-size: vars.$font-size-sm;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.2s;

    &:hover:not(:disabled) {
      background: vars.$color-primary-light;
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    &--cancel {
      border-color: vars.$color-danger;
      color: vars.$color-danger;

      &:hover:not(:disabled) {
        background: rgba(214, 69, 65, 0.1);
      }
    }
  }

  &__batch-hint {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__batch-progress {
    margin: 0 0 vars.$spacing-md;
    font-size: vars.$font-size-sm;
    color: vars.$color-primary;
  }

  &__batch-summary {
    margin: 0 0 vars.$spacing-md;
    padding: vars.$spacing-sm vars.$spacing-md;
    border-radius: vars.$border-radius;
    background: vars.$color-primary-light;
    color: vars.$color-primary;
    font-size: vars.$font-size-sm;
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
