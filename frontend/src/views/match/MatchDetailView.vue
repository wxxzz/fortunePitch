<script setup lang="ts">
/**
 * 页面B:赛事深度分析(Match Detail)- 详情页。
 * 顶部对战卡片 + Tab 导航(基本面|历史交锋|高阶数据|赔率走势|策略推荐)
 * + 内容区(结论卡片 / SHAP 归因 / 风险提示)。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useMatchStore } from '@/stores/match'
import { useAnalyticsStore } from '@/stores/analytics'
import { useStrategyStore } from '@/stores/strategy'
import { useBaseStore } from '@/stores/base'
import { getGame, type MatchGame } from '@/api/match/game'
import ShapAttributionChart, {
  type ShapFeature,
} from '@/components/analytics/ShapAttributionChart.vue'
import OddsTrendChart, {
  type OddsTrendPoint,
} from '@/components/strategy/OddsTrendChart.vue'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'

const route = useRoute()
const router = useRouter()
const matchId = route.params.matchId as string

const matchStore = useMatchStore()
const analyticsStore = useAnalyticsStore()
const strategyStore = useStrategyStore()
const baseStore = useBaseStore()
const { teams } = storeToRefs(baseStore)

const game = ref<MatchGame | null>(null)
const isDetailLoading = ref(true)
const detailError = ref<string | null>(null)
// SHAP 归因图加载态(模拟高阶计算耗时)
const isShapLoading = ref(true)

onMounted(async () => {
  void baseStore.fetchAll()
  void analyticsStore.fetchTeamStats(matchId)
  void strategyStore.fetchAll()
  try {
    game.value = await getGame(matchId)
  } catch (err) {
    detailError.value = err instanceof Error ? err.message : '比赛详情加载失败'
  } finally {
    isDetailLoading.value = false
  }
  // 模型归因计算耗时占位,展示骨架屏
  window.setTimeout(() => {
    isShapLoading.value = false
  }, 600)
})

const teamName = (teamId: number): string =>
  teams.value.find((t) => t.team_id === teamId)?.team_name ?? `球队 #${teamId}`

// ---------- Tab 导航 ----------

const TABS = ['基本面', '历史交锋', '高阶数据', '赔率走势', '策略推荐'] as const
const activeTab = ref<(typeof TABS)[number]>('策略推荐')

// ---------- 策略推荐 Tab 数据 ----------

const { teamStats } = storeToRefs(analyticsStore)
const { recommendations } = storeToRefs(strategyStore)

/** 本场置信度最高的推荐 */
const topRecommendation = computed(() =>
  [...recommendations.value]
    .filter((r) => r.match_id === matchId)
    .sort((a, b) => b.confidence_score - a.confidence_score)[0] ?? null,
)

/** SHAP 归因(演示数据,接入模型推理管道后由后端下发) */
const shapFeatures = ref<ShapFeature[]>([
  { name: '主队主场优势', value: 0.12 },
  { name: '主客 xG 差', value: 0.09 },
  { name: '客队防线漏洞', value: 0.08 },
  { name: '主队近期状态', value: 0.04 },
  { name: '客队伤停影响', value: -0.03 },
  { name: '历史交锋优势', value: -0.06 },
])

/** 风险提示(演示数据) */
const riskWarnings = ref<string[]>([
  '临场可能有大雨,利好防守反击打法',
  '本场主裁判出牌率偏高,中场绞杀或受影响',
])

