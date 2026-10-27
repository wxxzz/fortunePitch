<script setup lang="ts">
/**
 * 页面B:赛事深度分析(Match Detail)- 详情页。
 *
 * 薄壳父组件:负责比赛详情拉取、顶部对战卡片、Tab 导航与子组件装配;
 * 各 Tab 内容拆分为 src/components/match/detail/ 下的子组件,数据域
 * 逻辑拆分为 src/composables/ 下的组合函数:
 * - 高阶数据 / 历史交锋共享 insights(useMatchInsights,父级持有)
 * - 其他信息表单(useMatchExtraInfo,父级持有,顶部阵型摘要共用)
 * - 策略推荐 / 赔率走势 / 基本面 / AI 分析由各 Tab 自持
 * 各 Tab 经 KeepAlive 缓存,切换不丢状态;赛事复盘面板不缓存(重进刷新)。
 */
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useBaseStore } from '@/stores/base'
import { getGame, type MatchGame } from '@/api/match/game'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
import MatchRetrospectPanel from '@/components/match/MatchRetrospectPanel.vue'
import AdvancedTab from '@/components/match/detail/AdvancedTab.vue'
import AiAnalysisTab from '@/components/match/detail/AiAnalysisTab.vue'
import ExtraInfoTab from '@/components/match/detail/ExtraInfoTab.vue'
import FundamentalsTab from '@/components/match/detail/FundamentalsTab.vue'
import H2HTab from '@/components/match/detail/H2HTab.vue'
import OddsTrendTab from '@/components/match/detail/OddsTrendTab.vue'
import StrategyTab from '@/components/match/detail/StrategyTab.vue'
import { useMatchExtraInfo } from '@/composables/useMatchExtraInfo'
import { useMatchInsights } from '@/composables/useMatchInsights'

const route = useRoute()
const router = useRouter()
const matchId = route.params.matchId as string

const baseStore = useBaseStore()
const { teams } = storeToRefs(baseStore)

const game = ref<MatchGame | null>(null)
const isDetailLoading = ref(true)
const detailError = ref<string | null>(null)

// 高阶数据 / 历史交锋两 Tab 共享的 insights payload(懒加载,load 自带守卫)
const insightsState = useMatchInsights(matchId)

// 补充信息表单(父级持有:顶部对战卡片的阵型摘要与录入 Tab 共用一份)
const extraInfo = useMatchExtraInfo(matchId)

onMounted(async () => {
  void baseStore.fetchAll()
  void extraInfo.load()
  try {
    game.value = await getGame(matchId)
  } catch (err) {
    detailError.value = err instanceof Error ? err.message : '比赛详情加载失败'
  } finally {
    isDetailLoading.value = false
  }
})

const teamName = (teamId: number): string =>
  teams.value.find((t) => t.team_id === teamId)?.team_name ?? `球队 #${teamId}`

// ---------- Tab 导航 ----------

const TABS = ['基本面', '历史交锋', '高阶数据', '赔率走势', '策略推荐', '其他信息', 'AI 分析', '赛事复盘'] as const
const activeTab = ref<(typeof TABS)[number]>('策略推荐')

watch(
  activeTab,
  (tab) => {
    if (tab === '高阶数据' || tab === '历史交锋') void insightsState.load()
  },
  // immediate:即使未来默认 Tab 直接是高阶数据/历史交锋也能触发首次加载
  { immediate: true },
)

// ---------- AI 分析日志查看器的跨 Tab 刷新 ----------

const aiTab = ref<InstanceType<typeof AiAnalysisTab> | null>(null)

/** 其他 Tab 生成大模型分析后刷新日志列表(查看器未挂载时为空操作) */
function refreshLlmLogs(): void {
  aiTab.value?.refresh()
}

function handleBack(): void {
  void router.push('/match')
}
</script>