/** 赔率走势(演示数据,数据源接入后替换) */
const oddsTrendPoints = ref<OddsTrendPoint[]>([
  { time: 'T-5d', homeWin: 2.1, draw: 3.4, awayWin: 3.2 },
  { time: 'T-3d', homeWin: 2.0, draw: 3.45, awayWin: 3.35 },
  { time: 'T-1d', homeWin: 1.92, draw: 3.5, awayWin: 3.6 },
  { time: '即时', homeWin: 1.88, draw: 3.55, awayWin: 3.7 },
])

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
          <span class="match-detail__formation">阵型 4-3-3 vs 4-2-3-1(首发与伤停可视化待接入)</span>
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

      <!-- 内容区 -->
      <div class="match-detail__content">
        <div v-if="activeTab === '策略推荐'" class="match-detail__panel">
          <!-- 结论卡片 -->
          <div class="match-detail__conclusion">
            <template v-if="topRecommendation">
              <div class="match-detail__conclusion-main">
                <span class="match-detail__conclusion-label">推荐赛果</span>
                <strong class="match-detail__conclusion-outcome">
                  {{ topRecommendation.predicted_outcome }}
                </strong>
              </div>
              <div class="match-detail__conclusion-item">
                <span>置信度</span>
                <strong>{{ (topRecommendation.confidence_score * 100).toFixed(0) }}%</strong>
              </div>
              <div class="match-detail__conclusion-item">
                <span>建议注额比例</span>
                <strong>{{ (topRecommendation.confidence_score * 0.1).toFixed(3) }}(凯利折算)</strong>
              </div>
            </template>
            <p v-else class="match-detail__hint">暂无本场推荐</p>
          </div>

          <!-- 逻辑归因 SHAP -->
          <h3 class="match-detail__section-title">逻辑归因(SHAP)</h3>
          <SkeletonBlock v-if="isShapLoading" :height="260" />
          <template v-else>
            <ShapAttributionChart :features="shapFeatures" />
            <p class="match-detail__hint">
              红色条=利好主队因素,绿色条=利空主队因素(演示数据)
            </p>
          </template>

          <!-- 风险提示 -->
          <h3 class="match-detail__section-title">风险提示</h3>
          <ul class="match-detail__risks">
            <li v-for="warning in riskWarnings" :key="warning">
              <span class="match-detail__risk-icon" aria-hidden="true">⚠</span>
              {{ warning }}
            </li>
          </ul>
        </div>

        <div v-else-if="activeTab === '高阶数据'" class="match-detail__panel">
          <table class="match-detail__table">
            <thead>
              <tr>
                <th>球队 ID</th><th>xG</th><th>xGA</th><th>控球率</th><th>射正率</th><th>PPDA</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="stat in teamStats" :key="stat.stat_id">
                <td>{{ stat.team_id }}</td>
                <td>{{ stat.xg ?? '-' }}</td>
                <td>{{ stat.xga ?? '-' }}</td>
                <td>{{ stat.possession !== null ? `${stat.possession}%` : '-' }}</td>
                <td>{{ stat.shot_accuracy !== null ? `${stat.shot_accuracy}%` : '-' }}</td>
                <td>{{ stat.ppda ?? '-' }}</td>
              </tr>
              <tr v-if="teamStats.length === 0">
                <td colspan="6" class="match-detail__hint">暂无本场高阶数据</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-else-if="activeTab === '赔率走势'" class="match-detail__panel">
          <OddsTrendChart :points="oddsTrendPoints" />
          <p class="match-detail__hint">演示数据 · 赔率数据源接入后展示真实走势</p>
        </div>

        <div v-else-if="activeTab === '基本面'" class="match-detail__panel">
          <p class="match-detail__hint">
            基本面信息(联赛排名、伤停名单、赛程密度)待数据源接入后展示。
          </p>
        </div>

        <div v-else-if="activeTab === '历史交锋'" class="match-detail__panel">
          <p class="match-detail__hint">历史交锋记录待数据源接入后展示。</p>
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

  &__conclusion {
    display: flex;
    align-items: center;
    gap: vars.$spacing-lg;
    padding: vars.$spacing-lg;
    background: vars.$color-primary-light;
    border: 1px solid vars.$color-primary;
    border-radius: vars.$border-radius;

    &-main {
      display: flex;
      flex-direction: column;
    }

    &-label {
      font-size: vars.$font-size-sm;
      color: vars.$color-text-secondary;
    }

    &-outcome {
      font-size: 24px;
      color: vars.$color-positive;
    }

    &-item {
      display: flex;
      flex-direction: column;

      span {
        font-size: vars.$font-size-sm;
        color: vars.$color-text-secondary;
      }
    }
  }

  &__section-title {
    margin: vars.$spacing-md 0 0;
    font-size: vars.$font-size-md;
  }

  &__hint {
    margin: 0;
    font-size: vars.$font-size-sm;
    color: vars.$color-text-secondary;
  }

  &__risks {
    margin: 0;
    padding: 0;
    list-style: none;

    li {
      display: flex;
      align-items: center;
      gap: vars.$spacing-sm;
      padding: vars.$spacing-sm vars.$spacing-md;
      background: rgba(212, 136, 6, 0.08);
      border: 1px solid rgba(212, 136, 6, 0.35);
      border-radius: vars.$border-radius;
      margin-bottom: vars.$spacing-sm;
      font-size: vars.$font-size-sm;
    }
  }

  &__risk-icon {
    color: vars.$color-warning;
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
}
</style>