<template>
  <section class="match-detail">
    <button class="match-detail__back" type="button" @click="handleBack">
      <- 返回赛事中心
    </button>

    <p v-if="detailError" class="match-detail__error" role="alert">{{ detailError }}</p>
    <SkeletonBlock v-if="isDetailLoading" :height="160" label="加载比赛数据…" />

    <template v-else-if="game">
      <!-- 顶部对战卡片 -->
      <header class="match-detail__hero">
        <div class="match-detail__team">
          <span class="match-detail__badge">{{ teamName(game.home_team_id).slice(0, 2) }}</span>
          <strong>{{ teamName(game.home_team_id) }}</strong>
        </div>
        <div class="match-detail__center">
          <span class="match-detail__score">
            {{ game.home_score !== null ? `${game.home_score} : ${game.away_score}` : 'vs' }}
          </span>
          <span class="match-detail__meta">
            {{ new Date(game.match_time).toLocaleString() }} · 编号 {{ game.match_id }}
          </span>
          <span class="match-detail__formation">{{ extraInfo.heroFormationText }}</span>
        </div>
        <div class="match-detail__team">
          <span class="match-detail__badge">{{ teamName(game.away_team_id).slice(0, 2) }}</span>
          <strong>{{ teamName(game.away_team_id) }}</strong>
        </div>
      </header>

      <!-- Tab 导航区 -->
      <nav class="match-detail__tabs" role="tablist">
        <button
          v-for="tab in TABS"
          :key="tab"
          type="button"
          role="tab"
          class="match-detail__tab"
          :class="{ 'match-detail__tab--active': activeTab === tab }"
          :aria-selected="activeTab === tab"
          @click="activeTab = tab"
        >
          {{ tab }}
        </button>
      </nav>

      <!-- 内容区:各 Tab 子组件经 KeepAlive 缓存,切换不丢状态 -->
      <div class="match-detail__content">
        <KeepAlive>
          <StrategyTab v-if="activeTab === '策略推荐'" :match-id="matchId" />
          <AdvancedTab v-else-if="activeTab === '高阶数据'" :state="insightsState" />
          <OddsTrendTab
            v-else-if="activeTab === '赔率走势'"
            :match-id="matchId"
            @analysis-settled="refreshLlmLogs"
          />
          <FundamentalsTab
            v-else-if="activeTab === '基本面'"
            :match-id="matchId"
            :home-team-id="game.home_team_id"
            :away-team-id="game.away_team_id"
            :home-team-name="teamName(game.home_team_id)"
            :away-team-name="teamName(game.away_team_id)"
            @analysis-settled="refreshLlmLogs"
          />
          <H2HTab v-else-if="activeTab === '历史交锋'" :state="insightsState" />
          <ExtraInfoTab v-else-if="activeTab === '其他信息'" :state="extraInfo" />
          <AiAnalysisTab v-else-if="activeTab === 'AI 分析'" ref="aiTab" :match-id="matchId" />
        </KeepAlive>

        <!-- 赛事复盘:比对 AI 推荐与开奖结果,大模型归因并输出经验教训(不缓存,重进刷新) -->
        <div v-if="activeTab === '赛事复盘'" class="match-detail__panel">
          <MatchRetrospectPanel :match-id="matchId" />
        </div>
      </div>
    </template>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.match-detail {
  max-width: 960px;
  margin: 0 auto;

  &__back {
    margin-bottom: vars.$spacing-md;
    padding: 0;
    border: none;
    background: transparent;
    color: vars.$color-primary;
    cursor: pointer;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__hero {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: vars.$spacing-lg;
    padding: vars.$spacing-lg;
    margin-bottom: vars.$spacing-md;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
  }

  &__team {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: vars.$spacing-xs;
  }

  &__badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 56px;
    height: 56px;
    border-radius: 50%;
    background: vars.$color-primary;
    color: #fff;
    font-size: vars.$font-size-lg;
    font-weight: 700;
  }

  &__center {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: vars.$spacing-xs;
  }

  &__score {
    font-size: 28px;
    font-weight: 700;
    color: vars.$color-positive;
  }

  &__meta,
  &__formation {
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__tabs {
    display: flex;
    gap: vars.$spacing-xs;
    border-bottom: 1px solid vars.$color-border;
    margin-bottom: vars.$spacing-md;
  }

  &__tab {
    padding: vars.$spacing-sm vars.$spacing-lg;
    border: none;
    border-bottom: 2px solid transparent;
    background: transparent;
    color: vars.$color-text-secondary;
    cursor: pointer;

    &--active {
      border-bottom-color: vars.$color-primary;
      color: vars.$color-primary;
      font-weight: 600;
    }
  }

  &__content {
    min-height: 320px;
  }

  &__panel {
    display: flex;
    flex-direction: column;
    gap: vars.$spacing-md;
  }
}
</style>
